import sqlite3
import sys
import types
import unittest
from pathlib import Path

if "dotenv" not in sys.modules:
    dotenv_stub = types.ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *args, **kwargs: None
    sys.modules["dotenv"] = dotenv_stub

from db.aoki_base100 import build_base100_contract
from db.aoki_cusum import build_cusum_contract
from db.aoki_daily_performance import build_daily_performance


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "data" / "samee200.db"
START = 1777633200
END = 1780311600
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


@unittest.skipUnless(DATABASE.exists(), "La base histórica local no está disponible")
class MayCusumIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.connection = sqlite3.connect(
            f"file:{DATABASE.resolve()}?mode=ro&immutable=1", uri=True
        )
        cls.connection.row_factory = sqlite3.Row
        performance = build_daily_performance(
            cls.connection, START, END, model=MODEL
        )
        base100 = build_base100_contract(performance)
        cls.result = build_cusum_contract(performance, base100)

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()

    def test_may_counts_and_exclusions_match_base100(self):
        summary = self.result["summary"]
        self.assertEqual(summary["requestedDays"], 31)
        self.assertEqual(summary["evaluableDays"], 28)
        self.assertEqual(summary["excludedDays"], 3)
        self.assertEqual(summary["missingDays"], 0)
        excluded = {
            day["productionDate"]: day for day in self.result["daily"]
            if not day["includedInCusum"]
        }
        self.assertEqual(set(excluded), {
            "2026-05-08", "2026-05-20", "2026-05-21"
        })
        self.assertTrue(all(
            "LOW_STATE_COVERAGE" in day["exclusionReasons"]
            for day in excluded.values()
        ))

    def test_may_numeric_controls(self):
        summary = self.result["summary"]
        self.assertAlmostEqual(summary["totalResidualKWh"], 669.871255, places=5)
        self.assertAlmostEqual(summary["finalCusumKWh"], 669.871255, places=5)
        self.assertAlmostEqual(summary["favorableAccumulatedKWh"], 198.324447, places=5)
        self.assertAlmostEqual(summary["unfavorableAccumulatedKWh"], 868.195702, places=5)
        self.assertAlmostEqual(summary["finalPositiveCusumKWh"], 669.871255, places=5)
        self.assertEqual(summary["finalNegativeCusumKWh"], 0)
        self.assertAlmostEqual(summary["periodKnownEnergyKWh"], 25908.855474, places=5)
        self.assertAlmostEqual(summary["periodExpectedEnergyKWh"], 25238.984219, places=5)
        # Se copia la precisión publicada por el contrato 3.1; no se recalcula.
        self.assertAlmostEqual(summary["periodDeviationPct"], 2.654113, places=4)
        self.assertAlmostEqual(summary["periodBase100Index"], 102.654113, places=5)
        self.assertAlmostEqual(
            summary["unfavorableAccumulatedKWh"]
            - summary["favorableAccumulatedKWh"],
            summary["finalCusumKWh"],
            places=5,
        )

    def test_excluded_days_preserve_horizontal_continuity(self):
        by_date = {day["productionDate"]: day for day in self.result["daily"]}
        controls = {
            "2026-05-08": 70.725818,
            "2026-05-20": 302.083737,
            "2026-05-21": 302.083737,
        }
        for date, expected_cusum in controls.items():
            with self.subTest(date=date):
                self.assertIsNone(by_date[date]["cusumContributionKWh"])
                self.assertIsNone(by_date[date]["residualKWh"])
                self.assertAlmostEqual(by_date[date]["cusumKWh"], expected_cusum, places=5)

    def test_range_order_versions_and_reset(self):
        ranges = self.result["ranges"]
        self.assertEqual(ranges["requestedRange"]["startUtc"], START)
        self.assertEqual(ranges["requestedRange"]["endUtc"], END)
        self.assertTrue(ranges["startInclusive"])
        self.assertTrue(ranges["endExclusive"])
        dates = [day["productionDate"] for day in self.result["daily"]]
        self.assertEqual(len(dates), len(set(dates)))
        self.assertEqual(dates, sorted(dates))
        self.assertEqual(self.result["summary"]["resetPolicy"], "RANGE_START_ZERO")
        self.assertEqual(
            self.result["summary"]["calculationMethod"],
            "SIGNED_RESIDUAL_CUMSUM",
        )
        self.assertTrue(all(
            day["performanceQualityVersion"] for day in self.result["daily"]
        ))


if __name__ == "__main__":
    unittest.main()
