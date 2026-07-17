import sys
import types
import unittest

if "dotenv" not in sys.modules:
    dotenv_stub = types.ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *args, **kwargs: None
    sys.modules["dotenv"] = dotenv_stub

from db.aoki_daily_performance import calculate_daily_performance


START = 1777633200
END = START + 86400
MODEL = {
    "nombre_modelo": "LB_AOKI_ENVASES_HORAS_PRODUCTIVAS",
    "intercepto": 514.50,
    "coef_envases_buenos": 0.005018,
    "coef_horas_productivas": 16.5198,
    "r2": 0.9278,
    "r2_ajustado": 0.9248,
    "cv_rmse_pct": 3.64,
    "oficial": True,
}
QUALITY = {
    "version": "test-quality-v1",
    "status": "PROVISIONAL_QUALITY_THRESHOLDS",
    "minimumEnergyCoveragePct": 98,
    "minimumStateCoveragePct": 98,
    "maximumReconstructedEnergyPct": 20,
}


def state(productive=10, coverage=100, inconsistent=0):
    return {
        "daily": [{
            "productionDate": "2026-05-01", "productiveHours": productive,
            "idleHours": 10, "offHours": 4, "noDataHours": 0,
            "coveragePct": coverage, "inconsistentHours": inconsistent,
        }],
        "periodSummary": {"knownDataHours": coverage * 24 / 100},
        "thresholds": {"version": "state-v1"},
    }


def energy(measured=700, reconstructed=0, no_data_seconds=0, source=None):
    intervals = []
    if measured is not None:
        intervals.append({
            "productionDate": "2026-05-01", "durationSeconds": 86400 - no_data_seconds,
            "source": source or "ACCUMULATOR_DELTA", "energyKWh": measured,
        })
    if reconstructed:
        intervals.append({
            "productionDate": "2026-05-01", "durationSeconds": 3600,
            "source": "POWER_TRAPEZOIDAL", "energyKWh": reconstructed,
        })
    if no_data_seconds:
        intervals.append({
            "productionDate": "2026-05-01", "durationSeconds": no_data_seconds,
            "source": "NO_DATA", "energyKWh": None,
        })
    known_seconds = sum(i["durationSeconds"] for i in intervals if i["source"] != "NO_DATA")
    return {
        "intervals": intervals,
        "periodSummary": {"knownDurationHours": known_seconds / 3600},
        "config": {"version": "energy-v1"},
    }


def production(good=1000, bad=10, total=None):
    return {"2026-05-01": {
        "goodUnits": good, "badUnits": bad,
        "totalUnits": good + bad if total is None and good is not None else total,
    }}


def calculate(prod=None, states=None, energies=None):
    return calculate_daily_performance(
        START, END, production() if prod is None else prod,
        state() if states is None else states,
        energy() if energies is None else energies,
        MODEL, QUALITY,
    )


class DailyPerformanceTests(unittest.TestCase):
    def test_official_formula_and_daily_intercept(self):
        result = calculate()
        expected = 514.50 + 0.005018 * 1000 + 16.5198 * 10
        self.assertAlmostEqual(result["daily"][0]["expectedEnergyKWh"], expected, places=6)
        self.assertAlmostEqual(result["summary"]["totalExpectedEnergyKWh"], expected, places=6)
        self.assertEqual(result["model"]["interceptApplication"], "ONCE_PER_EVALUABLE_DAY")

    def test_total_units_is_not_used_by_formula(self):
        first = calculate(production(1000, 10, 1010))["daily"][0]["expectedEnergyKWh"]
        second = calculate(production(1000, 10, 999999))["daily"][0]["expectedEnergyKWh"]
        self.assertEqual(first, second)

    def test_measured_plus_reconstructed_is_known(self):
        item = calculate(energies=energy(600, 100))["daily"][0]
        self.assertEqual(item["knownEnergyKWh"], 700)
        self.assertIn("ENERGY_PARTIALLY_RECONSTRUCTED", item["qualityFlags"])

    def test_unrecoverable_energy_remains_null(self):
        item = calculate(energies=energy(600, 0, 3600))["daily"][0]
        self.assertIsNone(item["unrecoverableEnergyKWh"])
        self.assertIn("LOW_ENERGY_COVERAGE", item["qualityFlags"])
        complete = calculate()["daily"][0]
        self.assertIsNone(complete["unrecoverableEnergyKWh"])

    def test_missing_production_is_insufficient(self):
        item = calculate(prod={})["daily"][0]
        self.assertIsNone(item["expectedEnergyKWh"])
        self.assertIsNone(item["residualKWh"])
        self.assertIsNone(item["deviationPct"])
        self.assertEqual(item["evaluationStatus"], "INSUFFICIENT_INPUTS")

    def test_missing_productive_hours_is_insufficient(self):
        item = calculate(states=state(productive=None))["daily"][0]
        self.assertIsNone(item["expectedEnergyKWh"])
        self.assertEqual(item["evaluationStatus"], "INSUFFICIENT_INPUTS")

    def test_low_state_coverage_and_inconsistent_signals_are_visible(self):
        item = calculate(states=state(coverage=90, inconsistent=1))["daily"][0]
        self.assertEqual(item["evaluationStatus"], "EXCLUDED_FROM_EVALUATION")
        self.assertIn("LOW_STATE_COVERAGE", item["qualityFlags"])
        self.assertIn("INCONSISTENT_SIGNALS", item["qualityFlags"])

    def test_high_reconstruction_is_excluded(self):
        item = calculate(energies=energy(500, 200))["daily"][0]
        self.assertGreater(item["reconstructedEnergyPct"], 20)
        self.assertIn("ENERGY_PARTIALLY_RECONSTRUCTED", item["qualityFlags"])
        self.assertIn("EXCLUDED_FROM_EVALUATION", item["qualityFlags"])

    def test_performance_classifications_use_cv_rmse(self):
        expected = 514.50 + 0.005018 * 1000 + 16.5198 * 10
        cases = [
            (expected * 0.95, "FAVORABLE_PRELIMINARY"),
            (expected, "NEUTRAL_WITHIN_MODEL_VARIABILITY"),
            (expected * 1.05, "UNFAVORABLE_PRELIMINARY"),
        ]
        for known, classification in cases:
            with self.subTest(classification=classification):
                item = calculate(energies=energy(known))["daily"][0]
                self.assertEqual(item["performanceClassification"], classification)

    def test_versions_sources_and_provisional_quality_are_exposed(self):
        result = calculate()
        item = result["daily"][0]
        self.assertEqual(item["productiveHoursSource"], "ELECTRICAL_CLASSIFICATION_PRELIMINARY")
        self.assertEqual(item["energyReconstructionVersion"], "energy-v1")
        self.assertEqual(item["stateThresholdVersion"], "state-v1")
        self.assertEqual(result["quality"]["status"], "PROVISIONAL_QUALITY_THRESHOLDS")
        self.assertFalse(result["methodology"]["currentModelUsed"])
        self.assertNotIn("CURRENT_MODEL", result["methodology"]["energySourcesAllowed"])

    def test_current_model_energy_is_not_accepted(self):
        item = calculate(energies=energy(700, source="CURRENT_MODEL"))["daily"][0]
        self.assertIsNone(item["knownEnergyKWh"])
        self.assertIsNone(item["unrecoverableEnergyKWh"])
        self.assertEqual(item["evaluationStatus"], "INSUFFICIENT_INPUTS")


if __name__ == "__main__":
    unittest.main()
