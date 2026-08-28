from __future__ import annotations

from datetime import datetime, timezone

from .models import CanFrame, J1939Identifier


class FrameParseError(ValueError):
    pass


def decode_identifier(can_id: int) -> J1939Identifier:
    if isinstance(can_id, bool) or not isinstance(can_id, int):
        raise TypeError("can_id must be an integer")
    if not 0 <= can_id <= 0x1FFFFFFF:
        raise ValueError("can_id must be a 29-bit value")
    priority = (can_id >> 26) & 0x07
    reserved = (can_id >> 25) & 0x01
    data_page = (can_id >> 24) & 0x01
    pf = (can_id >> 16) & 0xFF
    ps = (can_id >> 8) & 0xFF
    source = can_id & 0xFF
    if pf < 240:
        destination = ps
        pgn = (data_page << 16) | (pf << 8)
        pdu_type = "PDU1"
    else:
        destination = 0xFF
        pgn = (data_page << 16) | (pf << 8) | ps
        pdu_type = "PDU2"
    return J1939Identifier(priority, reserved, data_page, pf, ps, source, destination, pgn, pdu_type)


def parse_slcan_line(line: str | bytes, timestamp: datetime | None = None) -> CanFrame:
    """Parsea únicamente el formato ASCII observado: T + ID(8) + DLC + DATA."""
    if isinstance(line, bytes):
        try:
            line = line.decode("ascii")
        except UnicodeDecodeError as exc:
            raise FrameParseError("serial line is not ASCII") from exc
    value = line.strip("\r\n ")
    if not value or value[0] != "T":
        raise FrameParseError("only extended SLCAN T frames are accepted")
    if len(value) < 10:
        raise FrameParseError("frame is too short")
    try:
        can_id = int(value[1:9], 16)
        dlc = int(value[9], 16)
    except ValueError as exc:
        raise FrameParseError("invalid CAN ID or DLC") from exc
    if dlc > 8:
        raise FrameParseError("classic CAN DLC must be 0..8")
    payload_hex = value[10:]
    if len(payload_hex) != dlc * 2:
        raise FrameParseError("payload length does not match DLC")
    try:
        payload = bytes.fromhex(payload_hex)
        identifier = decode_identifier(can_id)
    except ValueError as exc:
        raise FrameParseError(str(exc)) from exc
    now = timestamp or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return CanFrame(now.astimezone(timezone.utc), can_id, True, dlc, payload, identifier)


def parse_capture_record(line: str) -> CanFrame | None:
    value = line.strip()
    if not value or value.startswith("#") or value.startswith("timestamp_utc,"):
        return None
    parts = value.split(",")
    if len(parts) != 7:
        raise FrameParseError("capture record must have seven columns")
    stamp, can_id_hex, extended, dlc_text, data_hex, _pgn, _source = parts
    if extended.lower() != "true":
        raise FrameParseError("capture record is not extended CAN")
    stamp = stamp.removesuffix("Z") + "+00:00" if stamp.endswith("Z") else stamp
    timestamp = datetime.fromisoformat(stamp)
    compact = data_hex.replace(" ", "")
    return parse_slcan_line(f"T{can_id_hex}{int(dlc_text):X}{compact}", timestamp)
