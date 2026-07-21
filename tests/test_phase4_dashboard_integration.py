import hashlib
import sqlite3
import sys
import time
import types
import unittest
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

if "dotenv" not in sys.modules:
    dotenv_stub = types.ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *args, **kwargs: None
    sys.modules["dotenv"] = dotenv_stub

samee200_db_stub = types.ModuleType("db.samee200_db")
samee200_db_stub.get_conn = lambda: None
sys.modules["db.samee200_db"] = samee200_db_stub

from db.aoki_maintenance_validation_store import MaintenanceValidationStore
from db import fase2_dashboard
from db.fase4_dashboard import KPI_FIELDS, build_phase4_dashboard
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
class Phase4DashboardIntegrationTests(unittest.TestCase):
    def test_may_integrated_contract_is_deduplicated_and_read_only(self):
        master_before = sha256(MASTER)
        auxiliary_before = sha256(AUXILIARY)
        connection = sqlite3.connect(
            f"file:{MASTER.resolve()}?mode=ro&immutable=1", uri=True
        )
        connection.row_factory = sqlite3.Row
        store = MaintenanceValidationStore(AUXILIARY)
        periods = [dict(row) for row in connection.execute("""
            SELECT * FROM produccion_periodo
            WHERE fecha_hora_fin_utc > ? AND fecha_hora_inicio_utc < ?
            ORDER BY fecha_hora_inicio_utc
        """, (START, END)).fetchall()]
        production = calcular_modulo_produccion(periods, START, END)
        started = time.perf_counter()
        try:
            with ExitStack() as stack:
                stack.enter_context(patch.object(
                    fase2_dashboard, "obtener_modulo_produccion",
                    return_value=production,
                ))
                stack.enter_context(patch.object(
                    fase2_dashboard, "obtener_produccion_periodos",
                    return_value=periods,
                ))
                stack.enter_context(patch.object(
                    fase2_dashboard, "resumen_kpi_samee200",
                    return_value={"source": "stub"},
                ))
                result = build_phase4_dashboard(connection, START, END, store)
        finally:
            connection.close()
        elapsed = time.perf_counter() - started

        self.assertEqual(result["ranges"]["requestedRange"]["startUtc"], START)
        self.assertEqual(result["ranges"]["requestedRange"]["endUtc"], END)
        self.assertTrue(result["ranges"]["startInclusive"])
        self.assertTrue(result["ranges"]["endExclusive"])
        self.assertEqual(result["ranges"]["timezone"], "America/Bogota")
        self.assertEqual(len(result["maintenance"]["events"]), 114)
        self.assertEqual(result["maintenance"]["summary"]["confirmedFailures"], 0)
        self.assertEqual(result["uptime"]["status"], "NO_HUMAN_VALIDATIONS")
        self.assertEqual(
            result["reliability"]["readinessStatus"], "NO_HUMAN_VALIDATIONS"
        )
        self.assertFalse(result["quality"]["kpiVisible"])
        for field in KPI_FIELDS:
            self.assertIsNone(result["reliability"]["summary"][field])

        alert_summary = result["alerts"]["summary"]
        self.assertEqual(alert_summary["deduplicatedAlarmCount"], 236)
        self.assertEqual(alert_summary["openAlarmCount"], 236)
        self.assertEqual(alert_summary["confirmedFailureCountFromAlerts"], 0)
        correlations = alert_summary["correlations"]
        self.assertEqual(correlations["energyDeviationWithBase100"], 11)
        self.assertEqual(correlations["electricalEventWithSoloDetectada"], 101)
        self.assertEqual(correlations["maintenanceWithReconciliation"], 114)
        self.assertEqual(correlations["noDataWithLowStateCoverage"], 3)

        maintenance_ids = {
            event["maintenanceEventId"]
            for event in result["maintenance"]["events"]
        }
        self.assertTrue(all(
            event["maintenanceEventId"] in maintenance_ids
            for event in result["reliability"]["events"]
        ))
        self.assertTrue(all(
            alarm["maintenanceEventId"] in maintenance_ids
            for alarm in result["alerts"]["alarms"]
            if alarm["maintenanceEventId"] is not None
        ))
        self.assertLess(elapsed, 30)
        self.assertEqual(master_before, sha256(MASTER))
        self.assertEqual(auxiliary_before, sha256(AUXILIARY))
        self.assertFalse((ROOT / "data" / "aoki_alerts.db").exists())


if __name__ == "__main__":
    unittest.main()
