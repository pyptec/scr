import json
import math
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
METHOD_PATH = ROOT / "device" / "aoki_reliability_method.json"


def load_reliability_method(path=METHOD_PATH):
    with open(path, "r", encoding="utf-8") as file:
        method = json.load(file)
    if method.get("version") != "aoki-reliability-method-v1-2026-07":
        raise ValueError("Versión metodológica de confiabilidad no reconocida")
    if method.get("operatingTimeSource") != "VALIDATED_ASSET_UPTIME":
        raise ValueError("La única fuente autorizada es VALIDATED_ASSET_UPTIME")
    return method


def _finite_positive(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def _is_confirmed(event):
    return (
        event.get("validatedClassification") == "CORRECTIVE_FAILURE"
        and event.get("validationStatus") == "HUMAN_VALIDATED"
        and event.get("evidenceStatus") == "CURRENT"
        and event.get("validatedStartUtc") is not None
    )


def _censoring(event, start, end):
    event_start = event.get("validatedStartUtc")
    event_end = event.get("validatedEndUtc")
    if event_start is None:
        return "OUTSIDE_RANGE"
    event_start = int(event_start)
    if event_start < start:
        return "LEFT_CENSORED"
    if event_start >= end:
        return "OUTSIDE_RANGE"
    if event_end is None or int(event_end) > end:
        return "RIGHT_CENSORED"
    if int(event_end) <= event_start:
        return "RIGHT_CENSORED"
    return "FULLY_OBSERVED"


def _event_contract(event, start, end):
    censoring = _censoring(event, start, end)
    confirmed = _is_confirmed(event)
    downtime = event.get("validatedDowntimeMinutes")
    valid_downtime = _finite_positive(downtime)
    included_mtbf = confirmed and censoring in {"FULLY_OBSERVED", "RIGHT_CENSORED"}
    included_mttr = confirmed and censoring == "FULLY_OBSERVED" and valid_downtime
    included_availability = (
        confirmed
        and event.get("validatedEndUtc") is not None
        and int(event["validatedEndUtc"]) > max(int(event["validatedStartUtc"]), start)
        and int(event["validatedStartUtc"]) < end
    )
    reasons = []
    if event.get("validationStatus") != "HUMAN_VALIDATED":
        reasons.append("NOT_HUMAN_VALIDATED")
    if event.get("validatedClassification") != "CORRECTIVE_FAILURE":
        reasons.append("NOT_CORRECTIVE_FAILURE")
    if event.get("evidenceStatus") != "CURRENT":
        reasons.append("STALE_SOURCE_EVIDENCE")
    if event.get("validatedStartUtc") is None:
        reasons.append("MISSING_VALIDATED_START")
    if censoring == "LEFT_CENSORED":
        reasons.append("FAILURE_STARTED_BEFORE_RANGE")
    if censoring == "OUTSIDE_RANGE":
        reasons.append("FAILURE_START_OUTSIDE_RANGE")
    if censoring == "RIGHT_CENSORED":
        reasons.append("INCOMPLETE_REPAIR_IN_RANGE")
    if not valid_downtime:
        reasons.append("MISSING_OR_INVALID_VALIDATED_DOWNTIME")
    return {
        "maintenanceEventId": event.get("maintenanceEventId"),
        "validatedClassification": event.get("validatedClassification"),
        "validationStatus": event.get("validationStatus"),
        "evidenceStatus": event.get("evidenceStatus"),
        "validatedStartUtc": event.get("validatedStartUtc"),
        "validatedEndUtc": event.get("validatedEndUtc"),
        "validatedDowntimeMinutes": downtime,
        "censoringStatus": censoring,
        "includedInMtbf": included_mtbf,
        "includedInMttr": included_mttr,
        "includedInAvailability": included_availability,
        "exclusionReasons": list(dict.fromkeys(reasons)),
        "actorId": event.get("actorId"),
        "validationVersion": event.get("version"),
    }


def _null_summary(audit):
    return {
        **audit,
        "mtbfHours": None,
        "mttrHours": None,
        "technicalAvailabilityPct": None,
        "technicalAvailabilityByTimePct": None,
        "availabilityDifferencePctPoints": None,
        "failureRatePer1000Hours": None,
    }


def build_reliability_contract(uptime_contract, maintenance_contract, method=None):
    """Calcula KPI solo desde readiness, uptime y validaciones humanas vigentes."""
    uptime = deepcopy(uptime_contract)
    maintenance = deepcopy(maintenance_contract)
    method = deepcopy(method or load_reliability_method())
    ranges = uptime.get("ranges") or {}
    start, end = int(ranges["startUtc"]), int(ranges["endUtc"])
    events = [
        _event_contract(event, start, end)
        for event in maintenance.get("events", [])
    ]
    human_validations = [
        event for event in events
        if event["validationStatus"] in {
            "HUMAN_VALIDATED", "HUMAN_REJECTED", "SUPERSEDED"
        }
    ]
    confirmed = [event for event in events if event["includedInMtbf"]]
    repaired = [event for event in events if event["includedInMttr"]]
    stale_count = sum(
        event["evidenceStatus"] == "STALE_SOURCE_EVIDENCE"
        for event in events
    )
    uptime_summary = uptime.get("summary") or {}
    uptime_hours = uptime_summary.get("validatedAssetUptimeHours")
    corrective_hours = uptime_summary.get("validatedCorrectiveDowntimeHours")
    unresolved = uptime_summary.get("unresolvedHours")
    audit = {
        "confirmedFailureCount": len(confirmed),
        "failuresWithValidatedStart": len(confirmed),
        "failuresWithValidatedDowntime": len(repaired),
        "validatedAssetUptimeHours": uptime_hours,
        "validatedCorrectiveDowntimeHours": corrective_hours,
        "unresolvedHours": unresolved,
    }
    flags = []
    if not human_validations:
        status = "NO_HUMAN_VALIDATIONS"
    elif not confirmed:
        status = "INSUFFICIENT_CONFIRMED_FAILURES"
    elif not _finite_positive(uptime_hours):
        status = "INSUFFICIENT_OPERATING_TIME"
    elif not repaired or not _finite_positive(corrective_hours):
        status = "INSUFFICIENT_REPAIR_TIME_DATA"
    elif unresolved is None or unresolved > 0:
        status = "UNRESOLVED_OPERATING_TIME"
    elif stale_count:
        status = "STALE_VALIDATIONS"
    elif uptime.get("status") != "READY_FOR_RELIABILITY_KPI":
        status = {
            "NO_HUMAN_VALIDATIONS": "NO_HUMAN_VALIDATIONS",
            "INSUFFICIENT_CORRECTIVE_TIMES": "INSUFFICIENT_REPAIR_TIME_DATA",
            "INSUFFICIENT_OPERATING_WINDOWS": "INSUFFICIENT_OPERATING_TIME",
        }.get(uptime.get("status"), "INSUFFICIENT_OPERATING_TIME")
    else:
        status = "VALID"

    single = len(confirmed) == 1
    if single:
        flags.append("SINGLE_FAILURE_ESTIMATE")
    if stale_count:
        flags.append("STALE_SOURCE_EVIDENCE")
    if unresolved and unresolved > 0:
        flags.append("UNRESOLVED_OPERATING_TIME")

    summary = _null_summary(audit)
    if status == "VALID":
        mtbf = uptime_hours / len(confirmed)
        mttr = corrective_hours / len(repaired)
        by_time = uptime_hours / (uptime_hours + corrective_hours) * 100
        by_mtbf = mtbf / (mtbf + mttr) * 100
        difference = by_mtbf - by_time
        if abs(difference) > float(
            method["availabilityDifferenceTolerancePctPoints"]
        ):
            flags.append("AVAILABILITY_METHOD_MISMATCH")
        summary.update({
            "mtbfHours": round(mtbf, 6),
            "mttrHours": round(mttr, 6),
            "technicalAvailabilityPct": round(by_mtbf, 6),
            "technicalAvailabilityByTimePct": round(by_time, 6),
            "availabilityDifferencePctPoints": round(difference, 6),
            "failureRatePer1000Hours": round(1000 / mtbf, 6),
        })
        if not all(
            math.isfinite(summary[key])
            for key in (
                "mtbfHours", "mttrHours", "technicalAvailabilityPct",
                "technicalAvailabilityByTimePct", "failureRatePer1000Hours",
            )
        ):
            raise ValueError("El cálculo produjo un valor no finito")

    taxonomy_version = maintenance.get("taxonomyVersion")
    return {
        "ranges": {
            "requestedRange": {
                "startUtc": start, "endUtc": end,
            },
            "effectiveRange": {
                "startUtc": start, "endUtc": end,
            },
            "timezone": "America/Bogota",
            "startInclusive": True,
            "endExclusive": True,
        },
        "readinessStatus": uptime.get("status"),
        "status": status,
        "summary": summary,
        "events": events,
        "quality": {
            "flags": list(dict.fromkeys(flags)),
            "singleFailureEstimate": single,
            "staleEvidenceCount": stale_count,
            "unresolvedHours": unresolved,
        },
        "methodology": {
            "reliabilityMethodVersion": method["version"],
            "taxonomyVersion": taxonomy_version,
            "uptimePolicyVersion": (
                uptime.get("methodology") or {}
            ).get("policyVersion"),
            "failureDefinition": method["failureDefinition"],
            "mtbfMethod": method["mtbfMethod"],
            "mttrMethod": method["mttrMethod"],
            "availabilityMethod": method["availabilityMethod"],
            "secondaryAvailabilityMethod": method["secondaryAvailabilityMethod"],
            "operatingTimeSource": "VALIDATED_ASSET_UPTIME",
            "failureRateLabel": "INDICADOR_AUXILIAR",
            "usesElectricalProductiveAsUptime": False,
            "assumes24HoursPerDay": False,
            "usesElectricalOrReportedDowntime": False,
        },
    }
