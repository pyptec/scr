import copy
import unittest

from db.aoki_base100 import build_base100_contract


def contract(days):
    return {
        "ranges": {
            "requestedRange": {"startUtc": 1, "endUtc": 2},
            "timezone": "America/Bogota",
            "startInclusive": True,
            "endExclusive": True,
        },
        "model": {
            "nombre_modelo": "LB_AOKI_ENVASES_HORAS_PRODUCTIVAS",
            "cv_rmse_pct": 3.64,
        },
        "quality": {
            "thresholds": {
                "version": "quality-v1",
                "maximumReconstructedEnergyPct": 20,
            }
        },
        "methodology": {"interval": "[inicio, fin)"},
        "daily": days,
    }


def day(known=100, expected=100, status="VALID_PRELIMINARY",
        flags=None, reconstructed=0, date="2026-05-01"):
    return {
        "productionDate": date,
        "knownEnergyKWh": known,
        "expectedEnergyKWh": expected,
        "evaluationStatus": status,
        "energyCoveragePct": 100,
        "stateCoveragePct": 100,
        "reconstructedEnergyPct": reconstructed,
        "qualityFlags": list(flags or ["VALID_PRELIMINARY"]),
        "modelVersion": "model-v1",
    }


class Base100Tests(unittest.TestCase):
    def test_equal_to_100_is_neutral(self):
        item = build_base100_contract(contract([day()]))["daily"][0]
        self.assertEqual(item["base100Index"], 100)
        self.assertEqual(item["base100Classification"], "NEUTRAL_WITHIN_MODEL_VARIABILITY")

    def test_classification_limits_come_from_model_variability(self):
        cases = [
            (96.35, "FAVORABLE_PRELIMINARY"),
            (96.36, "NEUTRAL_WITHIN_MODEL_VARIABILITY"),
            (103.64, "NEUTRAL_WITHIN_MODEL_VARIABILITY"),
            (103.65, "UNFAVORABLE_PRELIMINARY"),
        ]
        for index, expected_classification in cases:
            with self.subTest(index=index):
                item = build_base100_contract(
                    contract([day(known=index, expected=100)])
                )["daily"][0]
                self.assertEqual(item["base100Classification"], expected_classification)

    def test_zero_expected_is_null_not_zero(self):
        item = build_base100_contract(contract([day(expected=0)]))["daily"][0]
        self.assertIsNone(item["base100Index"])
        self.assertFalse(item["includedInPeriodIndex"])
        self.assertIn("EXPECTED_ENERGY_NOT_POSITIVE", item["exclusionReasons"])

    def test_missing_known_energy_is_null_not_zero(self):
        item = build_base100_contract(contract([day(known=None)]))["daily"][0]
        self.assertIsNone(item["base100Index"])
        self.assertEqual(item["base100Classification"], "INSUFFICIENT_DATA")
        self.assertIn("KNOWN_ENERGY_MISSING", item["exclusionReasons"])

    def test_excluded_day_preserves_and_maps_quality_flags(self):
        source = day(
            status="EXCLUDED_FROM_EVALUATION",
            flags=["LOW_STATE_COVERAGE", "EXCLUDED_FROM_EVALUATION"],
        )
        item = build_base100_contract(contract([source]))["daily"][0]
        self.assertFalse(item["includedInPeriodIndex"])
        self.assertIsNone(item["base100Index"])
        self.assertIn("LOW_STATE_COVERAGE", item["qualityFlags"])
        self.assertIn("BASE100_LOW_STATE_COVERAGE", item["qualityFlags"])
        self.assertIn("BASE100_INSUFFICIENT_DATA", item["qualityFlags"])
        self.assertIn("LOW_STATE_COVERAGE", item["exclusionReasons"])

    def test_quality_mappings_and_version(self):
        source = day(
            status="EXCLUDED_FROM_EVALUATION", reconstructed=25,
            flags=["LOW_ENERGY_COVERAGE", "INCONSISTENT_SIGNALS",
                   "EXCLUDED_FROM_EVALUATION"],
        )
        item = build_base100_contract(contract([source]))["daily"][0]
        self.assertEqual(item["performanceQualityVersion"], "quality-v1")
        self.assertIn("BASE100_LOW_ENERGY_COVERAGE", item["qualityFlags"])
        self.assertIn("BASE100_HIGH_RECONSTRUCTION", item["qualityFlags"])
        self.assertIn("BASE100_INCONSISTENT_SIGNALS", item["qualityFlags"])

    def test_period_uses_ratio_of_sums_not_simple_average(self):
        result = build_base100_contract(contract([
            day(known=50, expected=100, date="2026-05-01"),
            day(known=200, expected=1000, date="2026-05-02"),
        ]))
        summary = result["summary"]
        simple_average = (50 + 20) / 2
        self.assertAlmostEqual(summary["periodBase100Index"], 250 / 1100 * 100, places=6)
        self.assertNotAlmostEqual(summary["periodBase100Index"], simple_average, places=6)
        self.assertEqual(summary["calculationMethod"], "RATIO_OF_SUMS")

    def test_insufficient_and_excluded_days_are_outside_both_sums(self):
        result = build_base100_contract(contract([
            day(100, 100, date="2026-05-01"),
            day(999, 100, status="EXCLUDED_FROM_EVALUATION",
                flags=["LOW_STATE_COVERAGE"], date="2026-05-02"),
            day(None, 100, status="INSUFFICIENT_INPUTS", date="2026-05-03"),
        ]))
        summary = result["summary"]
        self.assertEqual(summary["periodKnownEnergyKWh"], 100)
        self.assertEqual(summary["periodExpectedEnergyKWh"], 100)
        self.assertEqual(summary["includedDays"], 1)
        self.assertEqual(summary["excludedDays"], 1)
        self.assertEqual(summary["insufficientDays"], 1)

    def test_transformation_is_pure_and_does_not_recalculate_inputs(self):
        source = contract([day(known=123.456, expected=111.222)])
        original = copy.deepcopy(source)
        result = build_base100_contract(source)
        self.assertEqual(source, original)
        self.assertEqual(result["daily"][0]["knownEnergyKWh"], 123.456)
        self.assertEqual(result["daily"][0]["expectedEnergyKWh"], 111.222)
        self.assertEqual(result["methodology"]["sourceContract"], "SUBPHASE_3_1_DAILY_PERFORMANCE")

    def test_cusum_is_not_implemented(self):
        result = build_base100_contract(contract([day()]))
        self.assertFalse(result["methodology"]["cusumImplemented"])
        self.assertNotIn("cusum", result["summary"])


if __name__ == "__main__":
    unittest.main()
