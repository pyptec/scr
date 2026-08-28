from __future__ import annotations

from typing import Any

from .models import CanFrame, DecodedSignal


class SignalDecoder:
    def __init__(self, definitions: list[dict[str, Any]]) -> None:
        self.definitions = [dict(item) for item in definitions if item.get("enabled", True)]
        self._by_pgn: dict[int, list[dict[str, Any]]] = {}
        for item in self.definitions:
            pgn_value = item["pgn"]
            pgn = pgn_value if isinstance(pgn_value, int) else (int(str(pgn_value), 0) if str(pgn_value).lower().startswith("0x") else int(str(pgn_value), 16))
            self._by_pgn.setdefault(pgn, []).append(item)

    @property
    def known_pgns(self) -> set[int]:
        return set(self._by_pgn)

    def decode(self, frame: CanFrame) -> list[DecodedSignal]:
        if frame.j1939 is None:
            return []
        return [self._decode_one(frame, definition) for definition in self._by_pgn.get(frame.j1939.pgn, ())]

    @staticmethod
    def _decode_one(frame: CanFrame, definition: dict[str, Any]) -> DecodedSignal:
        start = int(definition["start_byte"]) - 1
        bit_length = int(definition["bit_length"])
        length = (bit_length + 7) // 8
        quality = "GOOD"
        raw: int | None = None
        value: float | int | str | None = None
        if bit_length % 8 or start < 0 or start + length > len(frame.data):
            quality = "INVALID"
        else:
            raw_bytes = frame.data[start : start + length]
            raw = int.from_bytes(raw_bytes, definition["byte_order"], signed=bool(definition["signed"]))
            invalid_values = {int(str(item), 0) if not isinstance(item, int) else item for item in definition.get("invalid_raw_values", [])}
            if raw in invalid_values:
                quality = "NOT_AVAILABLE"
            else:
                value = raw * float(definition["scale"]) + float(definition["offset"])
                if float(value).is_integer():
                    value = int(value)
                if (definition.get("minimum") is not None and value < definition["minimum"]) or (definition.get("maximum") is not None and value > definition["maximum"]):
                    quality = "INVALID"
                    value = None
                enum = definition.get("enum") or {}
                if quality == "GOOD" and str(raw) in enum:
                    value = enum[str(raw)]
        return DecodedSignal(
            key=str(definition["key"]), name=str(definition["name"]), value=value,
            raw_value=raw, unit=str(definition["unit"]), pgn=frame.j1939.pgn,
            source_address=frame.j1939.source_address, timestamp_utc=frame.timestamp_utc,
            quality=quality, confidence=str(definition["confidence"]), metadata=definition,
        )
