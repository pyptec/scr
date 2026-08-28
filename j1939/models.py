from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class J1939Identifier:
    priority: int
    reserved: int
    data_page: int
    pdu_format: int
    pdu_specific: int
    source_address: int
    destination_address: int
    pgn: int
    pdu_type: str


@dataclass(frozen=True, slots=True)
class CanFrame:
    timestamp_utc: datetime
    can_id: int
    is_extended: bool
    dlc: int
    data: bytes
    j1939: J1939Identifier | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "timestampUtc": self.timestamp_utc.isoformat().replace("+00:00", "Z"),
            "canId": f"{self.can_id:08X}",
            "extended": self.is_extended,
            "dlc": self.dlc,
            "data": self.data.hex(" ").upper(),
            "pgn": f"{self.j1939.pgn:04X}" if self.j1939 else None,
            "sourceAddress": f"{self.j1939.source_address:02X}" if self.j1939 else None,
        }


@dataclass(frozen=True, slots=True)
class DecodedSignal:
    key: str
    name: str
    value: float | int | str | None
    raw_value: int | None
    unit: str
    pgn: int
    source_address: int
    timestamp_utc: datetime
    quality: str
    confidence: str
    metadata: dict[str, Any] = field(default_factory=dict)
