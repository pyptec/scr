"""Adaptador aislado: oferta O(1) sin SQLite, escritor Ãºnico con reintento.

No estÃ¡ importado por J1939Runtime. No abre CAN ni aplica migraciones.
"""
from __future__ import annotations

import math
import queue
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime

from .engine_detector import DetectorClock, DetectorConfig, EngineDetector, EngineState, RpmSample
from .engine_store import EngineStore, RecordingBatch
from .models import DecodedSignal


@dataclass(frozen=True, slots=True)
class RecorderConfig:
    gateway_id: str
    detector: DetectorConfig
    enabled: bool = False
    queue_size: int = 256
    flush_seconds: float = 5
    retry_seconds: float = 0.25
    hourmeter_validated: bool = False

    def __post_init__(self):
        if not isinstance(self.gateway_id, str) or not self.gateway_id.strip():
            raise ValueError("explicit gateway_id required")
        if type(self.enabled) is not bool or type(self.hourmeter_validated) is not bool:
            raise ValueError("flags must be booleans")
        if type(self.queue_size) is not int or self.queue_size < 1:
            raise ValueError("queue_size must be positive")
        for value in (self.flush_seconds, self.retry_seconds):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError("flush/retry intervals must be finite and positive")


class EngineRecorder:
    def __init__(self, config: RecorderConfig, clock: DetectorClock, store: EngineStore, *, batch_observer=None) -> None:
        self.config, self.clock, self.store = config, clock, store
        self._batch_observer = batch_observer
        self.observer_errors = 0
        self.writer_id = str(uuid.uuid4())
        self.detector = EngineDetector(config.detector, clock) if config.enabled else None
        self._queue: queue.Queue[RecordingBatch] = queue.Queue(config.queue_size)
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._pending: RecordingBatch | None = None
        self._begun = False
        self.recovered_checkpoint: dict | None = None
        self._sequence = 0
        self._coverage = 0.0
        self._previous = None
        self._sample: RpmSample | None = None
        self._fresh = False
        self._last_submit = clock.monotonic() if config.enabled else 0
        self._last_state = EngineState.UNKNOWN
        self._discontinuity: str | None = None
        self._reset_pending = False
        self._hours: DecodedSignal | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.dropped_samples = self.write_errors = self.batches_written = 0
        self.last_error: str | None = None

    def _full(self, *, sample=False) -> bool:
        if self._queue.full():
            if sample:
                self.dropped_samples += 1
            self._reset_pending = True
            self._previous = None
            return True
        return False

    def offer_decoded(self, signal: DecodedSignal, *, evidence_ref: str | None = None) -> bool:
        """Recibe la seÃ±al del decoder existente, ANTES del filtro change/heartbeat."""
        if not self.config.enabled:
            return False
        if (self.config.hourmeter_validated and signal.key == "engine_total_hours"
                and signal.pgn == 0xFEE5 and signal.metadata.get("spn") == 247
                and signal.unit == "h" and signal.source_address == self.config.detector.source_address):
            with self._lock:
                self._hours = signal
            return True
        try:
            sample = RpmSample.from_decoded(signal, self.config.detector.equipment_id)
        except ValueError:
            return False
        return self.offer(sample, evidence_ref=evidence_ref)

    def offer(self, sample: RpmSample, *, evidence_ref: str | None = None) -> bool:
        if not self.config.enabled:
            return False
        cfg = self.config.detector
        if (sample.equipment_id != cfg.equipment_id or sample.source_address != cfg.source_address
                or sample.pgn != 0xF004 or sample.spn != 190):
            return False
        with self._lock:
            if self._full(sample=True):
                return False
            self._reset_if_needed()
            if (self._previous and isinstance(sample.timestamp_utc, datetime)
                    and sample.timestamp_utc.tzinfo is not None):
                dt = self.clock.monotonic() - self._previous[0]
                ds = (sample.timestamp_utc - self._previous[1]).total_seconds()
                if ds > 0 and (dt > cfg.max_sample_gap_seconds or ds > cfg.max_sample_gap_seconds):
                    self.detector.require_reconciliation()
                    self._previous = None
                    self._discontinuity = "observation_gap"
            previous_stamp = self.detector.last_valid_timestamp_utc
            events = self.detector.feed(sample)
            accepted = self.detector.last_valid_timestamp_utc != previous_stamp
            now = self.clock.monotonic()
            if accepted:
                if self._previous:
                    old_mono, old_stamp, old_state = self._previous
                    dt = now - old_mono
                    ds = (sample.timestamp_utc - old_stamp).total_seconds()
                    if dt > cfg.max_sample_gap_seconds or ds > cfg.max_sample_gap_seconds:
                        self._discontinuity = "observation_gap"
                    elif old_state == self.detector.state == EngineState.RUNNING and dt >= 0 and ds > 0:
                        self._coverage += min(dt, ds)
                self._previous = (now, sample.timestamp_utc, self.detector.state)
                self._sample, self._fresh = sample, True
            elif (not isinstance(sample.timestamp_utc, datetime) or sample.timestamp_utc.tzinfo is None
                  or previous_stamp is None or sample.timestamp_utc > previous_stamp):
                self._previous = None
                self._fresh = False
                self.detector.require_reconciliation()
                self._discontinuity = "invalid_rpm_evidence"
            self._submit(events, evidence_ref=evidence_ref)
            return accepted

    def _reset_if_needed(self):
        if self._reset_pending:
            self.detector.require_reconciliation()
            self._reset_pending = False
            self._fresh = False
            self._previous = None
            self._discontinuity = "queue_overflow"

    def _hourmeter(self):
        s = self._hours
        if not s or s.quality != "GOOD" or isinstance(s.value, bool) or not isinstance(s.value, (int, float)) or not math.isfinite(s.value) or s.value < 0:
            return None
        if s.timestamp_utc.tzinfo is None:
            return None
        age = (self.clock.utcnow() - s.timestamp_utc).total_seconds()
        return float(s.value) if 0 <= age <= self.config.detector.max_sample_age_seconds else None

    def _submit(self, events=(), *, force=False, evidence_ref=None):
        now = self.clock.monotonic()
        if not (force or events or self._discontinuity or self.detector.state != self._last_state
                or (self._fresh and now - self._last_submit >= self.config.flush_seconds)):
            return
        self._sequence += 1
        sample = self._sample if self._fresh else None
        batch = RecordingBatch(
            batch_id=f"{self.writer_id}:{self._sequence}", writer_id=self.writer_id,
            sequence=self._sequence, gateway_id=self.config.gateway_id,
            equipment_id=self.config.detector.equipment_id,
            source_address=self.config.detector.source_address,
            timestamp_utc=self.clock.utcnow(), state=self.detector.state,
            last_confirmed_state=self.detector.last_confirmed_state,
            events=tuple(events), observed_at_utc=sample.timestamp_utc if sample else None,
            rpm=sample.rpm if sample else None, verified_seconds=self._coverage,
            discontinuity=self._discontinuity, evidence_ref=evidence_ref, hourmeter=self._hourmeter(),
        )
        # lock de productor serializa full/put; el consumidor solo libera espacio.
        self._queue.put_nowait(batch)
        # Observador opcional: contrato no bloqueante; su fallo no altera el registrador.
        if self._batch_observer is not None:
            try:
                if self._batch_observer(batch) is False:
                    self.observer_errors += 1
            except Exception:
                self.observer_errors += 1
        self._fresh = False
        self._coverage = 0
        self._discontinuity = None
        self._last_state = self.detector.state
        self._last_submit = now

    def poll(self) -> None:
        if self.config.enabled:
            with self._lock:
                if not self._full():
                    self._reset_if_needed()
                    self._submit(self.detector.poll())

    def flush(self) -> bool:
        if not self.config.enabled:
            return True
        with self._lock:
            if self._full():
                return False
            # Vaciar evidencia pendiente; nunca inventar muestras ni confirmar por reloj.
            if self._fresh or self._coverage:
                self._submit(force=True)
            return True

    def drain_once(self) -> bool:
        """Solo escritor. Conserva EXACTAMENTE el mismo lote ante error/commit incierto."""
        if not self.config.enabled:
            return False
        with self._write_lock:
            if self._pending is None:
                try:
                    self._pending = self._queue.get_nowait()
                except queue.Empty:
                    return False
            try:
                if not self._begun:
                    self.recovered_checkpoint = self.store.begin_run(
                        self.config.gateway_id, self.config.detector.equipment_id,
                        self.writer_id, self._pending.timestamp_utc)
                    self._begun = True
                self.store.apply(self._pending)
            except Exception as exc:
                self.write_errors += 1
                self.last_error = type(exc).__name__
                return False
            self._queue.task_done()
            self._pending = None
            self.batches_written += 1
            self.last_error = None
            return True

    def status(self) -> dict:
        return {"enabled": self.config.enabled, "queued": self._queue.qsize() + int(self._pending is not None),
                "droppedSamples": self.dropped_samples, "writeErrors": self.write_errors,
                "lastError": self.last_error, "batchesWritten": self.batches_written,
                "observerErrors": self.observer_errors}

    def start(self):
        """ActivaciÃ³n explÃ­cita local; no se invoca desde ningÃºn servicio actual."""
        if not self.config.enabled:
            return
        if self._thread is not None:
            raise RuntimeError("worker already started")
        self._thread = threading.Thread(target=self._run, name="j1939-engine-writer", daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            self.poll()
            self.drain_once()
            self._stop.wait(self.config.retry_seconds if self.last_error else 0.05)
        # Un cierre limpio intenta vaciar; ante fallo deja lotes pendientes visibles.
        while self.drain_once():
            pass

    def close(self, timeout=2) -> bool:
        flushed = self.flush()
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        return flushed and (not self._thread or not self._thread.is_alive()) and self.status()["queued"] == 0
