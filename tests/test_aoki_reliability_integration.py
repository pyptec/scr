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

from db.aoki_events import detect_aoki_downtime_events
from db.aoki_maintenance_events import (
    build_maintenance_events,
    merge_human_validations,
)
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
class MayReliabilityIntegrationTests(unittest.TestCase):
    def test_real_readiness_blocks_kpi_and_both_databases_are_read_only(self):
        before_master = sha256(MASTER)
        before_auxiliary = sha256(AUXILIARY)
        connection = sqlite3.connect(
            f"file:{MASTER.resolve()}?mode=ro&immutable=1", uri=True
        )
        connection.row_factory = sqlite3.Row
        effective = resolve_reconciliation_range(connection, START, END)
        rows = query_aoki_rows(connection, *effective)
        periods = [dict(row) for row in connection.execute("""
            SELECT fecha, observaciones FROM produccion_periodo
            WHERE fecha_hora_fin_utc>? AND fecha_hora_inicio_utc<?
            ORDER BY fecha_hora_inicio_utc
        """, effective)]
        connection.close()
        states = classify_aoki_states(rows, *effective)
        detected = detect_aoki_downtime_events(states)
        reported = extract_reported_events(periods)
        reconciliation = reconcile_aoki_downtimes(
            detected["events"], reported, states["segments"], *effective
        )
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
        result = build_reliability_contract(uptime, maintenance)
        self.assertEqual(uptime["status"], "NO_HUMAN_VALIDATIONS")
        self.assertEqual(result["readinessStatus"], "NO_HUMAN_VALIDATIONS")
        self.assertEqual(result["status"], "NO_HUMAN_VALIDATIONS")
        self.assertEqual(result["summary"]["confirmedFailureCount"], 0)
        for key in (
            "mtbfHours", "mttrHours", "technicalAvailabilityPct",
            "technicalAvailabilityByTimePct", "failureRatePer1000Hours",
        ):
            self.assertIsNone(result["summary"][key])
        self.assertEqual(before_master, sha256(MASTER))
        self.assertEqual(before_auxiliary, sha256(AUXILIARY))


if __name__ == "__main__":
    unittest.main()
