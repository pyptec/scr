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
class MayBase100IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.connection = sqlite3.connect(
            f"file:{DATABASE.resolve()}?mode=ro&immutable=1", uri=True
        )
        cls.connection.row_factory = sqlite3.Row
        performance = build_daily_performance(
            cls.connection, START, END, model=MODEL
        )
        cls.result = build_base100_contract(performance)

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()

    def test_requested_included_and_excluded_days(self):
        summary = self.result["summary"]
        self.assertEqual(summary["requestedDays"], 31)
        self.assertEqual(summary["includedDays"], 28)
        self.assertEqual(summary["excludedDays"], 3)
        self.assertEqual(summary["insufficientDays"], 0)
        excluded = {
            day["productionDate"] for day in self.result["daily"]
            if not day["includedInPeriodIndex"]
        }
        self.assertEqual(excluded, {"2026-05-08", "2026-05-20", "2026-05-21"})
        for day in self.result["daily"]:
            if day["productionDate"] in excluded:
                self.assertIn("LOW_STATE_COVERAGE", day["exclusionReasons"])
                self.assertIsNone(day["base100Index"])

    def test_may_ratio_of_sums_controls(self):
        summary = self.result["summary"]
        self.assertAlmostEqual(summary["periodKnownEnergyKWh"], 25908.855474, places=5)
        self.assertAlmostEqual(summary["periodExpectedEnergyKWh"], 25238.984219, places=5)
        self.assertAlmostEqual(summary["periodBase100Index"], 102.654113, places=5)
        self.assertEqual(summary["classification"], "NEUTRAL_WITHIN_MODEL_VARIABILITY")
        simple_average = sum(
            day["base100Index"] for day in self.result["daily"]
            if day["includedInPeriodIndex"]
        ) / summary["includedDays"]
        self.assertAlmostEqual(simple_average, 102.555209, places=5)
        self.assertNotAlmostEqual(simple_average, summary["periodBase100Index"], places=5)

    def test_range_is_half_open_and_end_is_excluded(self):
        ranges = self.result["ranges"]
        self.assertEqual(ranges["requestedRange"]["startUtc"], START)
        self.assertEqual(ranges["requestedRange"]["endUtc"], END)
        self.assertEqual(ranges["timezone"], "America/Bogota")
        self.assertTrue(ranges["startInclusive"])
        self.assertTrue(ranges["endExclusive"])
        self.assertEqual(len(self.result["daily"]), 31)

    def test_contract_versions_and_no_cusum(self):
        self.assertEqual(set(self.result), {
            "ranges", "model", "quality", "daily", "summary", "methodology"
        })
        version = self.result["quality"]["thresholds"]["version"]
        self.assertTrue(version)
        self.assertTrue(all(
            day["performanceQualityVersion"] == version
            for day in self.result["daily"]
        ))
        self.assertFalse(self.result["methodology"]["cusumImplemented"])


if __name__ == "__main__":
    unittest.main()
