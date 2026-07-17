import copy
import inspect
import unittest

from db import aoki_impact
from db.aoki_impact import build_impact_contract


FACTORS_EMPTY = {
    "version": "impact-factors-v1",
    "currency": "COP",
    "energyTariffCopPerKWh": None,
    "tariffSource": None,
    "tariffEffectiveDate": None,
    "emissionFactorKgCo2ePerKWh": None,
    "emissionFactorSource": None,
    "emissionFactorEffectiveDate": None,
}


def contracts(residuals=(-10, 20, 0), included=(True, True, True)):
    dates = [f"2026-05-0{index + 1}" for index in range(len(residuals))]
    performance_daily = []
    base_daily = []
    cusum_daily = []
    accumulated = 0
    for date, residual, allowed in zip(dates, residuals, included):
        performance_daily.append({
            "productionDate": date, "residualKWh": residual,
            "knownEnergyKWh": 100, "expectedEnergyKWh": 100,
            "qualityFlags": ["VALID_PRELIMINARY"], "modelVersion": "model-v1",
        })
        base_daily.append({
            "productionDate": date, "includedInPeriodIndex": allowed,
            "base100Index": 100 if allowed else None,
            "exclusionReasons": [] if allowed else ["LOW_STATE_COVERAGE"],
            "performanceQualityVersion": "quality-v1",
        })
        if allowed:
            accumulated += residual
        cusum_daily.append({
            "productionDate": date,
            "residualKWh": residual if allowed else None,
            "includedInCusum": allowed,
            "exclusionReasons": [] if allowed else ["LOW_STATE_COVERAGE"],
            "base100Index": 100 if allowed else None,
            "cusumKWh": accumulated,
            "qualityFlags": ["VALID_PRELIMINARY"] if allowed else ["LOW_STATE_COVERAGE"],
            "modelVersion": "model-v1",
            "performanceQualityVersion": "quality-v1",
        })
    period_residual = sum(
        residual for residual, allowed in zip(residuals, included) if allowed
    )
    common = {
        "ranges": {
            "requestedRange": {
                "startUtc": 1, "endUtc": 2,
                "startLocal": "2026-05-01T06:00:00-05:00",
                "endLocal": f"2026-05-0{len(dates) + 1}T06:00:00-05:00",
            },
            "timezone": "America/Bogota",
            "startInclusive": True, "endExclusive": True,
        },
        "model": {"nombre_modelo": "model-v1"},
        "quality": {"thresholds": {"version": "quality-v1"}},
        "methodology": {},
    }
    performance = {
        **copy.deepcopy(common), "daily": performance_daily,
        "summary": {"totalResidualKWh": period_residual},
    }
    base100 = {
        **copy.deepcopy(common), "daily": base_daily,
        "summary": {"periodBase100Index": 100},
    }
    cusum = {
        **copy.deepcopy(common), "daily": cusum_daily,
        "summary": {
            "requestedDays": len(dates),
            "totalResidualKWh": period_residual,
            "finalCusumKWh": period_residual,
        },
    }
    return performance, base100, cusum


def impact(factors=None, overrides=None, residuals=(-10, 20, 0),
           included=(True, True, True)):
    return build_impact_contract(
        *contracts(residuals, included),
        factors=FACTORS_EMPTY if factors is None else factors,
        request_overrides=overrides,
    )


class ImpactTests(unittest.TestCase):
    def test_missing_factors_remain_null(self):
        result = impact()
        summary = result["summary"]
        self.assertIsNone(summary["periodEconomicImpactCop"])
        self.assertIsNone(summary["periodCo2eImpactKg"])
        self.assertEqual(summary["economicEvaluationStatus"], "TARIFF_NOT_CONFIGURED")
        self.assertEqual(
            summary["environmentalEvaluationStatus"],
            "EMISSION_FACTOR_NOT_CONFIGURED",
        )
        for day in result["daily"]:
            self.assertIsNone(day["economicImpactCop"])
            self.assertIsNone(day["co2eImpactKg"])

    def test_favorable_unfavorable_and_zero_with_fictitious_factors(self):
        result = impact(overrides={
            "energyTariffCopPerKWh": 1000,
            "emissionFactorKgCo2ePerKWh": 0.2,
        })
        favorable, unfavorable, neutral = result["daily"]
        self.assertEqual(favorable["economicImpactCop"], -10000)
        self.assertEqual(favorable["estimatedAvoidedCostCop"], 10000)
        self.assertEqual(favorable["estimatedAdditionalCostCop"], 0)
        self.assertEqual(unfavorable["economicImpactCop"], 20000)
        self.assertEqual(unfavorable["estimatedAvoidedCostCop"], 0)
        self.assertEqual(unfavorable["estimatedAdditionalCostCop"], 20000)
        self.assertEqual(neutral["economicImpactCop"], 0)
        self.assertEqual(favorable["co2eImpactKg"], -2)
        self.assertEqual(favorable["estimatedAvoidedEmissionsKgCo2e"], 2)
        self.assertEqual(unfavorable["estimatedAdditionalEmissionsKgCo2e"], 4)

    def test_zero_factors_are_valid_not_missing(self):
        result = impact(overrides={
            "energyTariffCopPerKWh": 0,
            "emissionFactorKgCo2ePerKWh": 0,
        })
        self.assertEqual(result["summary"]["periodEconomicImpactCop"], 0)
        self.assertEqual(result["summary"]["periodCo2eImpactKg"], 0)
        self.assertEqual(result["summary"]["economicEvaluationStatus"], "VALID_PRELIMINARY")
        self.assertEqual(
            result["summary"]["environmentalEvaluationStatus"],
            "VALID_PRELIMINARY",
        )

    def test_negative_and_invalid_factors_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "mayor o igual a cero"):
            impact(overrides={"energyTariffCopPerKWh": -1})
        with self.assertRaisesRegex(ValueError, "mayor o igual a cero"):
            impact(overrides={"emissionFactorKgCo2ePerKWh": -0.1})
        with self.assertRaisesRegex(ValueError, "numérico"):
            impact(overrides={"energyTariffCopPerKWh": "abc"})

    def test_excluded_day_has_null_impacts_even_with_factors(self):
        result = impact(
            overrides={
                "energyTariffCopPerKWh": 1000,
                "emissionFactorKgCo2ePerKWh": 0.2,
            },
            residuals=(10, 999), included=(True, False),
        )
        excluded = result["daily"][1]
        self.assertFalse(excluded["includedInImpact"])
        self.assertIsNone(excluded["residualKWh"])
        self.assertIsNone(excluded["economicImpactCop"])
        self.assertIsNone(excluded["estimatedAvoidedCostCop"])
        self.assertIsNone(excluded["co2eImpactKg"])
        self.assertEqual(excluded["economicEvaluationStatus"], "INSUFFICIENT_DATA")
        self.assertIn("LOW_STATE_COVERAGE", excluded["exclusionReasons"])

    def test_period_is_sum_of_evaluable_daily_impacts(self):
        result = impact(overrides={
            "energyTariffCopPerKWh": 1000,
            "emissionFactorKgCo2ePerKWh": 0.2,
        })
        included = [day for day in result["daily"] if day["includedInImpact"]]
        self.assertEqual(
            result["summary"]["periodEconomicImpactCop"],
            sum(day["economicImpactCop"] for day in included),
        )
        self.assertEqual(
            result["summary"]["periodCo2eImpactKg"],
            sum(day["co2eImpactKg"] for day in included),
        )
        self.assertEqual(result["summary"]["periodResidualKWh"], 10)

    def test_request_override_metadata_is_ephemeral_and_inputs_are_pure(self):
        performance, base100, cusum = contracts()
        factors = copy.deepcopy(FACTORS_EMPTY)
        originals = tuple(copy.deepcopy(item) for item in (
            performance, base100, cusum, factors
        ))
        result = build_impact_contract(
            performance, base100, cusum, factors,
            {"energyTariffCopPerKWh": "1000",
             "emissionFactorKgCo2ePerKWh": "0.2"},
        )
        self.assertEqual((performance, base100, cusum, factors), originals)
        self.assertEqual(result["inputs"]["tariffOrigin"], "REQUEST_OVERRIDE")
        self.assertEqual(
            result["inputs"]["emissionFactorOrigin"], "REQUEST_OVERRIDE"
        )
        self.assertEqual(
            result["inputs"]["tariffVersion"], "REQUEST_OVERRIDE_EPHEMERAL"
        )
        self.assertFalse(result["methodology"]["requestOverridesPersisted"])

    def test_units_currency_versions_and_sources(self):
        configured = {
            **FACTORS_EMPTY,
            "energyTariffCopPerKWh": 800,
            "tariffSource": "TEST_DOCUMENT",
            "tariffEffectiveDate": "2026-01-01",
            "emissionFactorKgCo2ePerKWh": 0.1,
            "emissionFactorSource": "TEST_DOCUMENT",
            "emissionFactorEffectiveDate": "2026-01-01",
        }
        result = impact(factors=configured)
        inputs = result["inputs"]
        self.assertEqual(inputs["currency"], "COP")
        self.assertEqual(inputs["energyTariffUnit"], "COP/kWh")
        self.assertEqual(inputs["emissionFactorUnit"], "kgCO2e/kWh")
        self.assertEqual(inputs["tariffSource"], "TEST_DOCUMENT")
        self.assertEqual(inputs["tariffVersion"], "impact-factors-v1")
        self.assertEqual(inputs["emissionFactorVersion"], "impact-factors-v1")

    def test_local_numeric_factors_require_traceable_metadata(self):
        with self.assertRaisesRegex(ValueError, "fuente, fecha efectiva y versión"):
            impact(factors={**FACTORS_EMPTY, "energyTariffCopPerKWh": 800})
        with self.assertRaisesRegex(ValueError, "fuente, fecha efectiva y versión"):
            impact(factors={
                **FACTORS_EMPTY, "emissionFactorKgCo2ePerKWh": 0.1
            })

    def test_service_has_no_database_legacy_defaults_or_external_queries(self):
        source = inspect.getsource(aoki_impact).lower()
        self.assertNotIn("sqlite", source)
        self.assertNotIn("get_conn", source)
        self.assertNotIn("query_", source)
        self.assertNotIn('"950"', source)
        self.assertNotIn('"0.164"', source)
        result = impact()
        self.assertFalse(result["methodology"]["externalSourcesQueried"])
        self.assertFalse(result["methodology"]["verifiedSavings"])
        self.assertFalse(result["methodology"]["certifiedEmissionReduction"])


if __name__ == "__main__":
    unittest.main()
