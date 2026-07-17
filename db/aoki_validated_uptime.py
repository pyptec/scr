import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = ROOT / "device" / "aoki_uptime_policy.json"


def load_uptime_policy(path=POLICY_PATH):
    with open(path, "r", encoding="utf-8") as file:
        policy = json.load(file)
    if policy.get("version") != "aoki-uptime-policy-v1-2026-07":
        raise ValueError("Versión de política de uptime no reconocida")
    if policy.get("electricalProductiveUse") != "EVIDENCE_ONLY":
        raise ValueError("PRODUCTIVE eléctrico solo puede ser evidencia")
    return policy


def _clip(intervals, start, end):
    return [
        (max(int(item[0]), start), min(int(item[1]), end))
        for item in intervals
        if min(int(item[1]), end) > max(int(item[0]), start)
    ]


def _union(intervals):
    merged = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        elif end > merged[-1][1]:
            merged[-1][1] = end
    return [(start, end) for start, end in merged]


def _intersection(left, right):
    return _union([
        (max(a, c), min(b, d))
        for a, b in left for c, d in right if min(b, d) > max(a, c)
    ])


def _subtract(base, excluded):
    output = []
    for start, end in _union(base):
        cursor = start
        for x_start, x_end in _union(excluded):
            if x_end <= cursor or x_start >= end:
                continue
            if x_start > cursor:
                output.append((cursor, min(x_start, end)))
            cursor = max(cursor, x_end)
            if cursor >= end:
                break
        if cursor < end:
            output.append((cursor, end))
    return output


def _seconds(intervals):
    return sum(end - start for start, end in _union(intervals))


def _segment_bounds(segment):
    if segment.get("startEpoch") is not None and segment.get("endEpoch") is not None:
        return int(segment["startEpoch"]), int(segment["endEpoch"])
    return (
        int(datetime.fromisoformat(segment["startUtc"]).timestamp()),
        int(datetime.fromisoformat(segment["endUtc"]).timestamp()),
    )


def build_validated_uptime(start_utc, end_utc, windows, maintenance_events,
                           no_data_segments=None, policy=None):
    start, end = int(start_utc), int(end_utc)
    if end <= start:
        raise ValueError("Rango inválido")
    policy = deepcopy(policy or load_uptime_policy())
    active = [window for window in windows if window["status"] == "HUMAN_VALIDATED"]
    grouped = {}
    for window in active:
        grouped.setdefault(window["windowType"], []).append(
            (window["startUtc"], window["endUtc"])
        )
    scheduled = _union(_clip(grouped.get("SCHEDULED_OPERATION", []), start, end))
    planned = _union(_clip(
        grouped.get("PLANNED_STOP", [])
        + grouped.get("EXTERNAL_STOP", [])
        + grouped.get("NON_OPERATING_PERIOD", []),
        start, end,
    ))
    unknown = _union(_clip(grouped.get("UNKNOWN", []), start, end))
    confirmed = [
        event for event in maintenance_events
        if event.get("confirmedFailure")
        and event.get("validatedStartUtc") is not None
        and start <= event.get("validatedStartUtc") < end
    ]
    corrective_events = [
        event for event in confirmed
        if event.get("validatedEndUtc") is not None
        and event.get("validatedEndUtc") > event.get("validatedStartUtc")
    ]
    corrective = _union(_clip([
        (event["validatedStartUtc"], event["validatedEndUtc"])
        for event in corrective_events
    ], start, end))
    no_data = _union(_clip([
        _segment_bounds(segment)
        for segment in (no_data_segments or [])
        if segment.get("state") == "NO_DATA"
    ], start, end))
    scheduled_planned = _intersection(scheduled, planned)
    scheduled_corrective = _intersection(scheduled, corrective)
    scheduled_no_data = _intersection(scheduled, no_data)
    scheduled_unknown = _intersection(scheduled, unknown)
    conflicts = _intersection(scheduled_corrective, scheduled_planned)
    exclusions = _union(
        scheduled_planned + scheduled_corrective + scheduled_no_data
        + scheduled_unknown + conflicts
    )
    uptime = _subtract(scheduled, exclusions)
    complete_corrective = sum(
        event.get("confirmedFailure", False)
        and event.get("validatedDowntimeMinutes") is not None
        and event["validatedDowntimeMinutes"] > 0
        and event.get("evidenceStatus") == "CURRENT"
        for event in confirmed
    )
    validations = [
        event for event in maintenance_events
        if event.get("validationStatus") in {
            "HUMAN_VALIDATED", "HUMAN_REJECTED", "SUPERSEDED"
        }
    ]
    unresolved = _union(scheduled_no_data + scheduled_unknown + conflicts)
    if not validations:
        readiness = "NO_HUMAN_VALIDATIONS"
    elif not scheduled:
        readiness = "INSUFFICIENT_OPERATING_WINDOWS"
    elif not confirmed or complete_corrective == 0:
        readiness = "INSUFFICIENT_CORRECTIVE_TIMES"
    elif unresolved:
        readiness = "INSUFFICIENT_OPERATING_WINDOWS"
    else:
        readiness = "READY_FOR_RELIABILITY_KPI"
    return {
        "ranges": {
            "startUtc": start, "endUtc": end, "timezone": "America/Bogota",
            "startInclusive": True, "endExclusive": True,
        },
        "status": readiness,
        "summary": {
            "validatedAssetUptimeHours": round(_seconds(uptime) / 3600, 6)
            if scheduled else None,
            "validatedCorrectiveDowntimeHours": round(
                _seconds(scheduled_corrective) / 3600, 6
            ) if scheduled else None,
            "excludedNoDataHours": round(_seconds(scheduled_no_data) / 3600, 6)
            if scheduled else None,
            "unresolvedHours": round(_seconds(unresolved) / 3600, 6)
            if scheduled else None,
            "validatedOperatingWindowCount": len(scheduled),
            "confirmedFailureCount": len(confirmed),
            "completeCorrectiveTimeCount": complete_corrective,
        },
        "intervals": {
            "scheduledOperation": scheduled,
            "validatedUptime": uptime,
            "plannedOrExternalStops": scheduled_planned,
            "validatedCorrectiveDowntime": scheduled_corrective,
            "noDataExcluded": scheduled_no_data,
            "unknownOrConflicting": unresolved,
        },
        "methodology": {
            "policyVersion": policy["version"],
            "operatingCalendarSource": "HUMAN_VALIDATED_WINDOWS",
            "electricalProductiveUse": "EVIDENCE_ONLY",
            "assumes24HoursPerDay": False,
            "calculatesMtbf": False,
            "calculatesMttr": False,
            "calculatesTechnicalAvailability": False,
        },
    }
