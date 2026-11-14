from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
from pathlib import Path

from j1939.engine_store import EngineStore
from j1939.engine_recorder import RecorderConfig
from j1939.parser import FrameParseError
from tests.test_j1939_engine_detector import synthetic_config
from tools.j1939_recorder_offline import main, parse_replay_line, run_replay

ROOT = Path(__file__).resolve().parent.parent


class RecorderReplayTests(unittest.TestCase):
    def test_candump_absolute_format_and_source(self):
        f = parse_replay_line("(1794657600.000000) can0 0CF004EA#FFFFFF0000FFFFFF", "candump")
        self.assertEqual((f.j1939.pgn, f.j1939.source_address, f.data[3:5]), (0xF004, 0xEA, b"\x00\x00"))
        self.assertEqual(f.timestamp_utc.tzinfo, timezone.utc)

    def test_capture_csv_reuses_existing_parser(self):
        f = parse_replay_line("2026-11-14T12:00:00Z,0CF004EA,true,8,FF FF FF 40 38 FF FF FF,F004,EA", "csv")
        self.assertEqual(f.can_id, 0x0CF004EA)
        self.assertIsNone(parse_replay_line("# header", "csv"))

    def test_unsupported_malformed_and_fd_fail_closed(self):
        for line in ("bad", "(1.0) can0 123#00", "(1.0) can0 0CF004EA##100", "(1.0) can0 0CF004EA#F"):
            with self.subTest(line=line), self.assertRaises(FrameParseError):
                parse_replay_line(line, "candump")
        with self.assertRaises(ValueError):
            parse_replay_line("x", "guessed")

    def test_synthetic_zero_rpm_replay_has_no_start_or_stop(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "synthetic-zero.log"
            path.write_text("\n".join(f"({1794657600+i}.000000) can0 0CF004EA#FFFFFF0000FFFFFF" for i in range(20)), encoding="utf-8")
            store = EngineStore(Path(folder) / "test.sqlite")
            store.migrate(create=True)
            result = run_replay(path, "candump", RecorderConfig("synthetic-gateway", synthetic_config(), enabled=True), store)
            self.assertEqual(result["maxRpm"], 0)
            self.assertEqual(result["rpmValidDecoded"], 20)
            self.assertEqual(result["rpmAccepted"], 20)
            self.assertNotIn("START", result["events"])
            self.assertNotIn("STOP", result["events"])
            self.assertEqual(result["events"]["STATE_RECONCILED"], 1)

    def test_synthetic_cycles_and_gap_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "synthetic-cycle.log"
            lines = []
            for second, rpm in enumerate([0]*3 + [1800]*5 + [0]*3):
                raw = int(rpm / 0.125).to_bytes(2, "little").hex().upper()
                lines.append(f"({1794657600+second}.000000) can0 0CF004EA#FFFFFF{raw}FFFFFF")
            path.write_text("\n".join(lines), encoding="utf-8")
            store = EngineStore(Path(folder) / "test.sqlite")
            store.migrate(create=True)
            result = run_replay(path, "candump", RecorderConfig("synthetic-gateway", synthetic_config(), enabled=True), store)
            self.assertEqual(result["events"]["START"], 1)
            self.assertEqual(result["events"]["STOP"], 1)

    def test_cli_requires_explicit_paths_and_offline_enable(self):
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()) as output:
            db = Path(folder) / "offline.sqlite"
            self.assertEqual(main(["migrate", "--database", str(db), "--create"]), 0)
            raw = Path(folder) / "synthetic.log"
            raw.write_text("\n".join(f"({1794657600+i}.000000) can0 0CF004EA#FFFFFF0000FFFFFF" for i in range(4)), encoding="utf-8")
            args = ["replay", "--input", str(raw), "--format", "candump", "--database", str(db),
                    "--config", str(ROOT / "config/j1939_recorder.example.json")]
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(args)
            self.assertEqual(main(args + ["--enable-offline-recording"]), 0)
            self.assertIn('"maxRpm": 0', output.getvalue())

    def test_replay_out_of_order_is_counted_not_reinterpreted(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "synthetic.log"
            path.write_text("\n".join(f"({1794657600+i}.000000) can0 0CF004EA#FFFFFF0000FFFFFF" for i in (0, 1, 2, 1, 3)), encoding="utf-8")
            store = EngineStore(Path(folder) / "test.sqlite")
            store.migrate(create=True)
            result = run_replay(path, "candump", RecorderConfig("synthetic-gateway", synthetic_config(), enabled=True), store)
            self.assertEqual(result["outOfOrder"], 1)
            self.assertEqual(result["rpmAccepted"], 4)


if __name__ == "__main__":
    unittest.main()
