from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from pathlib import Path

from .models import CanFrame
from datetime import datetime, timezone
from typing import Any

from .parser import decode_identifier, parse_capture_record, parse_slcan_line


class TransportError(OSError):
    pass


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


class SocketCanFrameSource(CanFrameSource):
    """Receptor SocketCAN pasivo; esta clase no expone ninguna operación TX."""

    def __init__(self, interface: str = "can0", timeout: float = 0.5, *, can_module: Any = None) -> None:
        if not interface:
            raise ValueError("J1939_CAN_INTERFACE is required")
        self.interface = interface
        self.timeout = timeout
        self._can_module = can_module
        self._bus = None

    def open(self) -> None:
        try:
            can_module = self._can_module
            if can_module is None:
                import can as can_module
            self._can_module = can_module
            self._bus = can_module.Bus(interface="socketcan", channel=self.interface)
        except Exception as exc:
            self._bus = None
            raise TransportError(f"cannot open SocketCAN interface {self.interface}: {exc}") from exc

    def read_frame(self) -> CanFrame | None:
        if self._bus is None:
            raise RuntimeError("SocketCAN source is not open")
        try:
            message = self._bus.recv(timeout=self.timeout)
        except Exception as exc:
            raise TransportError(f"SocketCAN receive failed on {self.interface}: {exc}") from exc
        if message is None:
            return None
        if not bool(message.is_extended_id):
            return None
        can_id = int(message.arbitration_id)
        timestamp_value = float(message.timestamp) if getattr(message, "timestamp", None) else 0
        timestamp = datetime.fromtimestamp(timestamp_value, timezone.utc) if timestamp_value > 0 else datetime.now(timezone.utc)
        data = bytes(message.data)
        return CanFrame(
            timestamp_utc=timestamp,
            can_id=can_id,
            is_extended=True,
            dlc=int(message.dlc),
            data=data,
            j1939=decode_identifier(can_id),
        )

    def close(self) -> None:
        if self._bus is not None:
            try:
                self._bus.shutdown()
            finally:
                self._bus = None


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
