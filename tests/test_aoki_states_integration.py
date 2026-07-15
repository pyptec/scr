import sqlite3
import unittest
from datetime import datetime, timezone
from pathlib import Path

from db.aoki_states import classify_aoki_states, query_aoki_rows
from db.aoki_events import detect_aoki_downtime_events


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "data" / "samee200.db"


@unittest.skipUnless(DATABASE.exists(), "La base histórica local no está disponible")
class AokiStatesLocalDatabaseIntegrationTests(unittest.TestCase):
    def test_may_to_june_25_is_read_only_and_hours_close_exactly(self):
        start = int(datetime(2026, 5, 1, 11, tzinfo=timezone.utc).timestamp())
        end = int(datetime(2026, 6, 26, 11, tzinfo=timezone.utc).timestamp())
        connection = sqlite3.connect(f"file:{DATABASE.resolve()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            source = query_aoki_rows(connection, start, end)
        finally:
            connection.close()

        result = classify_aoki_states(source, start, end)
        total = sum(day["scheduledHours"] for day in result["daily"])
        classified = sum(
            day[field]
            for day in result["daily"]
            for field in ("productiveHours", "idleHours", "offHours", "noDataHours")
        )
        self.assertEqual(result["datasetType"], "DATOS_HISTORICOS_DE_PRUEBA")
        self.assertEqual(result["gatewayId"], 10)
        self.assertEqual(result["deviceId"], 24)
        self.assertEqual(len(result["daily"]), 56)
        self.assertAlmostEqual(total, 1344.0, places=3)
        self.assertAlmostEqual(classified, total, places=2)
        self.assertEqual(result["periodSummary"]["balanceStatus"], "VALID")
        self.assertAlmostEqual(result["periodSummary"]["knownDataHours"], 1273.3072, places=3)
        self.assertEqual(len(result["traceability"]), result["quality"]["outputSamples"])

    def test_may_events_match_backend_kpis_without_duplicates(self):
        start = int(datetime(2026, 5, 1, 11, tzinfo=timezone.utc).timestamp())
        end = int(datetime(2026, 6, 1, 11, tzinfo=timezone.utc).timestamp())
        connection = sqlite3.connect(f"file:{DATABASE.resolve()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            source = query_aoki_rows(connection, start, end)
        finally:
            connection.close()
        detected = detect_aoki_downtime_events(classify_aoki_states(source, start, end))
        events, summary = detected["events"], detected["summary"]
        keys = [(event["startUtc"], event["endUtc"]) for event in events]
        self.assertEqual(summary["eventCount"], 103)
        self.assertAlmostEqual(summary["idleHours"], 250.2245, places=4)
        self.assertAlmostEqual(summary["offHours"], 6.9003, places=4)
        self.assertAlmostEqual(summary["nonProductiveHours"], 257.1248, places=4)
        self.assertAlmostEqual(sum(event["durationMinutes"] for event in events) / 60,
                               summary["nonProductiveHours"], places=4)
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all(set(event["stateMinutes"]) == {"IDLE", "OFF"} for event in events))
        self.assertTrue(all(event["status"] == "DETECTED" for event in events))
        self.assertTrue(all(event["classification"] == "SIN_CLASIFICAR" for event in events))
        self.assertEqual(summary["boundaryCensoredEvents"], 1)
