import sqlite3
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone

if "dotenv" not in sys.modules:
    dotenv_stub = types.ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *args, **kwargs: None
    sys.modules["dotenv"] = dotenv_stub

samee200_db_stub = types.ModuleType("db.samee200_db")
samee200_db_stub.get_conn = lambda: None
sys.modules["db.samee200_db"] = samee200_db_stub

from db.aoki_reconciliation import reconcile_aoki_downtimes, resolve_reconciliation_range


BOGOTA = timezone(timedelta(hours=-5))
CONFIG = {
    "version": "test-reconciliation-v1",
    "matchingToleranceMinutes": 20,
    "minimumOverlapMinutes": 10,
    "minimumOverlapPct": 30,
    "dataset": {"type": "DATOS_HISTORICOS_DE_PRUEBA"},
}


def local(value):
    return datetime.fromisoformat(value).replace(tzinfo=BOGOTA)


def electrical(event_id, start, end, quality="VALID_STATE"):
    start_dt, end_dt = local(start), local(end)
    return {
        "eventId": event_id,
        "startUtc": start_dt.astimezone(timezone.utc).isoformat(),
        "endUtc": end_dt.astimezone(timezone.utc).isoformat(),
        "startLocal": start_dt.isoformat(),
        "endLocal": end_dt.isoformat(),
        "durationMinutes": (end_dt - start_dt).total_seconds() / 60,
        "dominantState": "IDLE",
        "minimumCurrentA": 40,
        "averageCurrentA": 45,
        "averagePowerKW": 30,
        "sampleCount": 6,
        "quality": quality,
        "status": "DETECTED",
        "classification": "SIN_CLASIFICAR",
        "detectedBy": "ME337_1",
    }


def reported(event_id, start="10:00", end="11:00", duration=60,
             cause="mantenimiento", status="VALID", crosses=False):
    return {
        "eventId": event_id,
        "productionDate": "2026-05-01",
        "date": "2026-05-01",
        "startTime": start,
        "endTime": end,
        "durationMinutes": duration,
        "crossesMidnight": crosses,
        "rawText": f"Observación completa {event_id}",
        "matchedText": f"Parada {event_id}",
        "cause": cause,
        "temporalSource": "START_END" if start and end else "PARTIAL_TIME",
        "status": status,
    }


def no_data(start, end):
    return {
        "state": "NO_DATA",
        "startLocal": local(start).isoformat(),
        "endLocal": local(end).isoformat(),
        "durationSeconds": (local(end) - local(start)).total_seconds(),
    }


class AokiReconciliationTests(unittest.TestCase):
    def reconcile(self, electrical_events, reported_events, segments=None):
        start = int(local("2026-05-01T06:00:00").astimezone(timezone.utc).timestamp())
        end = int(local("2026-05-02T06:00:00").astimezone(timezone.utc).timestamp())
        return reconcile_aoki_downtimes(
            electrical_events, reported_events, segments or [], start, end, CONFIG
        )

    def test_exact_match(self):
        result = self.reconcile(
            [electrical("e1", "2026-05-01T10:00:00", "2026-05-01T11:00:00")],
            [reported("r1")],
        )
        item = result["events"][0]
        self.assertEqual(item["classification"], "REPORTADA_Y_DETECTADA")
        self.assertEqual(item["overlapMinutes"], 60)
        self.assertEqual(item["confidence"], "HIGH")
        self.assertIsNone(item["confidencePct"])
        self.assertFalse(item["isFailure"])

    def test_match_within_twenty_minutes_is_candidate_but_partial(self):
        item = self.reconcile(
            [electrical("e1", "2026-05-01T10:15:00", "2026-05-01T11:15:00")],
            [reported("r1")],
        )["events"][0]
        self.assertEqual(item["classification"], "PENDIENTE_REVISION")
        self.assertEqual(item["relations"][0]["startDifferenceMinutes"], 15)
        self.assertEqual(item["overlapMinutes"], 45)

    def test_total_containment_does_not_require_boundaries_within_tolerance(self):
        item = self.reconcile(
            [electrical("e1", "2026-05-01T09:30:00", "2026-05-01T11:30:00")],
            [reported("r1")],
        )["events"][0]
        self.assertEqual(item["classification"], "REPORTADA_Y_DETECTADA")
        self.assertTrue(item["relations"][0]["electricalContainsReported"])

    def test_partial_overlap_requires_review(self):
        item = self.reconcile(
            [electrical("e1", "2026-05-01T10:30:00", "2026-05-01T11:30:00")],
            [reported("r1")],
        )["events"][0]
        self.assertEqual(item["classification"], "PENDIENTE_REVISION")
        self.assertIn("Solapamiento parcial", item["reason"])

    def test_without_overlap_or_boundary_proximity_does_not_match(self):
        result = self.reconcile(
            [electrical("e1", "2026-05-01T13:00:00", "2026-05-01T14:00:00")],
            [reported("r1")],
        )
        self.assertEqual({item["classification"] for item in result["events"]},
                         {"SOLO_REPORTADA", "SOLO_DETECTADA"})

    def test_reported_only(self):
        item = self.reconcile([], [reported("r1")])["events"][0]
        self.assertEqual(item["classification"], "SOLO_REPORTADA")

    def test_electrical_only_is_not_a_failure(self):
        item = self.reconcile(
            [electrical("e1", "2026-05-01T10:00:00", "2026-05-01T11:00:00")], []
        )["events"][0]
        self.assertEqual(item["classification"], "SOLO_DETECTADA")
        self.assertEqual(item["status"], "PENDING_REVIEW")
        self.assertFalse(item["isFailure"])

    def test_no_data_prevents_reported_only_conclusion(self):
        item = self.reconcile(
            [], [reported("r1")], [no_data("2026-05-01T09:50:00", "2026-05-01T11:10:00")]
        )["events"][0]
        self.assertEqual(item["classification"], "SIN_DATOS")
        self.assertGreater(item["noDataOverlapMinutes"], 0)

    def test_midnight_crossing(self):
        report = reported("r1", "23:30", "01:00", 90, crosses=True)
        item = self.reconcile(
            [electrical("e1", "2026-05-01T23:30:00", "2026-05-02T01:00:00")], [report]
        )["events"][0]
        self.assertEqual(item["classification"], "REPORTADA_Y_DETECTADA")
        self.assertEqual(item["overlapMinutes"], 90)

    def test_one_report_to_multiple_electrical_events(self):
        result = self.reconcile([
            electrical("e1", "2026-05-01T10:00:00", "2026-05-01T10:30:00"),
            electrical("e2", "2026-05-01T10:30:00", "2026-05-01T11:00:00"),
        ], [reported("r1")])
        item = result["events"][0]
        self.assertEqual(item["classification"], "PENDIENTE_REVISION")
        self.assertEqual(set(item["electricalEventIds"]), {"e1", "e2"})
        self.assertEqual(len(item["relations"]), 2)

    def test_multiple_reports_to_one_electrical_event(self):
        first = reported("r1", "10:00", "10:30", 30)
        second = reported("r2", "10:30", "11:00", 30)
        item = self.reconcile(
            [electrical("e1", "2026-05-01T10:00:00", "2026-05-01T11:00:00")],
            [first, second],
        )["events"][0]
        self.assertEqual(item["classification"], "PENDIENTE_REVISION")
        self.assertEqual(set(item["reportedEventIds"]), {"r1", "r2"})

    def test_no_event_is_duplicated_across_outputs(self):
        result = self.reconcile([
            electrical("e1", "2026-05-01T10:00:00", "2026-05-01T10:30:00"),
            electrical("e2", "2026-05-01T10:30:00", "2026-05-01T11:00:00"),
        ], [reported("r1")])
        electrical_ids = [value for item in result["events"] for value in item["electricalEventIds"]]
        reported_ids = [value for item in result["events"] for value in item["reportedEventIds"]]
        self.assertEqual(len(electrical_ids), len(set(electrical_ids)))
        self.assertEqual(len(reported_ids), len(set(reported_ids)))

    def test_partial_report_stays_pending(self):
        partial = reported("r1", None, "14:00", None, status="PARTIAL")
        item = self.reconcile([], [partial])["events"][0]
        self.assertEqual(item["classification"], "PENDIENTE_REVISION")
        self.assertIn("sin intervalo temporal completo", item["reason"])

    def test_unclear_cause_requires_review(self):
        item = self.reconcile(
            [electrical("e1", "2026-05-01T10:00:00", "2026-05-01T11:00:00")],
            [reported("r1", cause=None)],
        )["events"][0]
        self.assertEqual(item["classification"], "PENDIENTE_REVISION")
        self.assertEqual(item["confidence"], "HIGH")
        self.assertIn("causa", item["reason"])

    def test_electrical_event_outside_effective_range_is_not_solo_detected(self):
        result = self.reconcile([
            electrical("inside", "2026-05-01T10:00:00", "2026-05-01T11:00:00"),
            electrical("after", "2026-05-02T07:00:00", "2026-05-02T08:00:00"),
        ], [])
        ids = [value for item in result["events"] for value in item["electricalEventIds"]]
        self.assertEqual(ids, ["inside"])

    def test_range_without_production_has_no_intersection(self):
        connection = sqlite3.connect(":memory:")
        connection.executescript("""
            CREATE TABLE produccion_periodo (
                fecha_hora_inicio_utc INTEGER, fecha_hora_fin_utc INTEGER
            );
            CREATE TABLE mediciones_detalle (
                timestamp_utc INTEGER, gateway_id INTEGER, device_id TEXT, unit_id INTEGER
            );
            INSERT INTO mediciones_detalle VALUES (100, 10, '24', 54);
        """)
        self.assertIsNone(resolve_reconciliation_range(connection, 0, 200))
        connection.close()


if __name__ == "__main__":
    unittest.main()
