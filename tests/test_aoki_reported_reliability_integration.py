import hashlib
import sqlite3
import sys
import types
import unittest
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

if "dotenv" not in sys.modules:
    dotenv_stub = types.ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *args, **kwargs: None
    sys.modules["dotenv"] = dotenv_stub

samee200_db_stub = types.ModuleType("db.samee200_db")
samee200_db_stub.get_conn = lambda: None
sys.modules["db.samee200_db"] = samee200_db_stub

from db.aoki_reconciliation import extract_reported_events
from db.aoki_reported_reliability import build_reported_reliability_contract
from db.produccion_samee200 import calcular_modulo_produccion


ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "data" / "samee200.db"
AUXILIARY = ROOT / "data" / "aoki_maintenance_validations.db"
START = int(datetime(2026, 5, 1, 11, tzinfo=timezone.utc).timestamp())
END = int(datetime(2026, 6, 1, 11, tzinfo=timezone.utc).timestamp())


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
class MayReportedReliabilityIntegrationTests(unittest.TestCase):
    def test_may_reported_contract_uses_26a_and_preserves_both_databases(self):
        master_before, auxiliary_before = sha256(MASTER), sha256(AUXILIARY)
        connection = sqlite3.connect(
            f"file:{MASTER.resolve()}?mode=ro&immutable=1", uri=True
        )
        connection.row_factory = sqlite3.Row
        periods = [dict(row) for row in connection.execute("""
            SELECT * FROM produccion_periodo
            WHERE fecha_hora_fin_utc > ? AND fecha_hora_inicio_utc < ?
            ORDER BY fecha_hora_inicio_utc
        """, (START, END))]
        connection.close()
        normalized_events = extract_reported_events(periods)
        production = calcular_modulo_produccion(periods, START, END)
        ranges = {
            "requestedRange": {"startUtc": START, "endUtc": END},
            "effectiveRange": {"startUtc": START, "endUtc": END},
            "timezone": "America/Bogota",
            "startInclusive": True,
            "endExclusive": True,
        }
        result = build_reported_reliability_contract(
            normalized_events, ranges,
            scheduled_reported_hours=production["horas_programadas"],
        )

        summary = result["summary"]
        counts = Counter(
            item["reportedStopSuggestedClassification"]
            for item in result["events"]
        )
        self.assertEqual(counts, {
            "CORRECTIVE_FAILURE": 5,
            "CLEANING": 1,
            "OPERATIONAL_STOP": 1,
            "UNDETERMINED": 6,
        })
        self.assertEqual(summary["reportedStopCount"], 13)
        self.assertEqual(summary["reportedStopDurationHours"], 14.5)
        self.assertEqual(summary["suggestedCorrectiveDowntimeHours"], 6.416667)
        self.assertEqual(summary["reportedPreliminaryMttrHours"], 1.604167)
        self.assertEqual(production["horas_programadas"], 735.5)
        self.assertEqual(summary["reportedOperatingHours"], 729.083333)
        self.assertEqual(summary["reportedPreliminaryMtbfHours"], 145.816667)
        self.assertEqual(summary["reportedPreliminaryAvailabilityPct"], 99.127578)
        self.assertEqual(summary["classificationCoveragePct"], 53.846154)
        self.assertEqual(result["status"], "LOW_CLASSIFICATION_COVERAGE")
        self.assertEqual(result["quality"]["excludedEventCount"], 1)
        self.assertEqual(
            result["methodology"]["operatingTimeSource"],
            "SCHEDULED_REPORTED_MINUS_SUGGESTED_CORRECTIVE",
        )
        self.assertTrue(all(not event["isConfirmedFailure"] for event in result["events"]))
        self.assertEqual(master_before, sha256(MASTER))
        self.assertEqual(auxiliary_before, sha256(AUXILIARY))


if __name__ == "__main__":
    unittest.main()
