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
from db.aoki_reconciliation import (
    extract_reported_events,
    reconcile_aoki_downtimes,
    resolve_reconciliation_range,
)
from db.aoki_states import classify_aoki_states, query_aoki_rows


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "data" / "samee200.db"


@unittest.skipUnless(DATABASE.exists(), "La base histórica local no está disponible")
class AokiReconciliationLocalIntegrationTests(unittest.TestCase):
    def test_historical_reconciliation_is_read_only_unique_and_production_bounded(self):
        requested_start = int(datetime(2026, 5, 1, 11, tzinfo=timezone.utc).timestamp())
        requested_end = int(datetime(2026, 7, 15, 11, tzinfo=timezone.utc).timestamp())
        connection = sqlite3.connect(f"file:{DATABASE.resolve()}?mode=ro&immutable=1", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            effective_range = resolve_reconciliation_range(
                connection, requested_start, requested_end
            )
            source = query_aoki_rows(connection, *effective_range)
            periods = [dict(row) for row in connection.execute("""
                SELECT fecha, observaciones
                FROM produccion_periodo
                WHERE fecha_hora_fin_utc > ? AND fecha_hora_inicio_utc < ?
                ORDER BY fecha_hora_inicio_utc
            """, effective_range)]
        finally:
            connection.close()

        classification = classify_aoki_states(source, *effective_range)
        detected = detect_aoki_downtime_events(classification)
        reported = extract_reported_events(periods)
        result = reconcile_aoki_downtimes(
            detected["events"], reported, classification["segments"], *effective_range
        )
        summary = result["summary"]
        self.assertEqual(effective_range, (1777633200, 1782471600))
        self.assertEqual(result["effectiveRange"]["endLocal"], "2026-06-26T06:00:00-05:00")
        self.assertEqual(summary["totalReportadas"], 26)
        self.assertEqual(summary["totalDetectadas"], 150)
        self.assertEqual(summary["totalSoloDetectadas"], 147)
        self.assertEqual(summary["totalSinDatos"], 1)
        self.assertEqual(summary["totalPendientesRevision"], 25)
        self.assertEqual(len(result["events"]), 173)
        self.assertEqual(len({item["reconciliationId"] for item in result["events"]}), 173)
        electrical_ids = [
            event_id for item in result["events"] for event_id in item["electricalEventIds"]
        ]
        reported_ids = [
            event_id for item in result["events"] for event_id in item["reportedEventIds"]
        ]
        self.assertEqual(len(electrical_ids), len(set(electrical_ids)))
        self.assertEqual(len(reported_ids), len(set(reported_ids)))
        self.assertTrue(all(item["isFailure"] is False for item in result["events"]))
        self.assertTrue(all(item["confidencePct"] is None for item in result["events"]))


if __name__ == "__main__":
    unittest.main()
