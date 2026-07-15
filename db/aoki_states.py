import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "device" / "aoki_state_thresholds.json"
BOGOTA = timezone(timedelta(hours=-5), name="America/Bogota")
GATEWAY_ID = 10
DEVICE_ID = "24"
CURRENT_UNIT_ID = 54
POWER_UNIT_ID = 61


def load_thresholds(path=CONFIG_PATH):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def _number(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def preprocess_measurements(rows, config):
    """Ordena y valida mediciones conservando IDs y valores originales."""
    prepared = []
    duplicates = 0
    invalid_values = 0
    out_of_order = 0
    previous_input_ts = None
    seen = set()

    for input_order, row in enumerate(rows):
        try:
            timestamp = int(row["timestamp_utc"])
            unit_id = int(row["unit_id"])
        except (KeyError, TypeError, ValueError):
            invalid_values += 1
            continue
        if previous_input_ts is not None and timestamp < previous_input_ts:
            out_of_order += 1
        previous_input_ts = timestamp
        raw_value = row.get("valor")
        exact_key = (timestamp, unit_id, str(raw_value))
        if exact_key in seen:
            duplicates += 1
            continue
        seen.add(exact_key)
        value = _number(raw_value)
        if value is None:
            invalid_values += 1
        prepared.append({
            "sourceId": row.get("id"), "inputOrder": input_order,
            "timestampUtc": timestamp, "unitId": unit_id,
            "rawValue": raw_value, "value": value,
        })

    prepared.sort(key=lambda item: (item["timestampUtc"], item["unitId"], item["inputOrder"]))
    power_by_timestamp = {}
    current_by_timestamp = {}
    conflicting_timestamps = 0
    for item in prepared:
        target = current_by_timestamp if item["unitId"] == CURRENT_UNIT_ID else power_by_timestamp
        timestamp = item["timestampUtc"]
        if timestamp in target and target[timestamp]["value"] != item["value"]:
            conflicting_timestamps += 1
            continue
        target.setdefault(timestamp, item)

    samples = []
    for timestamp, current in sorted(current_by_timestamp.items()):
        power = power_by_timestamp.get(timestamp)
        samples.append({
            "timestampUtc": timestamp,
            "currentAvgA": current["value"],
            "powerKW": power["value"] if power else None,
            "currentSourceId": current["sourceId"],
            "powerSourceId": power["sourceId"] if power else None,
            "currentRawValue": current["rawValue"],
            "powerRawValue": power["rawValue"] if power else None,
        })
    for index, sample in enumerate(samples):
        next_timestamp = samples[index + 1]["timestampUtc"] if index + 1 < len(samples) else None
        timestamp_dt = datetime.fromtimestamp(sample["timestampUtc"], timezone.utc)
        sample["deltaSeconds"] = next_timestamp - sample["timestampUtc"] if next_timestamp is not None else None
        sample["timestampLocal"] = timestamp_dt.astimezone(BOGOTA).isoformat()
        sample["productionDate"] = _production_date(sample["timestampUtc"])

    return {
        "samples": samples,
        "quality": {
            "inputRows": len(rows), "outputSamples": len(samples),
            "exactDuplicatesRemoved": duplicates,
            "invalidValues": invalid_values,
            "outOfOrderIntervals": out_of_order,
            "conflictingTimestampValues": conflicting_timestamps,
            "maximumGapSeconds": int(config["maximumGapMinutes"] * 60),
        },
    }


def _candidate_state(current, config):
    if current is None:
        return "NO_DATA"
    if current < config["offIdleCurrentA"]:
        return "OFF"
    if current < config["idleProductiveCurrentA"]:
        return "IDLE"
    return "PRODUCTIVE"


def _interval_quality(state, power, config):
    if state == "NO_DATA":
        return "NO_DATA"
    if power is None:
        return "PARTIAL_SIGNAL"
    if state == "PRODUCTIVE" and power <= config["powerZeroToleranceKW"]:
        return "INCONSISTENT_SIGNAL"
    return "VALID_STATE"


def _raw_intervals(samples, start_utc, end_utc, config):
    maximum_gap = int(config["maximumGapMinutes"] * 60)
    selected = [s for s in samples if start_utc <= s["timestampUtc"] < end_utc]
    intervals = []
    if not selected:
        return [{"start": start_utc, "end": end_utc, "candidate": "NO_DATA",
                 "current": None, "power": None, "quality": "NO_DATA", "sampleCount": 0}]
    if selected[0]["timestampUtc"] > start_utc:
        intervals.append({"start": start_utc, "end": selected[0]["timestampUtc"],
                          "candidate": "NO_DATA", "current": None, "power": None,
                          "quality": "NO_DATA", "sampleCount": 0})
    for index, sample in enumerate(selected):
        interval_end = selected[index + 1]["timestampUtc"] if index + 1 < len(selected) else end_utc
        interval_end = min(interval_end, end_utc)
        if interval_end <= sample["timestampUtc"]:
            continue
        gap = interval_end - sample["timestampUtc"]
        state = _candidate_state(sample["currentAvgA"], config)
        if gap > maximum_gap or state == "NO_DATA":
            state = "NO_DATA"
        intervals.append({
            "start": sample["timestampUtc"], "end": interval_end,
            "candidate": state, "current": sample["currentAvgA"] if state != "NO_DATA" else None,
            "power": sample["powerKW"] if state != "NO_DATA" else None,
            "quality": _interval_quality(state, sample["powerKW"], config),
            "sampleCount": 1, "trace": sample,
        })
    return intervals


def _apply_persistence(intervals, config):
    minimum_seconds = int(config["minimumPersistenceMinutes"] * 60)
    minimum_samples = int(config["minimumConsecutiveSamples"])
    confirmed = None
    pending_state = None
    pending_indexes = []
    pending_seconds = 0
    for index, interval in enumerate(intervals):
        candidate = interval["candidate"]
        if candidate == "NO_DATA":
            interval["state"] = "NO_DATA"
            confirmed = pending_state = None
            pending_indexes = []
            pending_seconds = 0
            continue
        if confirmed is None:
            confirmed = candidate
            interval["state"] = confirmed
            continue
        if candidate == confirmed:
            interval["state"] = confirmed
            pending_state = None
            pending_indexes = []
            pending_seconds = 0
            continue
        if candidate != pending_state:
            pending_state = candidate
            pending_indexes = []
            pending_seconds = 0
        pending_indexes.append(index)
        pending_seconds += interval["end"] - interval["start"]
        interval["state"] = confirmed
        if len(pending_indexes) >= minimum_samples or pending_seconds >= minimum_seconds:
            confirmed = pending_state
            for pending_index in pending_indexes:
                intervals[pending_index]["state"] = confirmed
            pending_state = None
            pending_indexes = []
            pending_seconds = 0
    for interval in intervals:
        interval["quality"] = _interval_quality(interval["state"], interval["power"], config)
    return intervals


def _production_date(timestamp):
    local = datetime.fromtimestamp(timestamp, timezone.utc).astimezone(BOGOTA)
    if local.hour < 6:
        local -= timedelta(days=1)
    return local.date().isoformat()


def _next_six_boundary(timestamp):
    local = datetime.fromtimestamp(timestamp, timezone.utc).astimezone(BOGOTA)
    boundary = local.replace(hour=6, minute=0, second=0, microsecond=0)
    if local >= boundary:
        boundary += timedelta(days=1)
    return int(boundary.astimezone(timezone.utc).timestamp())


def _split_at_production_day(intervals):
    output = []
    for interval in intervals:
        cursor = interval["start"]
        while cursor < interval["end"]:
            end = min(interval["end"], _next_six_boundary(cursor))
            part = dict(interval)
            part["start"], part["end"] = cursor, end
            output.append(part)
            cursor = end
    return output


def build_segments(intervals, config):
    quality_rank = {"VALID_STATE": 0, "PARTIAL_SIGNAL": 1, "INCONSISTENT_SIGNAL": 2, "NO_DATA": 3}
    segments = []
    for interval in _split_at_production_day(intervals):
        production_date = _production_date(interval["start"])
        if (segments and segments[-1]["state"] == interval["state"]
                and segments[-1]["productionDate"] == production_date
                and segments[-1]["endEpoch"] == interval["start"]):
            segment = segments[-1]
            duration = interval["end"] - interval["start"]
            segment["weightedCurrent"] += (interval["current"] or 0) * duration
            segment["weightedPower"] += (interval["power"] or 0) * duration
            segment["currentSeconds"] += duration if interval["current"] is not None else 0
            segment["powerSeconds"] += duration if interval["power"] is not None else 0
            segment["endEpoch"] = interval["end"]
            segment["sampleCount"] += interval["sampleCount"]
            if quality_rank[interval["quality"]] > quality_rank[segment["quality"]]:
                segment["quality"] = interval["quality"]
        else:
            duration = interval["end"] - interval["start"]
            segments.append({
                "state": interval["state"], "startEpoch": interval["start"], "endEpoch": interval["end"],
                "productionDate": production_date, "sampleCount": interval["sampleCount"],
                "weightedCurrent": (interval["current"] or 0) * duration,
                "weightedPower": (interval["power"] or 0) * duration,
                "currentSeconds": duration if interval["current"] is not None else 0,
                "powerSeconds": duration if interval["power"] is not None else 0,
                "quality": interval["quality"],
            })
    result = []
    for segment in segments:
        start_dt = datetime.fromtimestamp(segment["startEpoch"], timezone.utc)
        end_dt = datetime.fromtimestamp(segment["endEpoch"], timezone.utc)
        result.append({
            "state": segment["state"], "startUtc": start_dt.isoformat(), "endUtc": end_dt.isoformat(),
            "startLocal": start_dt.astimezone(BOGOTA).isoformat(), "endLocal": end_dt.astimezone(BOGOTA).isoformat(),
            "productionDate": segment["productionDate"],
            "durationSeconds": segment["endEpoch"] - segment["startEpoch"],
            "sampleCount": segment["sampleCount"],
            "averageCurrentA": round(segment["weightedCurrent"] / segment["currentSeconds"], 4) if segment["currentSeconds"] else None,
            "averagePowerKW": round(segment["weightedPower"] / segment["powerSeconds"], 4) if segment["powerSeconds"] else None,
            "quality": segment["quality"], "thresholdVersion": config["version"],
        })
    return result


def summarize_daily(segments, tolerance_seconds=600):
    days = {}
    for segment in segments:
        day = days.setdefault(segment["productionDate"], {
            "productionDate": segment["productionDate"], "PRODUCTIVE": 0, "IDLE": 0,
            "OFF": 0, "NO_DATA": 0, "stateTransitions": 0, "inconsistentSegments": 0,
            "lastState": None,
        })
        day[segment["state"]] += segment["durationSeconds"]
        if day["lastState"] is not None and day["lastState"] != segment["state"]:
            day["stateTransitions"] += 1
        day["lastState"] = segment["state"]
        if segment["quality"] == "INCONSISTENT_SIGNAL":
            day["inconsistentSegments"] += 1
    output = []
    for key in sorted(days):
        day = days[key]
        total = sum(day[state] for state in ("PRODUCTIVE", "IDLE", "OFF", "NO_DATA"))
        item = {"productionDate": key, "scheduledHours": round(total / 3600, 4)}
        for state, prefix in (("PRODUCTIVE", "productive"), ("IDLE", "idle"), ("OFF", "off"), ("NO_DATA", "noData")):
            item[prefix + "Hours"] = round(day[state] / 3600, 4)
            item[prefix + "Pct"] = round(day[state] / total * 100, 3) if total else None
        item["coveragePct"] = round((total - day["NO_DATA"]) / total * 100, 3) if total else None
        item["knownDataHours"] = round((total - day["NO_DATA"]) / 3600, 4)
        state_total = sum(item[prefix + "Hours"] for prefix in ("productive", "idle", "off", "noData"))
        balance_seconds = abs(state_total - item["scheduledHours"]) * 3600
        item["balanceDifferenceSeconds"] = round(balance_seconds, 3)
        item["balanceToleranceSeconds"] = int(tolerance_seconds)
        item["balanceStatus"] = "VALID" if balance_seconds <= tolerance_seconds else "OUT_OF_TOLERANCE"
        item["stateTransitions"] = day["stateTransitions"]
        item["inconsistentSegments"] = day["inconsistentSegments"]
        output.append(item)
    return output


def summarize_period(daily, start_utc, end_utc, tolerance_seconds=600):
    fields = {
        "productiveHours": sum(day["productiveHours"] for day in daily),
        "idleHours": sum(day["idleHours"] for day in daily),
        "offHours": sum(day["offHours"] for day in daily),
        "noDataHours": sum(day["noDataHours"] for day in daily),
    }
    expected_hours = (int(end_utc) - int(start_utc)) / 3600
    state_hours = sum(fields.values())
    difference_seconds = abs(expected_hours - state_hours) * 3600
    fields.update({
        "scheduledHours": round(expected_hours, 4),
        "knownDataHours": round(state_hours - fields["noDataHours"], 4),
        "coveragePct": round((state_hours - fields["noDataHours"]) / expected_hours * 100, 3)
        if expected_hours > 0 else None,
        "balanceDifferenceSeconds": round(difference_seconds, 3),
        "balanceToleranceSeconds": int(tolerance_seconds),
        "balanceStatus": "VALID" if difference_seconds <= tolerance_seconds else "OUT_OF_TOLERANCE",
    })
    for key in ("productiveHours", "idleHours", "offHours", "noDataHours"):
        fields[key] = round(fields[key], 4)
    return fields


def classify_aoki_states(rows, start_utc, end_utc, config=None):
    config = config or load_thresholds()
    preprocessed = preprocess_measurements(rows, config)
    raw = _raw_intervals(preprocessed["samples"], int(start_utc), int(end_utc), config)
    classified = _apply_persistence(raw, config)
    segments = build_segments(classified, config)
    tolerance_seconds = int(config["expectedIntervalMinutes"] * 60)
    daily = summarize_daily(segments, tolerance_seconds)
    return {
        "datasetType": config.get("dataset", {}).get("type", "DATOS_HISTORICOS_DE_PRUEBA"),
        "dataset": config.get("dataset"), "source": "ME337_1",
        "gatewayId": GATEWAY_ID, "deviceId": int(DEVICE_ID),
        "thresholds": config, "quality": preprocessed["quality"],
        "traceability": preprocessed["samples"],
        "segments": segments, "daily": daily,
        "periodSummary": summarize_period(daily, start_utc, end_utc, tolerance_seconds),
    }


def query_aoki_rows(conn, start_utc, end_utc):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, timestamp_utc, unit_id, valor
        FROM mediciones_detalle
        WHERE gateway_id = ? AND TRIM(device_id) = ?
          AND unit_id IN (?, ?)
          AND CAST(timestamp_utc AS INTEGER) >= ?
          AND CAST(timestamp_utc AS INTEGER) < ?
        ORDER BY id ASC
    """, (GATEWAY_ID, DEVICE_ID, CURRENT_UNIT_ID, POWER_UNIT_ID, int(start_utc), int(end_utc)))
    return [dict(row) for row in cursor.fetchall()]
