import hashlib
import sqlite3
import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path

if "dotenv" not in sys.modules:
    dotenv_stub = types.ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *args, **kwargs: None
    sys.modules["dotenv"] = dotenv_stub

samee200_db_stub = types.ModuleType("db.samee200_db")
samee200_db_stub.get_conn = lambda: None
sys.modules["db.samee200_db"] = samee200_db_stub

from db.aoki_events import detect_aoki_downtime_events
from db.aoki_maintenance_events import build_maintenance_events
from db.aoki_reconciliation import (
    extract_reported_events,
    reconcile_aoki_downtimes,
    resolve_reconciliation_range,
)
from db.aoki_states import classify_aoki_states, query_aoki_rows


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "data" / "samee200.db"
START = int(datetime(2026, 5, 1, 11, tzinfo=timezone.utc).timestamp())
END = int(datetime(2026, 6, 1, 11, tzinfo=timezone.utc).timestamp())


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@unittest.skipUnless(DATABASE.exists(), "La base histórica local no está disponible")
class MayMaintenanceIntegrationTests(unittest.TestCase):
    def test_may_contract_is_read_only_and_preserves_phase2_controls(self):
        before = sha256(DATABASE)
        connection = sqlite3.connect(
            f"file:{DATABASE.resolve()}?mode=ro&immutable=1", uri=True
        )
        connection.row_factory = sqlite3.Row
        try:
            effective = resolve_reconciliation_range(connection, START, END)
            rows = query_aoki_rows(connection, *effective)
            periods = [dict(row) for row in connection.execute("""
                SELECT fecha, observaciones
                FROM produccion_periodo
                WHERE fecha_hora_fin_utc > ? AND fecha_hora_inicio_utc < ?
                ORDER BY fecha_hora_inicio_utc
            """, effective)]
            maintenance_rows = connection.execute(
                "SELECT COUNT(*) FROM eventos_mantenimiento"
            ).fetchone()[0]
        finally:
            connection.close()

        states = classify_aoki_states(rows, *effective)
        detected = detect_aoki_downtime_events(states)
        reported = extract_reported_events(periods)
        reconciliation = reconcile_aoki_downtimes(
            detected["events"], reported, states["segments"], *effective
        )
        phase2 = {
            "ranges": {
                "requestedRange": {"startUtc": START, "endUtc": END},
                "timezone": "America/Bogota",
                "startInclusive": True,
                "endExclusive": True,
            },
            "electricalStates": {"daily": states["daily"]},
            "reconciliation": reconciliation,
        }
        result = build_maintenance_events(phase2)
        summary = result["summary"]

        self.assertEqual(effective, (START, END))
        self.assertEqual(summary["requestedDays"], 31)
        self.assertEqual(summary["reportedEvents"], 13)
        self.assertEqual(summary["completeElectricalEvents"], 103)
        self.assertEqual(summary["soloDetectada"], 101)
        self.assertEqual(summary["pendingReconciliation"], 13)
        self.assertEqual(summary["confirmedFailures"], 0)
        self.assertEqual(summary["suggestionsByClassification"], {
            "CLEANING": 1,
            "CORRECTIVE_FAILURE": 4,
            "PREVENTIVE_MAINTENANCE": 4,
            "UNDETERMINED": 105,
        })
        self.assertTrue(all(
            event["validatedClassification"] is None
            and event["validationStatus"] == "PENDING_HUMAN_REVIEW"
            and event["confirmedFailure"] is False
            for event in result["events"]
        ))
        self.assertEqual(maintenance_rows, 0)
        self.assertEqual(before, sha256(DATABASE))


if __name__ == "__main__":
    unittest.main()
