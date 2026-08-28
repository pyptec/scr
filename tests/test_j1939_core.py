from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from j1939.config import ConfigurationError, load_yaml
from j1939.decoder import SignalDecoder
from j1939.models import DecodedSignal
from j1939.parser import FrameParseError, decode_identifier, parse_slcan_line
from j1939.state import SignalState


ROOT = Path(__file__).resolve().parent.parent


class ParserTests(unittest.TestCase):
    def test_pdu2(self):
        item = decode_identifier(0x0CF004EA)
        self.assertEqual((item.priority, item.pgn, item.source_address, item.pdu_type), (3, 0xF004, 0xEA, "PDU2"))

    def test_pdu1(self):
        item = decode_identifier(0x18EA00EA)
        self.assertEqual((item.pgn, item.destination_address, item.pdu_type), (0xEA00, 0, "PDU1"))

    def test_serial_frame_and_failures(self):
        frame = parse_slcan_line("T0CF004EA8FFFFFF4038FFFFFF\r")
        self.assertEqual(frame.data, bytes.fromhex("FF FF FF 40 38 FF FF FF"))
        for line in ("", "t123", "T0CF004EAZ", "T0CF004EA8FF"):
            with self.assertRaises(FrameParseError): parse_slcan_line(line)
        with self.assertRaises(ValueError): decode_identifier(0x20000000)


class DecoderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_yaml(ROOT / "config/j1939_signals.yml")
        cls.decoder = SignalDecoder(cls.config["signals"])

    def test_confirmed_signals_and_unknown_pgn(self):
        rpm = self.decoder.decode(parse_slcan_line("T0CF004EA8FFFFFF4038FFFFFF\r"))[0]
        self.assertEqual((rpm.value, rpm.raw_value, rpm.quality), (1800, 0x3840, "GOOD"))
        temp = self.decoder.decode(parse_slcan_line("T18FEEEEA860FFFFFFFFFFFFFF\r"))[0]
        self.assertEqual(temp.value, 56)
        hours = self.decoder.decode(parse_slcan_line("T18FEE5EA8301B0000FFFFFFFF\r"))[0]
        self.assertEqual(hours.value, 348)
        self.assertEqual(self.decoder.decode(parse_slcan_line("T18EA00EA300F004\r")), [])

    def test_na_and_short_payload(self):
        na = self.decoder.decode(parse_slcan_line("T0CF004EA8FFFFFFFFFFFFFFFF\r"))[0]
        self.assertEqual(na.quality, "NOT_AVAILABLE")
        short = self.decoder.decode(parse_slcan_line("T0CF004EA3000000\r"))[0]
        self.assertEqual(short.quality, "INVALID")

    def test_generic_big_endian_signed_scale_offset(self):
        definition = {"key":"x","name":"X","pgn":"F004","start_byte":1,"bit_length":16,"byte_order":"big","signed":True,"scale":0.5,"offset":-1,"unit":"u","source":"test","enabled":True,"confidence":"CONFIRMED"}
        value = SignalDecoder([definition]).decode(parse_slcan_line("T0CF004EA2FFFC\r"))[0]
        self.assertEqual((value.raw_value, value.value), (-4, -3))

    def test_invalid_yaml(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.yml"; path.write_text("signals:\n  - key: x\n", encoding="utf-8")
            with self.assertRaises(ConfigurationError): load_yaml(path)


class StateTests(unittest.TestCase):
    def signal(self, value, stamp, quality="GOOD", threshold=0):
        return DecodedSignal("x", "X", value, int(value), "u", 0xF004, 0xEA, stamp, quality, "CONFIRMED", {"change_threshold": threshold})

    def test_change_no_change_heartbeat_quality_and_buffer(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        state = SignalState(600, recent_limit=1)
        self.assertEqual(state.update(self.signal(1, start))["publishReason"], "initial")
        self.assertIsNone(state.update(self.signal(1, start + timedelta(seconds=1))))
        self.assertIsNone(state.update(self.signal(1.4, start + timedelta(seconds=2), threshold=0.5)))
        self.assertEqual(state.update(self.signal(2, start + timedelta(seconds=3), threshold=0.5))["publishReason"], "changed")
        self.assertEqual(state.update(self.signal(2, start + timedelta(seconds=603), threshold=0.5))["publishReason"], "heartbeat")
        self.assertEqual(state.update(self.signal(2, start + timedelta(seconds=604), "INVALID"))["publishReason"], "quality_change")
        frame = parse_slcan_line("T0CF004EA8FFFFFF4038FFFFFF\r")
        state.record_frame(frame, True); state.record_frame(frame, True)
        self.assertEqual(len(state.recent()), 1)


if __name__ == "__main__": unittest.main()
