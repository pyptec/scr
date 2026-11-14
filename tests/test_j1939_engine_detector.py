from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from j1939.config import load_yaml
from j1939.decoder import SignalDecoder
from j1939.engine_detector import (
    DetectorConfig, EngineDetector, EngineState as S, EventType as E, RpmSample,
)
from j1939.parser import parse_slcan_line


class FakeClock:
    def __init__(self):
        self.seconds = 0.0
        self.utc = datetime(2026, 11, 14, tzinfo=timezone.utc)

    def monotonic(self):
        return self.seconds

    def utcnow(self):
        return self.utc

    def advance(self, seconds):
        self.seconds += seconds
        self.utc += timedelta(seconds=seconds)


def synthetic_config(**changes):
    # SOLO FIXTURE: SA y límites NO validados para Caterpillar/EMCP3 real.
    return replace(DetectorConfig(
        equipment_id="synthetic-generator", source_address=0xEA,
        rpm_start=600, rpm_stop=100, rpm_max=3000,
        start_samples=3, stop_samples=3, start_seconds=2, stop_seconds=2,
        timeout_seconds=5, max_sample_gap_seconds=2, max_sample_age_seconds=1,
    ), **changes)


class EngineDetectorTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.detector = EngineDetector(synthetic_config(), self.clock)

    def sample(self, rpm=1800, **changes):
        return replace(RpmSample(self.clock.utcnow(), rpm, 0xEA, "synthetic-generator"), **changes)

    def feed(self, rpm, advance=0, **changes):
        self.clock.advance(advance)
        return self.detector.feed(self.sample(rpm, **changes))

    def confirm(self, rpm):
        events = self.feed(rpm, 1)
        events += self.feed(rpm, 1)
        events += self.feed(rpm, 1)
        return events

    def running(self):
        self.confirm(0)
        events = self.confirm(1800)
        self.assertEqual([e.event_type for e in events], [E.START])
        return events

    def lose(self):
        self.clock.advance(5)
        events = self.detector.poll()
        self.assertEqual([e.event_type for e in events], [E.COMMUNICATION_LOST])
        return events

    def test_initial_unknown(self):
        self.assertEqual(self.detector.state, S.UNKNOWN)
        self.assertEqual(self.detector.last_confirmed_state, S.UNKNOWN)

    def test_stopped_confirmation_without_invented_stop(self):
        self.assertEqual(self.confirm(0), [])
        self.assertEqual(self.detector.state, S.STOPPED)

    def test_first_start_sample_is_only_candidate(self):
        self.confirm(0)
        self.assertEqual(self.feed(1800, 1), [])
        self.assertEqual(self.detector.state, S.STARTING)
        self.assertEqual(self.detector.last_confirmed_state, S.STOPPED)

    def test_start_event_contract(self):
        event = self.running()[0]
        self.assertEqual((event.previous_state, event.current_state), (S.STARTING, S.RUNNING))
        self.assertEqual((event.rpm, event.source_address, event.equipment_id),
                         (1800, 0xEA, "synthetic-generator"))
        self.assertEqual((event.pgn, event.spn, event.evidence_quality), (0xF004, 190, "CONFIRMED_RPM"))
        self.assertEqual(event.timestamp_utc, self.clock.utcnow())
        self.assertEqual(event.observed_at_utc, self.clock.utcnow())

    def test_continuous_running_has_no_repeated_start(self):
        self.running()
        for _ in range(20):
            self.assertEqual(self.feed(1800, 1), [])
        self.assertEqual(self.detector.state, S.RUNNING)

    def test_temporary_rpm_drop_cancels_stopping(self):
        self.running()
        self.assertEqual(self.feed(0, 1), [])
        self.assertEqual(self.detector.state, S.STOPPING)
        self.assertEqual(self.feed(1800, 1), [])
        self.assertEqual(self.detector.state, S.RUNNING)

    def test_stop_once(self):
        self.running()
        events = self.confirm(0)
        self.assertEqual([e.event_type for e in events], [E.STOP])
        self.assertEqual((events[0].previous_state, events[0].current_state), (S.STOPPING, S.STOPPED))
        self.assertEqual(self.confirm(0), [])

    def test_running_silence_never_stops(self):
        self.running()
        event = self.lose()[0]
        self.assertEqual(self.detector.state, S.COMM_LOST)
        self.assertEqual(self.detector.last_confirmed_state, S.RUNNING)
        self.assertIsNone(event.rpm)
        self.assertEqual(event.evidence_quality, "NO_VALID_RPM")
        self.clock.advance(100)
        self.assertEqual(self.detector.poll(), [])

    def test_stopped_silence(self):
        self.confirm(0)
        self.lose()
        self.assertEqual(self.detector.last_confirmed_state, S.STOPPED)

    def test_recovery_running_no_invented_start(self):
        self.running()
        self.lose()
        events = self.confirm(1800)
        self.assertEqual([e.event_type for e in events], [E.COMMUNICATION_RECOVERED])
        self.assertEqual((events[0].previous_state, events[0].current_state), (S.COMM_LOST, S.UNKNOWN))
        self.assertEqual(self.detector.state, S.RUNNING)

    def test_recovery_stopped_no_invented_stop(self):
        self.running()
        self.lose()
        events = self.confirm(0)
        self.assertEqual([e.event_type for e in events], [E.COMMUNICATION_RECOVERED])
        self.assertEqual(self.detector.state, S.STOPPED)
        self.assertEqual([e.event_type for e in self.confirm(1800)], [E.START])

    def test_wrong_source_cannot_refresh_or_recover(self):
        self.running()
        for _ in range(5):
            events = self.feed(1800, 1, source_address=1)
        self.assertEqual([e.event_type for e in events], [E.COMMUNICATION_LOST])
        self.assertEqual(self.feed(1800, 1, source_address=1), [])
        self.assertEqual(self.detector.state, S.COMM_LOST)

    def test_invalid_rpm_does_not_refresh(self):
        for value in (None, -1, 3001, float("nan"), float("inf"), True, "1800"):
            with self.subTest(value=value):
                self.setUp()
                self.running()
                self.assertEqual(self.feed(value, 1), [])
                self.clock.advance(4)
                self.assertEqual([e.event_type for e in self.detector.poll()], [E.COMMUNICATION_LOST])

    def test_not_available_quality_is_not_zero(self):
        self.running()
        for _ in range(3):
            self.assertEqual(self.feed(0, 1, quality="NOT_AVAILABLE"), [])
        self.assertEqual(self.detector.last_confirmed_state, S.RUNNING)
        self.clock.advance(2)
        self.assertEqual([e.event_type for e in self.detector.poll()], [E.COMMUNICATION_LOST])

    def test_duplicate_timestamps_do_not_confirm_or_refresh(self):
        self.confirm(0)
        self.clock.advance(1)
        sample = self.sample()
        self.detector.feed(sample)
        for _ in range(4):
            self.clock.advance(1)
            self.assertEqual(self.detector.feed(sample), [])
        self.assertEqual(self.detector.state, S.STARTING)
        self.clock.advance(1)
        self.assertEqual([e.event_type for e in self.detector.feed(sample)], [E.COMMUNICATION_LOST])

    def test_out_of_order_cannot_count_or_cancel_current_evidence(self):
        self.confirm(0)
        old = self.sample(0)
        self.feed(1800, 1)
        self.clock.advance(1)
        self.assertEqual(self.detector.feed(old), [])
        self.assertEqual(self.detector.state, S.STARTING)
        self.assertEqual(self.feed(1800), [])
        self.assertEqual([e.event_type for e in self.feed(1800, 1)], [E.START])

    def test_threshold_oscillation_does_not_confirm(self):
        self.confirm(0)
        for rpm in (600, 599, 601, 599, 600, 500, 600):
            self.assertEqual(self.feed(rpm, 1), [])
        self.assertEqual(self.detector.last_confirmed_state, S.STOPPED)

    def test_long_running_interval_has_bounded_state_and_no_stop(self):
        self.running()
        for _ in range(3600):
            self.assertEqual(self.feed(1800, 1), [])
        self.assertEqual(self.detector.state, S.RUNNING)
        self.assertFalse(hasattr(self.detector, "events"))

    def test_start_without_frames_timeout_once(self):
        self.clock.advance(4.999)
        self.assertEqual(self.detector.poll(), [])
        self.clock.advance(0.001)
        self.assertEqual([e.event_type for e in self.detector.poll()], [E.COMMUNICATION_LOST])
        self.assertEqual(self.detector.last_confirmed_state, S.UNKNOWN)

    def test_reinitialization_has_no_persistent_history_or_false_start(self):
        self.running()
        self.detector = EngineDetector(synthetic_config(), self.clock)
        self.assertEqual(self.detector.state, S.UNKNOWN)
        self.assertEqual(self.confirm(1800), [])
        self.assertEqual(self.detector.state, S.RUNNING)

    def test_first_observed_running_does_not_invent_start(self):
        self.assertEqual(self.confirm(1800), [])
        self.assertEqual(self.detector.state, S.RUNNING)

    def test_confirmation_requires_time_and_samples(self):
        self.confirm(0)
        for _ in range(3):
            self.assertEqual(self.feed(1800, 0.1), [])
        self.assertEqual(self.detector.state, S.STARTING)
        self.assertEqual([e.event_type for e in self.feed(1800, 1.9)], [E.START])

    def test_poll_cannot_confirm_without_new_samples(self):
        self.confirm(0)
        self.feed(1800, 1)
        self.clock.advance(2)
        self.assertEqual(self.detector.poll(), [])
        self.assertEqual(self.detector.state, S.STARTING)

    def test_invalid_sample_breaks_candidate(self):
        self.confirm(0)
        self.feed(1800, 1)
        self.feed(1800, 1)
        self.feed(None, 0.1)
        self.assertEqual(self.detector.state, S.STOPPED)
        self.assertEqual(self.feed(1800, 0.9), [])
        self.assertEqual(self.feed(1800, 1), [])
        self.assertEqual([e.event_type for e in self.feed(1800, 1)], [E.START])

    def test_gap_breaks_candidate_without_timeout(self):
        self.confirm(0)
        self.feed(1800, 1)
        self.feed(1800, 1)
        self.assertEqual(self.feed(1800, 3), [])
        self.assertEqual(self.feed(1800, 1), [])
        self.assertEqual([e.event_type for e in self.feed(1800, 1)], [E.START])

    def test_wrong_equipment_pgn_spn_cannot_refresh(self):
        for changes in ({"equipment_id": "other"}, {"pgn": 0xFEEE}, {"spn": 110}):
            with self.subTest(changes=changes):
                self.setUp()
                self.confirm(0)
                for _ in range(5):
                    events = self.feed(1800, 1, **changes)
                self.assertEqual([e.event_type for e in events], [E.COMMUNICATION_LOST])

    def test_stale_future_naive_timestamps_rejected(self):
        for stamp in (self.clock.utcnow() - timedelta(seconds=2),
                      self.clock.utcnow() + timedelta(seconds=1), datetime(2026, 11, 14)):
            with self.subTest(stamp=stamp):
                self.assertEqual(self.detector.feed(self.sample(timestamp_utc=stamp)), [])
                self.assertEqual(self.detector.state, S.UNKNOWN)
        self.assertEqual(self.confirm(1800), [])
        self.assertEqual(self.detector.state, S.RUNNING)

    def test_late_feed_expires_even_without_poll(self):
        self.running()
        events = self.feed(0, 6)
        self.assertEqual([e.event_type for e in events], [E.COMMUNICATION_LOST, E.COMMUNICATION_RECOVERED])
        self.assertEqual(self.detector.state, S.STOPPING)
        self.assertEqual(self.detector.last_confirmed_state, S.RUNNING)
        self.assertEqual(self.feed(0, 1), [])
        self.assertEqual(self.feed(0, 1), [])
        self.assertEqual(self.detector.state, S.STOPPED)

    def test_utc_jump_does_not_disable_monotonic_timeout(self):
        self.running()
        self.clock.utc -= timedelta(days=1)
        self.clock.seconds += 5
        self.assertEqual([e.event_type for e in self.detector.poll()], [E.COMMUNICATION_LOST])

    def test_invalid_clock_rejected(self):
        self.clock.seconds = -1
        with self.assertRaises(ValueError):
            self.detector.poll()
        self.clock.seconds = float("nan")
        with self.assertRaises(ValueError):
            self.detector.poll()

    def test_invalid_configuration_rejected(self):
        for changes in ({"equipment_id": ""}, {"source_address": None}, {"source_address": 254},
                        {"source_address": True}, {"rpm_stop": 600}, {"rpm_max": 500},
                        {"start_samples": 0}, {"stop_samples": 1.5}, {"start_seconds": -1},
                        {"timeout_seconds": 0}, {"max_sample_gap_seconds": 5},
                        {"max_sample_age_seconds": 5}, {"rpm_start": float("nan")}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                synthetic_config(**changes)

    def test_boundary_thresholds_and_new_cycle(self):
        self.confirm(100)
        self.assertEqual([e.event_type for e in self.confirm(600)], [E.START])
        self.assertEqual([e.event_type for e in self.confirm(100)], [E.STOP])
        self.assertEqual([e.event_type for e in self.confirm(600)], [E.START])

    def test_recovery_does_not_reuse_old_candidate(self):
        self.confirm(0)
        self.feed(1800, 1)
        self.feed(1800, 1)
        self.lose()
        self.assertEqual([e.event_type for e in self.feed(1800)], [E.COMMUNICATION_RECOVERED])
        self.assertEqual(self.feed(1800, 1), [])
        self.assertEqual(self.feed(1800, 1), [])
        self.assertEqual(self.detector.state, S.RUNNING)

    def test_buffered_burst_cannot_satisfy_acquisition_duration(self):
        self.confirm(0)
        self.feed(1800, 1)
        self.clock.advance(1)
        self.detector.feed(self.sample(timestamp_utc=self.clock.utcnow() - timedelta(seconds=0.5)))
        self.clock.advance(1)
        self.assertEqual(self.detector.feed(self.sample(
            timestamp_utc=self.clock.utcnow() - timedelta(seconds=0.5))), [])
        self.assertEqual(self.detector.state, S.STARTING)

    def test_decoder_adapter_real_contract_synthetic_payload(self):
        root = Path(__file__).resolve().parent.parent
        decoder = SignalDecoder(load_yaml(root / "config/j1939_signals.yml")["signals"])
        signal = decoder.decode(parse_slcan_line("T0CF004EA8FFFFFF4038FFFFFF", self.clock.utcnow()))[0]
        sample = RpmSample.from_decoded(signal, "synthetic-generator")
        self.assertEqual((sample.rpm, sample.source_address), (1800, 0xEA))
        self.assertEqual(self.detector.feed(sample), [])
        na = decoder.decode(parse_slcan_line("T0CF004EA8FFFFFFFFFFFFFFFF", self.clock.utcnow()))[0]
        self.assertIsNone(RpmSample.from_decoded(na, "synthetic-generator").rpm)
        self.assertEqual(RpmSample.from_decoded(na, "synthetic-generator").quality, "NOT_AVAILABLE")
        for other in (replace(signal, key="x"), replace(signal, pgn=0xFEEE),
                      replace(signal, metadata={"spn": 110}), replace(signal, unit="V")):
            with self.assertRaises(ValueError):
                RpmSample.from_decoded(other, "synthetic-generator")


if __name__ == "__main__":
    unittest.main()
