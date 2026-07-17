from copy import deepcopy


VALID_STATUS = "VALID_PRELIMINARY"
INSUFFICIENT_CLASSIFICATION = "INSUFFICIENT_DATA"


def _classify(index, variability):
    if index is None:
        return INSUFFICIENT_CLASSIFICATION
    if index < 100 - variability:
        return "FAVORABLE_PRELIMINARY"
    if index > 100 + variability:
        return "UNFAVORABLE_PRELIMINARY"
    return "NEUTRAL_WITHIN_MODEL_VARIABILITY"


def _base100_quality_flags(day, quality):
    flags = list(day.get("qualityFlags") or [])
    additions = []
    if "LOW_ENERGY_COVERAGE" in flags:
        additions.append("BASE100_LOW_ENERGY_COVERAGE")
    if "LOW_STATE_COVERAGE" in flags:
        additions.append("BASE100_LOW_STATE_COVERAGE")
    if "INCONSISTENT_SIGNALS" in flags:
        additions.append("BASE100_INCONSISTENT_SIGNALS")
    maximum_reconstructed = (
        (quality.get("thresholds") or {}).get("maximumReconstructedEnergyPct")
    )
    reconstructed = day.get("reconstructedEnergyPct")
    if (
        maximum_reconstructed is not None
        and reconstructed is not None
        and float(reconstructed) > float(maximum_reconstructed)
    ):
        additions.append("BASE100_HIGH_RECONSTRUCTION")
    for flag in additions:
        if flag not in flags:
            flags.append(flag)
    return flags


def _exclusion_reasons(day, flags):
    reasons = []
    for flag in day.get("qualityFlags") or []:
        if flag in {
            "LOW_STATE_COVERAGE",
            "LOW_ENERGY_COVERAGE",
            "INCONSISTENT_SIGNALS",
            "INSUFFICIENT_INPUTS",
            "EXCLUDED_FROM_EVALUATION",
        } and flag not in reasons:
            reasons.append(flag)
    if "BASE100_HIGH_RECONSTRUCTION" in flags:
        reasons.append("HIGH_RECONSTRUCTION")
    if day.get("knownEnergyKWh") is None:
        reasons.append("KNOWN_ENERGY_MISSING")
    if day.get("expectedEnergyKWh") is None:
        reasons.append("EXPECTED_ENERGY_MISSING")
    elif float(day["expectedEnergyKWh"]) <= 0:
        reasons.append("EXPECTED_ENERGY_NOT_POSITIVE")
    return reasons


def build_base100_contract(performance_contract):
    """Transforma el contrato 3.1 sin consultar ni recalcular sus fuentes."""
    source = deepcopy(performance_contract)
    model = source.get("model") or {}
    quality = source.get("quality") or {}
    variability = float(model["cv_rmse_pct"])
    quality_version = (quality.get("thresholds") or {}).get("version")
    daily = []

    for day in source.get("daily") or []:
        known = day.get("knownEnergyKWh")
        expected = day.get("expectedEnergyKWh")
        included = (
            day.get("evaluationStatus") == VALID_STATUS
            and known is not None
            and expected is not None
            and float(expected) > 0
        )
        index = float(known) / float(expected) * 100 if included else None
        flags = _base100_quality_flags(day, quality)
        if included:
            flags.append("BASE100_VALID_PRELIMINARY")
            reasons = []
        else:
            flags.append("BASE100_INSUFFICIENT_DATA")
            reasons = _exclusion_reasons(day, flags)
        daily.append({
            "productionDate": day.get("productionDate"),
            "knownEnergyKWh": known,
            "expectedEnergyKWh": expected,
            "base100Index": round(index, 6) if index is not None else None,
            "base100Classification": _classify(index, variability),
            "includedInPeriodIndex": included,
            "exclusionReasons": reasons,
            "energyCoveragePct": day.get("energyCoveragePct"),
            "stateCoveragePct": day.get("stateCoveragePct"),
            "reconstructedEnergyPct": day.get("reconstructedEnergyPct"),
            "qualityFlags": flags,
            "modelVersion": day.get("modelVersion"),
            "performanceQualityVersion": quality_version,
        })

    included_days = [day for day in daily if day["includedInPeriodIndex"]]
    period_known = sum(float(day["knownEnergyKWh"]) for day in included_days)
    period_expected = sum(float(day["expectedEnergyKWh"]) for day in included_days)
    period_index = (
        period_known / period_expected * 100
        if included_days and period_expected > 0 else None
    )
    source_daily = source.get("daily") or []
    summary = {
        "requestedDays": len(daily),
        "periodKnownEnergyKWh": round(period_known, 6) if included_days else None,
        "periodExpectedEnergyKWh": round(period_expected, 6) if included_days else None,
        "periodBase100Index": round(period_index, 6) if period_index is not None else None,
        "includedDays": len(included_days),
        "excludedDays": sum(
            day.get("evaluationStatus") == "EXCLUDED_FROM_EVALUATION"
            for day in source_daily
        ),
        "insufficientDays": sum(
            not output["includedInPeriodIndex"]
            and original.get("evaluationStatus") != "EXCLUDED_FROM_EVALUATION"
            for original, output in zip(source_daily, daily)
        ),
        "favorableDays": sum(
            day["base100Classification"] == "FAVORABLE_PRELIMINARY"
            for day in included_days
        ),
        "neutralDays": sum(
            day["base100Classification"] == "NEUTRAL_WITHIN_MODEL_VARIABILITY"
            for day in included_days
        ),
        "unfavorableDays": sum(
            day["base100Classification"] == "UNFAVORABLE_PRELIMINARY"
            for day in included_days
        ),
        "classification": _classify(period_index, variability),
        "calculationMethod": "RATIO_OF_SUMS",
        "modelVariabilityPct": variability,
        "favorableLimit": round(100 - variability, 6),
        "unfavorableLimit": round(100 + variability, 6),
    }
    methodology = deepcopy(source.get("methodology") or {})
    methodology.update({
        "base100Formula": "knownEnergyKWh / expectedEnergyKWh * 100",
        "periodCalculation": "RATIO_OF_SUMS",
        "sourceContract": "SUBPHASE_3_1_DAILY_PERFORMANCE",
        "nonEvaluableDays": "NULL_NOT_ZERO",
        "resultType": "BASE100_PRELIMINARY_NOT_DEMONSTRATED_SAVINGS",
        "cusumImplemented": False,
    })
    return {
        "ranges": deepcopy(source.get("ranges")),
        "model": deepcopy(model),
        "quality": deepcopy(quality),
        "daily": daily,
        "summary": summary,
        "methodology": methodology,
    }
