import os
import tempfile
import unittest
from pathlib import Path

from db.aoki_maintenance_auth import (
    authenticate_bearer,
    token_hash,
    writes_are_allowed,
)
from db.aoki_maintenance_validation_store import MaintenanceValidationStore


class MaintenanceAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = MaintenanceValidationStore(Path(self.temp.name) / "validations.db")
        self.store.initialize()

    def tearDown(self):
        self.temp.cleanup()

    def test_actor_is_not_preloaded_and_only_token_hash_is_stored(self):
        self.assertEqual(self.store.list_active_actors(), [])
        token = self.store.provision_actor(
            "validator-1", "Validador Uno", "MAINTENANCE_VALIDATOR"
        )
        actor = self.store.list_active_actors()[0]
        self.assertEqual(actor["tokenHash"], token_hash(token))
        self.assertNotEqual(actor["tokenHash"], token)
        self.assertNotIn(token, str(actor))

    def test_bearer_authentication_identifies_individual_actor(self):
        token = self.store.provision_actor(
            "validator-1", "Validador Uno", "MAINTENANCE_VALIDATOR"
        )
        actor = authenticate_bearer(self.store, f"Bearer {token}")
        self.assertEqual(actor["actorId"], "validator-1")
        self.assertIsNone(authenticate_bearer(self.store, "Bearer incorrecto"))

    def test_writes_require_flag_no_debug_and_safe_transport(self):
        enabled = {"MAINTENANCE_WRITES_ENABLED": "true"}
        self.assertEqual(
            writes_are_allowed(False, "127.0.0.1", {}, enabled), (True, None)
        )
        self.assertFalse(writes_are_allowed(True, "127.0.0.1", {}, enabled)[0])
        self.assertFalse(writes_are_allowed(False, "10.0.0.2", {}, enabled)[0])
        proxy = {
            **enabled, "MAINTENANCE_TRUSTED_PROXY_TLS": "true"
        }
        self.assertTrue(writes_are_allowed(
            False, "10.0.0.2", {"X-Forwarded-Proto": "https"}, proxy
        )[0])
        self.assertFalse(writes_are_allowed(
            False, "127.0.0.1", {}, os.environ
        )[0])


if __name__ == "__main__":
    unittest.main()
