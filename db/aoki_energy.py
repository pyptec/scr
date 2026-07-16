import json
import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "device" / "aoki_energy_reconstruction.json"
BOGOTA = timezone(timedelta(hours=-5), name="America/Bogota")
GATEWAY_ID = 10
DEVICE_ID = "24"
CURRENT_UNIT_ID = 54
POWER_UNIT_ID = 61
ENERGY_UNIT_ID = 100


def load_energy_config(path=CONFIG_PATH):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def _number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def preprocess_energy_rows(rows):
    """Agrupa señales por timestamp y conserva referencias a los registros origen."""
    points = {}
    duplicates = 0
    invalid = 0
    seen = set()
    previous = None
    out_of_order = 0
    for order, row in enumerate(rows):
        try:
            timestamp = int(row["timestamp_utc"])
            unit_id = int(row["unit_id"])
        except (KeyError, TypeError, ValueError):
            invalid += 1
            continue
        if previous is not None and timestamp < previous:
            out_of_order += 1
        previous = timestamp
        key = (timestamp, unit_id, str(row.get("valor")))
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        value = _number(row.get("valor"))
        if value is None:
            invalid += 1
        point = points.setdefault(timestamp, {"timestamp": timestamp, "signals": {}})
        point["signals"].setdefault(unit_id, {
            "value": value, "rawValue": row.get("valor"), "sourceId": row.get("id"),
            "inputOrder": order,
        })
    return {
        "points": [points[key] for key in sorted(points)],
        "quality": {"inputRows": len(rows), "exactDuplicatesRemoved": duplicates,
                    "invalidValues": invalid, "outOfOrderIntervals": out_of_order},
    }


def _signal(point, unit_id):
    return point.get("signals", {}).get(unit_id, {}).get("value")


def _valid_power(value, config):
    return value is not None and 0 <= value <= config["maximumDerivedPowerKW"]


def _production_date(timestamp):
    local = datetime.fromtimestamp(timestamp, timezone.utc).astimezone(BOGOTA)
    if local.hour < 6:
        local -= timedelta(days=1)
    return local.date().isoformat()


def reconstruct_energy_intervals(rows, config=None):
    config = config or load_energy_config()
    preprocessed = preprocess_energy_rows(rows)
    points = preprocessed["points"]
    intervals = []
    state_gap = int(config["stateMaximumGapMinutes"] * 60)
    recoverable_gap = int(config["maximumRecoverableAccumulatorGapMinutes"] * 60)

    for start, end in zip(points, points[1:]):
        delta_seconds = end["timestamp"] - start["timestamp"]
        if delta_seconds <= 0:
            continue
        hours = delta_seconds / 3600
        energy_start, energy_end = _signal(start, ENERGY_UNIT_ID), _signal(end, ENERGY_UNIT_ID)
        power_start, power_end = _signal(start, POWER_UNIT_ID), _signal(end, POWER_UNIT_ID)
        delta = energy_end - energy_start if energy_start is not None and energy_end is not None else None
        average_measured_power = (
            (power_start + power_end) / 2
            if _valid_power(power_start, config) and _valid_power(power_end, config) else None
        )
        source, quality, reason = "NO_DATA", "NO_DATA", None
        energy, average_power, cross_error = None, None, None

        accumulator_reason = None
        if delta is not None:
            derived_power = delta / hours
            if delta < 0:
                accumulator_reason = "ACCUMULATOR_RESET"
            elif delta_seconds > recoverable_gap:
                accumulator_reason = "ACCUMULATOR_GAP_EXCEEDS_LIMIT"
            elif derived_power > config["maximumDerivedPowerKW"]:
                accumulator_reason = "PHYSICALLY_IMPOSSIBLE_JUMP"
            else:
                if (delta_seconds <= state_gap and average_measured_power is not None
                        and average_measured_power > 0):
                    cross_error = abs(derived_power - average_measured_power) / average_measured_power * 100
                    if cross_error > config["crossValidationTolerancePct"]:
                        accumulator_reason = "INCONSISTENT_ENERGY_SOURCE"
                if accumulator_reason is None:
                    energy, average_power = delta, derived_power
                    source, quality = "ACCUMULATOR_DELTA", "MEASURED"
                    if delta_seconds > state_gap:
                        reason = "AGGREGATED_GAP_ENERGY"

        if source == "NO_DATA" and delta_seconds <= state_gap:
            if _valid_power(power_start, config) and _valid_power(power_end, config):
                average_power = (power_start + power_end) / 2
                energy = average_power * hours
                source, quality = "POWER_TRAPEZOIDAL", "RECONSTRUCTED_HIGH"
                reason = accumulator_reason or "ACCUMULATOR_UNAVAILABLE"
            elif _valid_power(power_start, config) or _valid_power(power_end, config):
                average_power = power_start if _valid_power(power_start, config) else power_end
                energy = average_power * hours
                source, quality = "POWER_RECTANGULAR", "RECONSTRUCTED_MEDIUM"
                reason = accumulator_reason or "ACCUMULATOR_UNAVAILABLE_SINGLE_POWER"
        if source == "NO_DATA":
            reason = accumulator_reason or "INSUFFICIENT_VALID_SOURCES"

        intervals.append({
            "startUtc": datetime.fromtimestamp(start["timestamp"], timezone.utc).isoformat(),
            "endUtc": datetime.fromtimestamp(end["timestamp"], timezone.utc).isoformat(),
            "productionDate": _production_date(start["timestamp"]),
            "durationSeconds": delta_seconds,
            "energyKWh": round(energy, 6) if energy is not None else None,
            "averagePowerKW": round(average_power, 6) if average_power is not None else None,
            "source": source, "quality": quality, "reason": reason,
            "crossValidationErrorPct": round(cross_error, 4) if cross_error is not None else None,
            "stateDataAvailable": delta_seconds <= state_gap,
            "trace": {
                "start": start["signals"], "end": end["signals"],
                "configurationVersion": config["version"],
            },
        })
    return {"config": config, "quality": preprocessed["quality"], "intervals": intervals}


def summarize_energy_daily(intervals, config):
    days = {}
    reconstructed_sources = {"POWER_TRAPEZOIDAL", "POWER_RECTANGULAR", "CURRENT_MODEL"}
    for interval in intervals:
        day = days.setdefault(interval["productionDate"], {
            "productionDate": interval["productionDate"], "measured": 0.0,
            "reconstructed": 0.0, "knownDuration": 0, "noDataDuration": 0,
            "totalDuration": 0, "sources": Counter(), "noDataIntervals": 0,
        })
        day["totalDuration"] += interval["durationSeconds"]
        day["sources"][interval["source"]] += 1
        if interval["source"] == "ACCUMULATOR_DELTA":
            day["measured"] += interval["energyKWh"]
            day["knownDuration"] += interval["durationSeconds"]
        elif interval["source"] in reconstructed_sources:
            day["reconstructed"] += interval["energyKWh"]
            day["knownDuration"] += interval["durationSeconds"]
        else:
            day["noDataDuration"] += interval["durationSeconds"]
            day["noDataIntervals"] += 1
    output = []
    for key in sorted(days):
        day = days[key]
        calculated = day["measured"] + day["reconstructed"]
        reconstructed_pct = day["reconstructed"] / calculated * 100 if calculated > 0 else None
        no_data_pct = day["noDataDuration"] / day["totalDuration"] * 100 if day["totalDuration"] else None
        output.append({
            "productionDate": key, "calculatedEnergyKWh": round(calculated, 6),
            "measuredEnergyKWh": round(day["measured"], 6),
            "reconstructedEnergyKWh": round(day["reconstructed"], 6),
            "unrecoverableEnergyKWh": None if day["noDataIntervals"] else 0.0,
            "reconstructedPct": round(reconstructed_pct, 4) if reconstructed_pct is not None else None,
            "noDataPct": round(no_data_pct, 4) if no_data_pct is not None else None,
            "energyCoveragePct": round(100 - no_data_pct, 4) if no_data_pct is not None else None,
            "noDataIntervals": day["noDataIntervals"], "intervalsBySource": dict(day["sources"]),
            "resultType": "ESTIMACIÓN" if reconstructed_pct is not None and reconstructed_pct > config["estimatedResultThresholdPct"] else "MEDICIÓN_CON_RECONSTRUCCIÓN_TRAZABLE",
        })
    return output


def summarize_energy_period(intervals):
    """Resume el periodo sin mezclar energía medida, reconstruida y NO_DATA."""
    measured = 0.0
    reconstructed = 0.0
    known_duration = 0.0
    no_data_duration = 0.0
    no_data_intervals = 0
    reconstructed_sources = {"POWER_TRAPEZOIDAL", "POWER_RECTANGULAR", "CURRENT_MODEL"}
    for interval in intervals:
        duration = float(interval.get("durationSeconds") or 0)
        source = interval.get("source")
        if source == "ACCUMULATOR_DELTA":
            measured += float(interval.get("energyKWh") or 0)
            known_duration += duration
        elif source in reconstructed_sources:
            reconstructed += float(interval.get("energyKWh") or 0)
            known_duration += duration
        else:
            no_data_duration += duration
            no_data_intervals += 1
    total_duration = known_duration + no_data_duration
    known_energy = measured + reconstructed
    return {
        "measuredEnergyKWh": round(measured, 6),
        "reconstructedEnergyKWh": round(reconstructed, 6),
        "knownEnergyKWh": round(known_energy, 6),
        "knownDurationHours": round(known_duration / 3600, 4),
        "noDataDurationHours": round(no_data_duration / 3600, 4),
        "energyCoveragePct": (
            round(known_duration / total_duration * 100, 4) if total_duration else None
        ),
        "reconstructedPct": (
            round(reconstructed / known_energy * 100, 4) if known_energy else None
        ),
        "noDataIntervals": no_data_intervals,
    }


def _boundary_no_data(start_utc, end_utc, config, reason):
    return {
        "startUtc": datetime.fromtimestamp(start_utc, timezone.utc).isoformat(),
        "endUtc": datetime.fromtimestamp(end_utc, timezone.utc).isoformat(),
        "productionDate": _production_date(start_utc), "durationSeconds": end_utc - start_utc,
        "energyKWh": None, "averagePowerKW": None, "source": "NO_DATA",
        "quality": "NO_DATA", "reason": reason, "crossValidationErrorPct": None,
        "stateDataAvailable": False,
        "trace": {"start": {}, "end": {}, "configurationVersion": config["version"]},
    }


def reconstruct_aoki_energy(rows, config=None, start_utc=None, end_utc=None):
    config = config or load_energy_config()
    result = reconstruct_energy_intervals(rows, config)
    points = preprocess_energy_rows(rows)["points"]
    if start_utc is not None and end_utc is not None:
        start_utc, end_utc = int(start_utc), int(end_utc)
        boundaries = []
        if not points:
            boundaries.append(_boundary_no_data(start_utc, end_utc, config, "NO_MEASUREMENTS_IN_RANGE"))
        else:
            if start_utc < points[0]["timestamp"]:
                boundaries.append(_boundary_no_data(start_utc, points[0]["timestamp"], config, "RANGE_START_WITHOUT_SOURCE"))
            if points[-1]["timestamp"] < end_utc:
                boundaries.append(_boundary_no_data(points[-1]["timestamp"], end_utc, config, "RANGE_END_WITHOUT_SOURCE"))
        result["intervals"] = sorted(result["intervals"] + boundaries, key=lambda item: item["startUtc"])
    result.update({
        "datasetType": "DATOS_HISTORICOS_DE_PRUEBA", "source": "ME337_1",
        "gatewayId": GATEWAY_ID, "deviceId": int(DEVICE_ID),
        "daily": summarize_energy_daily(result["intervals"], config),
        "periodSummary": summarize_energy_period(result["intervals"]),
        "currentModelUsed": False,
    })
    return result


def query_aoki_energy_rows(conn, start_utc, end_utc):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, timestamp_utc, unit_id, valor
        FROM mediciones_detalle
        WHERE gateway_id = ? AND TRIM(device_id) = ?
          AND unit_id IN (?, ?, ?)
          AND CAST(timestamp_utc AS INTEGER) >= ?
          AND CAST(timestamp_utc AS INTEGER) < ?
        ORDER BY id ASC
    """, (GATEWAY_ID, DEVICE_ID, CURRENT_UNIT_ID, POWER_UNIT_ID, ENERGY_UNIT_ID,
          int(start_utc), int(end_utc)))
    return [dict(row) for row in cursor.fetchall()]
