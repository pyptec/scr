from __future__ import annotations

import json
import queue
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import CanFrame

CAPTURE_ID = re.compile(r"^j1939_capture_\d{8}_\d{6}Z$")


def utc_text(value: datetime | None = None) -> str:
    return (value or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class CaptureError(RuntimeError):
    pass


class CaptureManager:
    def __init__(self, directory: Path, *, max_duration_seconds: int, max_file_mb: float, max_files: int, queue_size: int, metadata: dict[str, Any]) -> None:
        self.directory = directory
        self.max_duration_seconds = max_duration_seconds
        self.max_bytes = int(max_file_mb * 1024 * 1024)
        self.max_files = max_files
        self.queue_size = queue_size
        self.metadata = metadata
        self._lock = threading.RLock()
        self._queue: queue.Queue[tuple[str, Any] | None] | None = None
        self._thread: threading.Thread | None = None
        self._stream = None
        self._active = False
        self._started: datetime | None = None
        self._stopped: datetime | None = None
        self._file: Path | None = None
        self._note = ""
        self._bytes = 0
        self._frames = 0
        self._dropped = 0
        self._limit_reason: str | None = None

    def start(self, note: str = "", duration_seconds: int | None = None) -> dict[str, Any]:
        with self._lock:
            if self._active:
                raise CaptureError("CAPTURE_ALREADY_ACTIVE")
            self.directory.mkdir(parents=True, exist_ok=True)
            if len(list(self.directory.glob("j1939_capture_*.txt"))) >= self.max_files:
                raise CaptureError("CAPTURE_STORAGE_LIMIT")
            requested = int(duration_seconds or self.max_duration_seconds)
            if requested < 1 or requested > self.max_duration_seconds:
                raise CaptureError("CAPTURE_INVALID_DURATION")
            self._duration = requested
            self._started = datetime.now(timezone.utc)
            self._stopped = None
            capture_id = self._started.strftime("j1939_capture_%Y%m%d_%H%M%SZ")
            self._file = self.directory / f"{capture_id}.txt"
            if self._file.exists():
                raise CaptureError("CAPTURE_NAME_COLLISION")
            self._note = str(note).replace("\r", " ").replace("\n", " ")[:500]
            self._bytes = self._frames = self._dropped = 0
            self._limit_reason = None
            self._queue = queue.Queue(maxsize=self.queue_size)
            self._stream = self._file.open("x", encoding="utf-8", newline="\n")
            header = self._header()
            self._stream.write(header)
            self._stream.flush()
            self._bytes = len(header.encode("utf-8"))
            self._active = True
            self._thread = threading.Thread(target=self._writer, name="j1939-capture-writer", daemon=True)
            self._thread.start()
            return self.status()

    def _header(self) -> str:
        rows = [
            "# SAMEE100 J1939 capture",
            "# capture_version: samee100-j1939-capture-v1",
            f"# started_at_utc: {utc_text(self._started)}",
            "# stopped_at_utc: pending",
            f"# operator_note: {self._note}",
            f"# transport: {self.metadata.get('transport', '')}",
            f"# device: {self.metadata.get('device', '')}",
        ]
        if self.metadata.get("interface"):
            rows.append(f"# interface: {self.metadata['interface']}")
        if self.metadata.get("serial_baudrate") is not None:
            rows.append(f"# serial_baudrate: {self.metadata['serial_baudrate']}")
        rows.extend([
            f"# can_bitrate: {self.metadata.get('can_bitrate', '')}",
            f"# signal_config_version: {self.metadata.get('signal_config_version', '')}",
            "timestamp_utc,can_id,extended,dlc,data,pgn,source_address",
        ])
        return "\n".join(rows) + "\n"

    def offer(self, frame: CanFrame) -> None:
        with self._lock:
            target = self._queue if self._active else None
        if target is None:
            return
        try:
            target.put_nowait(("frame", frame))
        except queue.Full:
            with self._lock:
                self._dropped += 1

    def marker(self, note: str) -> dict[str, Any]:
        clean = str(note).replace("\r", " ").replace("\n", " ")[:500]
        if not clean:
            raise CaptureError("CAPTURE_MARKER_NOTE_REQUIRED")
        with self._lock:
            if not self._active or self._queue is None:
                raise CaptureError("CAPTURE_NOT_ACTIVE")
            try:
                self._queue.put_nowait(("marker", clean))
            except queue.Full as exc:
                raise CaptureError("CAPTURE_QUEUE_FULL") from exc
        return self.status()

    def _writer(self) -> None:
        assert self._queue is not None
        while True:
            try:
                item = self._queue.get(timeout=0.25)
            except queue.Empty:
                if self._duration_reached():
                    self.stop("MAX_DURATION")
                    return
                continue
            if item is None:
                break
            kind, value = item
            if kind == "marker":
                line = f'# MARKER {utc_text()} {json.dumps(value, ensure_ascii=False)}\n'
            else:
                frame: CanFrame = value
                public = frame.public_dict()
                line = f'{public["timestampUtc"]},{public["canId"]},true,{frame.dlc},{public["data"]},{public["pgn"]},{public["sourceAddress"]}\n'
            encoded = line.encode("utf-8")
            with self._lock:
                if self._bytes + len(encoded) > self.max_bytes:
                    self._limit_reason = "MAX_FILE_SIZE"
                    threading.Thread(target=self.stop, args=("MAX_FILE_SIZE",), daemon=True).start()
                    break
                self._stream.write(line)
                self._bytes += len(encoded)
                if kind == "frame":
                    self._frames += 1
        with self._lock:
            if self._stream:
                self._stream.flush()

    def _duration_reached(self) -> bool:
        with self._lock:
            return bool(self._active and self._started and (datetime.now(timezone.utc) - self._started).total_seconds() >= self._duration)

    def stop(self, reason: str | None = None) -> dict[str, Any]:
        with self._lock:
            if not self._active:
                if reason:
                    return self.status()
                raise CaptureError("CAPTURE_NOT_ACTIVE")
            self._active = False
            self._limit_reason = reason or self._limit_reason
            target = self._queue
            thread = self._thread
        # La cola se señaliza fuera del lock: el writer necesita el mismo lock
        # para drenar y una cola llena no debe provocar interbloqueo.
        if target is not None:
            try:
                target.put(None, timeout=3)
            except queue.Full:
                pass
        if thread and thread is not threading.current_thread():
            thread.join(timeout=3)
        with self._lock:
            if self._stream:
                self._stopped = datetime.now(timezone.utc)
                footer = f"# stopped_at_utc: {utc_text(self._stopped)}\n# captured_frames: {self._frames}\n# dropped_capture_frames: {self._dropped}\n"
                self._stream.write(footer)
                self._stream.flush()
                self._bytes += len(footer.encode("utf-8"))
                self._stream.close()
                self._stream = None
            return self.status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            elapsed = ((self._stopped or datetime.now(timezone.utc)) - self._started).total_seconds() if self._started else 0
            return {
                "captureActive": self._active,
                "captureStartedAt": utc_text(self._started) if self._started else None,
                "captureFileName": self._file.name if self._file else None,
                "captureId": self._file.stem if self._file else None,
                "captureElapsedSeconds": round(elapsed, 1),
                "captureBytesWritten": self._bytes,
                "capturedFrames": self._frames,
                "droppedCaptureFrames": self._dropped,
                "captureNote": self._note,
                "captureLimitReason": self._limit_reason,
            }

    def list_captures(self) -> list[dict[str, Any]]:
        if not self.directory.exists():
            return []
        return [{"captureId": p.stem, "fileName": p.name, "sizeBytes": p.stat().st_size, "modifiedAt": utc_text(datetime.fromtimestamp(p.stat().st_mtime, timezone.utc))} for p in sorted(self.directory.glob("j1939_capture_*.txt"), reverse=True) if CAPTURE_ID.fullmatch(p.stem)]

    def resolve(self, capture_id: str) -> Path:
        if not CAPTURE_ID.fullmatch(str(capture_id)):
            raise CaptureError("CAPTURE_NOT_FOUND")
        path = self.directory / f"{capture_id}.txt"
        if not path.is_file():
            raise CaptureError("CAPTURE_NOT_FOUND")
        return path
