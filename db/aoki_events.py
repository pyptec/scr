from collections import Counter
import hashlib


NON_PRODUCTIVE_STATES = {"IDLE", "OFF"}
QUALITY_RANK = {"VALID_STATE": 0, "PARTIAL_SIGNAL": 1, "INCONSISTENT_SIGNAL": 2}


def _weighted_average(parts, value_key):
    valid = [part for part in parts if part.get(value_key) is not None]
    seconds = sum(part["durationSeconds"] for part in valid)
    if not seconds:
        return None
    return round(sum(part[value_key] * part["durationSeconds"] for part in valid) / seconds, 4)


def _electrical_event_id(start_utc, end_utc, threshold_version):
    payload = f"ME337_1|10|24|{start_utc}|{end_utc}|{threshold_version}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]
    return f"electrical-{digest}"


def _build_event(parts, thresholds):
    duration = sum(part["durationSeconds"] for part in parts)
    sample_count = sum(part["sampleCount"] for part in parts)
    minimum_samples = int(thresholds["minimumConsecutiveSamples"])
    minimum_seconds = int(thresholds["minimumPersistenceMinutes"] * 60)
    if sample_count < minimum_samples and duration < minimum_seconds:
        return None

    seconds_by_state = Counter()
    for part in parts:
        seconds_by_state[part["state"]] += part["durationSeconds"]
    dominant = max(("OFF", "IDLE"), key=lambda state: (seconds_by_state[state], state == "OFF"))
    minimum_values = [part["minimumCurrentA"] for part in parts if part.get("minimumCurrentA") is not None]
    production_dates = list(dict.fromkeys(part["productionDate"] for part in parts))
    quality = max(
        (part.get("quality", "VALID_STATE") for part in parts),
        key=lambda item: QUALITY_RANK.get(item, 3),
    )
    start_utc = parts[0]["startUtc"]
    end_utc = parts[-1]["endUtc"]
    return {
        "eventId": _electrical_event_id(start_utc, end_utc, thresholds["version"]),
        "startUtc": start_utc,
        "endUtc": end_utc,
        "startLocal": parts[0]["startLocal"],
        "endLocal": parts[-1]["endLocal"],
        "productionDates": production_dates,
        "durationMinutes": round(duration / 60, 3),
        "dominantState": dominant,
        "minimumCurrentA": round(min(minimum_values), 4) if minimum_values else None,
        "averageCurrentA": _weighted_average(parts, "averageCurrentA"),
        "averagePowerKW": _weighted_average(parts, "averagePowerKW"),
        "sampleCount": sample_count,
        "stateMinutes": {
            "IDLE": round(seconds_by_state["IDLE"] / 60, 3),
            "OFF": round(seconds_by_state["OFF"] / 60, 3),
        },
        "detectedBy": "ME337_1",
        "status": "DETECTED",
        "classification": "SIN_CLASIFICAR",
        "quality": quality,
        "thresholdVersion": thresholds["version"],
    }


def detect_aoki_downtime_events(classification):
    """Agrupa estados no productivos válidos sin usar producción ni NO_DATA."""
    events = []
    boundary_censored = []
    pending = []
    thresholds = classification["thresholds"]

    def flush():
        nonlocal pending
        if pending:
            event = _build_event(pending, thresholds)
            if event is not None:
                events.append(event)
        pending = []

    for segment in classification.get("segments", []):
        if segment["state"] not in NON_PRODUCTIVE_STATES:
            flush()
            continue
        if pending and pending[-1]["endUtc"] != segment["startUtc"]:
            flush()
        pending.append(segment)
    flush()

    segments = classification.get("segments", [])
    if segments:
        range_start, range_end = segments[0]["startUtc"], segments[-1]["endUtc"]
        complete = []
        for event in events:
            reasons = []
            if event["startUtc"] == range_start:
                reasons.append("RANGE_START")
            if event["endUtc"] == range_end:
                reasons.append("RANGE_END")
            if reasons:
                boundary_censored.append({**event, "exclusionReasons": reasons})
            else:
                complete.append(event)
        events = complete

    idle_minutes = sum(event["stateMinutes"]["IDLE"] for event in events)
    off_minutes = sum(event["stateMinutes"]["OFF"] for event in events)
    return {
        "events": events,
        "summary": {
            "eventCount": len(events),
            "idleHours": round(idle_minutes / 60, 4),
            "offHours": round(off_minutes / 60, 4),
            "nonProductiveHours": round((idle_minutes + off_minutes) / 60, 4),
            "detectedBy": "ME337_1",
            "status": "DETECTED",
            "boundaryCensoredEvents": len(boundary_censored),
        },
        "boundaryCensoredEvents": boundary_censored,
    }
