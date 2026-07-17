import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from db.aoki_energy import (
    query_aoki_energy_rows,
    reconstruct_aoki_energy,
)
from db.aoki_states import classify_aoki_states, query_aoki_rows


ROOT = Path(__file__).resolve().parent.parent
QUALITY_CONFIG_PATH = ROOT / "device" / "aoki_performance_quality.json"
BOGOTA = timezone(timedelta(hours=-5), name="America/Bogota")
TIMEZONE_NAME = "America/Bogota"
PRODUCTIVE_HOURS_SOURCE = "ELECTRICAL_CLASSIFICATION_PRELIMINARY"
ALLOWED_ENERGY_SOURCES = {
    "ACCUMULATOR_DELTA",
    "POWER_TRAPEZOIDAL",
    "POWER_RECTANGULAR",
}


def load_performance_quality(path=QUALITY_CONFIG_PATH):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def _iso_utc(epoch):
    return datetime.fromtimestamp(int(epoch), timezone.utc).isoformat()


def _local_iso(epoch):
    return datetime.fromtimestamp(int(epoch), timezone.utc).astimezone(BOGOTA).isoformat()


def _day_range(production_date):
    local_start = datetime.fromisoformat(production_date).replace(
        hour=6, tzinfo=BOGOTA
    )
    local_end = local_start + timedelta(days=1)
    return (
        int(local_start.astimezone(timezone.utc).timestamp()),
        int(local_end.astimezone(timezone.utc).timestamp()),
    )


def _production_daily(conn, start_utc, end_utc):
    rows = conn.execute(
        """
        SELECT fecha, fecha_hora_inicio_utc, fecha_hora_fin_utc,
               envases_buenos, envases_malos
        FROM produccion_periodo
        WHERE fecha_hora_fin_utc > ? AND fecha_hora_inicio_utc < ?
        ORDER BY fecha_hora_inicio_utc
        """,
        (int(start_utc), int(end_utc)),
    ).fetchall()
    days = {}
    for raw in rows:
        row = dict(raw)
        period_start = int(row["fecha_hora_inicio_utc"])
        period_end = int(row["fecha_hora_fin_utc"])
        overlap_start = max(int(start_utc), period_start)
        overlap_end = min(int(end_utc), period_end)
        if overlap_end <= overlap_start or period_end <= period_start:
            continue
        factor = (overlap_end - overlap_start) / (period_end - period_start)
        item = days.setdefault(row["fecha"], {
            "goodUnits": 0.0, "badUnits": 0.0,
            "goodAvailable": True, "badAvailable": True,
        })
        if row["envases_buenos"] is None:
            item["goodAvailable"] = False
        else:
            item["goodUnits"] += float(row["envases_buenos"]) * factor
        if row["envases_malos"] is None:
            item["badAvailable"] = False
        else:
            item["badUnits"] += float(row["envases_malos"]) * factor
    result = {}
    for day, item in days.items():
        good = round(item["goodUnits"], 2) if item["goodAvailable"] else None
        bad = round(item["badUnits"], 2) if item["badAvailable"] else None
        result[day] = {
            "goodUnits": good,
            "badUnits": bad,
            "totalUnits": round(good + bad, 2) if good is not None and bad is not None else None,
        }
    return result


def _energy_daily(intervals):
    days = {}
    for interval in intervals:
        day = interval["productionDate"]
        item = days.setdefault(day, {
            "measured": 0.0, "reconstructed": 0.0,
            "knownDuration": 0.0, "noDataDuration": 0.0,
            "noDataIntervals": 0,
        })
        duration = float(interval.get("durationSeconds") or 0)
        source = interval.get("source")
        value = interval.get("energyKWh")
        if source == "ACCUMULATOR_DELTA" and value is not None:
            item["measured"] += float(value)
            item["knownDuration"] += duration
        elif source in {"POWER_TRAPEZOIDAL", "POWER_RECTANGULAR"} and value is not None:
            item["reconstructed"] += float(value)
            item["knownDuration"] += duration
        else:
            # CURRENT_MODEL and every unapproved/unknown source remain unavailable.
            item["noDataDuration"] += duration
            item["noDataIntervals"] += 1
    result = {}
    for day, item in days.items():
        total_duration = item["knownDuration"] + item["noDataDuration"]
        known = item["measured"] + item["reconstructed"]
        result[day] = {
            "measuredEnergyKWh": round(item["measured"], 6),
            "reconstructedEnergyKWh": round(item["reconstructed"], 6),
            "knownEnergyKWh": round(known, 6) if item["knownDuration"] > 0 else None,
            # No se cuantifica energía desconocida: nunca se sustituye por cero.
            "unrecoverableEnergyKWh": None,
            "energyCoveragePct": (
                round(item["knownDuration"] / total_duration * 100, 4)
                if total_duration > 0 else None
            ),
            "reconstructedEnergyPct": (
                round(item["reconstructed"] / known * 100, 4) if known > 0 else None
            ),
            "noDataIntervals": item["noDataIntervals"],
        }
    return result


def _classification(deviation_pct, variability_pct):
    if deviation_pct is None:
        return "INSUFFICIENT_DATA"
    if deviation_pct < -variability_pct:
        return "FAVORABLE_PRELIMINARY"
    if deviation_pct > variability_pct:
        return "UNFAVORABLE_PRELIMINARY"
    return "NEUTRAL_WITHIN_MODEL_VARIABILITY"


def calculate_daily_performance(
    start_utc, end_utc, production, states, energy, model=None, quality_config=None
):
    start_utc, end_utc = int(start_utc), int(end_utc)
    if end_utc <= start_utc:
        raise ValueError("El fin del periodo debe ser posterior al inicio")
    if model is None:
        from db.linea_base_samee200 import obtener_modelo_activo
        model = obtener_modelo_activo()
    quality_config = quality_config or load_performance_quality()
    state_days = {item["productionDate"]: item for item in states.get("daily", [])}
    energy_days = _energy_daily(energy.get("intervals", []))
    day_keys = sorted(set(state_days) | set(energy_days) | set(production))
    daily = []

    for day in day_keys:
        day_start, day_end = _day_range(day)
        clipped_start, clipped_end = max(start_utc, day_start), min(end_utc, day_end)
        if clipped_end <= clipped_start:
            continue
        prod = production.get(day, {})
        state = state_days.get(day, {})
        day_energy = energy_days.get(day, {})
        good = prod.get("goodUnits")
        productive = state.get("productiveHours")
        known = day_energy.get("knownEnergyKWh")
        energy_coverage = day_energy.get("energyCoveragePct")
        state_coverage = state.get("coveragePct")
        reconstructed_pct = day_energy.get("reconstructedEnergyPct")
        inconsistent = float(state.get("inconsistentHours") or 0)

        expected = None
        if good is not None and productive is not None:
            expected = (
                float(model["intercepto"])
                + float(model["coef_envases_buenos"]) * float(good)
                + float(model["coef_horas_productivas"]) * float(productive)
            )
        residual = known - expected if known is not None and expected is not None else None
        deviation = residual / expected * 100 if residual is not None and expected else None

        flags = []
        insufficient = good is None or productive is None or known is None
        if insufficient:
            flags.append("INSUFFICIENT_INPUTS")
        if (day_energy.get("reconstructedEnergyKWh") or 0) > 0:
            flags.append("ENERGY_PARTIALLY_RECONSTRUCTED")
        if state_coverage is None or state_coverage < quality_config["minimumStateCoveragePct"]:
            flags.append("LOW_STATE_COVERAGE")
        if energy_coverage is None or energy_coverage < quality_config["minimumEnergyCoveragePct"]:
            flags.append("LOW_ENERGY_COVERAGE")
        if inconsistent > 0:
            flags.append("INCONSISTENT_SIGNALS")
        reconstruction_high = (
            reconstructed_pct is not None
            and reconstructed_pct > quality_config["maximumReconstructedEnergyPct"]
        )
        quality_exclusion = (
            "LOW_STATE_COVERAGE" in flags
            or "LOW_ENERGY_COVERAGE" in flags
            or "INCONSISTENT_SIGNALS" in flags
            or reconstruction_high
        )
        if insufficient:
            status = "INSUFFICIENT_INPUTS"
        elif quality_exclusion:
            status = "EXCLUDED_FROM_EVALUATION"
            flags.append("EXCLUDED_FROM_EVALUATION")
        else:
            status = "VALID_PRELIMINARY"
            flags.append("VALID_PRELIMINARY")

        daily.append({
            "productionDate": day,
            "rangeStartUtc": _iso_utc(clipped_start),
            "rangeEndUtc": _iso_utc(clipped_end),
            "goodUnits": good,
            "badUnits": prod.get("badUnits"),
            "totalUnits": prod.get("totalUnits"),
            "productiveElectricalHours": productive,
            "productiveHoursSource": PRODUCTIVE_HOURS_SOURCE,
            "idleElectricalHours": state.get("idleHours"),
            "offElectricalHours": state.get("offHours"),
            "noDataHours": state.get("noDataHours"),
            "stateCoveragePct": state_coverage,
            "inconsistentHours": state.get("inconsistentHours"),
            "measuredEnergyKWh": day_energy.get("measuredEnergyKWh", 0.0),
            "reconstructedEnergyKWh": day_energy.get("reconstructedEnergyKWh", 0.0),
            "knownEnergyKWh": known,
            "unrecoverableEnergyKWh": day_energy.get("unrecoverableEnergyKWh"),
            "energyCoveragePct": energy_coverage,
            "reconstructedEnergyPct": reconstructed_pct,
            "expectedEnergyKWh": round(expected, 6) if expected is not None else None,
            "residualKWh": round(residual, 6) if residual is not None else None,
            "deviationPct": round(deviation, 4) if deviation is not None else None,
            "favorableDifferenceKWh": round(-residual, 6) if residual is not None and residual < 0 else 0.0 if residual is not None else None,
            "unfavorableDifferenceKWh": round(residual, 6) if residual is not None and residual > 0 else 0.0 if residual is not None else None,
            "performanceClassification": _classification(deviation, float(model["cv_rmse_pct"])),
            "qualityFlags": flags,
            "evaluationStatus": status,
            "modelVersion": model["nombre_modelo"],
            "energyReconstructionVersion": energy.get("config", {}).get("version"),
            "stateThresholdVersion": states.get("thresholds", {}).get("version"),
        })

    valid = [item for item in daily if item["evaluationStatus"] == "VALID_PRELIMINARY"]
    known_values = [item["knownEnergyKWh"] for item in daily if item["knownEnergyKWh"] is not None]
    measured_total = sum(float(item["measuredEnergyKWh"] or 0) for item in daily)
    reconstructed_total = sum(float(item["reconstructedEnergyKWh"] or 0) for item in daily)
    expected_total = sum(float(item["expectedEnergyKWh"]) for item in valid)
    residual_total = sum(float(item["residualKWh"]) for item in valid)
    scheduled_hours = (end_utc - start_utc) / 3600
    state_no_data = sum(float(item["noDataHours"] or 0) for item in daily)
    energy_known_hours = float(energy.get("periodSummary", {}).get("knownDurationHours") or 0)
    summary = {
        "scheduledHours": round(scheduled_hours, 4),
        "totalKnownEnergyKWh": round(sum(known_values), 6) if known_values else None,
        "totalExpectedEnergyKWh": round(expected_total, 6) if valid else None,
        "totalResidualKWh": round(residual_total, 6) if valid else None,
        "totalDeviationPct": round(residual_total / expected_total * 100, 4) if expected_total else None,
        "totalMeasuredEnergyKWh": round(measured_total, 6),
        "totalReconstructedEnergyKWh": round(reconstructed_total, 6),
        "favorableDifferenceKWh": round(-residual_total, 6) if valid and residual_total < 0 else 0.0 if valid else None,
        "unfavorableDifferenceKWh": round(residual_total, 6) if valid and residual_total > 0 else 0.0 if valid else None,
        "energyCoveragePct": round(energy_known_hours / scheduled_hours * 100, 4) if scheduled_hours else None,
        "stateCoveragePct": round((scheduled_hours - state_no_data) / scheduled_hours * 100, 3) if scheduled_hours else None,
        "validDays": len(valid),
        "excludedDays": sum(item["evaluationStatus"] == "EXCLUDED_FROM_EVALUATION" for item in daily),
        "insufficientDays": sum(item["evaluationStatus"] == "INSUFFICIENT_INPUTS" for item in daily),
        "favorableDays": sum(item["performanceClassification"] == "FAVORABLE_PRELIMINARY" and item in valid for item in daily),
        "neutralDays": sum(item["performanceClassification"] == "NEUTRAL_WITHIN_MODEL_VARIABILITY" and item in valid for item in daily),
        "unfavorableDays": sum(item["performanceClassification"] == "UNFAVORABLE_PRELIMINARY" and item in valid for item in daily),
    }
    return {
        "ranges": {
            "requestedRange": {
                "startUtc": start_utc, "endUtc": end_utc,
                "startLocal": _local_iso(start_utc), "endLocal": _local_iso(end_utc),
            },
            "timezone": TIMEZONE_NAME, "startInclusive": True, "endExclusive": True,
        },
        "model": {
            **model,
            "granularity": "PRODUCTION_DAY_06_00_TO_06_00",
            "interceptApplication": "ONCE_PER_EVALUABLE_DAY",
        },
        "daily": daily,
        "summary": summary,
        "quality": {
            "thresholds": quality_config,
            "status": "PROVISIONAL_QUALITY_THRESHOLDS",
        },
        "methodology": {
            "interval": "[inicio, fin)",
            "timezone": TIMEZONE_NAME,
            "productionDay": "06:00-06:00",
            "energySourcesAllowed": sorted(ALLOWED_ENERGY_SOURCES),
            "currentModelUsed": False,
            "productiveHoursSource": PRODUCTIVE_HOURS_SOURCE,
            "expectedEnergyAggregation": "SUM_OF_EVALUABLE_DAILY_EXPECTED_ENERGY",
            "resultType": "PRELIMINARY_NOT_DEMONSTRATED_SAVINGS",
        },
    }


def build_daily_performance(conn, start_utc, end_utc, model=None):
    state_rows = query_aoki_rows(conn, start_utc, end_utc)
    states = classify_aoki_states(state_rows, start_utc, end_utc)
    energy_rows = query_aoki_energy_rows(conn, start_utc, end_utc)
    energy = reconstruct_aoki_energy(
        energy_rows, start_utc=start_utc, end_utc=end_utc
    )
    production = _production_daily(conn, start_utc, end_utc)
    return calculate_daily_performance(
        start_utc, end_utc, production, states, energy, model=model
    )
