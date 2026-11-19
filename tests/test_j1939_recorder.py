from __future__ import annotations

import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from j1939.engine_detector import EngineState, RpmSample
from j1939.engine_recorder import EngineRecorder, RecorderConfig
from j1939.engine_store import EngineStore, RecordingBatch, WriterConflict, utc_text
from j1939.config import load_yaml
from j1939.decoder import SignalDecoder
from j1939.parser import parse_slcan_line
from j1939.service import J1939Runtime
from tests.test_j1939_engine_detector import FakeClock, synthetic_config

ROOT = Path(__file__).resolve().parent.parent


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "synthetic.sqlite"
        self.store = EngineStore(self.path, busy_ms=0)
        self.store.migrate(create=True)
        self.clock = FakeClock()
        self.config = RecorderConfig("synthetic-gateway", synthetic_config(), enabled=True, flush_seconds=1)
        self.recorder = EngineRecorder(self.config, self.clock, self.store)

    def rows(self, table, where="", args=()):
        with sqlite3.connect(self.path) as c:
            c.row_factory = sqlite3.Row
            return [dict(row) for row in c.execute("SELECT * FROM " + table + where, args)]

    def events(self, kind=None):
        return self.rows("j1939_engine_events", " WHERE event_type=?" if kind else "", (kind,) if kind else ())

    def drain(self):
        while self.recorder.drain_once():
            pass
        self.assertIsNone(self.recorder.last_error)

    def feed(self, rpm, *, quality="GOOD", step=1, **changes):
        self.clock.advance(step)
        sample = replace(RpmSample(self.clock.utcnow(), rpm, 0xEA, "synthetic-generator", quality=quality), **changes)
        result = self.recorder.offer(sample, evidence_ref="synthetic:unit-test")
        self.drain()
        return result

    def confirm(self, rpm):
        for _ in range(3):
            self.feed(rpm)

    def running(self):
        self.confirm(0)
        self.confirm(1800)
        self.assertEqual(len(self.events("START")), 1)

    def lose(self):
        self.clock.advance(5)
        self.recorder.poll()
        self.drain()

    def test_start_record_and_open_session(self):
        self.running()
        event = self.events("START")[0]
        self.assertEqual((event["gateway_id"], event["equipment_id"], event["source_address"]),
                         ("synthetic-gateway", "synthetic-generator", 0xEA))
        self.assertEqual((event["pgn"], event["spn"], event["rpm"]), (0xF004, 190, 1800))
        session = self.rows("j1939_engine_sessions")[0]
        self.assertEqual((session["status"], session["active"]), ("ABIERTA", 1))
        self.assertIsNone(session["ended_at_utc"])
        self.assertEqual(session["start_event_id"], event["event_id"])
        self.assertEqual(event["evidence_ref"], "synthetic:unit-test")

    def test_stop_closes_and_calculates_duration(self):
        self.running()
        for _ in range(4):
            self.feed(1800)
        self.confirm(0)
        session = self.rows("j1939_engine_sessions")[0]
        self.assertEqual((session["status"], session["active"]), ("CERRADA", 0))
        self.assertEqual(session["duration_seconds"], 7)
        self.assertEqual(session["verified_seconds"], 4)
        self.assertEqual(len(self.events("STOP")), 1)
        self.assertEqual(session["close_reason"], "confirmed_stop")

    def test_loss_does_not_stop_or_close_session(self):
        self.running()
        self.lose()
        self.assertEqual(len(self.events("COMM_LOST")), 1)
        self.assertEqual(len(self.events("STOP")), 0)
        session = self.rows("j1939_engine_sessions")[0]
        self.assertEqual((session["status"], session["active"]), ("INDETERMINADA", 1))
        self.assertIsNone(session["ended_at_utc"])
        self.assertIsNone(session["time_without_communication"])

    def test_recovery_running_preserves_session_no_duplicate_start(self):
        self.running()
        session_id = self.rows("j1939_engine_sessions")[0]["session_id"]
        self.lose()
        self.confirm(1800)
        self.assertEqual(len(self.events("START")), 1)
        self.assertEqual(len(self.events("COMM_RECOVERED")), 1)
        self.assertEqual(self.rows("j1939_engine_sessions")[0]["session_id"], session_id)
        self.assertEqual(self.rows("j1939_engine_sessions")[0]["time_without_communication"], 8)
        self.assertIsNone(self.rows("j1939_engine_sessions")[0]["duration_seconds"])

    def test_recovery_stopped_does_not_invent_stop(self):
        self.running()
        self.lose()
        self.confirm(0)
        self.assertEqual(len(self.events("STOP")), 0)
        session = self.rows("j1939_engine_sessions")[0]
        self.assertEqual((session["status"], session["active"]), ("INDETERMINADA", 0))
        self.assertIsNone(session["ended_at_utc"])
        self.assertEqual(session["close_reason"], "reconciled_stopped_unknown_stop")

    def test_restart_running_recovers_open_session(self):
        self.running()
        original = self.rows("j1939_engine_sessions")[0]["session_id"]
        self.clock.advance(10)
        self.recorder = EngineRecorder(self.config, self.clock, EngineStore(self.path))
        self.confirm(1800)
        self.assertEqual(len(self.events("START")), 1)
        self.assertEqual(self.rows("j1939_engine_sessions")[0]["session_id"], original)
        self.assertEqual(self.recorder.recovered_checkpoint["last_confirmed_state"], "RUNNING")
        self.assertEqual(self.rows("j1939_observation_gaps")[0]["reason"], "process_restart")
        self.assertEqual(self.rows("j1939_engine_sessions")[0]["quality"], "INCOMPLETE")

    def test_restart_stopped_keeps_unknown_stop_time(self):
        self.running()
        self.clock.advance(10)
        self.recorder = EngineRecorder(self.config, self.clock, self.store)
        self.confirm(0)
        self.assertEqual(len(self.events("STOP")), 0)
        session = self.rows("j1939_engine_sessions")[0]
        self.assertIsNone(session["ended_at_utc"])
        self.assertEqual(session["active"], 0)

    def test_duplicate_start_and_stop_samples_do_not_duplicate_events(self):
        self.running()
        for rpm in (1800, 0):
            if rpm == 0:
                self.confirm(0)
            sample = RpmSample(self.clock.utcnow(), rpm, 0xEA, "synthetic-generator")
            for _ in range(5):
                self.assertFalse(self.recorder.offer(sample))
            self.drain()
        self.assertEqual(len(self.events("START")), 1)
        self.assertEqual(len(self.events("STOP")), 1)

    def test_event_and_registration_timestamps_are_utc(self):
        self.running()
        event = self.events("START")[0]
        for key in ("timestamp_utc", "observed_at_utc", "recorded_at_utc"):
            self.assertTrue(event[key].endswith("Z"))
        self.assertEqual(event["timestamp_utc"], utc_text(self.clock.utcnow()))

    def test_out_of_order_samples_no_transition(self):
        self.running()
        sample = RpmSample(self.clock.utcnow() - timedelta(seconds=2), 0, 0xEA, "synthetic-generator")
        self.assertFalse(self.recorder.offer(sample))
        self.drain()
        self.assertEqual(len(self.events("STOP")), 0)

    def test_invalid_na_and_other_source_do_not_create_start(self):
        self.confirm(0)
        for value, quality in ((None, "NOT_AVAILABLE"), (float("nan"), "GOOD"), (-1, "GOOD"), (1800, "INVALID")):
            self.assertFalse(self.feed(value, quality=quality))
        self.feed(1800, source_address=1)
        self.assertEqual(len(self.events("START")), 0)

    def test_sqlite_busy_retains_same_batch_then_recovers(self):
        lock = sqlite3.connect(self.path, isolation_level=None)
        self.addCleanup(lock.close)
        lock.execute("BEGIN IMMEDIATE")
        self.clock.advance(1)
        self.recorder.offer(RpmSample(self.clock.utcnow(), 0, 0xEA, "synthetic-generator"))
        self.assertFalse(self.recorder.drain_once())
        batch_id = self.recorder._pending.batch_id
        self.assertEqual(self.recorder.last_error, "OperationalError")
        lock.rollback()
        self.assertTrue(self.recorder.drain_once())
        self.assertEqual(self.rows("j1939_recorder_batches")[0]["batch_id"], batch_id)

    def test_write_failure_rolls_back_event_and_session_and_checkpoint(self):
        self.confirm(0)
        self.feed(1800)
        self.feed(1800)
        before = self.store.checkpoint("synthetic-gateway", "synthetic-generator")
        self.clock.advance(1)
        self.recorder.offer(RpmSample(self.clock.utcnow(), 1800, 0xEA, "synthetic-generator"))
        original = self.store._insert_event
        def insert_then_fail(*args):
            original(*args)
            raise sqlite3.OperationalError("synthetic disk failure")
        with patch.object(self.store, "_insert_event", side_effect=insert_then_fail):
            self.assertFalse(self.recorder.drain_once())
        self.assertEqual(len(self.events("START")), 0)
        self.assertEqual(self.rows("j1939_engine_sessions"), [])
        self.assertEqual(self.store.checkpoint("synthetic-gateway", "synthetic-generator"), before)
        self.drain()
        self.assertEqual(len(self.events("START")), 1)

    def test_commit_uncertainty_retries_exact_batch_idempotently(self):
        self.confirm(0)
        self.feed(1800)
        self.feed(1800)
        self.clock.advance(1)
        self.recorder.offer(RpmSample(self.clock.utcnow(), 1800, 0xEA, "synthetic-generator"))
        original = self.store.apply
        def commit_then_fail(batch):
            original(batch)
            raise sqlite3.OperationalError("synthetic response lost after commit")
        with patch.object(self.store, "apply", side_effect=commit_then_fail):
            self.assertFalse(self.recorder.drain_once())
        self.assertEqual(len(self.events("START")), 1)
        self.drain()
        self.assertEqual(len(self.events("START")), 1)
        self.assertEqual(len(self.rows("j1939_engine_sessions")), 1)

    def test_migration_idempotent_and_integrity(self):
        self.running()
        self.store.migrate()
        self.assertEqual(len(self.rows("j1939_schema_migrations")), 1)
        self.assertEqual(len(self.events("START")), 1)
        with sqlite3.connect(self.path) as c:
            self.assertEqual(c.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(c.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(c.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertGreaterEqual(len(c.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_j1939_%'").fetchall()), 4)

    def test_migration_does_not_change_existing_measurements(self):
        path = Path(self.temp.name) / "existing.sqlite"
        with sqlite3.connect(path) as c:
            c.execute("CREATE TABLE mediciones(id INTEGER PRIMARY KEY, payload_json TEXT)")
            c.execute("INSERT INTO mediciones VALUES(1,'synthetic history')")
        EngineStore(path).migrate()
        with sqlite3.connect(path) as c:
            self.assertEqual(c.execute("SELECT * FROM mediciones").fetchall(), [(1, "synthetic history")])

    def test_migration_collision_rolls_back(self):
        path = Path(self.temp.name) / "conflict.sqlite"
        with sqlite3.connect(path) as c:
            c.execute("CREATE TABLE j1939_engine_events(old_column TEXT)")
        with self.assertRaises(ValueError):
            EngineStore(path).migrate()
        with sqlite3.connect(path) as c:
            self.assertEqual(c.execute("SELECT name FROM sqlite_master WHERE name='j1939_schema_migrations'").fetchall(), [])

    def test_multiple_cycles(self):
        self.confirm(0)
        for _ in range(4):
            self.confirm(1800)
            self.confirm(0)
        self.assertEqual(len(self.events("START")), 4)
        self.assertEqual(len(self.events("STOP")), 4)
        self.assertTrue(all(s["status"] == "CERRADA" for s in self.rows("j1939_engine_sessions")))

    def test_default_disabled_has_no_store_or_thread_effect(self):
        disabled = EngineRecorder(replace(self.config, enabled=False), self.clock, self.store)
        with patch.object(self.store, "apply") as apply, patch.object(self.store, "begin_run") as begin:
            disabled.start(); disabled.poll()
            self.assertFalse(disabled.offer(RpmSample(self.clock.utcnow(), 0, 0xEA, "synthetic-generator")))
            self.assertFalse(disabled.drain_once())
            self.assertTrue(disabled.close())
            apply.assert_not_called(); begin.assert_not_called()

    def test_can_runtime_continues_with_unavailable_database_and_queue_full(self):
        config = replace(self.config, queue_size=2)
        missing = EngineStore(Path(self.temp.name) / "missing" / "unavailable.sqlite")
        recorder = EngineRecorder(config, self.clock, missing)
        settings = dict(signal_file=ROOT / "config/j1939_signals.yml", heartbeat_seconds=600,
                        recent_frame_limit=2, transport="replay", replay_file="synthetic",
                        can_bitrate=250000, capture_dir=Path(self.temp.name),
                        capture_max_duration_seconds=10, capture_max_file_mb=1,
                        capture_max_files=2, capture_queue_size=2)
        runtime = J1939Runtime(settings)
        decoder = SignalDecoder(load_yaml(settings["signal_file"])["signals"])
        for _ in range(20):
            self.clock.advance(1)
            frame = parse_slcan_line("T0CF004EA8FFFFFF4038FFFFFF", self.clock.utcnow())
            runtime.process(frame)
            recorder.offer_decoded(decoder.decode(frame)[0])
            recorder.drain_once()
        self.assertEqual(runtime.status()["framesReceived"], 20)
        self.assertGreater(recorder.write_errors, 0)
        self.assertGreater(recorder.dropped_samples, 0)
        self.assertLessEqual(recorder.status()["queued"], 3)

    def test_first_observed_running_has_unknown_start(self):
        self.confirm(1800)
        self.assertEqual(len(self.events("START")), 0)
        session = self.rows("j1939_engine_sessions")[0]
        self.assertEqual(session["status"], "INDETERMINADA")
        self.assertIsNone(session["started_at_utc"])

    def test_new_writer_fences_old_pending_commands(self):
        self.running()
        self.clock.advance(1)
        self.recorder.offer(RpmSample(self.clock.utcnow(), 1800, 0xEA, "synthetic-generator"))
        self.store.begin_run("synthetic-gateway", "synthetic-generator", "new-writer", self.clock.utcnow())
        self.assertFalse(self.recorder.drain_once())
        self.assertEqual(self.recorder.last_error, "WriterConflict")

    def test_reused_batch_id_with_different_payload_rejected(self):
        self.confirm(0)
        self.clock.advance(1)
        self.recorder.offer(RpmSample(self.clock.utcnow(), 1800, 0xEA, "synthetic-generator"))
        batch = self.recorder._queue.queue[0]
        self.drain()
        self.assertFalse(self.store.apply(batch))
        with self.assertRaises(ValueError):
            self.store.apply(replace(batch, rpm=900))

    def test_direct_out_of_order_batch_rejected(self):
        self.confirm(0)
        cp = self.store.checkpoint("synthetic-gateway", "synthetic-generator")
        batch = RecordingBatch("manual", self.recorder.writer_id, cp["sequence"] + 1,
                               "synthetic-gateway", "synthetic-generator", 0xEA, self.clock.utcnow(),
                               EngineState.STOPPED, EngineState.STOPPED,
                               observed_at_utc=self.clock.utcnow() - timedelta(seconds=1), rpm=0)
        with self.assertRaises(ValueError):
            self.store.apply(batch)

    def test_hourmeter_requires_explicit_validation_and_same_source(self):
        decoder = SignalDecoder(load_yaml(ROOT / "config/j1939_signals.yml")["signals"])
        hours = decoder.decode(parse_slcan_line("T18FEE5EA8301B0000FFFFFFFF", self.clock.utcnow()))[0]
        self.assertFalse(self.recorder.offer_decoded(hours))
        self.recorder = EngineRecorder(replace(self.config, hourmeter_validated=True), self.clock, self.store)
        self.running()
        self.assertIsNone(self.rows("j1939_engine_sessions")[0]["initial_hourmeter"])
        self.assertTrue(self.recorder.offer_decoded(replace(hours, timestamp_utc=self.clock.utcnow())))
        self.clock.advance(1)
        self.assertEqual(self.recorder._hourmeter(), 348)
        self.clock.advance(1)
        self.assertIsNone(self.recorder._hourmeter())

    def test_poll_timeout_without_any_frames_is_durable(self):
        self.clock.advance(5)
        self.recorder.poll(); self.drain()
        self.assertEqual(len(self.events("COMM_LOST")), 1)
        self.assertEqual(self.rows("j1939_engine_sessions"), [])

    def test_missing_database_is_not_created_implicitly(self):
        missing = Path(self.temp.name) / "typo.sqlite"
        with self.assertRaises(sqlite3.OperationalError):
            EngineStore(missing).begin_run("g", "e", "w", self.clock.utcnow())
        self.assertFalse(missing.exists())


    def test_invalid_numeric_rpm_breaks_duration_coverage(self):
        self.running()
        self.feed(1800)
        before = self.rows("j1939_engine_sessions")[0]["verified_seconds"]
        self.feed(float("nan"))
        self.feed(1800)
        session = self.rows("j1939_engine_sessions")[0]
        self.assertEqual(session["verified_seconds"], before)
        self.assertEqual(session["quality"], "INCOMPLETE")
        self.assertEqual(self.rows("j1939_observation_gaps")[0]["reason"], "invalid_rpm_evidence")

    def test_queue_overflow_marks_gap_and_reconciles_without_false_stop(self):
        self.running()
        self.recorder = EngineRecorder(replace(self.config, queue_size=1), self.clock, self.store)
        self.clock.advance(1)
        self.recorder.offer(RpmSample(self.clock.utcnow(), 1800, 0xEA, "synthetic-generator"))
        self.clock.advance(1)
        self.assertFalse(self.recorder.offer(RpmSample(self.clock.utcnow(), 0, 0xEA, "synthetic-generator")))
        self.drain()
        self.confirm(0)
        self.assertEqual(self.recorder.dropped_samples, 1)
        self.assertEqual(len(self.events("STOP")), 0)
        self.assertEqual(self.rows("j1939_engine_sessions")[0]["status"], "INDETERMINADA")

    def test_background_writer_commits_without_operator_or_network(self):
        import threading
        committed = threading.Event()
        original = self.store.apply
        def notify(batch):
            result = original(batch)
            if any(e.event_type.value == "START" for e in batch.events):
                committed.set()
            return result
        with patch.object(self.store, "apply", side_effect=notify):
            self.recorder.start()
            try:
                for rpm in (0, 0, 0, 1800, 1800, 1800):
                    self.clock.advance(1)
                    self.recorder.offer(RpmSample(self.clock.utcnow(), rpm, 0xEA, "synthetic-generator"))
                self.assertTrue(committed.wait(3), self.recorder.status())
            finally:
                closed = self.recorder.close(timeout=3)
            self.assertTrue(closed)
        self.assertEqual(len(self.events("START")), 1)

    def test_flush_coalesces_stable_rpm_without_raw_event_per_frame(self):
        self.recorder = EngineRecorder(replace(self.config, flush_seconds=5), self.clock, self.store)
        self.running()
        before = len(self.rows("j1939_recorder_batches"))
        event_count = len(self.events())
        for _ in range(40):
            self.feed(1800, step=0.1)
        self.assertEqual(len(self.rows("j1939_recorder_batches")), before)
        self.recorder.flush(); self.drain()
        self.assertEqual(len(self.events()), event_count)
        self.assertAlmostEqual(self.rows("j1939_engine_sessions")[0]["verified_seconds"], 4)

    def test_hourmeter_initial_and_final_only_with_validated_fresh_evidence(self):
        decoder = SignalDecoder(load_yaml(ROOT / "config/j1939_signals.yml")["signals"])
        hours = decoder.decode(parse_slcan_line("T18FEE5EA8301B0000FFFFFFFF", self.clock.utcnow()))[0]
        self.recorder = EngineRecorder(replace(self.config, hourmeter_validated=True), self.clock, self.store)
        self.confirm(0)
        for value in (1800, 1800, 1800, 0, 0, 0):
            self.clock.advance(1)
            self.recorder.offer_decoded(replace(hours, timestamp_utc=self.clock.utcnow()))
            self.recorder.offer(RpmSample(self.clock.utcnow(), value, 0xEA, "synthetic-generator"))
            self.drain()
        session = self.rows("j1939_engine_sessions")[0]
        self.assertEqual((session["initial_hourmeter"], session["final_hourmeter"]), (348, 348))

    def test_decoded_rpm_requires_confirmed_confidence(self):
        decoder = SignalDecoder(load_yaml(ROOT / "config/j1939_signals.yml")["signals"])
        rpm = decoder.decode(parse_slcan_line("T0CF004EA8FFFFFF4038FFFFFF", self.clock.utcnow()))[0]
        self.assertFalse(self.recorder.offer_decoded(replace(rpm, confidence="PROBABLE")))
        self.assertIsNone(self.recorder.detector.last_valid_timestamp_utc)

    def test_probable_rpm_breaks_coverage_without_false_transition(self):
        decoder=SignalDecoder(load_yaml(ROOT / 'config/j1939_signals.yml')['signals'])
        self.running()
        before=self.rows('j1939_engine_sessions')[0]['verified_seconds']
        self.clock.advance(1)
        rpm=decoder.decode(parse_slcan_line('T0CF004EA8FFFFFF4038FFFFFF',self.clock.utcnow()))[0]
        self.assertFalse(self.recorder.offer_decoded(replace(rpm,confidence='PROBABLE')))
        self.drain()
        for _ in range(3): self.feed(1800)
        session=self.rows('j1939_engine_sessions')[0]
        self.assertEqual(session['verified_seconds'],before)
        self.assertEqual(len(self.events('START')),1)
        self.assertEqual(len(self.events('STOP')),0)
        self.assertEqual(len(self.rows('j1939_engine_sessions')),1)
        self.assertTrue(any(g['reason']=='invalid_rpm_confidence' for g in self.rows('j1939_observation_gaps')))

    def test_hourmeter_rejects_future_old_and_unconfirmed(self):
        decoder = SignalDecoder(load_yaml(ROOT / "config/j1939_signals.yml")["signals"])
        hours = decoder.decode(parse_slcan_line("T18FEE5EA8301B0000FFFFFFFF", self.clock.utcnow()))[0]
        self.recorder = EngineRecorder(replace(self.config, hourmeter_validated=True), self.clock, self.store)
        self.recorder.offer_decoded(hours)
        self.recorder.offer_decoded(replace(hours, value=999, timestamp_utc=self.clock.utcnow()+timedelta(days=1)))
        self.assertEqual(self.recorder._hourmeter(),348)
        self.recorder.offer_decoded(replace(hours, value=999, confidence="PROBABLE", timestamp_utc=self.clock.utcnow()))
        self.assertEqual(self.recorder._hourmeter(),348)
        self.clock.advance(3)
        self.assertIsNone(self.recorder._hourmeter())

    def test_sql_constraints_and_migration_checksum_detect_corruption(self):
        self.running()
        with sqlite3.connect(self.path) as c:
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute("UPDATE j1939_engine_sessions SET verified_seconds=-1")
            c.execute("UPDATE j1939_schema_migrations SET checksum='wrong'")
        with self.assertRaises(ValueError):
            self.store.migrate()

    def test_unresolved_shutdown_reports_pending_not_success(self):
        self.clock.advance(1)
        self.recorder.offer(RpmSample(self.clock.utcnow(), 0, 0xEA, "synthetic-generator"))
        with patch.object(self.store, "begin_run", side_effect=sqlite3.OperationalError("synthetic")):
            self.assertFalse(self.recorder.drain_once())
            self.assertFalse(self.recorder.close())
        self.assertGreater(self.recorder.status()["queued"], 0)
        self.drain()

    def test_invalid_gap_then_changed_state_reconciles_without_writer_deadlock(self):
        self.running()
        self.feed(None, quality="NOT_AVAILABLE")
        self.confirm(0)
        self.assertEqual(len(self.events("STOP")), 0)
        self.assertEqual(self.rows("j1939_engine_sessions")[0]["active"], 0)
        self.assertIsNone(self.recorder.last_error)
        self.confirm(1800)
        self.assertEqual(len(self.events("START")), 2)

    def test_continuous_invalid_samples_do_not_postpone_timeout(self):
        self.running()
        for _ in range(6):
            self.feed(None, quality="NOT_AVAILABLE")
        self.assertEqual(len(self.events("COMM_LOST")), 1)
        self.assertEqual(len(self.events("STOP")), 0)
        self.assertEqual(self.recorder.detector.last_confirmed_state, EngineState.RUNNING)

    def test_short_observation_gap_then_start_reconciles_without_fabrication(self):
        self.confirm(0)
        self.feed(1800)
        self.feed(1800, step=3)
        self.feed(1800)
        self.feed(1800)
        self.assertEqual(len(self.events("START")), 0)
        self.assertIsNone(self.recorder.last_error)
        self.assertEqual(self.rows("j1939_engine_sessions")[0]["status"], "INDETERMINADA")

    def test_observed_stop_is_known_even_when_session_start_is_unknown(self):
        self.confirm(1800)
        self.confirm(0)
        session = self.rows("j1939_engine_sessions")[0]
        self.assertIsNone(session["started_at_utc"])
        self.assertIsNotNone(session["ended_at_utc"])
        self.assertEqual(session["status"], "INDETERMINADA")
        self.assertIsNone(session["duration_seconds"])
        self.assertEqual(len(self.events("STOP")), 1)

    def test_default_configuration_is_disabled(self):
        self.assertFalse(RecorderConfig("synthetic-gateway", synthetic_config()).enabled)

if __name__ == "__main__":
    unittest.main()
