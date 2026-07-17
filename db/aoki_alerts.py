import hashlib
import json
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
RULES_PATH = ROOT / "device" / "aoki_alert_rules.json"
RULES_VERSION = "aoki-alert-rules-v1-2026-07"


def load_alert_rules(path=RULES_PATH):
    with open(path, "r", encoding="utf-8") as file:
        rules = json.load(file)
    if rules.get("version") != RULES_VERSION:
        raise ValueError("Versión de reglas de alarmas no reconocida")
    if rules.get("persistence") is not False:
        raise ValueError("La subfase 4.3 no permite persistencia")
    if rules.get("externalNotifications") is not False:
        raise ValueError("La subfase 4.3 no permite notificaciones externas")
    return rules


def _epoch(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return int(datetime.fromisoformat(str(value)).timestamp())


def _iso(epoch):
    return (
        datetime.fromtimestamp(int(epoch), timezone.utc).isoformat()
        if epoch is not None else None
    )


def _hash(*parts):
    payload = "|".join(str(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _day_range(day):
    start = _epoch(day.get("rangeStartUtc"))
    end = _epoch(day.get("rangeEndUtc"))
    return start, end


def _new_alarm(
    alarm_type, rule, source_ids, start, end, title, description,
    observed=None, threshold=None, unit=None, evidence=None, flags=None,
    correlation_key=None, maintenance_event_id=None, correlated_types=None,
    severity=None,
):
    source_ids = sorted(set(str(value) for value in source_ids if value is not None))
    natural_range = f"{start if start is not None else '-'}:{end if end is not None else '-'}"
    identity = _hash(alarm_type, *source_ids, RULES_VERSION, natural_range)
    deduplication_key = _hash(alarm_type, *source_ids, RULES_VERSION, natural_range)
    return {
        "alarmId": f"alarm-{identity[:24]}",
        "alarmType": alarm_type,
        "severity": severity or rule["severity"],
        "status": "OPEN",
        "title": title,
        "description": description,
        "detectedAtUtc": _iso(end),
        "rangeStartUtc": _iso(start),
        "rangeEndUtc": _iso(end),
        "sourceModule": rule["sourceModule"],
        "sourceEntityIds": source_ids,
        "ruleId": alarm_type,
        "ruleVersion": RULES_VERSION,
        "observedValue": observed,
        "thresholdValue": threshold,
        "unit": unit,
        "evidence": deepcopy(evidence or {}),
        "qualityFlags": list(dict.fromkeys(flags or [])),
        "deduplicationKey": deduplication_key,
        "correlationKey": correlation_key,
        "correlatedAlarmTypes": sorted(set(correlated_types or [])),
        "requiresHumanReview": alarm_type in {
            "UNREPORTED_ELECTRICAL_EVENT",
            "REPORTED_STOP_NOT_DETECTED",
            "MAINTENANCE_REVIEW_REQUIRED",
            "STALE_MAINTENANCE_EVIDENCE",
        } or "UNREPORTED_ELECTRICAL_EVENT" in (correlated_types or []),
        "maintenanceEventId": maintenance_event_id,
        "isConfirmedFailure": False,
    }


def _energy_alerts(performance, base100, rules):
    alerts = []
    base_by_day = {
        day.get("productionDate"): day for day in base100.get("daily", [])
    }
    variability = (performance.get("model") or {}).get("cv_rmse_pct")
    quality = (performance.get("quality") or {}).get("thresholds") or {}
    for day in performance.get("daily", []):
        date = day.get("productionDate")
        start, end = _day_range(day)
        flags = day.get("qualityFlags") or []
        base = base_by_day.get(date) or {}
        correlation = f"energy-day:{date}"
        common_evidence = {
            "productionDate": date,
            "evaluationStatus": day.get("evaluationStatus"),
            "performanceClassification": day.get("performanceClassification"),
            "deviationPct": day.get("deviationPct"),
            "base100Index": base.get("base100Index"),
            "base100Classification": base.get("base100Classification"),
            "modelVersion": day.get("modelVersion"),
            "performanceQualityVersion": base.get("performanceQualityVersion"),
            "base100Correlated": True,
        }
        classification = day.get("performanceClassification")
        if day.get("evaluationStatus") == "VALID_PRELIMINARY" and classification in {
            "UNFAVORABLE_PRELIMINARY", "FAVORABLE_PRELIMINARY",
        }:
            alarm_type = (
                "ENERGY_OVERCONSUMPTION"
                if classification == "UNFAVORABLE_PRELIMINARY"
                else "ENERGY_FAVORABLE_DEVIATION"
            )
            alerts.append(_new_alarm(
                alarm_type, rules[alarm_type], [f"production-day:{date}"],
                start, end,
                "Diferencia energética desfavorable preliminar"
                if alarm_type == "ENERGY_OVERCONSUMPTION"
                else "Diferencia energética favorable preliminar",
                "La clasificación diaria supera la variabilidad del modelo; no demuestra ahorro ni falla.",
                day.get("deviationPct"),
                variability if alarm_type == "ENERGY_OVERCONSUMPTION" else -float(variability),
                "%",
                common_evidence, flags, correlation,
            ))
        for flag, alarm_type, field, threshold_name, unit in (
            ("LOW_ENERGY_COVERAGE", "LOW_ENERGY_COVERAGE", "energyCoveragePct",
             "minimumEnergyCoveragePct", "%"),
            ("LOW_STATE_COVERAGE", "LOW_STATE_COVERAGE", "stateCoveragePct",
             "minimumStateCoveragePct", "%"),
        ):
            if flag in flags:
                alerts.append(_new_alarm(
                    alarm_type, rules[alarm_type], [f"production-day:{date}"],
                    start, end, "Cobertura insuficiente",
                    "La jornada no alcanza el umbral versionado de cobertura y no se interpreta como cero.",
                    day.get(field), quality.get(threshold_name), unit,
                    common_evidence, flags, f"data-quality-day:{date}",
                ))
    return alerts


def _no_data_alerts(phase2, rules):
    alerts = []
    states = phase2.get("electricalStates") or {}
    threshold = (states.get("thresholds") or {}).get("maximumGapMinutes")
    if threshold is None:
        return alerts
    for segment in states.get("segments", []):
        duration = segment.get("durationSeconds")
        if (
            segment.get("state") != "NO_DATA"
            or duration is None
            or float(duration) / 60 <= float(threshold)
        ):
            continue
        start, end = _epoch(segment.get("startUtc")), _epoch(segment.get("endUtc"))
        date = segment.get("productionDate")
        source_id = f"no-data:{start}:{end}"
        alerts.append(_new_alarm(
            "NO_DATA_PROLONGED", rules["NO_DATA_PROLONGED"], [source_id],
            start, end, "Ausencia prolongada de datos eléctricos",
            "El segmento NO_DATA supera el máximo versionado; no se convierte en consumo ni parada.",
            round(float(duration) / 60, 3), threshold, "min",
            {
                "state": "NO_DATA",
                "productionDate": date,
                "thresholdVersion": (states.get("thresholds") or {}).get("version"),
            },
            ["NO_DATA"], f"data-quality-day:{date}",
        ))
    return alerts


def _operational_alerts(phase2, rules):
    events = (phase2.get("electricalEvents") or {}).get("events", [])
    reconciliations = (phase2.get("reconciliation") or {}).get("events", [])
    by_electrical = {}
    for item in reconciliations:
        for event_id in item.get("electricalEventIds", []):
            by_electrical[event_id] = item
    alerts = []
    for event in events:
        state = event.get("dominantState")
        if state not in {"IDLE", "OFF"}:
            continue
        event_id = event.get("eventId")
        reconciliation = by_electrical.get(event_id) or {}
        solo = reconciliation.get("classification") == "SOLO_DETECTADA"
        alarm_type = (
            "ELECTRICAL_IDLE_EVENT" if state == "IDLE"
            else "ELECTRICAL_OFF_EVENT"
        )
        correlated = ["UNREPORTED_ELECTRICAL_EVENT"] if solo else []
        severity = (
            rules["UNREPORTED_ELECTRICAL_EVENT"]["severity"]
            if solo else rules[alarm_type]["severity"]
        )
        alerts.append(_new_alarm(
            alarm_type, rules[alarm_type], [event_id],
            _epoch(event.get("startUtc")), _epoch(event.get("endUtc")),
            f"Evento eléctrico {state}",
            "Evento operacional detectado por persistencia eléctrica; no constituye una falla confirmada.",
            event.get("durationMinutes"),
            (phase2.get("electricalStates") or {}).get("thresholds", {}).get(
                "minimumPersistenceMinutes"
            ),
            "min",
            {
                "dominantState": state,
                "electricalEventId": event_id,
                "thresholdVersion": event.get("thresholdVersion"),
                "reconciliationId": reconciliation.get("reconciliationId"),
                "reconciliationClassification": reconciliation.get("classification"),
                "reconciliationVersion": reconciliation.get("reconciliationVersion"),
            },
            [event.get("quality")] if event.get("quality") else [],
            f"electrical-event:{event_id}", correlated_types=correlated,
            severity=severity,
        ))
    for item in reconciliations:
        if item.get("classification") != "SOLO_REPORTADA":
            continue
        event_ids = item.get("reportedEventIds") or [item.get("reconciliationId")]
        alerts.append(_new_alarm(
            "REPORTED_STOP_NOT_DETECTED", rules["REPORTED_STOP_NOT_DETECTED"],
            event_ids, _epoch(item.get("startReported")), _epoch(item.get("endReported")),
            "Parada reportada sin evento eléctrico asociado",
            "El reporte requiere revisión; su ausencia eléctrica no confirma ni descarta una falla.",
            item.get("reportedDurationMinutes"), None, "min",
            {
                "reconciliationId": item.get("reconciliationId"),
                "classification": item.get("classification"),
                "reconciliationVersion": item.get("reconciliationVersion"),
            },
            ["REQUIRES_HUMAN_REVIEW"],
            f"reconciliation:{item.get('reconciliationId')}",
        ))
    return alerts


def _maintenance_alerts(maintenance, rules):
    alerts = []
    for event in maintenance.get("events", []):
        stale = event.get("evidenceStatus") == "STALE_SOURCE_EVIDENCE"
        pending = event.get("validationStatus") == "PENDING_HUMAN_REVIEW"
        if not stale and not pending:
            continue
        alarm_type = (
            "STALE_MAINTENANCE_EVIDENCE" if stale
            else "MAINTENANCE_REVIEW_REQUIRED"
        )
        maintenance_id = event.get("maintenanceEventId")
        starts = [
            _epoch(value) for value in (
                event.get("reportedStart"), event.get("electricalStart")
            ) if value is not None
        ]
        ends = [
            _epoch(value) for value in (
                event.get("reportedEnd"), event.get("electricalEnd")
            ) if value is not None
        ]
        correlated = (
            ["MAINTENANCE_REVIEW_REQUIRED"] if stale and pending else []
        )
        alerts.append(_new_alarm(
            alarm_type, rules[alarm_type], [maintenance_id],
            min(starts) if starts else None, max(ends) if ends else None,
            "Evidencia de mantenimiento obsoleta" if stale
            else "Evento pendiente de revisión humana",
            "La alarma solicita revisión y no confirma una falla correctiva.",
            event.get("validationStatus"), None, None,
            {
                "maintenanceEventId": maintenance_id,
                "suggestedClassification": event.get("suggestedClassification"),
                "validatedClassification": event.get("validatedClassification"),
                "validationStatus": event.get("validationStatus"),
                "evidenceStatus": event.get("evidenceStatus"),
                "sourceClassification": event.get("sourceClassification"),
                "reconciliationId": event.get("reconciliationId"),
                "taxonomyVersion": event.get("taxonomyVersion"),
            },
            ["HUMAN_REVIEW_REQUIRED"],
            (
                f"reconciliation:{event.get('reconciliationId')}"
                if event.get("reconciliationId")
                else f"maintenance:{maintenance_id}"
            ),
            maintenance_event_id=maintenance_id, correlated_types=correlated,
        ))
    return alerts


def _reliability_alert(reliability, rules):
    if reliability.get("status") == "VALID":
        return []
    ranges = reliability.get("ranges") or {}
    requested = ranges.get("requestedRange") or {}
    start, end = requested.get("startUtc"), requested.get("endUtc")
    return [_new_alarm(
        "RELIABILITY_KPI_UNAVAILABLE", rules["RELIABILITY_KPI_UNAVAILABLE"],
        [f"reliability-range:{start}:{end}"], start, end,
        "KPI de confiabilidad no disponibles",
        "El contrato de confiabilidad no está VALID; no se comparan KPI contra metas inexistentes.",
        reliability.get("status"), "VALID", None,
        {
            "status": reliability.get("status"),
            "readinessStatus": reliability.get("readinessStatus"),
            "methodology": deepcopy(reliability.get("methodology") or {}),
        },
        list((reliability.get("quality") or {}).get("flags") or []),
        f"reliability-range:{start}:{end}",
    )]


def _correlation_summary(alarms):
    low_state_keys = {
        item["correlationKey"] for item in alarms
        if item["alarmType"] == "LOW_STATE_COVERAGE"
    }
    no_data_correlated = [
        item for item in alarms
        if item["alarmType"] == "NO_DATA_PROLONGED"
        and item["correlationKey"] in low_state_keys
    ]
    return {
        "energyDeviationWithBase100": sum(
            item["alarmType"] in {
                "ENERGY_OVERCONSUMPTION", "ENERGY_FAVORABLE_DEVIATION"
            }
            and item.get("evidence", {}).get("base100Index") is not None
            for item in alarms
        ),
        "electricalEventWithSoloDetectada": sum(
            "UNREPORTED_ELECTRICAL_EVENT" in item["correlatedAlarmTypes"]
            for item in alarms
        ),
        "maintenanceWithReconciliation": sum(
            item["sourceModule"] == "MAINTENANCE"
            and bool(item.get("evidence", {}).get("reconciliationId"))
            for item in alarms
        ),
        "noDataWithLowStateCoverage": len(no_data_correlated),
        "noDataLowCoverageCorrelationGroups": len({
            item["correlationKey"] for item in no_data_correlated
        }),
    }


def build_alert_contract(
    phase2_contract, performance_contract, base100_contract,
    maintenance_contract, reliability_contract, config=None,
):
    """Genera alarmas deterministas en memoria desde contratos ya calculados."""
    config = deepcopy(config or load_alert_rules())
    rules = config["activeRules"]
    phase2 = deepcopy(phase2_contract)
    performance = deepcopy(performance_contract)
    base100 = deepcopy(base100_contract)
    maintenance = deepcopy(maintenance_contract)
    reliability = deepcopy(reliability_contract)
    requested = (performance.get("ranges") or {}).get("requestedRange") or {}
    start, end = requested.get("startUtc"), requested.get("endUtc")
    alerts = []
    alerts.extend(_energy_alerts(performance, base100, rules))
    alerts.extend(_no_data_alerts(phase2, rules))
    alerts.extend(_operational_alerts(phase2, rules))
    alerts.extend(_maintenance_alerts(maintenance, rules))
    alerts.extend(_reliability_alert(reliability, rules))
    alerts.sort(key=lambda item: (
        item["rangeStartUtc"] or "", item["alarmType"], item["alarmId"]
    ))
    ids = [item["alarmId"] for item in alerts]
    dedup = [item["deduplicationKey"] for item in alerts]
    if len(ids) != len(set(ids)) or len(dedup) != len(set(dedup)):
        raise ValueError("La generación produjo alarmas duplicadas")

    emitted = Counter({alarm_type: 0 for alarm_type in rules})
    emitted.update(item["alarmType"] for item in alerts)
    raw = Counter(emitted)
    correlated = Counter({alarm_type: 0 for alarm_type in rules})
    for item in alerts:
        for alarm_type in item["correlatedAlarmTypes"]:
            raw[alarm_type] += 1
            correlated[alarm_type] += 1
    by_severity = Counter(item["severity"] for item in alerts)
    by_module = Counter(item["sourceModule"] for item in alerts)
    return {
        "ranges": {
            "requestedRange": {"startUtc": start, "endUtc": end},
            "timezone": "America/Bogota",
            "startInclusive": True,
            "endExclusive": True,
        },
        "rulesVersion": config["version"],
        "status": "READ_ONLY_IN_MEMORY",
        "alarms": alerts,
        "summary": {
            "rawRuleMatches": dict(sorted(raw.items())),
            "emittedByType": dict(sorted(emitted.items())),
            "correlatedWithoutDuplicate": dict(sorted(correlated.items())),
            "deduplicatedAlarmCount": len(alerts),
            "openAlarmCount": len(alerts),
            "bySeverity": dict(sorted(by_severity.items())),
            "byModule": dict(sorted(by_module.items())),
            "correlations": _correlation_summary(alerts),
            "confirmedFailureCountFromAlerts": 0,
        },
        "methodology": {
            "source": "EXISTING_PHASE_2_3_4_CONTRACTS",
            "deterministic": True,
            "inMemory": True,
            "persistence": False,
            "acknowledgement": False,
            "resolution": False,
            "suppression": False,
            "externalNotifications": False,
            "idleOffOrSoloDetectadaAreFailures": False,
            "noDataConvertedToZero": False,
            "cusumDecisionLimitsUsed": False,
            "reliabilityTargetsUsed": False,
        },
    }


def find_alert(contract, alarm_id):
    return next(
        (item for item in contract.get("alarms", [])
         if item.get("alarmId") == alarm_id),
        None,
    )


def filter_alert_contract(contract, alarm_type=None, severity=None,
                          status=None, module=None):
    result = deepcopy(contract)
    filters = {
        "alarmType": alarm_type,
        "severity": severity,
        "status": status,
        "sourceModule": module,
    }
    alarms = [
        item for item in result.get("alarms", [])
        if all(value is None or item.get(field) == value
               for field, value in filters.items())
    ]
    rule_ids = (contract.get("summary") or {}).get("rawRuleMatches", {}).keys()
    emitted = Counter({rule_id: 0 for rule_id in rule_ids})
    emitted.update(item["alarmType"] for item in alarms)
    correlated = Counter({rule_id: 0 for rule_id in rule_ids})
    correlated.update(
        alarm_type
        for item in alarms
        for alarm_type in item.get("correlatedAlarmTypes", [])
    )
    raw = emitted + correlated
    result["alarms"] = alarms
    result["summary"] = {
        "rawRuleMatches": dict(sorted(raw.items())),
        "emittedByType": dict(sorted(emitted.items())),
        "correlatedWithoutDuplicate": dict(sorted(correlated.items())),
        "deduplicatedAlarmCount": len(alarms),
        "openAlarmCount": sum(item["status"] == "OPEN" for item in alarms),
        "bySeverity": dict(sorted(Counter(
            item["severity"] for item in alarms
        ).items())),
        "byModule": dict(sorted(Counter(
            item["sourceModule"] for item in alarms
        ).items())),
        "correlations": _correlation_summary(alarms),
        "confirmedFailureCountFromAlerts": 0,
    }
    result["filters"] = {
        key: value for key, value in (
            ("type", alarm_type), ("severity", severity),
            ("status", status), ("module", module),
        ) if value is not None
    }
    return result
