import sqlite3
import sys
import types
import unittest
from pathlib import Path

if "dotenv" not in sys.modules:
    dotenv_stub = types.ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *args, **kwargs: None
    sys.modules["dotenv"] = dotenv_stub

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
class MayDailyPerformanceIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.connection = sqlite3.connect(
            f"file:{DATABASE.resolve()}?mode=ro&immutable=1", uri=True
        )
        cls.connection.row_factory = sqlite3.Row
        cls.result = build_daily_performance(cls.connection, START, END, model=MODEL)

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()

    def test_may_has_31_days_and_744_scheduled_hours(self):
        self.assertEqual(len(self.result["daily"]), 31)
        self.assertEqual(self.result["summary"]["scheduledHours"], 744)

    def test_validated_energy_controls(self):
        summary = self.result["summary"]
        self.assertAlmostEqual(summary["totalMeasuredEnergyKWh"], 28467.0, places=3)
        self.assertAlmostEqual(summary["totalReconstructedEnergyKWh"], 544.321168, places=5)
        self.assertAlmostEqual(summary["totalKnownEnergyKWh"], 29011.321168, places=5)

    def test_period_total_is_sum_of_evaluable_daily_values(self):
        evaluable = [
            day for day in self.result["daily"]
            if day["evaluationStatus"] == "VALID_PRELIMINARY"
        ]
        expected = sum(day["expectedEnergyKWh"] for day in evaluable)
        residual = sum(day["residualKWh"] for day in evaluable)
        self.assertAlmostEqual(self.result["summary"]["totalExpectedEnergyKWh"], expected, places=5)
        self.assertAlmostEqual(self.result["summary"]["totalResidualKWh"], residual, places=5)

    def test_end_is_exclusive_everywhere(self):
        self.assertTrue(self.result["ranges"]["endExclusive"])
        self.assertEqual(self.result["ranges"]["requestedRange"]["endUtc"], END)
        for day in self.result["daily"]:
            self.assertLessEqual(
                int(__import__("datetime").datetime.fromisoformat(day["rangeEndUtc"]).timestamp()),
                END,
            )
        count = self.connection.execute(
            """SELECT COUNT(*) FROM mediciones_detalle
               WHERE gateway_id=10 AND TRIM(device_id)='24'
                 AND unit_id IN (54,61,100) AND CAST(timestamp_utc AS INTEGER)=?""",
            (END,),
        ).fetchone()[0]
        selected = self.connection.execute(
            """SELECT COUNT(*) FROM mediciones_detalle
               WHERE gateway_id=10 AND TRIM(device_id)='24'
                 AND unit_id IN (54,61,100)
                 AND CAST(timestamp_utc AS INTEGER)>=?
                 AND CAST(timestamp_utc AS INTEGER)<?""",
            (START, END),
        ).fetchone()[0]
        self.assertGreater(selected, 0)
        if count:
            self.assertGreater(count, 0)

    def test_model_is_official_and_not_retrained(self):
        self.assertTrue(self.result["model"]["oficial"])
        self.assertEqual(self.result["model"]["intercepto"], 514.50)
        self.assertEqual(self.result["model"]["coef_envases_buenos"], 0.005018)
        self.assertEqual(self.result["model"]["coef_horas_productivas"], 16.5198)
        self.assertEqual(
            self.result["methodology"]["expectedEnergyAggregation"],
            "SUM_OF_EVALUABLE_DAILY_EXPECTED_ENERGY",
        )


if __name__ == "__main__":
    unittest.main()
