from __future__ import annotations

import os
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from j1939.capture import CaptureManager
from j1939.config import ConfigurationError, load_project_env, runtime_settings
from j1939.transport import (
    ReplayCanFrameSource,
    SerialCanFrameSource,
    SocketCanFrameSource,
    TransportError,
)
from j1939.state import SignalState
from services.j1939_can_service import create_frame_source, main


ROOT = Path(__file__).resolve().parent.parent


class FakeBus:
    def __init__(self, messages=()):
        self.messages = list(messages)
        self.recv_calls = []
        self.shutdown_calls = 0

    def recv(self, timeout):
        self.recv_calls.append(timeout)
        return self.messages.pop(0) if self.messages else None

    def shutdown(self):
        self.shutdown_calls += 1


def message(*, extended=True):
    return SimpleNamespace(
        arbitration_id=0x0CF004EA,
        is_extended_id=extended,
        dlc=8,
        data=bytearray.fromhex("FF FF FF 40 38 FF FF FF"),
        timestamp=1_700_000_000.25,
    )


class SocketCanSourceTests(unittest.TestCase):
    def test_open_can0_receive_extended_and_close(self):
        bus = FakeBus([message()])
        module = SimpleNamespace(Bus=Mock(return_value=bus))
        source = SocketCanFrameSource("can0", timeout=0.2, can_module=module)
        source.open()
        module.Bus.assert_called_once_with(interface="socketcan", channel="can0")
        frame = source.read_frame()
        self.assertEqual(frame.can_id, 0x0CF004EA)
        self.assertEqual(frame.dlc, 8)
        self.assertEqual(frame.data, bytes.fromhex("FF FF FF 40 38 FF FF FF"))
        self.assertTrue(frame.is_extended)
        self.assertEqual(frame.j1939.source_address, 0xEA)
        self.assertEqual(frame.timestamp_utc, datetime.fromtimestamp(1_700_000_000.25, timezone.utc))
        self.assertEqual(bus.recv_calls, [0.2])
        source.close()
        self.assertEqual(bus.shutdown_calls, 1)

    def test_timeout_and_standard_frame_are_ignored(self):
        bus = FakeBus([message(extended=False)])
        source = SocketCanFrameSource("can0", can_module=SimpleNamespace(Bus=Mock(return_value=bus)))
        source.open()
        self.assertIsNone(source.read_frame())
        self.assertIsNone(source.read_frame())
        source.close()

    def test_open_error_then_reopen_supports_service_reconnection(self):
        bus = FakeBus()
        factory = Mock(side_effect=[OSError("can0 missing"), bus])
        source = SocketCanFrameSource("can0", can_module=SimpleNamespace(Bus=factory))
        with self.assertRaises(TransportError):
            source.open()
        source.open()
        source.close()
        self.assertEqual(factory.call_count, 2)

    def test_receive_error_is_normalized(self):
        bus = FakeBus()
        bus.recv = Mock(side_effect=OSError("interface down"))
        source = SocketCanFrameSource("can0", can_module=SimpleNamespace(Bus=Mock(return_value=bus)))
        source.open()
        with self.assertRaises(TransportError):
            source.read_frame()
        source.close()

    def test_socketcan_capture_metadata_and_replay_compatibility(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = CaptureManager(
                Path(folder), max_duration_seconds=10, max_file_mb=1, max_files=2,
                queue_size=10, metadata={"transport":"socketcan", "device":"can0",
                                         "interface":"can0", "can_bitrate":250000,
                                         "signal_config_version":"v1"},
            )
            capture = manager.start("socketcan", 5)
            bus = FakeBus([message()])
            source = SocketCanFrameSource("can0", can_module=SimpleNamespace(Bus=Mock(return_value=bus)))
            source.open(); manager.offer(source.read_frame()); source.close(); manager.stop()
            text = manager.resolve(capture["captureId"]).read_text(encoding="utf-8")
            self.assertIn("# transport: socketcan", text)
            self.assertIn("# interface: can0", text)
            self.assertNotIn("# serial_baudrate:", text)
            replay = ReplayCanFrameSource(manager.resolve(capture["captureId"])); replay.open()
            try: self.assertEqual(replay.read_frame().can_id, 0x0CF004EA)
            finally: replay.close()


class ConfigurationAndSelectionTests(unittest.TestCase):
    def settings(self, transport):
        return {"transport":transport, "can_interface":"can0", "serial_device":"COM3",
                "serial_baudrate":115200, "replay_file":"capture.txt"}

    def test_explicit_transport_selection(self):
        stop = threading.Event()
        self.assertIsInstance(create_frame_source(self.settings("socketcan"), stop), SocketCanFrameSource)
        self.assertIsInstance(create_frame_source(self.settings("serial"), stop), SerialCanFrameSource)
        self.assertIsInstance(create_frame_source(self.settings("replay"), stop), ReplayCanFrameSource)
        with self.assertRaises(ConfigurationError): create_frame_source(self.settings("invalid"), stop)

    def test_runtime_socketcan_environment(self):
        env = {"J1939_ENABLED":"true", "J1939_TRANSPORT":"socketcan",
               "J1939_CAN_INTERFACE":"can0", "J1939_CAN_BITRATE":"250000"}
        with patch.dict(os.environ, env, clear=True):
            settings = runtime_settings(ROOT)
        self.assertTrue(settings["enabled"])
        self.assertEqual((settings["transport"], settings["can_interface"], settings["can_bitrate"]),
                         ("socketcan", "can0", 250000))

    def test_generic_reconnect_counter_keeps_serial_compatibility(self):
        state = SignalState()
        state.configure_transport("socketcan", "can0")
        state.set_connected(True, reconnect=True)
        status = state.status()
        self.assertEqual(status["transportReconnectCount"], 1)
        self.assertEqual(status["serialReconnectCount"], 0)
        self.assertEqual((status["device"], status["interface"]), ("can0", "can0"))

    def test_project_env_uses_root_and_does_not_override(self):
        called = {}
        def fake_load_dotenv(*, dotenv_path, override):
            called.update(path=dotenv_path, override=override); return True
        fake_module = SimpleNamespace(load_dotenv=fake_load_dotenv)
        with patch.dict(sys.modules, {"dotenv": fake_module}):
            self.assertTrue(load_project_env(ROOT))
        self.assertEqual(called, {"path": ROOT / ".env", "override": False})

    def test_disabled_main_does_not_create_transport(self):
        with patch("services.j1939_can_service.load_project_env"), \
             patch("services.j1939_can_service.runtime_settings", return_value={"enabled":False}), \
             patch("services.j1939_can_service.create_frame_source") as create, \
             patch.object(sys, "argv", ["j1939_can_service.py"]):
            self.assertEqual(main(), 0)
            create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
