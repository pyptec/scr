from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
import tracemalloc
import unittest
from contextlib import closing
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from j1939.config import runtime_settings
from j1939.integration import build_integration
from j1939.evidence_store import EvidenceStore
from j1939.parser import parse_slcan_line
from j1939.service import J1939Runtime
from tests.test_j1939_engine_detector import FakeClock, synthetic_config

ROOT = Path(__file__).resolve().parent.parent


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.clock = FakeClock()
        self.store = EvidenceStore(self.root / "engine.sqlite", busy_ms=0)
        self.store.migrate_evidence(create=True)
        self.raw = dict(gateway_id="synthetic-gateway", detector=asdict(synthetic_config()),
                        database=str(self.store.path),
                        signal_sources=dict(engine_speed=234, coolant_temperature=235,
                                            dc_voltage_field_1=234, engine_total_hours=234),
                        recorder=dict(queue_size=8, flush_seconds=5),
                        evidence=dict(directory=str(self.root / "raw"), min_free_bytes=0,
                                      max_file_bytes=1024, max_total_bytes=1000000))
        self.config = self.root / "config.json"
        self.settings = dict(signal_file=ROOT / "config/j1939_signals.yml", heartbeat_seconds=600,
                             recent_frame_limit=2, transport="replay", replay_file="synthetic",
                             can_bitrate=250000, capture_dir=self.root / "manual",
                             capture_max_duration_seconds=10, capture_max_file_mb=1,
                             capture_max_files=2, capture_queue_size=8,
                             engine_events_enabled=True, auto_evidence_enabled=True,
                             engine_config=str(self.config))
        self.integration = None
        self.addCleanup(self.cleanup)

    def cleanup(self):
        if self.integration:
            self.integration.recorder.flush()
            while self.integration.recorder.drain_once(): pass
            self.integration.close()
        self.temp.cleanup()

    def make(self, *, start=False):
        self.config.write_text(json.dumps(self.raw), encoding="utf-8")
        self.integration = build_integration(self.settings, clock=self.clock, start=start)
        with patch("j1939.integration.build_integration", return_value=self.integration):
            self.runtime = J1939Runtime(self.settings)
        return self.integration

    def drain(self):
        while self.integration.recorder.drain_once(): pass
        if self.integration.evidence:
            while self.integration.evidence.drain_once(): pass

    def feed(self, rpm=0, source=234, *, drain=True):
        self.clock.advance(1)
        raw = int(rpm / 0.125).to_bytes(2, "little").hex().upper()
        frame = parse_slcan_line(f"T0CF004{source:02X}8FFFFFF{raw}FFFFFF", self.clock.utcnow())
        self.runtime.process(frame)
        if drain: self.drain()
        return frame

    def confirm(self, rpm):
        for _ in range(3): self.feed(rpm)

    def events(self):
        with closing(sqlite3.connect(self.store.path)) as c:
            return [r[0] for r in c.execute("SELECT event_type FROM j1939_engine_events ORDER BY rowid")]

    def test_defaults_and_disabled_no_observer_io(self):
        with patch.dict(os.environ, {}, clear=True):
            s = runtime_settings(ROOT)
        self.assertFalse(s["engine_events_enabled"])
        self.assertFalse(s["auto_evidence_enabled"])
        with patch("j1939.integration.Path.read_text", side_effect=AssertionError("IO forbidden")):
            self.assertIsNone(build_integration({}))
        self.settings.update(engine_events_enabled=False, auto_evidence_enabled=False)
        with patch("j1939.integration.build_integration", side_effect=AssertionError("disabled")):
            runtime = J1939Runtime(self.settings)
            runtime.process(parse_slcan_line("T0CF004EA8FFFFFF0000FFFFFF", self.clock.utcnow()))
            self.assertEqual(runtime.status()["framesReceived"], 1)
        self.assertFalse((self.root / "raw").exists())

    def test_start_stop_same_decoder_and_duplicate_frames(self):
        self.make(); self.confirm(0); self.confirm(1800)
        frame = self.feed(1800)
        self.runtime.process(frame); self.drain()
        self.confirm(0)
        self.assertEqual(self.events().count("START"), 1)
        self.assertEqual(self.events().count("STOP"), 1)
        with closing(sqlite3.connect(self.store.path)) as c:
            rows = c.execute("SELECT status,duration_seconds FROM j1939_engine_sessions").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "CERRADA")
        self.assertGreater(rows[0][1], 0)
        self.assertTrue(list((self.root / "raw").glob("*.partial")))

    def test_silence_poll_recovery_no_false_stop(self):
        self.make(); self.confirm(0); self.confirm(1800)
        self.clock.advance(6); self.integration.recorder.poll(); self.drain()
        self.assertIn("COMM_LOST", self.events()); self.assertNotIn("STOP", self.events())
        self.confirm(1800)
        self.assertIn("COMM_RECOVERED", self.events())
        self.assertEqual(self.events().count("START"), 1)

    def test_worker_polls_when_no_rx(self):
        self.make(start=True)
        for _ in range(3): self.feed(0, drain=False)
        self.clock.advance(6)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if "COMM_LOST" in self.events(): break
            time.sleep(0.02)
        self.assertIn("COMM_LOST", self.events())

    def test_wrong_source_out_of_order_no_events(self):
        self.make(); self.confirm(0)
        for _ in range(4): self.feed(1800, source=235)
        frame = parse_slcan_line("T0CF004EA8FFFFFF4038FFFFFF", self.clock.utcnow())
        self.clock.advance(3)
        self.runtime.process(frame); self.drain()
        self.assertNotIn("START", self.events())

    def test_restart_open_session_reconciles_without_duplicate_start(self):
        self.make(); self.confirm(0); self.confirm(1800)
        self.integration.close(); self.integration = None
        self.make(); self.confirm(1800)
        with closing(sqlite3.connect(self.store.path)) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM j1939_engine_sessions").fetchone()[0], 1)
        self.assertEqual(self.events().count("START"), 1)
        self.assertNotIn("STOP", self.events())

    def test_sqlite_busy_queue_full_reception_continues(self):
        self.make()
        with closing(sqlite3.connect(self.store.path, timeout=0)) as lock:
            lock.execute("BEGIN IMMEDIATE")
            for _ in range(60): self.feed(0)
            self.assertGreater(self.integration.recorder.write_errors, 0)
            self.assertGreater(self.integration.recorder.dropped_samples, 0)
            self.assertEqual(self.runtime.status()["framesReceived"], 60)
            lock.rollback()
        self.drain()
        self.assertIsNone(self.integration.recorder.last_error)

    def test_raw_write_failure_preserves_publications(self):
        self.make(); self.confirm(0)
        with patch.object(self.integration.evidence, "_write", side_effect=OSError("synthetic full disk")):
            self.confirm(1800)
        self.assertIn("START", self.events())
        self.assertGreater(self.integration.evidence.storage_errors, 0)
        self.assertEqual(self.runtime.status()["framesReceived"], 6)

    def test_rotated_raw_metadata_real_session(self):
        self.make(); self.confirm(0); self.confirm(1800)
        for _ in range(30): self.feed(1800)
        self.confirm(0)
        for _ in range(61): self.feed(0)
        with closing(sqlite3.connect(self.store.path)) as c:
            rows = c.execute("SELECT session_id,size_bytes FROM j1939_evidence_segments").fetchall()
        self.assertGreater(len(rows), 1)
        self.assertTrue(all(r[0] for r in rows))
        self.assertTrue(all(r[1] <= 1024 for r in rows))

    def test_signals_from_explicit_different_ecu_and_freshness(self):
        self.make(); self.confirm(0)
        # Coolant is FEEE, source EB; wrong source EA must not replace it.
        for sa in (235, 234):
            self.runtime.process(parse_slcan_line(f"T18FEEE{sa:02X}850FFFFFFFFFFFFFF", self.clock.utcnow()))
        self.assertEqual(self.integration.latest["coolant_temperature"].source_address, 235)
        self.confirm(1800)
        with closing(sqlite3.connect(self.store.path)) as c:
            ref = c.execute("SELECT evidence_ref FROM j1939_engine_events WHERE event_type='START'").fetchone()[0]
        snapshots = {s["key"]:s for s in json.loads(ref)["signals"]}
        self.assertEqual(snapshots["coolant_temperature"]["sourceAddress"], 235)
        self.assertFalse(snapshots["coolant_temperature"]["available"])
        self.assertIsNone(snapshots["coolant_temperature"]["value"])
        self.assertTrue(snapshots["engine_speed"]["available"])

    def test_no_migration_missing_database_fail_open(self):
        self.raw["database"] = str(self.root / "missing.sqlite")
        self.config.write_text(json.dumps(self.raw), encoding="utf-8")
        runtime = J1939Runtime(self.settings)
        self.assertIsNone(runtime.engine_integration)
        runtime.process(parse_slcan_line("T0CF004EA8FFFFFF0000FFFFFF", self.clock.utcnow()))
        self.assertEqual(runtime.status()["framesReceived"], 1)
        self.assertFalse((self.root / "missing.sqlite").exists())

    def test_measurement_database_forbidden_unchanged(self):
        with closing(sqlite3.connect(self.store.path)) as c:
            c.execute("CREATE TABLE mediciones(value REAL)"); c.commit()
        self.config.write_text(json.dumps(self.raw), encoding="utf-8")
        before = self.store.path.read_bytes()
        with self.assertRaises(ValueError): build_integration(self.settings, start=False)
        self.assertEqual(before, self.store.path.read_bytes())

    def test_raw_requires_events(self):
        with self.assertRaises(ValueError):
            build_integration(dict(engine_events_enabled=False, auto_evidence_enabled=True))

    def test_optional_raw_disabled_no_files(self):
        self.settings["auto_evidence_enabled"] = False
        self.make(); self.confirm(0); self.confirm(1800)
        self.assertIn("START", self.events())
        self.assertIsNone(self.integration.evidence)
        self.assertFalse((self.root / "raw").exists())

    def test_observer_exception_isolated_from_decoder(self):
        self.make()
        with patch.object(self.integration, "offer_decoded", side_effect=RuntimeError):
            self.feed(0)
        self.assertEqual(self.integration.errors, 1)
        self.assertEqual(self.runtime.status()["decodeErrorCount"], 0)
        self.assertEqual(self.runtime.state.signals()[0]["value"], 0)

    def test_out_of_order_sample_does_not_replace_latest(self):
        self.make(); old = self.feed(0); self.feed(0)
        latest = self.integration.latest["engine_speed"].timestamp_utc
        self.runtime.process(old); self.drain()
        self.assertEqual(self.integration.latest["engine_speed"].timestamp_utc, latest)
        self.assertNotIn("START", self.events())

    def test_checksum_mismatch_disables_only_recorder(self):
        with closing(sqlite3.connect(self.store.path)) as c:
            c.execute("UPDATE j1939_schema_migrations SET checksum='invalid' WHERE version=2"); c.commit()
        self.config.write_text(json.dumps(self.raw), encoding="utf-8")
        runtime = J1939Runtime(self.settings)
        self.assertIsNone(runtime.engine_integration)
        self.assertEqual(runtime.status()["engineIntegration"]["initializationOrOfferError"], "ValueError")

    def test_future_sample_does_not_poison_snapshot_cache(self):
        self.make(); self.feed(0)
        future = parse_slcan_line("T0CF004EA8FFFFFF4038FFFFFF", self.clock.utcnow() + timedelta(days=1))
        self.runtime.process(future)
        self.confirm(0); self.confirm(1800)
        self.assertEqual(self.integration.latest["engine_speed"].timestamp_utc, self.clock.utcnow())
        self.assertIn("START", self.events())

    def test_service_lifecycle_uses_one_source_and_closes_observer(self):
        from services import j1939_can_service as service
        source, runtime, server, thread = MagicMock(), MagicMock(), MagicMock(), MagicMock()
        source.read_frame.return_value = None
        runtime.capture.status.return_value = {"captureActive": False}
        settings = dict(enabled=True, transport="replay", replay_file="fixture",
                        api_host="127.0.0.1", api_port=8765)
        with patch.object(service, "load_project_env"), patch.object(service, "signal"), \
             patch.object(service, "runtime_settings", return_value=settings), \
             patch.object(service, "create_frame_source", return_value=source) as create, \
             patch.object(service, "J1939Runtime", return_value=runtime), \
             patch.object(service, "start_local_api", return_value=(server, thread)), \
             patch.object(service.sys, "argv", ["j1939_can_service.py"]):
            self.assertEqual(service.main(), 0)
        create.assert_called_once(); source.open.assert_called_once(); source.close.assert_called_once()
        runtime.close_engine_integration.assert_called_once(); source.send.assert_not_called()
        server.shutdown.assert_called_once()

    def test_api_start_failure_closes_observer(self):
        from services import j1939_can_service as service
        runtime = MagicMock()
        settings = dict(enabled=True, transport="replay", replay_file="fixture",
                        api_host="127.0.0.1", api_port=8765)
        with patch.object(service, "load_project_env"), patch.object(service, "signal"), \
             patch.object(service, "runtime_settings", return_value=settings), \
             patch.object(service, "create_frame_source") as create, \
             patch.object(service, "J1939Runtime", return_value=runtime), \
             patch.object(service, "start_local_api", side_effect=OSError("synthetic bind failure")), \
             patch.object(service.sys, "argv", ["j1939_can_service.py"]):
            with self.assertRaises(OSError): service.main()
        runtime.close_engine_integration.assert_called_once()
        create.return_value.open.assert_not_called()

    def test_bounded_cost_offers_without_io_or_can(self):
        self.make()
        frame = parse_slcan_line("T0CF004EA8FFFFFF0000FFFFFF", self.clock.utcnow())
        tracemalloc.start(); start = time.process_time()
        with patch("sqlite3.connect", side_effect=AssertionError("RX SQL forbidden")), \
             patch("socket.socket", side_effect=AssertionError("RX network forbidden")), \
             patch("builtins.open", side_effect=AssertionError("RX file forbidden")):
            for _ in range(10000): self.runtime.process(frame)
        cpu = time.process_time() - start
        _, peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
        print(f"SYNTHETIC_RX_BENCH frames=10000 cpu_seconds={cpu:.4f} traced_peak_bytes={peak}")
        self.assertEqual(self.runtime.status()["framesReceived"], 10000)
        self.assertLessEqual(self.integration.evidence.status()["queued"], 2048)
        self.assertLessEqual(len(self.integration.latest), 4)
        self.assertLess(peak, 10000000)


if __name__ == "__main__":
    unittest.main()
