"""Extensión aditiva de EngineStore; no modifica su migración 001 ni sus transacciones."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .engine_store import EngineStore, utc_text

MIGRATION = Path(__file__).parent / "migrations/002_auto_evidence.sql"


class EvidenceStore(EngineStore):
    def migrate_evidence(self, *, create=False):
        self.migrate(create=create)
        sql = MIGRATION.read_text(encoding="utf-8")
        checksum = hashlib.sha256(sql.encode()).hexdigest()
        with self._transaction() as c:
            row = c.execute("SELECT checksum FROM j1939_schema_migrations WHERE version=2").fetchone()
            if row:
                if row[0] != checksum:
                    raise ValueError("evidence migration checksum mismatch")
                return
            statement = ""
            for line in sql.splitlines(True):
                statement += line
                if sqlite3.complete_statement(statement):
                    c.execute(statement)
                    statement = ""
            if statement.strip():
                raise ValueError("incomplete evidence migration")
            c.execute("INSERT INTO j1939_schema_migrations VALUES(2,?,?)", (checksum, utc_text(datetime.now(timezone.utc))))

    def save_segment(self, meta: dict):
        """Upsert idempotente; vinculación al lote real confirmado, nunca por proximidad horaria."""
        with self._transaction() as c:
            row = c.execute("SELECT session_id FROM j1939_evidence_batch_sessions WHERE batch_id=?", (meta["anchor_batch_id"],)).fetchone()
            session = row[0] if row else None
            c.execute("""INSERT INTO j1939_evidence_segments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(segment_id) DO UPDATE SET session_id=COALESCE(excluded.session_id,j1939_evidence_segments.session_id),
                file_path=excluded.file_path,started_at_utc=excluded.started_at_utc,ended_at_utc=excluded.ended_at_utc,
                frame_count=excluded.frame_count,pgn_json=excluded.pgn_json,source_json=excluded.source_json,
                size_bytes=excluded.size_bytes,integrity=excluded.integrity,close_reason=excluded.close_reason,
                sha256=excluded.sha256,manifest_json=excluded.manifest_json""",
                      (meta["segment_id"], meta["capture_id"], meta["anchor_batch_id"], session, meta["file_path"],
                       meta["started_at_utc"], meta["ended_at_utc"], meta["frame_count"], json.dumps(meta["pgns"]),
                       json.dumps(meta["sources"]), meta["size_bytes"], meta["integrity"], meta["close_reason"],
                       meta["sha256"], json.dumps(meta, sort_keys=True)))
            return session

    def session_closed(self, segment_id: str) -> bool:
        with self._transaction() as c:
            row = c.execute("""SELECT s.status,s.active FROM j1939_engine_sessions s
                JOIN j1939_evidence_segments e ON e.session_id=s.session_id WHERE e.segment_id=?""", (segment_id,)).fetchone()
            return bool(row and row[0] == "CERRADA" and row[1] == 0)
