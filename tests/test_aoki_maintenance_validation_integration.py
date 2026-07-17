import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from db.aoki_maintenance_validation_store import (
    MaintenanceValidationStore,
    backup_database,
)


ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "data" / "samee200.db"


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@unittest.skipUnless(MASTER.exists(), "La base histórica local no está disponible")
class MaintenanceValidationIntegrationTests(unittest.TestCase):
    def test_auxiliary_initialization_and_backup_never_modify_master(self):
        master_before = sha256(MASTER)
        connection = sqlite3.connect(
            f"file:{MASTER.resolve()}?mode=ro&immutable=1", uri=True
        )
        try:
            maintenance_rows = connection.execute(
                "SELECT COUNT(*) FROM eventos_mantenimiento"
            ).fetchone()[0]
        finally:
            connection.close()

        with tempfile.TemporaryDirectory() as temporary:
            auxiliary = Path(temporary) / "aoki_maintenance_validations.db"
            store = MaintenanceValidationStore(auxiliary)
            store.initialize()
            self.assertEqual(store.list_active_actors(), [])
            backup = backup_database(auxiliary, Path(temporary) / "backups")
            self.assertTrue(backup.exists())
            self.assertTrue(backup.with_suffix(".json").exists())
            restored = sqlite3.connect(
                f"file:{backup.resolve()}?mode=ro&immutable=1", uri=True
            )
            try:
                self.assertEqual(
                    restored.execute("PRAGMA integrity_check").fetchone()[0], "ok"
                )
            finally:
                restored.close()

        self.assertEqual(maintenance_rows, 0)
        self.assertEqual(master_before, sha256(MASTER))


if __name__ == "__main__":
    unittest.main()
