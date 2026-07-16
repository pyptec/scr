import json
import os
import sqlite3
import subprocess
import sys
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

from db import fase2_dashboard
from db.aoki_energy import query_aoki_energy_rows
from db.aoki_states import query_aoki_rows
from db.produccion_samee200 import calcular_modulo_produccion


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "data" / "samee200.db"
START = 1777633200
END = 1780311600


class Phase2TemporalContractTests(unittest.TestCase):
    def test_may_contract_is_half_open_and_uses_bogota(self):
        contract = fase2_dashboard.temporal_contract(START, END)
        self.assertEqual(contract["requestedRange"]["startUtc"], START)
        self.assertEqual(contract["effectiveRange"]["endUtc"], END)
        self.assertEqual(contract["timezone"], "America/Bogota")
        self.assertTrue(contract["startInclusive"])
        self.assertTrue(contract["endExclusive"])
        self.assertEqual(contract["requestedRange"]["startLocal"][:16], "2026-05-01T06:00")
        self.assertEqual(contract["requestedRange"]["endLocal"][:16], "2026-06-01T06:00")

    def test_measurement_exactly_at_end_is_excluded(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE mediciones_detalle (
                id INTEGER, timestamp_utc INTEGER, gateway_id INTEGER,
                device_id TEXT, unit_id INTEGER, valor TEXT
            )
        """)
        rows = [
            (1, START, 10, "24", 54, "30"),
            (2, END - 1, 10, "24", 61, "20"),
            (3, END, 10, "24", 54, "80"),
            (4, END, 10, "24", 100, "12345"),
        ]
        conn.executemany("INSERT INTO mediciones_detalle VALUES (?, ?, ?, ?, ?, ?)", rows)
        state_rows = query_aoki_rows(conn, START, END)
        energy_rows = query_aoki_energy_rows(conn, START, END)
        conn.close()
        self.assertEqual({int(row["id"]) for row in state_rows}, {1, 2})
        self.assertNotIn(3, {int(row["id"]) for row in state_rows})
        self.assertNotIn(4, {int(row["id"]) for row in energy_rows})
        self.assertTrue(all(int(row["timestamp_utc"]) < END for row in state_rows + energy_rows))

    def test_closed_reconciliation_effective_range_alias_is_preserved(self):
        result = {"effectiveRange": None, "events": []}
        fase2_dashboard.attach_temporal_contract(result, START, END, reconciliable=None)
        self.assertIsNone(result["effectiveRange"])
        self.assertIsNone(result["reconciliableRange"])
        self.assertEqual(result["requestedRange"]["endUtc"], END)

    @unittest.skipUnless(subprocess.run(
        ["node", "--version"], capture_output=True, check=False
    ).returncode == 0, "Node.js no está disponible")
    def test_manual_bogota_datetime_is_browser_timezone_independent(self):
        module_path = json.dumps(str(ROOT / "static" / "js" / "dashboard.js"))
        script = (
            f"const d=require({module_path});"
            "process.stdout.write(String(d.datetimeLocalAUnix('2026-05-01T06:00')));"
        )
        outputs = []
        for browser_timezone in ("America/Bogota", "UTC", "Asia/Tokyo"):
            environment = dict(os.environ, TZ=browser_timezone)
            completed = subprocess.run(
                ["node", "-e", script], capture_output=True, text=True,
                env=environment, check=True,
            )
            outputs.append(int(completed.stdout))
        self.assertEqual(outputs, [START, START, START])


@unittest.skipUnless(DATABASE.exists(), "La base histórica local no está disponible")
class Phase2MayLocalIntegrationTests(unittest.TestCase):
    def test_integrated_contract_matches_validated_may_controls_read_only(self):
        connection = sqlite3.connect(f"file:{DATABASE.resolve()}?mode=ro&immutable=1", uri=True)
        connection.row_factory = sqlite3.Row
        periods = [dict(row) for row in connection.execute("""
            SELECT * FROM produccion_periodo
            WHERE fecha_hora_fin_utc > ? AND fecha_hora_inicio_utc < ?
            ORDER BY fecha_hora_inicio_utc
        """, (START, END)).fetchall()]
        production = calcular_modulo_produccion(periods, START, END)
        with ExitStack() as stack:
            stack.enter_context(patch.object(
                fase2_dashboard, "obtener_modulo_produccion", return_value=production
            ))
            stack.enter_context(patch.object(
                fase2_dashboard, "obtener_produccion_periodos", return_value=periods
            ))
            stack.enter_context(patch.object(
                fase2_dashboard, "resumen_kpi_samee200", return_value={"source": "stub"}
            ))
            result = fase2_dashboard.build_phase2_dashboard(connection, START, END)
        connection.close()

        states = result["electricalStates"]["periodSummary"]
        energy = result["energy"]["periodSummary"]
        self.assertEqual(len(result["electricalStates"]["daily"]), 31)
        self.assertAlmostEqual(states["scheduledHours"], 744.0, places=3)
        self.assertAlmostEqual(states["productiveHours"], 452.9291, places=4)
        self.assertAlmostEqual(states["idleHours"], 251.0994, places=4)
        self.assertAlmostEqual(states["offHours"], 6.9003, places=4)
        self.assertAlmostEqual(states["noDataHours"], 33.0712, places=4)
        self.assertAlmostEqual(states["coveragePct"], 95.555, places=3)
        self.assertEqual(states["balanceStatus"], "VALID")
        self.assertAlmostEqual(energy["measuredEnergyKWh"], 28467.0, places=3)
        self.assertAlmostEqual(energy["reconstructedEnergyKWh"], 544.321168, places=5)
        self.assertAlmostEqual(energy["knownEnergyKWh"], 29011.321168, places=5)
        self.assertAlmostEqual(energy["energyCoveragePct"], 99.9629, places=4)
        self.assertEqual(energy["noDataIntervals"], 2)
        self.assertEqual(len(result["electricalEvents"]["events"]), 103)
        reconciliation = result["reconciliation"]["summary"]
        self.assertEqual(reconciliation["totalReportadas"], 13)
        self.assertEqual(reconciliation["totalDetectadas"], 103)
        self.assertEqual(reconciliation["totalSoloDetectadas"], 101)
        self.assertEqual(reconciliation["totalPendientesRevision"], 13)
        self.assertEqual(result["datasetType"], "DATOS_HISTORICOS_DE_PRUEBA")
        for section in ("production", "quality", "energy", "electricalStates",
                        "electricalEvents", "reconciliation", "legacyDashboard"):
            self.assertEqual(result[section]["timezone"], "America/Bogota")
            self.assertTrue(result[section]["startInclusive"])
            self.assertTrue(result[section]["endExclusive"])
        self.assertIn("periodo", result["production"])
        self.assertIn("effectiveRange", result["reconciliation"])
        self.assertIsNotNone(result["reconciliation"]["reconciliableRange"])


if __name__ == "__main__":
    unittest.main()
