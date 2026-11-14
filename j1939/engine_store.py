"""Almacén explícito J1939: ninguna ruta de DB ni migración automática al importar."""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .engine_detector import EngineEvent, EngineState

MIGRATION = Path(__file__).parent / "migrations" / "001_engine_recorder.sql"


def utc_text(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware UTC timestamp required")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def elapsed(start: str, end: str) -> float | None:
    delta = (datetime.fromisoformat(end.replace("Z", "+00:00")) -
             datetime.fromisoformat(start.replace("Z", "+00:00"))).total_seconds()
    return delta if delta >= 0 else None


@dataclass(frozen=True, slots=True)
class RecordingBatch:
    batch_id: str
    writer_id: str
    sequence: int
    gateway_id: str
    equipment_id: str
    source_address: int
    timestamp_utc: datetime
    state: EngineState
    last_confirmed_state: EngineState
    events: tuple[EngineEvent, ...] = ()
    observed_at_utc: datetime | None = None
    rpm: float | None = None
    verified_seconds: float = 0
    discontinuity: str | None = None
    evidence_ref: str | None = None
    hourmeter: float | None = None


class WriterConflict(RuntimeError):
    pass


class EngineStore:
    def __init__(self, path: str | Path, *, busy_ms: int = 50) -> None:
        self.path = Path(path).resolve()
        if type(busy_ms) is not int or busy_ms < 0:
            raise ValueError("busy_ms must be a nonnegative integer")
        self.busy_ms = busy_ms

    @contextmanager
    def _transaction(self):
        # mode=rw: errores de ruta NO crean una DB vacía por accidente.
        conn = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True,
                               timeout=self.busy_ms / 1000, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def migrate(self, *, create: bool = False) -> None:
        """Acción administrativa explícita; nunca llamada por el adaptador."""
        sql = MIGRATION.read_text(encoding="utf-8")
        checksum = hashlib.sha256(sql.encode()).hexdigest()
        if create and not self.path.exists():
            # Creación exclusiva; nunca sustituye un archivo ni crea carpetas.
            self.path.touch(exist_ok=False)
        # WAL solo durante preparación explícita, fuera de BEGIN.
        conn = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=self.busy_ms / 1000)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        finally:
            conn.close()
        with self._transaction() as c:
            c.execute("CREATE TABLE IF NOT EXISTS j1939_schema_migrations(version INTEGER PRIMARY KEY, checksum TEXT NOT NULL, applied_at_utc TEXT NOT NULL)")
            existing = c.execute("SELECT checksum FROM j1939_schema_migrations WHERE version=1").fetchone()
            if existing:
                if existing[0] != checksum:
                    raise ValueError("migration checksum mismatch")
                return
            names = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'j1939_%' AND name!='j1939_schema_migrations'").fetchall()
            if names:
                raise ValueError("unmanaged J1939 tables already exist")
            statement = ""
            for line in sql.splitlines(True):
                statement += line
                if sqlite3.complete_statement(statement):
                    c.execute(statement)
                    statement = ""
            if statement.strip():
                raise ValueError("incomplete migration")
            c.execute("INSERT INTO j1939_schema_migrations VALUES (1,?,?)",
                      (checksum, utc_text(datetime.now(timezone.utc))))

    def checkpoint(self, gateway: str, equipment: str) -> dict | None:
        with self._transaction() as c:
            row = c.execute("SELECT * FROM j1939_recorder_checkpoint WHERE gateway_id=? AND equipment_id=?", (gateway, equipment)).fetchone()
            return dict(row) if row else None

    @staticmethod
    def _gap(c, gateway, equipment, session, stamp, reason, gap_id):
        c.execute("INSERT OR IGNORE INTO j1939_observation_gaps(gap_id,gateway_id,equipment_id,session_id,started_at_utc,reason) VALUES(?,?,?,?,?,?)",
                  (gap_id, gateway, equipment, session, stamp, reason))
        if session:
            c.execute("UPDATE j1939_engine_sessions SET status='INDETERMINADA',quality='INCOMPLETE',duration_seconds=NULL,time_without_communication=NULL WHERE session_id=?", (session,))

    def begin_run(self, gateway: str, equipment: str, writer: str, at: datetime) -> dict | None:
        """Fencing explícito de un único escritor por equipo; candidatos se reconfirman."""
        if not all(isinstance(x, str) and x.strip() for x in (gateway, equipment, writer)):
            raise ValueError("gateway/equipment/writer required")
        stamp = utc_text(at)
        with self._transaction() as c:
            row = c.execute("SELECT * FROM j1939_recorder_checkpoint WHERE gateway_id=? AND equipment_id=?", (gateway, equipment)).fetchone()
            if row and row["writer_id"] == writer:
                return dict(row)
            if row:
                self._gap(c, gateway, equipment, row["session_id"], row["last_observed_at_utc"] or stamp,
                          "process_restart", "restart:" + writer)
                c.execute("UPDATE j1939_recorder_checkpoint SET writer_id=?,sequence=0,state='UNKNOWN',needs_reconcile=1 WHERE gateway_id=? AND equipment_id=?", (writer, gateway, equipment))
            else:
                c.execute("INSERT INTO j1939_recorder_checkpoint VALUES(?,?,?,0,'UNKNOWN','UNKNOWN',NULL,NULL,1)", (gateway, equipment, writer))
            return dict(row) if row else None

    def apply(self, batch: RecordingBatch) -> bool:
        """Evento/sesión/cobertura/checkpoint/dedupe se confirman juntos o ninguno."""
        stamp = utc_text(batch.timestamp_utc)
        observed = utc_text(batch.observed_at_utc) if batch.observed_at_utc else None
        if (type(batch.sequence) is not int or batch.sequence < 1 or not batch.batch_id
                or type(batch.source_address) is not int or not 0 <= batch.source_address <= 253
                or not math.isfinite(batch.verified_seconds) or batch.verified_seconds < 0):
            raise ValueError("invalid batch")
        if observed and observed > stamp:
            raise ValueError("future observation")
        for value in (batch.rpm, batch.hourmeter):
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
                raise ValueError("invalid reading")
        for event in batch.events:
            if event.equipment_id != batch.equipment_id or event.source_address != batch.source_address:
                raise ValueError("event identity mismatch")
        payload = json.dumps(asdict(batch), default=lambda value: utc_text(value) if isinstance(value, datetime) else str(value), sort_keys=True, allow_nan=False)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        with self._transaction() as c:
            previous = c.execute("SELECT payload_hash FROM j1939_recorder_batches WHERE batch_id=?", (batch.batch_id,)).fetchone()
            if previous:
                if previous[0] != digest:
                    raise ValueError("batch identity reused with different payload")
                return False
            row = c.execute("SELECT * FROM j1939_recorder_checkpoint WHERE gateway_id=? AND equipment_id=?", (batch.gateway_id, batch.equipment_id)).fetchone()
            if not row or row["writer_id"] != batch.writer_id or row["sequence"] + 1 != batch.sequence:
                raise WriterConflict("writer fenced or batch sequence out of order")
            if observed and row["last_observed_at_utc"] and observed < row["last_observed_at_utc"]:
                raise ValueError("observation timestamp regressed")
            session = row["session_id"]
            reconcile = bool(row["needs_reconcile"])
            if batch.verified_seconds and session:
                c.execute("UPDATE j1939_engine_sessions SET verified_seconds=verified_seconds+? WHERE session_id=?", (batch.verified_seconds, session))
            if batch.discontinuity:
                self._gap(c, batch.gateway_id, batch.equipment_id, session,
                          row["last_observed_at_utc"] or stamp, batch.discontinuity, batch.batch_id + ":gap")
                reconcile = True
            for index, event in enumerate(batch.events):
                kind = {"COMMUNICATION_LOST": "COMM_LOST", "COMMUNICATION_RECOVERED": "COMM_RECOVERED"}.get(event.event_type.value, event.event_type.value)
                event_id = batch.batch_id + ":" + str(index)
                event_stamp = utc_text(event.timestamp_utc)
                self._insert_event(c, batch, event_id, kind, event_stamp, event.previous_state.value,
                                   event.current_state.value, event.rpm, event.reason, event.evidence_quality,
                                   utc_text(event.observed_at_utc) if event.observed_at_utc else None)
                if kind == "COMM_LOST":
                    self._gap(c, batch.gateway_id, batch.equipment_id, session,
                              row["last_observed_at_utc"] or stamp, "valid_rpm_timeout", event_id + ":gap")
                    reconcile = True
                elif kind == "START":
                    if reconcile or session:
                        raise ValueError("START without a reconciled stopped baseline")
                    session = self._open_session(c, batch, event_id, event_stamp, confirmed=True)
                elif kind == "STOP":
                    if reconcile or not session:
                        raise ValueError("STOP without observed running session")
                    current = c.execute("SELECT * FROM j1939_engine_sessions WHERE session_id=?", (session,)).fetchone()
                    span = elapsed(current["started_at_utc"], event_stamp) if current["started_at_utc"] else None
                    complete = current["quality"] == "CONFIRMED" and span is not None
                    c.execute("UPDATE j1939_engine_sessions SET stop_event_id=?,ended_at_utc=?,observed_until_utc=?,final_rpm=?,final_hourmeter=?,active=0,status=?,duration_seconds=?,close_reason='confirmed_stop' WHERE session_id=?",
                              (event_id, event_stamp, observed or stamp, batch.rpm, batch.hourmeter,
                               "CERRADA" if complete else "INDETERMINADA", span if complete else None, session))
                    session = None
            # Estado estable sin START/STOP tras inicio o hueco = reconciliación, no transición física.
            if reconcile and observed and batch.state in (EngineState.RUNNING, EngineState.STOPPED):
                self._insert_event(c, batch, batch.batch_id + ":reconciled", "STATE_RECONCILED", stamp,
                                   row["last_confirmed_state"], batch.state.value, batch.rpm,
                                   "new_valid_samples_confirm_state_without_proving_transition", "INCOMPLETE_HISTORY", observed)
                gap = c.execute("SELECT * FROM j1939_observation_gaps WHERE gateway_id=? AND equipment_id=? AND recovered_at_utc IS NULL", (batch.gateway_id, batch.equipment_id)).fetchone()
                if gap:
                    duration = elapsed(gap["started_at_utc"], stamp)
                    if duration is not None:
                        c.execute("UPDATE j1939_observation_gaps SET recovered_at_utc=?,duration_seconds=? WHERE gap_id=?", (stamp, duration, gap["gap_id"]))
                if batch.state == EngineState.RUNNING and session is None:
                    session = self._open_session(c, batch, None, stamp, confirmed=False)
                elif batch.state == EngineState.STOPPED and session:
                    c.execute("UPDATE j1939_engine_sessions SET active=0,status='INDETERMINADA',quality='INCOMPLETE',duration_seconds=NULL,close_reason='reconciled_stopped_unknown_stop',observed_until_utc=? WHERE session_id=?", (observed, session))
                    session = None
                reconcile = False
            if session and observed:
                c.execute("UPDATE j1939_engine_sessions SET observed_until_utc=? WHERE session_id=?", (observed, session))
            # NULL si queda un hueco abierto; no confundir con cero segundos perdidos.
            c.execute("UPDATE j1939_engine_sessions SET time_without_communication=(SELECT CASE WHEN SUM(CASE WHEN recovered_at_utc IS NULL THEN 1 ELSE 0 END)>0 THEN NULL ELSE COALESCE(SUM(duration_seconds),0) END FROM j1939_observation_gaps g WHERE g.session_id=j1939_engine_sessions.session_id) WHERE session_id IN (?,?)", (row["session_id"], session))
            c.execute("UPDATE j1939_recorder_checkpoint SET sequence=?,state=?,last_confirmed_state=?,last_observed_at_utc=COALESCE(?,last_observed_at_utc),session_id=?,needs_reconcile=? WHERE gateway_id=? AND equipment_id=?",
                      (batch.sequence, batch.state.value, (batch.last_confirmed_state.value if batch.last_confirmed_state != EngineState.UNKNOWN else row["last_confirmed_state"]), observed, session, int(reconcile), batch.gateway_id, batch.equipment_id))
            c.execute("INSERT INTO j1939_recorder_batches VALUES(?,?,?,?,?,?)", (batch.batch_id, batch.writer_id, batch.sequence, batch.gateway_id, batch.equipment_id, digest))
        return True

    @staticmethod
    def _insert_event(c, batch, event_id, kind, stamp, previous, current, rpm, reason, quality, observed):
        c.execute("INSERT INTO j1939_engine_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (event_id, batch.gateway_id, batch.equipment_id, stamp, kind, previous, current, rpm,
                   batch.source_address, 0xF004, 190, reason, quality, batch.evidence_ref, observed,
                   utc_text(datetime.now(timezone.utc))))

    @staticmethod
    def _open_session(c, batch, event_id, stamp, *, confirmed):
        session = batch.batch_id + ":session"
        c.execute("INSERT INTO j1939_engine_sessions(session_id,gateway_id,equipment_id,start_event_id,started_at_utc,observed_from_utc,observed_until_utc,status,active,initial_rpm,initial_hourmeter,quality,time_without_communication) VALUES(?,?,?,?,?,?,?,?,1,?,?,?,0)",
                  (session, batch.gateway_id, batch.equipment_id, event_id, stamp if confirmed else None,
                   batch.observed_at_utc and utc_text(batch.observed_at_utc) or stamp,
                   batch.observed_at_utc and utc_text(batch.observed_at_utc) or stamp,
                   "ABIERTA" if confirmed else "INDETERMINADA", batch.rpm, batch.hourmeter,
                   "CONFIRMED" if confirmed else "INCOMPLETE"))
        return session
