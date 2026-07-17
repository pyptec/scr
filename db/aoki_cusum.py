from copy import deepcopy
from datetime import datetime, timedelta


def _production_date(local_datetime):
    value = local_datetime
    if value.hour < 6:
        value -= timedelta(days=1)
    return value.date()


def _expected_dates(ranges):
    requested = (ranges or {}).get("requestedRange") or {}
    start = datetime.fromisoformat(requested["startLocal"])
    end = datetime.fromisoformat(requested["endLocal"])
    cursor = _production_date(start)
    dates = []
    while True:
        boundary = datetime.combine(
            cursor, datetime.min.time(), tzinfo=start.tzinfo
        ).replace(hour=6)
        next_boundary = boundary + timedelta(days=1)
        if boundary >= end:
            break
        if next_boundary > start:
            dates.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return dates


def _unique_by_date(rows, contract_name):
    output = {}
    for row in rows or []:
        date = row.get("productionDate")
        if not date:
            raise ValueError(f"{contract_name}: productionDate es obligatorio")
        if date in output:
            raise ValueError(f"{contract_name}: fecha duplicada {date}")
        output[date] = row
    return output


def build_cusum_contract(performance_contract, base100_contract):
    """Acumula residuos ya validados sin acceder ni recalcular sus fuentes."""
    performance = deepcopy(performance_contract)
    base100 = deepcopy(base100_contract)
    performance_by_date = _unique_by_date(
        performance.get("daily"), "SUBPHASE_3_1"
    )
    base100_by_date = _unique_by_date(base100.get("daily"), "SUBPHASE_3_2")
    expected_dates = _expected_dates(performance.get("ranges"))
    all_dates = sorted(
        set(expected_dates) | set(performance_by_date) | set(base100_by_date)
    )

    cusum = 0.0
    positive_cusum = 0.0
    negative_cusum = 0.0
    favorable_accumulated = 0.0
    unfavorable_accumulated = 0.0
    daily = []
    missing_days = 0

    for production_date in all_dates:
        source = performance_by_date.get(production_date)
        base = base100_by_date.get(production_date)
        missing = source is None or base is None
        included = bool(
            not missing and base.get("includedInPeriodIndex")
        )
        exclusion_reasons = (
            list(base.get("exclusionReasons") or []) if base else []
        )
        quality_flags = list(base.get("qualityFlags") or []) if base else []

        if missing:
            missing_days += 1
            included = False
            if "MISSING_DAY" not in exclusion_reasons:
                exclusion_reasons.append("MISSING_DAY")
            if "MISSING_DAY" not in quality_flags:
                quality_flags.append("MISSING_DAY")

        contribution = None
        if included:
            contribution = source.get("residualKWh")
            if contribution is None:
                raise ValueError(
                    f"SUBPHASE_3_1: residuo faltante para jornada evaluable {production_date}"
                )
            contribution = float(contribution)
            cusum += contribution
            positive_cusum = max(0.0, positive_cusum + contribution)
            negative_cusum = min(0.0, negative_cusum + contribution)
            if contribution < 0:
                favorable_accumulated += abs(contribution)
            elif contribution > 0:
                unfavorable_accumulated += contribution

        daily.append({
            "productionDate": production_date,
            "knownEnergyKWh": source.get("knownEnergyKWh") if source else None,
            "expectedEnergyKWh": source.get("expectedEnergyKWh") if source else None,
            "residualKWh": contribution,
            "cusumContributionKWh": contribution,
            "cusumKWh": round(cusum, 6),
            "positiveCusumKWh": round(positive_cusum, 6),
            "negativeCusumKWh": round(negative_cusum, 6),
            "includedInCusum": included,
            "exclusionReasons": exclusion_reasons,
            "performanceClassification": (
                source.get("performanceClassification")
                if included else "INSUFFICIENT_DATA"
            ),
            "base100Index": base.get("base100Index") if base else None,
            "energyCoveragePct": source.get("energyCoveragePct") if source else None,
            "stateCoveragePct": source.get("stateCoveragePct") if source else None,
            "reconstructedEnergyPct": (
                source.get("reconstructedEnergyPct") if source else None
            ),
            "qualityFlags": quality_flags,
            "modelVersion": source.get("modelVersion") if source else None,
            "performanceQualityVersion": (
                base.get("performanceQualityVersion") if base else None
            ),
        })

    included_days = sum(day["includedInCusum"] for day in daily)
    excluded_days = sum(
        not day["includedInCusum"] and "MISSING_DAY" not in day["exclusionReasons"]
        for day in daily
    )
    base_summary = base100.get("summary") or {}
    performance_summary = performance.get("summary") or {}
    summary = {
        "requestedDays": len(expected_dates),
        "totalResidualKWh": round(cusum, 6) if included_days else None,
        "finalCusumKWh": round(cusum, 6) if included_days else None,
        "favorableAccumulatedKWh": round(favorable_accumulated, 6),
        "unfavorableAccumulatedKWh": round(unfavorable_accumulated, 6),
        "finalPositiveCusumKWh": round(positive_cusum, 6),
        "finalNegativeCusumKWh": round(negative_cusum, 6),
        "evaluableDays": included_days,
        "excludedDays": excluded_days,
        "missingDays": missing_days,
        "periodExpectedEnergyKWh": base_summary.get("periodExpectedEnergyKWh"),
        "periodKnownEnergyKWh": base_summary.get("periodKnownEnergyKWh"),
        "periodDeviationPct": performance_summary.get("totalDeviationPct"),
        "periodBase100Index": base_summary.get("periodBase100Index"),
        "resetPolicy": "RANGE_START_ZERO",
        "calculationMethod": "SIGNED_RESIDUAL_CUMSUM",
    }
    methodology = deepcopy(performance.get("methodology") or {})
    methodology.update({
        "sourceContracts": [
            "SUBPHASE_3_1_DAILY_PERFORMANCE",
            "SUBPHASE_3_2_BASE100",
        ],
        "residualSource": "SUBPHASE_3_1_RESIDUAL_KWH",
        "inclusionMask": "SUBPHASE_3_2_INCLUDED_IN_PERIOD_INDEX",
        "signConvention": "POSITIVE_UNFAVORABLE_NEGATIVE_FAVORABLE",
        "resetPolicy": "RANGE_START_ZERO",
        "calculationMethod": "SIGNED_RESIDUAL_CUMSUM",
        "excludedContribution": "NULL_WITH_CUSUM_CARRY_FORWARD",
        "statisticalDecisionParametersUsed": False,
        "alarmsImplemented": False,
        "resultType": "DESCRIPTIVE_PRELIMINARY_NOT_CONFIRMED_SAVINGS",
    })
    return {
        "ranges": deepcopy(performance.get("ranges")),
        "model": deepcopy(performance.get("model")),
        "quality": deepcopy(performance.get("quality")),
        "daily": daily,
        "summary": summary,
        "methodology": methodology,
    }
