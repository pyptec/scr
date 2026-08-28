from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from pathlib import Path

from .models import CanFrame
from .parser import parse_capture_record, parse_slcan_line


class CanFrameSource(ABC):
    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def read_frame(self) -> CanFrame | None: ...

    @abstractmethod
    def close(self) -> None: ...


class SerialCanFrameSource(CanFrameSource):
    """Fuente RX-only. Nunca escribe comandos ni tramas al puerto."""

    def __init__(self, device: str, baudrate: int, timeout: float = 0.5) -> None:
        if not device:
            raise ValueError("J1939_SERIAL_DEVICE is required")
        self.device = device
        self.baudrate = baudrate
        self.timeout = timeout
        self._serial = None

    def open(self) -> None:
        import serial
        self._serial = serial.Serial(port=self.device, baudrate=self.baudrate, timeout=self.timeout)

    def read_frame(self) -> CanFrame | None:
        if self._serial is None:
            raise RuntimeError("serial source is not open")
        line = self._serial.readline()
        return parse_slcan_line(line) if line else None

    def close(self) -> None:
        if self._serial is not None:
            self._serial.close()
            self._serial = None


class ReplayCanFrameSource(CanFrameSource):
    def __init__(self, path: str | Path, stop_event: threading.Event | None = None) -> None:
        self.path = Path(path)
        self.stop_event = stop_event
        self._stream = None

    def open(self) -> None:
        self._stream = self.path.open(encoding="utf-8")

    def read_frame(self) -> CanFrame | None:
        if self._stream is None:
            raise RuntimeError("replay source is not open")
        while True:
            line = self._stream.readline()
            if not line:
                if self.stop_event:
                    self.stop_event.set()
                return None
            frame = parse_capture_record(line)
            if frame is not None:
                return frame

    def close(self) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None
