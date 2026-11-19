"""Detector RPM aislado. Sin transporte, persistencia ni reloj global.

El llamador entrega todas las muestras, antes de filtrar cambios/heartbeat,
y llama poll() periódicamente incluso cuando no recibe ninguna trama.
No hay umbrales de producción por defecto ni continuidad entre instancias.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol

from .models import DecodedSignal


class EngineState(str, Enum):
    UNKNOWN = "UNKNOWN"
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    COMM_LOST = "COMM_LOST"


class EventType(str, Enum):
    START = "START"
    STOP = "STOP"
    COMMUNICATION_LOST = "COMMUNICATION_LOST"
    COMMUNICATION_RECOVERED = "COMMUNICATION_RECOVERED"


class DetectorClock(Protocol):
    def monotonic(self) -> float: ...

    def utcnow(self) -> datetime: ...


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _utc(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


@dataclass(frozen=True, slots=True)
class DetectorConfig:
    """Todos los límites deben elegirse explícitamente; calibración física pendiente."""

    equipment_id: str
    source_address: int
    rpm_start: float
    rpm_stop: float
    rpm_max: float
    start_samples: int
    stop_samples: int
    start_seconds: float
    stop_seconds: float
    timeout_seconds: float
    max_sample_gap_seconds: float
    max_sample_age_seconds: float

    def __post_init__(self) -> None:
        if not isinstance(self.equipment_id, str) or not self.equipment_id.strip():
            raise ValueError("equipment_id is required")
        if type(self.source_address) is not int or not 0 <= self.source_address <= 253:
            raise ValueError("source_address must be an explicit ECU address (0..253)")
        names = ("rpm_start", "rpm_stop", "rpm_max", "start_seconds", "stop_seconds",
                 "timeout_seconds", "max_sample_gap_seconds", "max_sample_age_seconds")
        if any(not _finite(getattr(self, name)) for name in names):
            raise ValueError("limits must be finite numbers")
        if not 0 <= self.rpm_stop < self.rpm_start <= self.rpm_max:
            raise ValueError("require 0 <= rpm_stop < rpm_start <= rpm_max")
        if any(type(n) is not int or n < 1 for n in (self.start_samples, self.stop_samples)):
            raise ValueError("sample counts must be positive integers")
        if min(self.start_seconds, self.stop_seconds) < 0:
            raise ValueError("confirmation times must be nonnegative")
        if not 0 < self.max_sample_gap_seconds < self.timeout_seconds:
            raise ValueError("sample gap must be positive and less than timeout")
        if not 0 < self.max_sample_age_seconds < self.timeout_seconds:
            raise ValueError("sample age must be positive and less than timeout")


@dataclass(frozen=True, slots=True)
class RpmSample:
    timestamp_utc: datetime
    rpm: float | int | None
    source_address: int
    equipment_id: str
    pgn: int = 0xF004
    spn: int = 190
    quality: str = "GOOD"

    @classmethod
    def from_decoded(cls, signal: DecodedSignal, equipment_id: str) -> RpmSample:
        """Adaptación explícita del contrato existente; no adivina equipo ni ECU."""
        if (signal.key != "engine_speed" or signal.pgn != 0xF004
                or signal.unit != "rpm" or signal.metadata.get("spn") != 190
                or signal.confidence != "CONFIRMED"):
            raise ValueError("expected engine_speed / F004 / SPN 190 / rpm")
        return cls(signal.timestamp_utc, signal.value, signal.source_address,
                   equipment_id, quality=signal.quality)


@dataclass(frozen=True, slots=True)
class EngineEvent:
    event_type: EventType
    timestamp_utc: datetime
    previous_state: EngineState
    current_state: EngineState
    rpm: float | int | None
    source_address: int
    equipment_id: str
    reason: str
    evidence_quality: str
    observed_at_utc: datetime | None
    pgn: int = 0xF004
    spn: int = 190


class EngineDetector:
    """FSM de un equipo/ECU; llamadas serializadas por el consumidor.

    feed devuelve eventos nuevos; poll detecta silencio. Rechaza timestamps
    repetidos/fuera de orden, atrasados o futuros. El timestamp de adquisición
    debe distinguir muestras independientes. Eventos no son durables en fase 02.
    """

    def __init__(self, config: DetectorConfig, clock: DetectorClock) -> None:
        self.config = config
        self.clock = clock
        self._state = EngineState.UNKNOWN
        self._last_confirmed = EngineState.UNKNOWN
        self._baseline = EngineState.UNKNOWN
        self._last_tick: float | None = None
        now, _ = self._now()
        self._created = now
        self._last_valid: float | None = None
        self._last_stamp: datetime | None = None
        self._candidate: EngineState | None = None
        self._candidate_count = 0
        self._candidate_since = now
        self._candidate_stamp: datetime | None = None

    @property
    def state(self) -> EngineState:
        return self._state

    @property
    def last_confirmed_state(self) -> EngineState:
        return self._last_confirmed

    @property
    def last_valid_timestamp_utc(self) -> datetime | None:
        """Evidencia aceptada; permite adaptar persistencia sin repetir validación."""
        return self._last_stamp

    def require_reconciliation(self) -> None:
        """Interrumpe evidencia continua sin rejuvenecer el timeout ni borrar historia."""
        self._baseline = EngineState.UNKNOWN
        self._clear_candidate()
        if self._state != EngineState.COMM_LOST:
            self._state = EngineState.UNKNOWN

    def _now(self) -> tuple[float, datetime]:
        now, utc = self.clock.monotonic(), self.clock.utcnow()
        if not _finite(now) or (self._last_tick is not None and now < self._last_tick):
            raise ValueError("clock must provide finite, nondecreasing monotonic time")
        if not _utc(utc):
            raise ValueError("clock must provide timezone-aware UTC time")
        self._last_tick = now
        return now, utc.astimezone(timezone.utc)

    def _clear_candidate(self) -> None:
        self._candidate = None
        self._candidate_count = 0
        self._candidate_stamp = None

    def _cancel_candidate(self) -> None:
        self._clear_candidate()
        if self._state != EngineState.COMM_LOST:
            self._state = self._baseline

    def _event(self, kind: EventType, previous: EngineState, utc: datetime,
               sample: RpmSample | None, reason: str, quality: str) -> EngineEvent:
        return EngineEvent(kind, utc, previous, self._state,
                           sample.rpm if sample else None, self.config.source_address,
                           self.config.equipment_id, reason, quality,
                           sample.timestamp_utc.astimezone(timezone.utc) if sample else None)

    def _expire(self, now: float, utc: datetime) -> list[EngineEvent]:
        reference = self._last_valid if self._last_valid is not None else self._created
        if now - reference < self.config.timeout_seconds or self._state == EngineState.COMM_LOST:
            return []
        previous = self._state
        self._state = EngineState.COMM_LOST
        self._baseline = EngineState.UNKNOWN
        self._clear_candidate()
        return [self._event(EventType.COMMUNICATION_LOST, previous, utc, None,
                            "valid_rpm_timeout", "NO_VALID_RPM")]

    def poll(self) -> list[EngineEvent]:
        """Evaluar timeout sin depender de que llegue una muestra nueva."""
        now, utc = self._now()
        return self._expire(now, utc)

    def feed(self, sample: RpmSample) -> list[EngineEvent]:
        now, utc = self._now()
        events = self._expire(now, utc)
        cfg = self.config
        if (sample.equipment_id != cfg.equipment_id
                or type(sample.source_address) is not int or sample.source_address != cfg.source_address
                or type(sample.pgn) is not int or sample.pgn != 0xF004
                or type(sample.spn) is not int or sample.spn != 190):
            return events
        if not _utc(sample.timestamp_utc):
            self._cancel_candidate()
            return events
        stamp = sample.timestamp_utc.astimezone(timezone.utc)
        # Mismo timestamp se trata conservadoramente como repetido, aun si cambia el valor.
        if self._last_stamp is not None and stamp <= self._last_stamp:
            return events
        age = (utc - stamp).total_seconds()
        if (not 0 <= age <= cfg.max_sample_age_seconds or sample.quality != "GOOD"
                or not _finite(sample.rpm) or not 0 <= sample.rpm <= cfg.rpm_max):
            self._cancel_candidate()
            return events
        if self._state == EngineState.COMM_LOST:
            previous = self._state
            self._state = EngineState.UNKNOWN
            events.append(self._event(EventType.COMMUNICATION_RECOVERED, previous, utc,
                                      sample, "valid_target_rpm_received", "VALID_SAMPLE"))
        if self._last_valid is not None and (now - self._last_valid > cfg.max_sample_gap_seconds
                or (stamp - self._last_stamp).total_seconds() > cfg.max_sample_gap_seconds):
            self._cancel_candidate()
        self._last_valid, self._last_stamp = now, stamp
        target = (EngineState.RUNNING if sample.rpm >= cfg.rpm_start else
                  EngineState.STOPPED if sample.rpm <= cfg.rpm_stop else None)
        if target is None or target == self._baseline:
            self._cancel_candidate()
            return events
        if target != self._candidate:
            self._candidate = target
            self._candidate_count = 0
            self._candidate_since = now
            self._candidate_stamp = stamp
        self._candidate_count += 1
        self._state = EngineState.STARTING if target == EngineState.RUNNING else EngineState.STOPPING
        count = cfg.start_samples if target == EngineState.RUNNING else cfg.stop_samples
        seconds = cfg.start_seconds if target == EngineState.RUNNING else cfg.stop_seconds
        # Cantidad Y tiempo; ni ráfagas almacenadas ni poll() completan confirmación.
        if (self._candidate_count < count or now - self._candidate_since < seconds
                or (stamp - self._candidate_stamp).total_seconds() < seconds):
            return events
        previous, baseline = self._state, self._baseline
        self._state = self._baseline = self._last_confirmed = target
        self._clear_candidate()
        # Inicialización/reconciliación no prueba transición física durante el hueco.
        if baseline != EngineState.UNKNOWN:
            kind = EventType.START if target == EngineState.RUNNING else EventType.STOP
            events.append(self._event(kind, previous, utc, sample,
                                      "rpm_samples_and_time_confirmed", "CONFIRMED_RPM"))
        return events
