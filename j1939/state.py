from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any

from .models import CanFrame, DecodedSignal


class SignalState:
    def __init__(self, heartbeat_seconds: int = 600, recent_limit: int = 200) -> None:
        self.heartbeat_seconds = heartbeat_seconds
        self._lock = threading.RLock()
        self._signals: dict[str, dict[str, Any]] = {}
        self._recent: deque[dict[str, Any]] = deque(maxlen=recent_limit)
        self._status = {
            "connected": False, "transport": None, "device": None, "lastFrameAt": None,
            "framesReceived": 0, "framesDecoded": 0, "unknownPgnCount": 0,
            "decodeErrorCount": 0, "serialReconnectCount": 0, "signalsChanged": 0,
            "heartbeatPublishes": 0,
        }

    def configure_transport(self, transport: str, device: str | None) -> None:
        with self._lock:
            self._status.update(transport=transport, device=device)

    def set_connected(self, connected: bool, reconnect: bool = False) -> None:
        with self._lock:
            self._status["connected"] = connected
            if reconnect:
                self._status["serialReconnectCount"] += 1

    def record_frame(self, frame: CanFrame, known: bool) -> None:
        with self._lock:
            item = frame.public_dict()
            self._recent.append(item)
            self._status["framesReceived"] += 1
            self._status["lastFrameAt"] = item["timestampUtc"]
            if not known:
                self._status["unknownPgnCount"] += 1

    def record_decode_error(self) -> None:
        with self._lock:
            self._status["decodeErrorCount"] += 1

    def record_decoded_frame(self) -> None:
        with self._lock:
            self._status["framesDecoded"] += 1

    def update(self, signal: DecodedSignal, now: datetime | None = None) -> dict[str, Any] | None:
        now = now or signal.timestamp_utc
        with self._lock:
            previous = self._signals.get(signal.key)
            reason = "initial"
            if previous:
                if previous["quality"] != signal.quality:
                    reason = "quality_change"
                elif self._changed(previous["value"], signal.value, signal.metadata):
                    reason = "changed"
                elif (now - datetime.fromisoformat(previous["lastPublishedAt"].replace("Z", "+00:00"))).total_seconds() >= self.heartbeat_seconds:
                    reason = "heartbeat"
                else:
                    reason = ""
            changed_at = now if not previous or reason == "changed" else datetime.fromisoformat(previous["lastChangedAt"].replace("Z", "+00:00"))
            published_at = now if reason else (datetime.fromisoformat(previous["lastPublishedAt"].replace("Z", "+00:00")) if previous else now)
            item = {
                "key": signal.key, "name": signal.name, "value": signal.value, "rawValue": signal.raw_value,
                "unit": signal.unit, "pgn": f"{signal.pgn:04X}", "sourceAddress": f"{signal.source_address:02X}",
                "timestampUtc": signal.timestamp_utc.isoformat().replace("+00:00", "Z"), "quality": signal.quality,
                "confidence": signal.confidence, "lastChangedAt": changed_at.isoformat().replace("+00:00", "Z"),
                "lastPublishedAt": published_at.isoformat().replace("+00:00", "Z"), "publishReason": reason or previous.get("publishReason"),
            }
            self._signals[signal.key] = item
            if reason in {"initial", "changed", "quality_change"}:
                self._status["signalsChanged"] += 1
            if reason == "heartbeat":
                self._status["heartbeatPublishes"] += 1
            return dict(item) if reason else None

    @staticmethod
    def _changed(old: Any, new: Any, definition: dict[str, Any]) -> bool:
        if old is None or new is None or not isinstance(old, (int, float)) or not isinstance(new, (int, float)):
            return old != new
        absolute = float(definition.get("change_threshold", 0))
        percent = float(definition.get("change_threshold_pct", 0))
        delta = abs(float(new) - float(old))
        return delta > max(absolute, abs(float(old)) * percent / 100.0)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"status": dict(self._status), "signals": [dict(x) for x in self._signals.values()], "recentFrames": list(self._recent)}

    def status(self) -> dict[str, Any]:
        return self.snapshot()["status"]

    def signals(self) -> list[dict[str, Any]]:
        return self.snapshot()["signals"]

    def recent(self) -> list[dict[str, Any]]:
        return self.snapshot()["recentFrames"]
