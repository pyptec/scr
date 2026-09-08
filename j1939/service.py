from __future__ import annotations

import json
import logging
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from .capture import CaptureError, CaptureManager
from .config import load_yaml
from .decoder import SignalDecoder
from .state import SignalState

LOGGER = logging.getLogger(__name__)


class J1939Runtime:
    def __init__(self, settings: dict[str, Any]) -> None:
        config = load_yaml(settings["signal_file"])
        heartbeat = int(settings.get("heartbeat_seconds") or config.get("publish", {}).get("heartbeat_seconds", 600))
        self.settings = settings
        self.decoder = SignalDecoder(config["signals"])
        self.state = SignalState(heartbeat, settings["recent_frame_limit"])
        device = settings.get("can_interface") if settings["transport"] == "socketcan" else settings.get("serial_device") or settings.get("replay_file")
        self.state.configure_transport(settings["transport"], device)
        capture_metadata = {
            "transport": settings["transport"], "device": device,
            "can_bitrate": settings["can_bitrate"],
            "signal_config_version": config.get("version", ""),
        }
        if settings["transport"] == "socketcan":
            capture_metadata["interface"] = settings.get("can_interface")
        elif settings["transport"] == "serial":
            capture_metadata["serial_baudrate"] = settings.get("serial_baudrate")
        self.capture = CaptureManager(
            Path(settings["capture_dir"]), max_duration_seconds=settings["capture_max_duration_seconds"],
            max_file_mb=settings["capture_max_file_mb"], max_files=settings["capture_max_files"],
            queue_size=settings["capture_queue_size"], metadata=capture_metadata,
        )

    def status(self) -> dict[str, Any]:
        result = self.state.status()
        result["droppedCaptureFrames"] = self.capture.status()["droppedCaptureFrames"]
        return result

    def process(self, frame) -> list[dict[str, Any]]:
        known = bool(frame.j1939 and frame.j1939.pgn in self.decoder.known_pgns)
        self.state.record_frame(frame, known)
        self.capture.offer(frame)
        publications = []
        try:
            decoded = self.decoder.decode(frame)
            if decoded:
                self.state.record_decoded_frame()
            for signal in decoded:
                published = self.state.update(signal)
                if published:
                    publications.append(published)
                    LOGGER.info("signal_publish reason=%s key=%s", published["publishReason"], published["key"])
        except Exception:
            self.state.record_decode_error()
            LOGGER.exception("decode_error")
        return publications


def make_handler(runtime: J1939Runtime):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            LOGGER.debug(format, *args)

        def _json(self, value, status=200):
            payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload))); self.end_headers(); self.wfile.write(payload)

        def _body(self):
            length = min(int(self.headers.get("Content-Length", "0")), 4096)
            return json.loads(self.rfile.read(length) or b"{}")

        def do_GET(self):
            path = unquote(self.path.split("?", 1)[0])
            if path == "/api/j1939/status": return self._json(runtime.status())
            if path == "/api/j1939/signals": return self._json({"signals": runtime.state.signals()})
            if path.startswith("/api/j1939/signals/"):
                key = path.rsplit("/", 1)[-1]; item = next((x for x in runtime.state.signals() if x["key"] == key), None)
                return self._json(item or {"error": "SIGNAL_NOT_FOUND"}, 200 if item else 404)
            if path == "/api/j1939/frames/recent": return self._json({"frames": runtime.state.recent()})
            if path == "/api/j1939/capture/status": return self._json(runtime.capture.status())
            if path == "/api/j1939/captures": return self._json({"captures": runtime.capture.list_captures()})
            prefix = "/api/j1939/captures/"
            if path.startswith(prefix) and path.endswith("/download"):
                capture_id = path[len(prefix):-len("/download")]
                try: target = runtime.capture.resolve(capture_id)
                except CaptureError as exc: return self._json({"error": str(exc)}, 404)
                self.send_response(200); self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="{target.name}"'); self.send_header("Content-Length", str(target.stat().st_size)); self.end_headers()
                with target.open("rb") as stream: shutil.copyfileobj(stream, self.wfile, length=64 * 1024)
                return None
            return self._json({"error": "NOT_FOUND"}, 404)

        def do_POST(self):
            try:
                body = self._body()
                if self.path == "/api/j1939/capture/start": return self._json(runtime.capture.start(body.get("note", ""), body.get("durationSeconds")))
                if self.path == "/api/j1939/capture/stop": return self._json(runtime.capture.stop())
                if self.path == "/api/j1939/capture/marker": return self._json(runtime.capture.marker(body.get("note", "")))
                return self._json({"error": "NOT_FOUND"}, 404)
            except (CaptureError, ValueError, json.JSONDecodeError) as exc:
                return self._json({"error": str(exc)}, 409)
    return Handler


def start_local_api(runtime: J1939Runtime, host: str, port: int) -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = ThreadingHTTPServer((host, port), make_handler(runtime))
    thread = threading.Thread(target=server.serve_forever, name="j1939-local-api", daemon=True)
    thread.start()
    return server, thread
