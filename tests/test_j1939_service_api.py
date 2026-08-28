from __future__ import annotations

import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from j1939.parser import parse_slcan_line
from j1939.service import J1939Runtime, start_local_api


ROOT = Path(__file__).resolve().parent.parent


class ServiceApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        settings = {
            "signal_file": ROOT / "config/j1939_signals.yml", "heartbeat_seconds": 600,
            "recent_frame_limit": 2, "transport": "replay", "replay_file": "fixture.log",
            "serial_device": "", "serial_baudrate": 115200, "capture_dir": Path(self.temp.name),
            "capture_max_duration_seconds": 60, "capture_max_file_mb": 1, "capture_max_files": 2,
            "capture_queue_size": 10, "can_bitrate": 250000,
        }
        self.runtime = J1939Runtime(settings)
        self.server, self.thread = start_local_api(self.runtime, "127.0.0.1", 0)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        if self.runtime.capture.status()["captureActive"]: self.runtime.capture.stop()
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2); self.temp.cleanup()

    def request(self, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method="POST" if body is not None else "GET", headers={"Content-Type":"application/json"})
        with urllib.request.urlopen(req) as response: return response.status, response.read(), response.headers

    def test_status_signals_capture_download_and_safe_id(self):
        self.runtime.process(parse_slcan_line("T0CF004EA8FFFFFF4038FFFFFF\r"))
        self.assertEqual(json.loads(self.request("/api/j1939/status")[1])["framesReceived"], 1)
        signals = json.loads(self.request("/api/j1939/signals")[1])["signals"]
        self.assertEqual(signals[0]["key"], "engine_speed")
        started = json.loads(self.request("/api/j1939/capture/start", {"note":"test", "durationSeconds":5})[1])
        self.runtime.process(parse_slcan_line("T0CF004EA8FFFFFF4038FFFFFF\r"))
        self.request("/api/j1939/capture/marker", {"note":"event"})
        self.request("/api/j1939/capture/stop", {})
        status, data, headers = self.request(f'/api/j1939/captures/{started["captureId"]}/download')
        self.assertEqual(status, 200); self.assertIn(b"0CF004EA", data); self.assertIn("attachment", headers["Content-Disposition"])
        with self.assertRaises(urllib.error.HTTPError): self.request("/api/j1939/captures/..%2Fsecret/download")


if __name__ == "__main__": unittest.main()
