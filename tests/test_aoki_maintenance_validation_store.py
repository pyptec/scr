import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from db.aoki_maintenance_validation_store import (
    ConflictError,
    EvidenceConflictError,
    MaintenanceValidationStore,
    StoreError,
)


EVENT = {
    "maintenanceEventId": "maintenance-test",
    "taxonomyVersion": "aoki-maintenance-taxonomy-v1-2026-07",
    "evidenceHashVersion": "aoki-maintenance-evidence-hash-v1",
    "sourceEvidenceHash": "a" * 64,
}


class MaintenanceValidationStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "validations.db"
        self.store = MaintenanceValidationStore(self.path)
        self.store.initialize()
        token = self.store.provision_actor(
            "actor-1", "Actor Uno", "MAINTENANCE_VALIDATOR"
        )
        self.assertTrue(token)
        self.actor = self.store.list_active_actors()[0]

    def tearDown(self):
        self.temp.cleanup()

    def payload(self, **changes):
        payload = {
            "validatedClassification": "CORRECTIVE_FAILURE",
            "validationStatus": "HUMAN_VALIDATED",
            "validatedStartUtc": 1000,
            "validatedEndUtc": 1600,
            "sourceEvidenceHash": "a" * 64,
            "actor": "actor-1",
            "reviewComment": "Revisado",
        }
        payload.update(changes)
        return payload

    def test_schema_is_separate_and_contains_required_tables(self):
        connection = sqlite3.connect(self.path)
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        connection.close()
        self.assertTrue({
            "maintenance_validation_current",
            "maintenance_validation_history",
            "validated_operating_windows",
            "validated_operating_window_history",
        }.issubset(tables))

    def test_create_update_history_and_duration_calculation(self):
        first = self.store.save_validation(
            EVENT, self.payload(), self.actor, 0, "request-1"
        )
        self.assertEqual(first["version"], 1)
        self.assertEqual(first["validatedDowntimeMinutes"], 10)
        second = self.store.save_validation(
            EVENT, self.payload(reviewComment="Segunda revisión"),
            self.actor, 1, "request-2",
        )
        self.assertEqual(second["version"], 2)
        history = self.store.validation_history("maintenance-test")
        self.assertEqual(len(history), 2)
        self.assertEqual((history[0]["previousVersion"], history[1]["newVersion"]), (0, 2))

    def test_idempotency_and_optimistic_conflict(self):
        first = self.store.save_validation(
            EVENT, self.payload(), self.actor, 0, "same-request"
        )
        repeated = self.store.save_validation(
            EVENT, self.payload(), self.actor, 0, "same-request"
        )
        self.assertEqual(first, repeated)
        self.assertEqual(len(self.store.validation_history("maintenance-test")), 1)
        with self.assertRaises(ConflictError):
            self.store.save_validation(
                EVENT, self.payload(), self.actor, 0, "new-request"
            )

    def test_actor_evidence_classification_and_time_validation(self):
        with self.assertRaises(StoreError):
            self.store.save_validation(
                EVENT, self.payload(actor="suplantado"), self.actor, 0, "r1"
            )
        with self.assertRaises(EvidenceConflictError):
            self.store.save_validation(
                EVENT, self.payload(sourceEvidenceHash="b" * 64),
                self.actor, 0, "r2",
            )
        with self.assertRaises(StoreError):
            self.store.save_validation(
                EVENT, self.payload(validatedClassification="INVALID"),
                self.actor, 0, "r3",
            )
        with self.assertRaises(StoreError):
            self.store.save_validation(
                EVENT, self.payload(validatedEndUtc=900), self.actor, 0, "r4"
            )

    def test_duration_override_requires_reason(self):
        with self.assertRaises(StoreError):
            self.store.save_validation(
                EVENT, self.payload(validatedDowntimeMinutes=20),
                self.actor, 0, "override-1",
            )
        result = self.store.save_validation(
            EVENT, self.payload(
                validatedDowntimeMinutes=20,
                durationOverrideReason="Tiempo verificado en orden de trabajo",
            ),
            self.actor, 0, "override-2",
        )
        self.assertEqual(result["validatedDowntimeMinutes"], 20)

    def test_history_is_append_only_at_database_level(self):
        self.store.save_validation(EVENT, self.payload(), self.actor, 0, "history-1")
        connection = sqlite3.connect(self.path)
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE maintenance_validation_history SET changeReason='x'"
            )
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM maintenance_validation_history")
        connection.close()

    def test_windows_validate_overlap_version_and_history(self):
        admin_token = self.store.provision_actor(
            "admin-1", "Admin Uno", "MAINTENANCE_ADMIN"
        )
        self.assertTrue(admin_token)
        admin = next(
            actor for actor in self.store.list_active_actors()
            if actor["actorId"] == "admin-1"
        )
        payload = {
            "windowId": "window-1", "startUtc": 1000, "endUtc": 2000,
            "windowType": "SCHEDULED_OPERATION", "source": "Plan aprobado",
            "policyVersion": "aoki-uptime-policy-v1-2026-07",
        }
        result = self.store.save_window(payload, admin, 0, "window-request-1")
        self.assertEqual(result["version"], 1)
        with self.assertRaises(ConflictError):
            self.store.save_window({
                **payload, "windowId": "window-2", "startUtc": 1500, "endUtc": 2500
            }, admin, 0, "window-request-2")
        self.assertEqual(len(self.store.window_history("window-1")), 1)


if __name__ == "__main__":
    unittest.main()
