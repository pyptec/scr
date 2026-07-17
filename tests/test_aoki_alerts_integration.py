import hashlib
import sqlite3
import sys
import types
import unittest
from pathlib import Path

if "dotenv" not in sys.modules:
    dotenv_stub = types.ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *args, **kwargs: None
    sys.modules["dotenv"] = dotenv_stub

samee200_db_stub = types.ModuleType("db.samee200_db")
samee200_db_stub.get_conn = lambda: None
sys.modules["db.samee200_db"] = samee200_db_stub

from db.aoki_alerts import build_alert_contract
from db.aoki_base100 import build_base100_contract
from db.aoki_daily_performance import build_daily_performance
from db.aoki_events import detect_aoki_downtime_events
from db.aoki_maintenance_events import build_maintenance_events, merge_human_validations
from db.aoki_maintenance_validation_store import MaintenanceValidationStore
from db.aoki_reconciliation import (
    extract_reported_events,
    reconcile_aoki_downtimes,
    resolve_reconciliation_range,
)
from db.aoki_reliability import build_reliability_contract
from db.aoki_states import classify_aoki_states, query_aoki_rows
from db.aoki_validated_uptime import build_validated_uptime


ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "data" / "samee200.db"
AUXILIARY = ROOT / "data" / "aoki_maintenance_validations.db"
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


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@unittest.skipUnless(
    MASTER.exists() and AUXILIARY.exists(),
    "Las bases locales requeridas no están disponibles",
)
class MayAlertIntegrationTests(unittest.TestCase):
    def test_may_produces_approved_deduplicated_counts_read_only(self):
        before_master = sha256(MASTER)
        before_auxiliary = sha256(AUXILIARY)
        connection = sqlite3.connect(
            f"file:{MASTER.resolve()}?mode=ro&immutable=1", uri=True
        )
        connection.row_factory = sqlite3.Row
        performance = build_daily_performance(
            connection, START, END, model=MODEL
        )
        base100 = build_base100_contract(performance)
        effective = resolve_reconciliation_range(connection, START, END)
        states = classify_aoki_states(
            query_aoki_rows(connection, *effective), *effective
        )
        electrical = detect_aoki_downtime_events(states)
        periods = [dict(row) for row in connection.execute("""
            SELECT fecha, observaciones FROM produccion_periodo
            WHERE fecha_hora_fin_utc>? AND fecha_hora_inicio_utc<?
            ORDER BY fecha_hora_inicio_utc
        """, effective)]
        connection.close()
        reconciliation = reconcile_aoki_downtimes(
            electrical["events"], extract_reported_events(periods),
            states["segments"], *effective,
        )
        phase2 = {
            "electricalStates": states,
            "electricalEvents": electrical,
            "reconciliation": reconciliation,
        }
        automatic = build_maintenance_events({
            "ranges": {},
            "electricalStates": {"daily": states["daily"]},
            "reconciliation": reconciliation,
        })
        store = MaintenanceValidationStore(AUXILIARY)
        maintenance = merge_human_validations(
            automatic, store.list_validations()
        )
        uptime = build_validated_uptime(
            START, END, store.list_windows(START, END),
            maintenance["events"], states["segments"],
        )
        reliability = build_reliability_contract(uptime, maintenance)
        result = build_alert_contract(
            phase2, performance, base100, maintenance, reliability
        )
        raw = result["summary"]["rawRuleMatches"]
        emitted = result["summary"]["emittedByType"]
        self.assertEqual(raw["ENERGY_OVERCONSUMPTION"], 9)
        self.assertEqual(raw["ENERGY_FAVORABLE_DEVIATION"], 2)
        self.assertEqual(raw["LOW_STATE_COVERAGE"], 3)
        self.assertEqual(raw["NO_DATA_PROLONGED"], 4)
        self.assertEqual(raw["ELECTRICAL_IDLE_EVENT"], 103)
        self.assertEqual(raw["ELECTRICAL_OFF_EVENT"], 0)
        self.assertEqual(raw["UNREPORTED_ELECTRICAL_EVENT"], 101)
        self.assertEqual(raw["REPORTED_STOP_NOT_DETECTED"], 0)
        self.assertEqual(raw["MAINTENANCE_REVIEW_REQUIRED"], 114)
        self.assertEqual(raw["STALE_MAINTENANCE_EVIDENCE"], 0)
        self.assertEqual(raw["RELIABILITY_KPI_UNAVAILABLE"], 1)
        self.assertEqual(emitted["ELECTRICAL_IDLE_EVENT"], 103)
        self.assertEqual(emitted["UNREPORTED_ELECTRICAL_EVENT"], 0)
        self.assertEqual(
            result["summary"]["deduplicatedAlarmCount"], 236
        )
        correlations = result["summary"]["correlations"]
        self.assertEqual(correlations["energyDeviationWithBase100"], 11)
        self.assertEqual(
            correlations["electricalEventWithSoloDetectada"], 101
        )
        self.assertEqual(correlations["maintenanceWithReconciliation"], 114)
        self.assertEqual(correlations["noDataWithLowStateCoverage"], 3)
        self.assertEqual(
            correlations["noDataLowCoverageCorrelationGroups"], 3
        )
        self.assertEqual(
            result["summary"]["confirmedFailureCountFromAlerts"], 0
        )
        self.assertTrue(result["ranges"]["endExclusive"])
        self.assertTrue(all(
            item["rangeStartUtc"] is None
            or int(__import__("datetime").datetime.fromisoformat(
                item["rangeStartUtc"]
            ).timestamp()) < END
            for item in result["alarms"]
        ))
        self.assertEqual(before_master, sha256(MASTER))
        self.assertEqual(before_auxiliary, sha256(AUXILIARY))
        self.assertFalse((ROOT / "data" / "aoki_alerts.db").exists())


if __name__ == "__main__":
    unittest.main()
