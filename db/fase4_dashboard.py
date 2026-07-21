from copy import deepcopy

from db.aoki_alerts import build_alert_contract
from db.aoki_base100 import build_base100_contract
from db.aoki_daily_performance import build_daily_performance
from db.aoki_maintenance_events import (
    EVIDENCE_HASH_VERSION,
    build_maintenance_events,
    merge_human_validations,
)
from db.aoki_reliability import build_reliability_contract
from db.aoki_validated_uptime import build_validated_uptime
from db.fase2_dashboard import build_phase2_dashboard


KPI_FIELDS = (
    "mtbfHours",
    "mttrHours",
    "technicalAvailabilityPct",
    "technicalAvailabilityByTimePct",
    "failureRatePer1000Hours",
)


def _normalized_ranges(phase2, start, end):
    source = deepcopy((phase2.get("ranges") or {}))
    return {
        "requestedRange": deepcopy(source.get("requestedRange") or {
            "startUtc": start, "endUtc": end,
        }),
        "effectiveRange": deepcopy(source.get("effectiveRange") or {
            "startUtc": start, "endUtc": end,
        }),
        "reconciliableRange": deepcopy(source.get("reconciliableRange")),
        "timezone": "America/Bogota",
        "startInclusive": True,
        "endExclusive": True,
    }


def _gated_reliability(contract):
    result = deepcopy(contract)
    visible = result.get("status") == "VALID"
    summary = result.setdefault("summary", {})
    if not visible:
        for field in KPI_FIELDS:
            summary[field] = None
    result["kpiVisible"] = visible
    result["kpiExplanation"] = (
        "KPI calculados con validaciones humanas y uptime validado."
        if visible else
        "KPI no disponibles: reliability.status debe ser VALID; "
        f"estado actual {result.get('status') or 'NO_DISPONIBLE'}."
    )
    return result


def build_phase4_dashboard(conn, start_utc, end_utc, validation_store):
    """Compone una sola canalización aprobada sin recalcular sus resultados."""
    start, end = int(start_utc), int(end_utc)
    if end <= start:
        raise ValueError("El fin del periodo debe ser posterior al inicio")

    phase2 = build_phase2_dashboard(conn, start, end)
    performance = build_daily_performance(conn, start, end)
    base100 = build_base100_contract(performance)

    automatic_maintenance = build_maintenance_events(phase2)
    maintenance_ids = {
        event["maintenanceEventId"]
        for event in automatic_maintenance.get("events", [])
    }
    validations = [
        item for item in validation_store.list_validations()
        if item.get("maintenanceEventId") in maintenance_ids
    ]
    maintenance = merge_human_validations(automatic_maintenance, validations)
    windows = validation_store.list_windows(start, end)
    uptime = build_validated_uptime(
        start,
        end,
        windows,
        maintenance["events"],
        (phase2.get("electricalStates") or {}).get("segments", []),
    )
    reliability_source = build_reliability_contract(uptime, maintenance)
    alerts = build_alert_contract(
        phase2, performance, base100, maintenance, reliability_source
    )
    reliability = _gated_reliability(reliability_source)
    ranges = _normalized_ranges(phase2, start, end)
    kpi_visible = reliability["kpiVisible"]

    return {
        "ranges": ranges,
        "maintenance": maintenance,
        "validations": {
            "records": deepcopy(validations),
            "operatingWindows": deepcopy(windows),
            "summary": {
                "validationCount": len(validations),
                "humanValidatedCount": maintenance["summary"]["humanValidated"],
                "pendingHumanReviewCount": maintenance["summary"]["pendingHumanReview"],
                "operatingWindowCount": len(windows),
            },
        },
        "uptime": uptime,
        "reliability": reliability,
        "alerts": alerts,
        "methodology": {
            "pipeline": [
                "PHASE_2", "MAINTENANCE_4_1", "HUMAN_VALIDATIONS_4_1B",
                "VALIDATED_UPTIME_4_1B", "RELIABILITY_4_2", "ALERTS_4_3",
                "INTEGRATED_DTO_4_4",
            ],
            "taxonomyVersion": maintenance.get("taxonomyVersion"),
            "evidenceHashVersion": EVIDENCE_HASH_VERSION,
            "uptimePolicyVersion": (
                uptime.get("methodology") or {}
            ).get("policyVersion"),
            "reliabilityMethodVersion": (
                reliability.get("methodology") or {}
            ).get("reliabilityMethodVersion"),
            "alertRulesVersion": alerts.get("rulesVersion"),
            "maintenanceEventIdSource": "MAINTENANCE_4_1_UNCHANGED",
            "recalculatesApprovedKpi": False,
            "recalculatesApprovedAlerts": False,
        },
        "quality": {
            "kpiVisible": kpi_visible,
            "readinessStatus": reliability.get("readinessStatus"),
            "reliabilityStatus": reliability.get("status"),
            "explanations": [reliability["kpiExplanation"]],
            "flags": deepcopy((reliability.get("quality") or {}).get("flags", [])),
            "alarmDeduplicationPreserved": True,
            "maintenanceEventIdsPreserved": True,
        },
    }
