"""Compatibilidad Flask sin DB, .env, GPIO ni importación del util operativo."""
from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import URLError

ROOT = Path(__file__).resolve().parent.parent


class DashboardProxyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # api.app llama init_db al importar: se neutraliza ANTES de ejecutarlo.
        spec = importlib.util.spec_from_file_location("j1939_dashboard_test_app", ROOT / "api/app.py")
        cls.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {spec.name: cls.module, "util": types.ModuleType("util"), "dotenv": types.SimpleNamespace(load_dotenv=Mock(return_value=False))}), \
                patch("db.samee100_db.init_db") as init, \
                patch("db.samee100_db.get_conn", side_effect=AssertionError("DB forbidden")), \
                patch("sqlite3.connect", side_effect=AssertionError("SQLite forbidden")):
            spec.loader.exec_module(cls.module)
            init.assert_called_once_with()
        cls.module.app.config["TESTING"] = True

    def setUp(self):
        self.client = self.module.app.test_client()
        self.env = patch.dict(os.environ, {"J1939_ENABLED": "true", "J1939_LOCAL_API_PORT": "8765"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_existing_get_endpoints_keep_proxy_contract(self):
        for route in ("status", "signals", "signals/engine_speed", "frames/recent", "capture/status", "captures"):
            with self.subTest(route=route):
                payload = {"sourceAddress": "EA", "value": 1800, "quality": "GOOD"}
                response = io.BytesIO(json.dumps(payload).encode())
                response.status = 200
                with patch.object(self.module.urllib.request, "urlopen", return_value=response) as proxy:
                    result = self.client.get("/api/j1939/" + route)
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.get_json(), payload)
                request = proxy.call_args.args[0]
                self.assertEqual(request.full_url, "http://127.0.0.1:8765/api/j1939/" + route)
                self.assertEqual(proxy.call_args.kwargs["timeout"], 3)

    def test_disabled_and_unavailable_do_not_report_stopped(self):
        with patch.dict(os.environ, {"J1939_ENABLED": "false"}), \
                patch.object(self.module.urllib.request, "urlopen") as proxy:
            result = self.client.get("/api/j1939/status")
            self.assertEqual(result.status_code, 503)
            proxy.assert_not_called()
        with patch.object(self.module.urllib.request, "urlopen", side_effect=URLError("offline")):
            result = self.client.get("/api/j1939/status")
            self.assertEqual(result.status_code, 503)
            self.assertNotIn("STOPPED", result.get_data(as_text=True))

    def test_dashboard_preserves_electrical_chart_and_conditional_j1939(self):
        with patch.object(self.module, "get_conn", side_effect=AssertionError("DB forbidden")):
            response = self.client.get("/dashboard")
            self.assertEqual(response.status_code, 200)
            text = response.get_data(as_text=True)
            for required in ("chartPrincipal", "tablaUltimos", "j1939Signals", "j1939RpmValue",
                             "j1939CaptureDuration", "Sin dato validado", "js/j1939_diagnostics.js"):
                self.assertIn(required, text)
            self.assertLess(text.index("js/j1939_diagnostics.js"), text.index("js/dashboard.js"))
            with patch.dict(os.environ, {"J1939_ENABLED": "false"}):
                text = self.client.get("/dashboard").get_data(as_text=True)
                self.assertNotIn('id="j1939Section"', text)
                self.assertIn('id="chartPrincipal"', text)

    def test_capture_posts_still_forward_without_can_operations(self):
        for action in ("start", "stop", "marker"):
            response = io.BytesIO(b'{"ok": true}')
            response.status = 200
            with patch.object(self.module.urllib.request, "urlopen", return_value=response) as proxy:
                result = self.client.post("/api/j1939/capture/" + action, json={"note": "synthetic"})
            self.assertEqual(result.status_code, 200)
            req = proxy.call_args.args[0]
            self.assertEqual(req.get_method(), "POST")
            self.assertEqual(json.loads(req.data), {"note": "synthetic"})

    def test_engine_verification_proxy_and_invalid_path(self):
        response = io.BytesIO(b'{"temporal_integrity":"INCOMPLETE"}'); response.status = 200
        with patch.object(self.module.urllib.request, "urlopen", return_value=response) as proxy:
            result = self.client.get('/api/j1939/engine/evidence/session:1/segment-1/verify')
            self.assertEqual(result.status_code, 200)
            self.assertIn('/engine/evidence/session:1/segment-1/verify', proxy.call_args.args[0].full_url)
        with patch.object(self.module.urllib.request, "urlopen") as proxy:
            result = self.client.get('/api/j1939/engine/evidence/session/segment!/verify')
            self.assertEqual(result.status_code, 404)
            proxy.assert_not_called()

    def test_unsafe_capture_and_signal_paths_rejected(self):
        with patch.object(self.module.urllib.request, "urlopen") as proxy:
            self.assertEqual(self.client.post("/api/j1939/capture/unknown", json={}).status_code, 404)
            self.assertEqual(self.client.get("/api/j1939/signals/INVALID!").status_code, 404)
            self.assertEqual(self.client.get("/api/j1939/captures/invalid/download").status_code, 404)
            proxy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
