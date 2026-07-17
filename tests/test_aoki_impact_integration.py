import hashlib
import json
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
from db.aoki_impact import build_impact_contract, load_impact_factors


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "data" / "samee200.db"
CONFIG = ROOT / "device" / "aoki_impact_factors.json"
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
class MayImpactIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.connection = sqlite3.connect(
            f"file:{DATABASE.resolve()}?mode=ro&immutable=1", uri=True
        )
        cls.connection.row_factory = sqlite3.Row
        cls.performance = build_daily_performance(
            cls.connection, START, END, model=MODEL
        )
        cls.base100 = build_base100_contract(cls.performance)
        cls.cusum = build_cusum_contract(cls.performance, cls.base100)
        cls.factors = load_impact_factors()

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()

    def test_may_without_factors(self):
        result = build_impact_contract(
            self.performance, self.base100, self.cusum, self.factors
        )
        summary = result["summary"]
        self.assertEqual(summary["requestedDays"], 31)
        self.assertEqual(summary["evaluableDays"], 28)
        self.assertEqual(summary["excludedDays"], 3)
        self.assertAlmostEqual(summary["periodResidualKWh"], 669.871255, places=5)
        self.assertEqual(
            summary["periodResidualKWh"],
            self.cusum["summary"]["finalCusumKWh"],
        )
        self.assertIsNone(summary["periodEconomicImpactCop"])
        self.assertIsNone(summary["periodCo2eImpactKg"])
        self.assertEqual(summary["economicEvaluationStatus"], "TARIFF_NOT_CONFIGURED")
        self.assertEqual(
            summary["environmentalEvaluationStatus"],
            "EMISSION_FACTOR_NOT_CONFIGURED",
        )
        self.assertTrue(result["ranges"]["endExclusive"])

    def test_may_with_fictitious_test_factors(self):
        result = build_impact_contract(
            self.performance, self.base100, self.cusum, self.factors,
            {
                "energyTariffCopPerKWh": 1000,
                "emissionFactorKgCo2ePerKWh": 0.2,
            },
        )
        summary = result["summary"]
        self.assertAlmostEqual(summary["periodEconomicImpactCop"], 669871.255, places=3)
        self.assertAlmostEqual(summary["periodCo2eImpactKg"], 133.974251, places=5)
        excluded = {
            day["productionDate"] for day in result["daily"]
            if not day["includedInImpact"]
        }
        self.assertEqual(excluded, {
            "2026-05-08", "2026-05-20", "2026-05-21"
        })
        self.assertTrue(all(
            day["economicImpactCop"] is None and day["co2eImpactKg"] is None
            for day in result["daily"] if not day["includedInImpact"]
        ))

    def test_override_does_not_persist_configuration(self):
        before = hashlib.sha256(CONFIG.read_bytes()).hexdigest()
        build_impact_contract(
            self.performance, self.base100, self.cusum, self.factors,
            {"energyTariffCopPerKWh": 1000,
             "emissionFactorKgCo2ePerKWh": 0.2},
        )
        after = hashlib.sha256(CONFIG.read_bytes()).hexdigest()
        self.assertEqual(before, after)
        stored = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertIsNone(stored["energyTariffCopPerKWh"])
        self.assertIsNone(stored["emissionFactorKgCo2ePerKWh"])


if __name__ == "__main__":
    unittest.main()
