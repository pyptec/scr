import sqlite3
import unittest
from datetime import datetime, timezone
from pathlib import Path

from db.aoki_energy import query_aoki_energy_rows, reconstruct_aoki_energy


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "data" / "samee200.db"


@unittest.skipUnless(DATABASE.exists(), "La base histórica local no está disponible")
class AokiEnergyLocalIntegrationTests(unittest.TestCase):
    def test_reconstruction_is_read_only_and_keeps_source_proportions(self):
        start = int(datetime(2026, 5, 1, 11, tzinfo=timezone.utc).timestamp())
        end = int(datetime(2026, 6, 26, 11, tzinfo=timezone.utc).timestamp())
        connection = sqlite3.connect(f"file:{DATABASE.resolve()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            rows = query_aoki_energy_rows(connection, start, end)
        finally:
            connection.close()
        result = reconstruct_aoki_energy(rows, start_utc=start, end_utc=end)
        measured = sum(i["energyKWh"] or 0 for i in result["intervals"] if i["source"] == "ACCUMULATOR_DELTA")
        reconstructed = sum(i["energyKWh"] or 0 for i in result["intervals"] if i["source"].startswith("POWER_"))
        self.assertEqual(result["datasetType"], "DATOS_HISTORICOS_DE_PRUEBA")
        self.assertGreater(measured, 0)
        self.assertGreater(reconstructed, 0)
        self.assertFalse(result["currentModelUsed"])
        self.assertTrue(any(i["reason"] == "AGGREGATED_GAP_ENERGY" for i in result["intervals"]))
        self.assertTrue(any(i["source"] == "NO_DATA" for i in result["intervals"]))


if __name__ == "__main__":
    unittest.main()
