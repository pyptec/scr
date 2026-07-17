import json
import math
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "device" / "aoki_impact_factors.json"


def load_impact_factors(path=CONFIG_PATH):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def _validated_optional_number(value, name):
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{name} debe ser numérico")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} debe ser numérico") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} debe ser finito")
    if number < 0:
        raise ValueError(f"{name} debe ser mayor o igual a cero")
    return number


def _unique_by_date(contract, name):
    output = {}
    for row in contract.get("daily") or []:
        date = row.get("productionDate")
        if not date or date in output:
            raise ValueError(f"{name}: fecha faltante o duplicada {date}")
        output[date] = row
    return output


def _resolved_inputs(factors, request_overrides):
    factors = deepcopy(factors or {})
    overrides = deepcopy(request_overrides or {})
    currency = factors.get("currency") or "COP"
    if currency != "COP":
        raise ValueError("La moneda de esta subfase debe ser COP")

    tariff_override = overrides.get("energyTariffCopPerKWh")
    emission_override = overrides.get("emissionFactorKgCo2ePerKWh")
    tariff = _validated_optional_number(
        tariff_override if tariff_override is not None
        else factors.get("energyTariffCopPerKWh"),
        "energyTariffCopPerKWh",
    )
    emission = _validated_optional_number(
        emission_override if emission_override is not None
        else factors.get("emissionFactorKgCo2ePerKWh"),
        "emissionFactorKgCo2ePerKWh",
    )
    config_version = factors.get("version")
    tariff_is_override = tariff_override is not None
    emission_is_override = emission_override is not None
    if tariff is not None and not tariff_is_override and not all([
        config_version,
        factors.get("tariffSource"),
        factors.get("tariffEffectiveDate"),
    ]):
        raise ValueError("La tarifa local requiere fuente, fecha efectiva y versión")
    if emission is not None and not emission_is_override and not all([
        config_version,
        factors.get("emissionFactorSource"),
        factors.get("emissionFactorEffectiveDate"),
    ]):
        raise ValueError(
            "El factor local requiere fuente, fecha efectiva y versión"
        )
    return {
        "currency": currency,
        "energyTariffCopPerKWh": tariff,
        "energyTariffUnit": "COP/kWh",
        "tariffSource": (
            "REQUEST_OVERRIDE" if tariff_is_override
            else factors.get("tariffSource")
        ),
        "tariffEffectiveDate": (
            None if tariff_is_override else factors.get("tariffEffectiveDate")
        ),
        "tariffVersion": (
            "REQUEST_OVERRIDE_EPHEMERAL" if tariff_is_override
            else config_version if tariff is not None else None
        ),
        "tariffOrigin": (
            "REQUEST_OVERRIDE" if tariff_is_override
            else "LOCAL_VERSIONED_CONFIG" if tariff is not None
            else "NOT_CONFIGURED"
        ),
        "emissionFactorKgCo2ePerKWh": emission,
        "emissionFactorUnit": "kgCO2e/kWh",
        "emissionFactorSource": (
            "REQUEST_OVERRIDE" if emission_is_override
            else factors.get("emissionFactorSource")
        ),
        "emissionFactorEffectiveDate": (
            None if emission_is_override
            else factors.get("emissionFactorEffectiveDate")
        ),
        "emissionFactorVersion": (
            "REQUEST_OVERRIDE_EPHEMERAL" if emission_is_override
            else config_version if emission is not None else None
        ),
        "emissionFactorOrigin": (
            "REQUEST_OVERRIDE" if emission_is_override
            else "LOCAL_VERSIONED_CONFIG" if emission is not None
            else "NOT_CONFIGURED"
        ),
        "configurationVersion": config_version,
    }


def build_impact_contract(
    performance_contract,
    base100_contract,
    cusum_contract,
    factors,
    request_overrides=None,
):
    """Transformación pura: aplica factores explícitos a residuos ya calculados."""
    performance = deepcopy(performance_contract)
    base100 = deepcopy(base100_contract)
    cusum = deepcopy(cusum_contract)
    inputs = _resolved_inputs(factors, request_overrides)
    performance_days = _unique_by_date(performance, "SUBPHASE_3_1")
    base100_days = _unique_by_date(base100, "SUBPHASE_3_2")
    cusum_days = _unique_by_date(cusum, "SUBPHASE_3_3")

    period_residual = (cusum.get("summary") or {}).get("totalResidualKWh")
    final_cusum = (cusum.get("summary") or {}).get("finalCusumKWh")
    if (
        period_residual is not None and final_cusum is not None
        and abs(float(period_residual) - float(final_cusum)) > 0.000001
    ):
        raise ValueError("periodResidualKWh no coincide con finalCusumKWh")

    tariff = inputs["energyTariffCopPerKWh"]
    emission_factor = inputs["emissionFactorKgCo2ePerKWh"]
    daily = []
    for date in sorted(cusum_days):
        source = cusum_days[date]
        base = base100_days.get(date)
        performance_day = performance_days.get(date)
        if base is None or performance_day is None:
            raise ValueError(f"Contratos incompletos para {date}")
        included = bool(source.get("includedInCusum"))
        if included != bool(base.get("includedInPeriodIndex")):
            raise ValueError(f"Máscara Base 100/CUSUM inconsistente para {date}")
        residual = source.get("residualKWh") if included else None

        economic = float(residual) * tariff if residual is not None and tariff is not None else None
        environmental = (
            float(residual) * emission_factor
            if residual is not None and emission_factor is not None else None
        )
        if not included:
            economic_status = environmental_status = "INSUFFICIENT_DATA"
        else:
            economic_status = (
                "VALID_PRELIMINARY" if tariff is not None
                else "TARIFF_NOT_CONFIGURED"
            )
            environmental_status = (
                "VALID_PRELIMINARY" if emission_factor is not None
                else "EMISSION_FACTOR_NOT_CONFIGURED"
            )
        daily.append({
            "productionDate": date,
            "residualKWh": residual,
            "includedInImpact": included,
            "exclusionReasons": list(source.get("exclusionReasons") or []),
            "energyTariffCopPerKWh": tariff,
            "economicImpactCop": round(economic, 9) if economic is not None else None,
            "estimatedAvoidedCostCop": (
                round(abs(economic), 9) if economic is not None and economic < 0
                else 0.0 if economic is not None else None
            ),
            "estimatedAdditionalCostCop": (
                round(economic, 9) if economic is not None and economic > 0
                else 0.0 if economic is not None else None
            ),
            "emissionFactorKgCo2ePerKWh": emission_factor,
            "co2eImpactKg": (
                round(environmental, 9) if environmental is not None else None
            ),
            "estimatedAvoidedEmissionsKgCo2e": (
                round(abs(environmental), 9)
                if environmental is not None and environmental < 0
                else 0.0 if environmental is not None else None
            ),
            "estimatedAdditionalEmissionsKgCo2e": (
                round(environmental, 9)
                if environmental is not None and environmental > 0
                else 0.0 if environmental is not None else None
            ),
            "base100Index": source.get("base100Index"),
            "cusumKWh": source.get("cusumKWh"),
            "economicEvaluationStatus": economic_status,
            "environmentalEvaluationStatus": environmental_status,
            "qualityFlags": list(source.get("qualityFlags") or []),
            "modelVersion": source.get("modelVersion"),
            "tariffVersion": inputs["tariffVersion"],
            "emissionFactorVersion": inputs["emissionFactorVersion"],
        })

    included_days = [day for day in daily if day["includedInImpact"]]
    economic_valid = tariff is not None and bool(included_days)
    environmental_valid = emission_factor is not None and bool(included_days)
    summary = {
        "requestedDays": (cusum.get("summary") or {}).get("requestedDays"),
        "periodResidualKWh": period_residual,
        "periodEconomicImpactCop": (
            round(sum(day["economicImpactCop"] for day in included_days), 6)
            if economic_valid else None
        ),
        "periodEstimatedAvoidedCostCop": (
            round(sum(day["estimatedAvoidedCostCop"] for day in included_days), 6)
            if economic_valid else None
        ),
        "periodEstimatedAdditionalCostCop": (
            round(sum(day["estimatedAdditionalCostCop"] for day in included_days), 6)
            if economic_valid else None
        ),
        "periodCo2eImpactKg": (
            round(sum(day["co2eImpactKg"] for day in included_days), 6)
            if environmental_valid else None
        ),
        "periodEstimatedAvoidedEmissionsKgCo2e": (
            round(sum(day["estimatedAvoidedEmissionsKgCo2e"] for day in included_days), 6)
            if environmental_valid else None
        ),
        "periodEstimatedAdditionalEmissionsKgCo2e": (
            round(sum(day["estimatedAdditionalEmissionsKgCo2e"] for day in included_days), 6)
            if environmental_valid else None
        ),
        "evaluableDays": len(included_days),
        "excludedDays": len(daily) - len(included_days),
        "energyTariffCopPerKWh": tariff,
        "emissionFactorKgCo2ePerKWh": emission_factor,
        "economicEvaluationStatus": (
            "VALID_PRELIMINARY" if economic_valid
            else "TARIFF_NOT_CONFIGURED" if tariff is None
            else "INSUFFICIENT_DATA"
        ),
        "environmentalEvaluationStatus": (
            "VALID_PRELIMINARY" if environmental_valid
            else "EMISSION_FACTOR_NOT_CONFIGURED" if emission_factor is None
            else "INSUFFICIENT_DATA"
        ),
        "currency": "COP",
        "methodologyStatus": "PRELIMINARY_ESTIMATE",
    }
    methodology = {
        "sourceContracts": [
            "SUBPHASE_3_1_DAILY_PERFORMANCE",
            "SUBPHASE_3_2_BASE100",
            "SUBPHASE_3_3_CUSUM",
        ],
        "residualSource": "SUBPHASE_3_3_RESIDUAL_KWH",
        "inclusionMask": "SUBPHASE_3_3_INCLUDED_IN_CUSUM",
        "periodResidualSource": "SUBPHASE_3_3_TOTAL_RESIDUAL_KWH",
        "economicUnit": "COP",
        "tariffUnit": "COP/kWh",
        "environmentalUnit": "kgCO2e",
        "emissionFactorUnit": "kgCO2e/kWh",
        "requestOverridesPersisted": False,
        "externalSourcesQueried": False,
        "verifiedSavings": False,
        "certifiedEmissionReduction": False,
        "resultType": "PRELIMINARY_ESTIMATE",
    }
    return {
        "ranges": deepcopy(performance.get("ranges")),
        "inputs": inputs,
        "daily": daily,
        "summary": summary,
        "methodology": methodology,
        "quality": deepcopy(performance.get("quality")),
    }
