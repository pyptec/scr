from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from j1939.capture import CaptureError, CaptureManager
from j1939.parser import parse_capture_record, parse_slcan_line
from j1939.transport import ReplayCanFrameSource


class CaptureTests(unittest.TestCase):
    def manager(self, path, **overrides):
        values = {"max_duration_seconds": 10, "max_file_mb": 1, "max_files": 2, "queue_size": 2, "metadata": {"transport":"replay","device":"fixture","serial_baudrate":115200,"can_bitrate":250000,"signal_config_version":"v1"}}
        values.update(overrides); return CaptureManager(Path(path), **values)

    def test_start_marker_stop_file_and_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = self.manager(folder)
            started = manager.start("Arranque", 5)
            with self.assertRaises(CaptureError): manager.start()
            frame = parse_slcan_line("T0CF004EA8FFFFFF4038FFFFFF\r")
            manager.offer(frame); manager.marker("Interruptor cerrado")
            stopped = manager.stop()
            self.assertFalse(stopped["captureActive"])
            target = manager.resolve(started["captureId"])
            text = target.read_text(encoding="utf-8")
            self.assertIn("# SAMEE100 J1939 capture", text)
            self.assertIn("# operator_note: Arranque", text)
            self.assertIn("# MARKER", text)
            self.assertIn(",0CF004EA,true,8,FF FF FF 40 38 FF FF FF,F004,EA", text)
            replay = ReplayCanFrameSource(target); replay.open()
            try: self.assertEqual(replay.read_frame().can_id, 0x0CF004EA)
            finally: replay.close()
            with self.assertRaises(CaptureError): manager.resolve("../../samee100")
            with self.assertRaises(CaptureError): manager.stop()

    def test_duration_and_storage_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = self.manager(folder, max_duration_seconds=1, max_files=1)
            manager.start(duration_seconds=1); time.sleep(1.4)
            self.assertFalse(manager.status()["captureActive"])
            with self.assertRaisesRegex(CaptureError, "CAPTURE_STORAGE_LIMIT"): manager.start()

    def test_queue_drop_does_not_block(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = self.manager(folder, queue_size=1)
            manager.start()
            frame = parse_slcan_line("T0CF004EA8FFFFFF4038FFFFFF\r")
            begin = time.perf_counter()
            for _ in range(10000): manager.offer(frame)
            elapsed = time.perf_counter() - begin
            status = manager.stop()
            self.assertLess(elapsed, 1.0)
            self.assertGreater(status["droppedCaptureFrames"], 0)

    def test_capture_record_rejects_malformed(self):
        with self.assertRaises(ValueError): parse_capture_record("bad")


if __name__ == "__main__": unittest.main()
