"""Optional observer of the existing RX stream. No CAN access or migrations."""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import math
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from .auto_evidence import AutoEvidence, EvidenceConfig, REPO_ROOT
from .engine_detector import DetectorConfig
from .engine_recorder import EngineRecorder, RecorderConfig
from .evidence_store import EvidenceStore

SIGNALS = {"engine_speed": 0xF004, "coolant_temperature": 0xFEEE,
           "dc_voltage_field_1": 0xFEF7, "engine_total_hours": 0xFEE5}


class SystemClock:
    def monotonic(self):
        return time.monotonic()

    def utcnow(self):
        return datetime.now(timezone.utc)


class EngineIntegration:
    def __init__(self, recorder, evidence=None, signal_sources=None):
        self.recorder, self.evidence = recorder, evidence
        self.signal_sources = signal_sources or {}
        self.latest = {}
        self.errors = 0

    def start(self):
        if self.evidence:
            self.evidence.start()
        self.recorder.start()

    def offer_frame(self, frame):
        if self.evidence:
            self.evidence.offer_frame(frame)

    def offer_decoded(self, signal):
        now = self.recorder.clock.utcnow()
        # At most four explicit key/SA pairs; never mix ECUs or replace newer data.
        if (signal.key in SIGNALS and signal.pgn == SIGNALS[signal.key]
                and self.signal_sources.get(signal.key) == signal.source_address
                and signal.timestamp_utc.tzinfo is not None
                and signal.timestamp_utc.utcoffset() is not None
                and signal.timestamp_utc <= now):
            old = self.latest.get(signal.key)
            if old is None or signal.timestamp_utc > old.timestamp_utc:
                self.latest[signal.key] = signal
        snapshots = []
        for key, s in self.latest.items():
            age = (now - s.timestamp_utc).total_seconds()
            valid = (s.quality == "GOOD" and not isinstance(s.value, bool)
                     and isinstance(s.value, (int, float)) and math.isfinite(s.value)
                     and 0 <= age <= self.recorder.config.detector.max_sample_age_seconds)
            snapshots.append(dict(key=key, sourceAddress=s.source_address, pgn=s.pgn,
                                  spn=s.metadata.get("spn"), timestampUtc=s.timestamp_utc.isoformat(),
                                  quality=s.quality, confidence=s.confidence, unit=s.unit,
                                  value=s.value if valid else None, available=valid))
        # Existing event evidence_ref stores a versioned bounded JSON snapshot.
        self.recorder.offer_decoded(signal, evidence_ref=json.dumps(
            {"kind": "j1939_signal_snapshot_v1", "signals": snapshots}, allow_nan=False))

    def status(self):
        return dict(enabled=True, errors=self.errors, recorder=self.recorder.status(),
                    evidence=self.evidence.status() if self.evidence else {"enabled": False})

    def close(self):
        # Keep evidence observer alive until final recorder batches have been offered.
        recorded = self.recorder.close()
        captured = self.evidence.close() if self.evidence else True
        return recorded and captured


def build_integration(settings, *, clock=None, start=True):
    """Disabled means no config read, database connection, directory or worker."""
    events = settings.get("engine_events_enabled", False)
    raw_enabled = settings.get("auto_evidence_enabled", False)
    if not events:
        if raw_enabled:
            raise ValueError("automatic evidence requires engine events")
        return None
    raw = json.loads(Path(settings["engine_config"]).read_text(encoding="utf-8"))
    detector = DetectorConfig(**raw["detector"])
    database = Path(raw["database"])
    if not database.is_absolute() or database.resolve().is_relative_to(REPO_ROOT):
        raise ValueError("dedicated absolute database path outside repository required")
    # Read-only verification; migrations are a separate operator action.
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as c:
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if any(t != "sqlite_sequence" and not t.startswith("j1939_") for t in tables):
            raise ValueError("dedicated J1939 database required; measurement DB forbidden")
        versions = dict(c.execute("SELECT version,checksum FROM j1939_schema_migrations"))
        for version, name in ((1, "001_engine_recorder.sql"), (2, "002_auto_evidence.sql")):
            if version == 2 and not raw_enabled:
                continue
            expected = hashlib.sha256((Path(__file__).parent / "migrations" / name).read_text(encoding="utf-8").encode()).hexdigest()
            if versions.get(version) != expected:
                raise ValueError("explicit verified migrations required")
    clock = clock or SystemClock()
    store = EvidenceStore(database)
    sources = raw.get("signal_sources", {})
    if set(sources) - SIGNALS.keys() or any(type(sa) is not int or not 0 <= sa <= 253 for sa in sources.values()):
        raise ValueError("explicit valid signal source addresses required")
    if sources.get("engine_speed") != detector.source_address:
        raise ValueError("RPM source must match detector")
    evidence = None
    if raw_enabled:
        options = dict(raw["evidence"])
        directory = Path(options.pop("directory"))
        if not directory.is_absolute():
            raise ValueError("absolute RAW directory required")
        selections = tuple((SIGNALS[key], sa) for key, sa in sources.items())
        evidence = AutoEvidence(EvidenceConfig(directory, selections, raw["gateway_id"],
                                detector.equipment_id, detector.source_address, enabled=True, **options), clock, store)
    recorder = EngineRecorder(RecorderConfig(raw["gateway_id"], detector, enabled=True,
                              **raw.get("recorder", {})), clock, store,
                              batch_observer=evidence.observe_batch if evidence else None)
    observer = EngineIntegration(recorder, evidence, sources)
    if start:
        try:
            observer.start()
        except Exception:
            observer.close()
            raise
    return observer
