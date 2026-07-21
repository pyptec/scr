import json
import math
import re
import unicodedata
from collections import Counter
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
METHOD_PATH = ROOT / "device" / "aoki_reported_reliability_method.json"
METHOD_VERSION = "aoki-reported-reliability-v1-2026-07"
CLASSIFICATIONS = (
    "CORRECTIVE_FAILURE", "PREVENTIVE_MAINTENANCE", "PREDICTIVE_MAINTENANCE",
    "CLEANING", "CHANGEOVER", "MATERIAL_SHORTAGE", "QUALITY_ADJUSTMENT",
    "PLANNED_STOP", "OPERATIONAL_STOP", "DATA_QUALITY_EVENT", "OTHER",
    "UNDETERMINED",
)


def load_reported_reliability_method(path=METHOD_PATH):
    with open(path, "r", encoding="utf-8") as file:
        method = json.load(file)
    if method.get("version") != METHOD_VERSION:
        raise ValueError("Versión de confiabilidad reportada no reconocida")
    if method.get("isTechnicalKpi") is not False:
        raise ValueError("La confiabilidad reportada no puede ser KPI técnico")
    return method


def _text(value):
    normalized = unicodedata.normalize("NFD", str(value or ""))
    normalized = "".join(
        char for char in normalized if unicodedata.category(char) != "Mn"
    )
    return " ".join(normalized.casefold().split())


def _has(text, pattern):
    return re.search(pattern, text, re.IGNORECASE) is not None


def classify_reported_stop(event):
    """Clasifica conservadoramente un evento ya normalizado por 2.6A."""
    text = _text(event.get("matchedText"))
    reasons = []
    if not text:
        classification = "UNDETERMINED"
        reasons.append("El evento normalizado no contiene matchedText suficiente.")
    else:
        signals = set()
        if _has(text, r"\b(?:falla|fallas|dano|averia|rotura|escape|fuga|reparacion)\b") \
                or _has(text, r"\bno\s+(?:levanta|alcanza)\b.*\bpresion\b") \
                or _has(text, r"\bbooster\b") \
                or _has(text, r"\b(?:empaque|valvula)\s+danad[ao]\b") \
                or _has(text, r"\bcambio\s+de\s+(?:una\s+)?pieza\b"):
            signals.add("CORRECTIVE_FAILURE")
        if _has(text, r"\b(?:mantenimiento\s+preventivo|engrase|lubricacion|inspeccion\s+preventiva|ajuste\s+preventivo)\b"):
            signals.add("PREVENTIVE_MAINTENANCE")
        if _has(text, r"\b(?:limpieza|limpiar|lavado|soplar\s+filtros?)\b"):
            signals.add("CLEANING")
        if _has(text, r"\bcambio\s+de\s+(?:molde|producto|formato)\b"):
            signals.add("CHANGEOVER")
        if _has(text, r"\b(?:falta|sin|espera\s+de)\s+(?:de\s+)?(?:material|materia\s+prima)\b"):
            signals.add("MATERIAL_SHORTAGE")
        if _has(text, r"\b(?:ajuste\s+de\s+calidad|rechazo|calibracion\s+de\s+producto|ajuste\s+de\s+molde\s+por\s+calidad)\b"):
            signals.add("QUALITY_ADJUSTMENT")
        if _has(text, r"\b(?:parada\s+programada|programad[ao])\b"):
            signals.add("PLANNED_STOP")
        if _has(text, r"\b(?:parada|detencion)\s+operacional\b"):
            signals.add("OPERATIONAL_STOP")

        ambiguous = _has(
            text,
            r"\btemperatura\s+de\s+aceite\b|\btratamiento\s+de\s+agua\b"
            r"|\baditivo\s+(?:de\s+)?agua\b|\bcambio\s+de\s+resortes?\b",
        )
        if len(signals) == 1 and not ambiguous:
            classification = next(iter(signals))
            reasons.append("El fragmento normalizado contiene una evidencia textual autorizada.")
        elif len(signals) > 1:
            classification = "UNDETERMINED"
            reasons.append("El fragmento contiene causas múltiples o conflictivas.")
        elif ambiguous or _has(text, r"\b(?:mantenimiento|ajuste)\b"):
            classification = "UNDETERMINED"
            reasons.append("La acción o condición es ambigua sin evidencia adicional.")
        else:
            classification = "OPERATIONAL_STOP"
            reasons.append("Parada reportada sin evidencia explícita de falla o mantenimiento.")

    return {
        "reportedEventId": event.get("reportedEventId") or event.get("eventId"),
        "productionDate": event.get("productionDate"),
        "rawText": event.get("rawText"),
        "matchedText": event.get("matchedText"),
        "cause": event.get("cause"),
        "reportedStart": event.get("reportedStart") or event.get("startTime"),
        "reportedEnd": event.get("reportedEnd") or event.get("endTime"),
        "reportedDurationMinutes": (
            event.get("reportedDurationMinutes")
            if "reportedDurationMinutes" in event else event.get("durationMinutes")
        ),
        "temporalSource": event.get("temporalSource"),
        "status": event.get("status"),
        "qualityFlags": deepcopy(event.get("qualityFlags") or []),
        "reconciliationId": event.get("reconciliationId"),
        "electricalEventIds": deepcopy(event.get("electricalEventIds") or []),
        "reportedStopSuggestedClassification": classification,
        "classificationReasons": reasons,
        "validatedClassification": None,
        "validationStatus": "PENDING_HUMAN_REVIEW",
        "requiresHumanReview": True,
        "isConfirmedFailure": False,
    }


def reported_events_from_phase2(phase2_contract):
    """Recupera, sin reinterpretar fuentes, los eventos 2.6A de conciliación."""
    by_id = {}
    for item in (phase2_contract.get("reconciliation") or {}).get("events", []):
        for source in item.get("reportedEvents", []):
            event = deepcopy(source)
            event_id = event.get("eventId")
            if not event_id:
                continue
            event["reconciliationId"] = item.get("reconciliationId")
            event["electricalEventIds"] = deepcopy(item.get("electricalEventIds") or [])
            by_id.setdefault(event_id, event)
    return sorted(by_id.values(), key=lambda item: (
        item.get("productionDate") or "", item.get("eventId") or ""
    ))


def _positive(value):
    return (
        isinstance(value, (int, float)) and not isinstance(value, bool)
        and math.isfinite(value) and value > 0
    )


def build_reported_reliability_contract(
    reported_events, ranges, actual_reported_operating_hours=None,
    scheduled_reported_hours=None, method=None,
):
    method = deepcopy(method or load_reported_reliability_method())
    events = [classify_reported_stop(event) for event in deepcopy(reported_events)]
    counts = Counter(event["reportedStopSuggestedClassification"] for event in events)
    duration_minutes = Counter({name: 0.0 for name in CLASSIFICATIONS})
    excluded = []
    valid_duration_count = 0
    for event in events:
        duration = event.get("reportedDurationMinutes")
        valid = event.get("status") in method["validDurationStatuses"] and _positive(duration)
        event["durationIncluded"] = valid
        event["durationExclusionReason"] = None if valid else "INVALID_OR_MISSING_REPORTED_DURATION"
        if valid:
            valid_duration_count += 1
            duration_minutes[event["reportedStopSuggestedClassification"]] += float(duration)
        else:
            excluded.append({
                "reportedEventId": event["reportedEventId"],
                "reason": event["durationExclusionReason"],
            })

    classified = len(events) - counts["UNDETERMINED"]
    coverage = classified / len(events) * 100 if events else None
    corrective_count = counts["CORRECTIVE_FAILURE"]
    corrective_with_duration = sum(
        event["reportedStopSuggestedClassification"] == "CORRECTIVE_FAILURE"
        and event["durationIncluded"] for event in events
    )
    corrective_hours = duration_minutes["CORRECTIVE_FAILURE"] / 60
    mttr = (
        corrective_hours / corrective_with_duration
        if corrective_with_duration else None
    )

    flags = []
    if _positive(actual_reported_operating_hours):
        operating_hours = float(actual_reported_operating_hours)
        operating_source = "ACTUAL_REPORTED_OPERATING_HOURS"
        availability_method = "REPORTED_OPERATING_TIME_RATIO"
    elif _positive(scheduled_reported_hours):
        operating_hours = max(float(scheduled_reported_hours) - corrective_hours, 0)
        operating_source = "SCHEDULED_REPORTED_MINUS_SUGGESTED_CORRECTIVE"
        availability_method = "SCHEDULED_REPORTED_TIME_RATIO"
        flags.append("ESTIMATED_REPORTED_OPERATING_TIME")
    else:
        operating_hours = None
        operating_source = "NO_REPORTED_OPERATING_TIME"
        availability_method = None

    mtbf = (
        operating_hours / corrective_count
        if operating_hours is not None and corrective_count else None
    )
    availability = None
    if operating_hours is not None:
        denominator = operating_hours + corrective_hours
        availability = operating_hours / denominator * 100 if denominator > 0 else None

    if not events:
        status = "NO_REPORTED_STOPS"
    elif coverage < float(method["classificationCoverageMinimumPct"]):
        status = "LOW_CLASSIFICATION_COVERAGE"
    elif not corrective_count:
        status = "NO_SUGGESTED_CORRECTIVE_FAILURES"
    elif not corrective_with_duration:
        status = "INSUFFICIENT_REPORTED_DURATIONS"
    elif operating_hours is None:
        status = "INSUFFICIENT_REPORTED_OPERATING_TIME"
    else:
        status = "VALID_PRELIMINARY_REPORTED"

    duration_hours = {
        name: round(duration_minutes[name] / 60, 6) for name in CLASSIFICATIONS
    }
    return {
        "ranges": deepcopy(ranges),
        "status": status,
        "summary": {
            "reportedStopCount": len(events),
            "reportedStopDurationHours": round(sum(duration_minutes.values()) / 60, 6),
            "reportedStopsWithValidDuration": valid_duration_count,
            "classifiedReportedStopCount": classified,
            "unclassifiedReportedStopCount": counts["UNDETERMINED"],
            "classificationCoveragePct": round(coverage, 6) if coverage is not None else None,
            "suggestedCorrectiveFailureCount": corrective_count,
            "suggestedCorrectiveFailuresWithDuration": corrective_with_duration,
            "suggestedCorrectiveDowntimeHours": round(corrective_hours, 6),
            "preventiveMaintenanceHours": duration_hours["PREVENTIVE_MAINTENANCE"],
            "cleaningHours": duration_hours["CLEANING"],
            "changeoverHours": duration_hours["CHANGEOVER"],
            "materialShortageHours": duration_hours["MATERIAL_SHORTAGE"],
            "qualityAdjustmentHours": duration_hours["QUALITY_ADJUSTMENT"],
            "plannedStopHours": duration_hours["PLANNED_STOP"],
            "operationalStopHours": duration_hours["OPERATIONAL_STOP"],
            "undeterminedStopHours": duration_hours["UNDETERMINED"],
            "reportedOperatingHours": round(operating_hours, 6) if operating_hours is not None else None,
            "reportedPreliminaryMttrHours": round(mttr, 6) if mttr is not None else None,
            "reportedPreliminaryMtbfHours": round(mtbf, 6) if mtbf is not None else None,
            "reportedPreliminaryAvailabilityPct": round(availability, 6) if availability is not None else None,
        },
        "byClassification": {
            name: {"count": counts[name], "durationHours": duration_hours[name]}
            for name in CLASSIFICATIONS
        },
        "events": events,
        "excludedEvents": excluded,
        "methodology": {
            "version": method["version"],
            "statusLabel": "PRELIMINAR_REPORTADO",
            "mttrMethod": method["mttrMethod"],
            "operatingTimeSource": operating_source,
            "availabilityMethod": availability_method,
            "scheduledReportedHours": scheduled_reported_hours,
            "usesElectricalProductiveHours": False,
            "usesElectricalKnownTime": False,
            "assumes24HoursPerDay": False,
            "sourceContract": "NORMALIZED_REPORTED_STOPS_2_6A",
            "isTechnicalKpi": False,
            "isPreliminary": True,
            "requiresHumanValidation": True,
        },
        "quality": {
            "flags": flags,
            "classificationCoverageMinimumPct": method["classificationCoverageMinimumPct"],
            "excludedEventCount": len(excluded),
        },
    }
