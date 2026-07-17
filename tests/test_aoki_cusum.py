import copy
import inspect
import unittest

from db import aoki_cusum
from db.aoki_cusum import build_cusum_contract


def ranges(start="2026-05-01T06:00:00-05:00",
           end="2026-05-04T06:00:00-05:00"):
    return {
        "requestedRange": {
            "startUtc": 1, "endUtc": 2,
            "startLocal": start, "endLocal": end,
        },
        "timezone": "America/Bogota",
        "startInclusive": True,
        "endExclusive": True,
    }


def performance_day(date, residual, classification="NEUTRAL_WITHIN_MODEL_VARIABILITY"):
    return {
        "productionDate": date,
        "knownEnergyKWh": 100,
        "expectedEnergyKWh": 100,
        "residualKWh": residual,
        "performanceClassification": classification,
        "energyCoveragePct": 100,
        "stateCoveragePct": 100,
        "reconstructedEnergyPct": 0,
        "qualityFlags": ["VALID_PRELIMINARY"],
        "modelVersion": "model-v1",
    }


def base_day(date, included=True, index=100, reasons=None):
    return {
        "productionDate": date,
        "includedInPeriodIndex": included,
        "base100Index": index if included else None,
        "exclusionReasons": list(reasons or []),
        "qualityFlags": ["BASE100_VALID_PRELIMINARY"] if included else ["BASE100_INSUFFICIENT_DATA"],
        "performanceQualityVersion": "quality-v1",
    }


def contracts(residuals=(10, -20, 0), included=(True, True, True)):
    dates = [f"2026-05-0{index + 1}" for index in range(len(residuals))]
    performance = {
        "ranges": ranges(end=f"2026-05-0{len(residuals) + 1}T06:00:00-05:00"),
        "model": {"nombre_modelo": "model-v1"},
        "quality": {"thresholds": {"version": "quality-v1"}},
        "methodology": {"interval": "[inicio, fin)"},
        "summary": {"totalDeviationPct": -3.5},
        "daily": [
            performance_day(date, residual)
            for date, residual in zip(dates, residuals)
        ],
    }
    base100 = {
        "ranges": copy.deepcopy(performance["ranges"]),
        "model": copy.deepcopy(performance["model"]),
        "quality": copy.deepcopy(performance["quality"]),
        "methodology": {},
        "summary": {
            "periodKnownEnergyKWh": 280,
            "periodExpectedEnergyKWh": 300,
            "periodBase100Index": 93.333333,
        },
        "daily": [
            base_day(date, allowed, reasons=[] if allowed else ["LOW_STATE_COVERAGE"])
            for date, allowed in zip(dates, included)
        ],
    }
    return performance, base100


class CusumTests(unittest.TestCase):
    def test_signed_positive_negative_and_zero_residuals(self):
        result = build_cusum_contract(*contracts())
        daily = result["daily"]
        self.assertEqual(daily[0]["cusumKWh"], 10)
        self.assertEqual(daily[1]["cusumKWh"], -10)
        self.assertEqual(daily[2]["cusumKWh"], -10)
        self.assertEqual(daily[0]["positiveCusumKWh"], 10)
        self.assertEqual(daily[1]["positiveCusumKWh"], 0)
        self.assertEqual(daily[1]["negativeCusumKWh"], -20)
        self.assertEqual(daily[2]["cusumContributionKWh"], 0)

    def test_excluded_day_is_null_and_carries_all_series(self):
        result = build_cusum_contract(*contracts(
            residuals=(10, 999, -5), included=(True, False, True)
        ))
        excluded = result["daily"][1]
        self.assertIsNone(excluded["residualKWh"])
        self.assertIsNone(excluded["cusumContributionKWh"])
        self.assertEqual(excluded["cusumKWh"], 10)
        self.assertEqual(excluded["positiveCusumKWh"], 10)
        self.assertEqual(excluded["negativeCusumKWh"], 0)
        self.assertIn("LOW_STATE_COVERAGE", excluded["exclusionReasons"])
        self.assertEqual(result["summary"]["finalCusumKWh"], 5)

    def test_missing_day_is_explicit_and_does_not_contribute(self):
        performance, base100 = contracts(residuals=(10, 20, 30))
        performance["daily"].pop(1)
        base100["daily"].pop(1)
        result = build_cusum_contract(performance, base100)
        missing = result["daily"][1]
        self.assertEqual(missing["productionDate"], "2026-05-02")
        self.assertIn("MISSING_DAY", missing["exclusionReasons"])
        self.assertFalse(missing["includedInCusum"])
        self.assertIsNone(missing["cusumContributionKWh"])
        self.assertEqual(missing["cusumKWh"], 10)
        self.assertEqual(result["summary"]["missingDays"], 1)

    def test_final_totals_are_distinct_and_signed(self):
        result = build_cusum_contract(*contracts(residuals=(10, -20, 5)))
        summary = result["summary"]
        self.assertEqual(summary["totalResidualKWh"], -5)
        self.assertEqual(summary["finalCusumKWh"], -5)
        self.assertEqual(summary["favorableAccumulatedKWh"], 20)
        self.assertEqual(summary["unfavorableAccumulatedKWh"], 15)
        self.assertEqual(summary["finalPositiveCusumKWh"], 5)
        self.assertEqual(summary["finalNegativeCusumKWh"], -15)

    def test_reset_is_zero_for_every_call_without_carry(self):
        first = build_cusum_contract(*contracts(residuals=(50,)))
        second = build_cusum_contract(*contracts(residuals=(-10,)))
        self.assertEqual(first["daily"][0]["cusumKWh"], 50)
        self.assertEqual(second["daily"][0]["cusumKWh"], -10)
        self.assertEqual(second["summary"]["resetPolicy"], "RANGE_START_ZERO")

    def test_base100_totals_are_copied_not_recalculated(self):
        performance, base100 = contracts()
        result = build_cusum_contract(performance, base100)
        self.assertEqual(result["summary"]["periodKnownEnergyKWh"], 280)
        self.assertEqual(result["summary"]["periodExpectedEnergyKWh"], 300)
        self.assertEqual(result["summary"]["periodBase100Index"], 93.333333)
        self.assertEqual(result["summary"]["periodDeviationPct"], -3.5)

    def test_inputs_are_not_mutated_and_residual_is_copied(self):
        performance, base100 = contracts(residuals=(12.345678,))
        original_performance = copy.deepcopy(performance)
        original_base100 = copy.deepcopy(base100)
        result = build_cusum_contract(performance, base100)
        self.assertEqual(performance, original_performance)
        self.assertEqual(base100, original_base100)
        self.assertEqual(result["daily"][0]["residualKWh"], 12.345678)

    def test_rows_are_sorted_and_duplicates_are_rejected(self):
        performance, base100 = contracts()
        performance["daily"].reverse()
        base100["daily"].reverse()
        result = build_cusum_contract(performance, base100)
        dates = [day["productionDate"] for day in result["daily"]]
        self.assertEqual(dates, sorted(dates))
        performance["daily"].append(copy.deepcopy(performance["daily"][0]))
        with self.assertRaisesRegex(ValueError, "fecha duplicada"):
            build_cusum_contract(performance, base100)

    def test_service_has_no_database_or_statistical_alarm_dependencies(self):
        source = inspect.getsource(aoki_cusum).lower()
        self.assertNotIn("sqlite", source)
        self.assertNotIn("get_conn", source)
        self.assertNotIn("query_", source)
        self.assertNotIn("v-mask", source)
        self.assertNotIn('"k"', source)
        self.assertNotIn('"h"', source)
        result = build_cusum_contract(*contracts())
        self.assertFalse(result["methodology"]["statisticalDecisionParametersUsed"])
        self.assertFalse(result["methodology"]["alarmsImplemented"])
        self.assertIn("NOT_CONFIRMED_SAVINGS", result["methodology"]["resultType"])


if __name__ == "__main__":
    unittest.main()
