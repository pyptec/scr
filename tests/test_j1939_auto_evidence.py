from __future__ import annotations

import hashlib
import json
import socket
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from j1939.auto_evidence import AutoEvidence, EvidenceConfig, REPO_ROOT
from j1939.config import load_yaml
from j1939.decoder import SignalDecoder
from j1939.engine_recorder import EngineRecorder, RecorderConfig
from j1939.evidence_store import EvidenceStore
from j1939.parser import parse_capture_record, parse_slcan_line
from tests.test_j1939_engine_detector import FakeClock, synthetic_config


class AutoEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.directory = self.root / "external-evidence"
        self.store = EvidenceStore(self.root / "synthetic.sqlite", busy_ms=0)
        self.store.migrate_evidence(create=True)
        self.clock = FakeClock()
        self.cfg = EvidenceConfig(self.directory, ((0xF004, 0xEA), (0xFEEE, 0xEA), (0xFEE5, 0xEA), (0xFEF7, 0xEA)),
                                  gateway_id="synthetic-gateway", equipment_id="synthetic-generator", engine_source_address=0xEA,
                                  enabled=True, max_file_bytes=16384, max_total_bytes=4*1024*1024,
                                  min_free_bytes=0, segment_seconds=1000)
        self.capture = AutoEvidence(self.cfg, self.clock, self.store)
        self.recorder_config = RecorderConfig("synthetic-gateway", synthetic_config(), enabled=True, flush_seconds=1000)
        self.recorder = EngineRecorder(self.recorder_config, self.clock, self.store, batch_observer=self.capture.observe_batch)
        self.decoder = SignalDecoder(load_yaml(REPO_ROOT / "config/j1939_signals.yml")["signals"])
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.capture.close()
        self.temp.cleanup()

    def drain_capture(self):
        while self.capture.drain_once(): pass

    def drain_recorder(self):
        while self.recorder.drain_once(): pass

    def frame(self, rpm=0, *, source=0xEA):
        raw = int(rpm / 0.125).to_bytes(2, "little").hex().upper()
        return parse_slcan_line(f"T0CF004{source:02X}8FFFFFF{raw}FFFFFF", self.clock.utcnow())

    def feed(self, rpm=0, *, step=1):
        self.clock.advance(step)
        frame = self.frame(rpm)
        self.capture.offer_frame(frame)
        self.recorder.offer_decoded(self.decoder.decode(frame)[0])
        self.drain_recorder(); self.drain_capture()
        return frame

    def warm(self, seconds=70):
        for _ in range(seconds): self.feed(0)

    def running(self, *, warm=5):
        self.warm(warm)
        for _ in range(3): self.feed(1800)
        self.assertIsNotNone(self.capture.status()["activeCapture"])

    def stop_and_tail(self):
        for _ in range(3): self.feed(0)
        stopped = self.clock.utcnow()
        for _ in range(int(self.cfg.post_seconds)): self.feed(0)
        return stopped

    def metas(self):
        return [json.loads(p.read_text(encoding="utf-8")) for p in self.directory.glob("j1939_auto_*.json")]

    def frames(self):
        result = []
        for meta in self.metas():
            path = Path(meta["file_path"])
            if not path.exists(): continue
            for line in path.read_text(encoding="utf-8").splitlines():
                try: frame = parse_capture_record(line)
                except ValueError: continue
                if frame: result.append((meta["capture_id"], frame))
        return result

    def events(self, kind):
        with closing(sqlite3.connect(self.store.path)) as c:
            return c.execute("SELECT COUNT(*) FROM j1939_engine_events WHERE event_type=?", (kind,)).fetchone()[0]

    def reconfigure(self, **changes):
        self.capture.close()
        self.cfg = replace(self.cfg, **changes)
        self.capture = AutoEvidence(self.cfg, self.clock, self.store)
        self.recorder = EngineRecorder(self.recorder_config, self.clock, self.store, batch_observer=self.capture.observe_batch)

    def test_prebuffer_60_seconds_includes_real_candidate_transition(self):
        self.running(warm=70)
        start = self.clock.utcnow()
        self.capture.close()
        stamps = [f.timestamp_utc for _, f in self.frames()]
        self.assertLessEqual(min(stamps), start - timedelta(seconds=62))
        self.assertEqual(max(stamps), start)
        speeds = [int.from_bytes(f.data[3:5], "little") * 0.125 for _, f in self.frames()]
        self.assertIn(0, speeds); self.assertIn(1800, speeds)

    def test_memory_limits_and_short_prebuffer_are_visible(self):
        self.reconfigure(max_buffer_frames=12)
        self.running(warm=70)
        self.assertLessEqual(self.capture.status()["buffered"], 12)
        self.assertGreater(self.capture.status()["bufferEvictions"], 0)
        self.capture.close()
        self.assertIn("prebuffer_short", self.metas()[0]["warnings"])

    def test_prebuffer_time_is_bounded_including_confirmation_allowance(self):
        self.warm(120)
        buffered = self.capture._buffer
        self.assertLessEqual(buffered[-1][0] - buffered[0][0], 90)
        self.assertLessEqual(len(buffered), 91)

    def test_start_running_and_stop_markers_are_captured(self):
        self.running()
        self.feed(1800)
        self.stop_and_tail()
        contents = "\n".join(Path(m["file_path"]).read_text(encoding="utf-8") for m in self.metas())
        self.assertIn('"type": "START"', contents)
        self.assertIn('"type": "STOP"', contents)
        self.assertEqual(self.events("START"), 1)
        self.assertEqual(self.events("STOP"), 1)

    def test_60_seconds_after_confirmed_stop(self):
        self.running(warm=70)
        stopped = self.stop_and_tail()
        self.assertIsNone(self.capture.status()["activeCapture"])
        self.assertEqual(max(f.timestamp_utc for _, f in self.frames()), stopped + timedelta(seconds=60))
        self.assertTrue(all(m["close_reason"] == "post_stop_elapsed" for m in self.metas()))
        self.assertTrue(all(m["integrity"] == "COMPLETE" for m in self.metas()))

    def test_no_frames_in_post_window_is_incomplete(self):
        self.running(warm=70)
        for _ in range(3): self.feed(0)
        self.clock.advance(60); self.drain_capture()
        self.assertIn("post_window_no_rx", self.metas()[-1]["warnings"])
        self.assertEqual(self.metas()[-1]["integrity"], "INCOMPLETE")

    def test_communication_loss_never_closes_capture_or_invents_stop(self):
        self.running()
        original = self.capture.status()["activeCapture"]
        self.clock.advance(5)
        self.recorder.poll(); self.drain_recorder(); self.drain_capture()
        self.assertEqual(self.capture.status()["activeCapture"], original)
        self.assertEqual(self.events("STOP"), 0)
        for _ in range(3): self.feed(1800)
        self.assertEqual(self.capture.status()["activeCapture"], original)
        self.capture.close()
        text = "\n".join(Path(m["file_path"]).read_text(encoding="utf-8") for m in self.metas())
        self.assertIn("COMMUNICATION_LOST", text)
        self.assertIn("COMMUNICATION_RECOVERED", text)
        self.assertEqual(self.events("START"), 1)

    def test_rotation_by_size_preserves_all_frames_and_bounded_files(self):
        self.reconfigure(max_file_bytes=4096)
        self.running(warm=70)
        for _ in range(80): self.feed(1800)
        self.capture.close()
        self.assertGreater(len(self.metas()), 1)
        self.assertTrue(all(m["size_bytes"] <= 4096 for m in self.metas()))
        keys = [(cap, f.timestamp_utc, f.can_id, f.data) for cap, f in self.frames()]
        self.assertEqual(len(keys), len(set(keys)))

    def test_rotation_by_time(self):
        self.reconfigure(pre_seconds=1, max_confirmation_seconds=2, segment_seconds=2)
        self.running()
        for _ in range(6): self.feed(1800)
        self.capture.close()
        self.assertGreater(len(self.metas()), 2)
        self.assertTrue(any(m["close_reason"] == "rotation" for m in self.metas()))

    def test_disk_full_does_not_stop_recorder_or_receiver_offer(self):
        self.running()
        with patch("j1939.auto_evidence.shutil.disk_usage") as usage:
            usage.return_value.free = 0
            self.feed(1800)
        self.assertGreater(self.capture.storage_errors, 0)
        self.assertEqual(self.events("STOP"), 0)
        self.feed(1800)
        self.assertIsNotNone(self.capture.status()["activeCapture"])

    def test_write_error_keeps_partial_and_resumes_without_raw_retry_duplicates(self):
        self.running()
        original = self.capture._write
        with patch.object(self.capture, "_write", side_effect=OSError("synthetic full disk")):
            self.feed(1800)
        self.feed(1800)
        self.capture.close()
        self.assertTrue(any(m["close_reason"] == "write_error" for m in self.metas()))
        keys = [(cap, f.timestamp_utc, f.can_id, f.data) for cap, f in self.frames()]
        self.assertEqual(len(keys), len(set(keys)))

    def test_restart_recovers_incomplete_raw_and_links_new_segments_same_session(self):
        self.running()
        self.capture._file.close()
        self.capture._file = self.capture._meta = self.capture._capture = None
        self.capture._lease.close(); self.capture._lease = None
        self.clock.advance(10)
        self.capture = AutoEvidence(self.cfg, self.clock, self.store)
        self.recorder = EngineRecorder(self.recorder_config, self.clock, self.store, batch_observer=self.capture.observe_batch)
        for _ in range(3): self.feed(1800)
        self.capture.close()
        self.capture.synchronize()
        self.assertTrue(any(m["close_reason"] == "recovered_incomplete" for m in self.metas()))
        with closing(sqlite3.connect(self.store.path)) as c:
            sessions = c.execute("SELECT DISTINCT session_id FROM j1939_evidence_segments WHERE session_id IS NOT NULL").fetchall()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(self.events("STOP"), 0)
        self.assertEqual(self.events("START"), 1)

    def test_metadata_retry_is_idempotent_and_does_not_rewrite_raw(self):
        self.warm()
        with patch.object(self.store, "save_segment", side_effect=sqlite3.OperationalError("synthetic busy")):
            for _ in range(3): self.feed(1800)
            self.capture.close()
        hashes = {m["segment_id"]: hashlib.sha256(Path(m["file_path"]).read_bytes()).hexdigest() for m in self.metas()}
        self.capture.synchronize(); self.capture.synchronize()
        with closing(sqlite3.connect(self.store.path)) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM j1939_evidence_segments").fetchone()[0], len(hashes))
        self.assertEqual(hashes, {m["segment_id"]: hashlib.sha256(Path(m["file_path"]).read_bytes()).hexdigest() for m in self.metas()})

    def test_sqlite_unavailable_raw_continues_and_association_resolves_later(self):
        self.warm()
        with patch.object(self.store, "apply", side_effect=sqlite3.OperationalError("synthetic busy")), \
                patch.object(self.store, "save_segment", side_effect=sqlite3.OperationalError("synthetic busy")):
            for _ in range(3): self.feed(1800)
            self.feed(1800)
            self.assertTrue(self.capture._file is not None)
        self.drain_recorder()
        self.capture.close(); self.capture.synchronize()
        with closing(sqlite3.connect(self.store.path)) as c:
            self.assertIsNotNone(c.execute("SELECT session_id FROM j1939_evidence_segments").fetchone()[0])
        self.assertEqual(self.events("START"), 1)

    def test_session_file_metadata_sha_pgn_source_and_size(self):
        self.running()
        self.stop_and_tail()
        for m in self.metas():
            p = Path(m["file_path"])
            self.assertEqual(m["size_bytes"], p.stat().st_size)
            self.assertEqual(m["sha256"], hashlib.sha256(p.read_bytes()).hexdigest())
            self.assertIn("F004", m["pgns"]); self.assertIn("EA", m["sources"])
            self.assertIsNotNone(m["session_id"])
            self.assertGreater(m["frame_count"], 0)
        with closing(sqlite3.connect(self.store.path)) as c:
            self.assertEqual(c.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(c.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_raw_retry_and_control_retry_do_not_duplicate(self):
        self.running()
        frame = self.frame(1800)
        self.assertFalse(self.capture.offer_frame(frame))
        batch = self.recorder._queue.queue[0] if not self.recorder._queue.empty() else None
        # Comando ya procesado con la misma secuencia del escritor.
        from j1939.engine_store import RecordingBatch
        b = RecordingBatch("retry", self.recorder.writer_id, self.recorder._sequence,
                           "synthetic-gateway", "synthetic-generator", 0xEA,
                           self.clock.utcnow(), self.recorder.detector.state, self.recorder.detector.last_confirmed_state)
        before = self.capture.status()["queued"]
        self.assertTrue(self.capture.observe_batch(b))
        self.assertEqual(self.capture.status()["queued"], before)

    def test_explicit_pgn_sa_selection_does_not_mix_ecus(self):
        self.clock.advance(1)
        self.assertFalse(self.capture.offer_frame(self.frame(0, source=1)))
        temp = parse_slcan_line("T18FEEEEA860FFFFFFFFFFFFFF", self.clock.utcnow())
        self.assertTrue(self.capture.offer_frame(temp))
        self.drain_capture()
        self.assertEqual(len(self.capture._buffer), 1)
        self.assertEqual(self.capture._buffer[0][1].j1939.pgn, 0xFEEE)

    def test_operation_without_internet(self):
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")):
            self.running()
            self.stop_and_tail()
        self.assertEqual(self.events("STOP"), 1)

    def test_queue_overflow_is_bounded_and_does_not_call_disk_on_offer(self):
        self.reconfigure(queue_size=4)
        with patch.object(self.capture, "_initialize", side_effect=AssertionError("no IO on offer")):
            for _ in range(10):
                self.clock.advance(0.1)
                self.capture.offer_frame(self.frame())
        self.assertLessEqual(self.capture.status()["queued"], 2)
        self.assertGreater(self.capture.dropped_frames, 0)

    def test_default_disabled_has_no_files_or_worker(self):
        capture = AutoEvidence(replace(self.cfg, enabled=False, directory=self.root / "disabled"), self.clock, self.store)
        self.assertFalse(capture.offer_frame(self.frame()))
        capture.start(); self.assertTrue(capture.close())
        self.assertFalse((self.root / "disabled").exists())

    def test_configuration_rejects_repo_directory_and_unbounded_limits(self):
        with self.assertRaises(ValueError): replace(self.cfg, directory=REPO_ROOT / "data/evidence")
        for changes in ({"max_buffer_frames": 0}, {"queue_size": 2}, {"pre_seconds": float("inf")},
                        {"selections": ()}, {"selections": ((0xF004, 255),)}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): replace(self.cfg, **changes)

    def test_retention_disabled_and_unbacked_evidence_protected(self):
        self.running(warm=70); self.stop_and_tail()
        with self.assertRaises(PermissionError): self.capture.prune(authorized=True)
        self.capture.config = replace(self.cfg, retention_enabled=True, retention_seconds=1)
        self.clock.advance(2)
        self.assertEqual(self.capture.prune(authorized=True), 0)
        self.assertTrue(all(Path(m["file_path"]).exists() for m in self.metas()))

    def test_backed_up_active_session_is_protected_from_retention(self):
        self.reconfigure(retention_enabled=True, retention_seconds=1, segment_seconds=10)
        self.running(warm=70)
        complete = [m for m in self.metas() if m["integrity"] == "COMPLETE"]
        self.assertTrue(complete)
        for m in complete: self.capture.acknowledge_backup(m["segment_id"], m["sha256"])
        self.clock.advance(2)
        self.assertEqual(self.capture.prune(authorized=True), 0)

    def test_authorized_retention_only_for_complete_closed_backed_up_segments(self):
        self.reconfigure(retention_enabled=True, retention_seconds=1)
        self.running(warm=70); self.stop_and_tail()
        for m in self.metas(): self.capture.acknowledge_backup(m["segment_id"], m["sha256"])
        self.clock.advance(2)
        self.assertEqual(self.capture.prune(authorized=True), len(self.metas()))
        self.assertTrue(all(m["integrity"] == "DELETED" for m in self.metas()))
        self.assertEqual(self.capture.prune(authorized=True), 0)

    def test_directory_lease_prevents_two_writers(self):
        self.warm(1)
        other = AutoEvidence(self.cfg, self.clock, self.store)
        try:
            self.clock.advance(1); other.offer_frame(self.frame())
            self.assertFalse(other.drain_once())
            self.assertGreater(other.storage_errors, 0)
        finally: other.close()

    def test_migration_002_idempotent_and_preserves_001(self):
        self.warm(3)
        before = (REPO_ROOT / "j1939/migrations/001_engine_recorder.sql").read_bytes()
        self.store.migrate_evidence()
        self.assertEqual(before, (REPO_ROOT / "j1939/migrations/001_engine_recorder.sql").read_bytes())
        with closing(sqlite3.connect(self.store.path)) as c:
            self.assertEqual(c.execute("SELECT version FROM j1939_schema_migrations ORDER BY version").fetchall(), [(1,), (2,)])

    def test_failing_observer_does_not_change_prompt04_events(self):
        self.recorder._batch_observer = lambda batch: (_ for _ in ()).throw(OSError("synthetic observer failure"))
        self.warm(3)
        for _ in range(3): self.feed(1800)
        self.assertEqual(self.events("START"), 1)
        self.assertGreater(self.recorder.observer_errors, 0)

    def test_storage_file_limit_never_deletes_previous_evidence(self):
        self.reconfigure(max_files=1, segment_seconds=2)
        self.running()
        initial = set(self.directory.glob("*.txt*"))
        for _ in range(5): self.feed(1800)
        self.assertGreater(self.capture.storage_errors, 0)
        self.assertTrue(initial.issubset(set(self.directory.glob("*.txt*"))))


    def test_new_start_during_post_tail_keeps_distinct_sessions_and_candidate_window(self):
        self.running(warm=70)
        for _ in range(3): self.feed(0)
        candidate = self.clock.utcnow() + timedelta(seconds=1)
        for _ in range(3): self.feed(1800)
        self.capture.close()
        metas = self.metas()
        self.assertEqual(len({m["capture_id"] for m in metas}), 2)
        self.assertEqual(len({m["session_id"] for m in metas}), 2)
        newest = max(metas, key=lambda m: m["ended_at_utc"])
        self.assertLessEqual(newest["started_at_utc"], (candidate - timedelta(seconds=60)).isoformat(timespec="microseconds").replace("+00:00", "Z"))
        self.assertTrue(any(m["close_reason"] == "new_start_during_post_window" for m in metas))

    def test_foreign_gateway_equipment_or_engine_control_rejected(self):
        from j1939.engine_store import RecordingBatch
        from j1939.engine_detector import EngineState
        b = RecordingBatch("foreign", "writer", 1, "other", "synthetic-generator", 0xEA,
                           self.clock.utcnow(), EngineState.RUNNING, EngineState.RUNNING)
        self.assertFalse(self.capture.observe_batch(b))
        self.assertFalse(self.capture.observe_batch(replace(b, gateway_id="synthetic-gateway", source_address=1)))
        self.assertFalse(self.capture.observe_batch(replace(b, gateway_id="synthetic-gateway", equipment_id="other")))
        self.assertEqual(self.capture.status()["queued"], 0)

    def test_partial_or_uncertain_write_counts_actual_rows_without_replaying_frame(self):
        self.running()
        original = self.capture._write
        def write_then_fail(data):
            original(data)
            raise OSError("synthetic acknowledgement lost after raw write")
        with patch.object(self.capture, "_write", side_effect=write_then_fail):
            self.feed(1800)
        self.feed(1800); self.capture.close()
        for m in self.metas():
            rows = 0
            for line in Path(m["file_path"]).read_text(encoding="utf-8").splitlines():
                try: rows += int(parse_capture_record(line) is not None)
                except ValueError: pass
            self.assertEqual(m["frame_count"], rows)
        keys = [(cap, f.timestamp_utc, f.can_id, f.data) for cap, f in self.frames()]
        self.assertEqual(len(keys), len(set(keys)))

    def test_orphan_partial_with_truncated_line_recovers_without_complete_claim(self):
        import uuid
        self.directory.mkdir()
        path = self.directory / f"j1939_auto_{uuid.uuid4().hex}_{uuid.uuid4().hex}.txt.partial"
        path.write_text("2026-11-14T00:00:00Z,0CF004EA,true,8,FF FF FF 00 00 FF FF FF,F004,EA\ntruncated", encoding="utf-8")
        self.drain_capture()
        m = self.metas()[0]
        self.assertEqual(m["frame_count"], 1)
        self.assertEqual(m["integrity"], "INCOMPLETE")
        self.assertIn("orphan", m["warnings"])
        self.assertIn("malformed_record", m["warnings"])
        self.assertIsNone(m["session_id"])

    def test_missing_finalized_raw_is_reported_without_inventing_data(self):
        self.running(); self.capture.close()
        meta = self.metas()[0]
        path = Path(meta["file_path"])
        # Eliminación simulada exclusivamente en directorio temporal conocido.
        self.assertTrue(path.resolve().is_relative_to(self.root.resolve()))
        path.unlink()
        self.capture = AutoEvidence(self.cfg, self.clock, self.store)
        self.drain_capture()
        self.assertEqual(self.metas()[0]["integrity"], "MISSING")

    def test_corrupt_manifest_preserved_and_does_not_stop_new_capture(self):
        self.running(); self.capture.close()
        p = next(self.directory.glob("j1939_auto_*.json"))
        p.write_text("{broken-json", encoding="utf-8")
        self.capture = AutoEvidence(self.cfg, self.clock, self.store)
        self.drain_capture()
        self.assertEqual(p.read_text(encoding="utf-8"), "{broken-json")
        self.assertGreater(self.capture.metadata_errors, 0)
        self.assertIsNotNone(self.capture._lease)

    def test_background_worker_writes_and_closes_without_network(self):
        self.capture.start()
        self.running()
        self.assertTrue(self.capture.close(timeout=5))
        self.assertTrue(self.metas())
        self.assertTrue(all(m["integrity"] == "INCOMPLETE" for m in self.metas()))

    def test_metadata_migration_collision_rolls_back_version2(self):
        path = self.root / "collision.sqlite"
        store = EvidenceStore(path)
        store.migrate(create=True)
        with closing(sqlite3.connect(path)) as c:
            c.execute("CREATE TABLE j1939_evidence_segments(old TEXT)"); c.commit()
        with self.assertRaises(sqlite3.OperationalError): store.migrate_evidence()
        with closing(sqlite3.connect(path)) as c:
            self.assertEqual(c.execute("SELECT version FROM j1939_schema_migrations").fetchall(), [(1,)])
            self.assertEqual(c.execute("SELECT name FROM sqlite_master WHERE name='j1939_evidence_batch_sessions'").fetchall(), [])

    def test_retention_rejects_false_hash_attestation(self):
        self.running(warm=70); self.stop_and_tail()
        m = self.metas()[0]
        with self.assertRaises(ValueError): self.capture.acknowledge_backup(m["segment_id"], "0" * 64)
        self.assertTrue(Path(m["file_path"]).exists())

    def test_custom_post_window_and_preconfirmation_limit_are_explicit(self):
        self.reconfigure(pre_seconds=2, post_seconds=3, max_confirmation_seconds=4)
        self.running(warm=10)
        stopped = self.stop_and_tail()
        self.assertIsNone(self.capture.status()["activeCapture"])
        self.assertEqual(max(f.timestamp_utc for _, f in self.frames()), stopped + timedelta(seconds=3))

    def test_stop_deadline_survives_storage_failure(self):
        self.running()
        with patch("j1939.auto_evidence.shutil.disk_usage") as usage:
            usage.return_value.free = 0
            for _ in range(3): self.feed(0)
            self.clock.advance(60); self.drain_capture()
        self.assertIsNone(self.capture.status()["activeCapture"])
        self.assertEqual(self.events("STOP"), 1)

if __name__ == "__main__":
    unittest.main()
