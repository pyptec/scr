import hashlib
import json
import secrets
import sqlite3
import time
from pathlib import Path

from db.aoki_maintenance_auth import ROLES, token_hash


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = ROOT / "data" / "aoki_maintenance_validations.db"
SCHEMA_VERSION = 1


class StoreError(Exception):
    status_code = 422
    code = "VALIDATION_ERROR"


class ConflictError(StoreError):
    status_code = 409
    code = "VERSION_CONFLICT"


class EvidenceConflictError(ConflictError):
    code = "SOURCE_EVIDENCE_CHANGED"


class NotFoundError(StoreError):
    status_code = 404
    code = "NOT_FOUND"


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_metadata (
    schemaVersion INTEGER PRIMARY KEY,
    appliedAtUtc INTEGER NOT NULL,
    applicationVersion TEXT NOT NULL,
    migrationHash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS validation_actors (
    actorId TEXT PRIMARY KEY,
    displayName TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('MAINTENANCE_VALIDATOR','MAINTENANCE_ADMIN')),
    tokenHash TEXT NOT NULL UNIQUE CHECK(length(tokenHash)=64),
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    createdAtUtc INTEGER NOT NULL,
    revokedAtUtc INTEGER,
    createdByActorId TEXT
);
CREATE TABLE IF NOT EXISTS maintenance_validation_current (
    maintenanceEventId TEXT PRIMARY KEY,
    validatedClassification TEXT,
    validationStatus TEXT NOT NULL CHECK(validationStatus IN
      ('PENDING_HUMAN_REVIEW','HUMAN_VALIDATED','HUMAN_REJECTED','SUPERSEDED')),
    validatedStartUtc INTEGER,
    validatedEndUtc INTEGER,
    validatedDowntimeMinutes REAL,
    durationOverrideReason TEXT,
    causeCategory TEXT,
    affectedSystem TEXT,
    affectedComponent TEXT,
    interventionDescription TEXT,
    reviewComment TEXT,
    actorId TEXT NOT NULL,
    validatedAtUtc INTEGER NOT NULL,
    version INTEGER NOT NULL CHECK(version>=1),
    taxonomyVersion TEXT NOT NULL,
    evidenceHashVersion TEXT NOT NULL,
    sourceEvidenceHash TEXT NOT NULL CHECK(length(sourceEvidenceHash)=64),
    createdAtUtc INTEGER NOT NULL,
    updatedAtUtc INTEGER NOT NULL,
    FOREIGN KEY(actorId) REFERENCES validation_actors(actorId),
    CHECK(validatedEndUtc IS NULL OR validatedStartUtc IS NOT NULL),
    CHECK(validatedEndUtc IS NULL OR validatedEndUtc > validatedStartUtc),
    CHECK(validatedDowntimeMinutes IS NULL OR validatedDowntimeMinutes > 0),
    CHECK(validationStatus != 'HUMAN_VALIDATED' OR validatedClassification IS NOT NULL)
);
CREATE TABLE IF NOT EXISTS maintenance_validation_history (
    historyId INTEGER PRIMARY KEY AUTOINCREMENT,
    requestId TEXT NOT NULL UNIQUE,
    maintenanceEventId TEXT NOT NULL,
    previousVersion INTEGER NOT NULL,
    newVersion INTEGER NOT NULL,
    previousPayloadJson TEXT,
    newPayloadJson TEXT NOT NULL,
    actorId TEXT NOT NULL,
    changedAtUtc INTEGER NOT NULL,
    sourceEvidenceHash TEXT NOT NULL,
    taxonomyVersion TEXT NOT NULL,
    changeReason TEXT NOT NULL,
    FOREIGN KEY(actorId) REFERENCES validation_actors(actorId)
);
CREATE TABLE IF NOT EXISTS validated_operating_windows (
    windowId TEXT PRIMARY KEY,
    startUtc INTEGER NOT NULL,
    endUtc INTEGER NOT NULL,
    windowType TEXT NOT NULL CHECK(windowType IN
      ('SCHEDULED_OPERATION','PLANNED_STOP','EXTERNAL_STOP',
       'NON_OPERATING_PERIOD','UNKNOWN')),
    source TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('HUMAN_VALIDATED','SUPERSEDED')),
    actorId TEXT NOT NULL,
    comment TEXT,
    version INTEGER NOT NULL CHECK(version>=1),
    policyVersion TEXT NOT NULL,
    createdAtUtc INTEGER NOT NULL,
    updatedAtUtc INTEGER NOT NULL,
    FOREIGN KEY(actorId) REFERENCES validation_actors(actorId),
    CHECK(endUtc > startUtc)
);
CREATE TABLE IF NOT EXISTS validated_operating_window_history (
    historyId INTEGER PRIMARY KEY AUTOINCREMENT,
    requestId TEXT NOT NULL UNIQUE,
    windowId TEXT NOT NULL,
    previousVersion INTEGER NOT NULL,
    newVersion INTEGER NOT NULL,
    previousPayloadJson TEXT,
    newPayloadJson TEXT NOT NULL,
    actorId TEXT NOT NULL,
    changedAtUtc INTEGER NOT NULL,
    changeReason TEXT NOT NULL,
    policyVersion TEXT NOT NULL,
    FOREIGN KEY(actorId) REFERENCES validation_actors(actorId)
);
CREATE TRIGGER IF NOT EXISTS maintenance_history_no_update
BEFORE UPDATE ON maintenance_validation_history BEGIN
  SELECT RAISE(ABORT, 'maintenance history is append-only');
END;
CREATE TRIGGER IF NOT EXISTS maintenance_history_no_delete
BEFORE DELETE ON maintenance_validation_history BEGIN
  SELECT RAISE(ABORT, 'maintenance history is append-only');
END;
CREATE TRIGGER IF NOT EXISTS window_history_no_update
BEFORE UPDATE ON validated_operating_window_history BEGIN
  SELECT RAISE(ABORT, 'window history is append-only');
END;
CREATE TRIGGER IF NOT EXISTS window_history_no_delete
BEFORE DELETE ON validated_operating_window_history BEGIN
  SELECT RAISE(ABORT, 'window history is append-only');
END;
CREATE INDEX IF NOT EXISTS idx_validation_status
ON maintenance_validation_current(validationStatus, validatedClassification);
CREATE INDEX IF NOT EXISTS idx_windows_range
ON validated_operating_windows(startUtc, endUtc, status);
"""


def _now():
    return int(time.time())


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _row(row):
    return dict(row) if row is not None else None


class MaintenanceValidationStore:
    def __init__(self, path=DEFAULT_DB_PATH):
        self.path = Path(path)

    def connect(self):
        connection = sqlite3.connect(str(self.path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = self.connect()
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(SCHEMA)
            migration_hash = hashlib.sha256(SCHEMA.encode("utf-8")).hexdigest()
            connection.execute("""
                INSERT OR IGNORE INTO schema_metadata
                (schemaVersion, appliedAtUtc, applicationVersion, migrationHash)
                VALUES (?, ?, ?, ?)
            """, (SCHEMA_VERSION, _now(), "fase4-subfase4.1B", migration_hash))
            connection.commit()
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise StoreError("Falló integrity_check de la base auxiliar")
        finally:
            connection.close()

    def list_active_actors(self):
        connection = self.connect()
        try:
            return [
                dict(row) for row in connection.execute("""
                    SELECT actorId, displayName, role, tokenHash
                    FROM validation_actors WHERE active=1 ORDER BY actorId
                """)
            ]
        finally:
            connection.close()

    def provision_actor(self, actor_id, display_name, role, created_by=None, token=None):
        if not actor_id or not display_name or role not in ROLES:
            raise StoreError("Actor, nombre y rol válido son obligatorios")
        token = token or secrets.token_urlsafe(32)
        connection = self.connect()
        try:
            connection.execute("""
                INSERT INTO validation_actors
                (actorId, displayName, role, tokenHash, active, createdAtUtc, createdByActorId)
                VALUES (?, ?, ?, ?, 1, ?, ?)
            """, (actor_id, display_name, role, token_hash(token), _now(), created_by))
            connection.commit()
        finally:
            connection.close()
        return token

    def revoke_actor(self, actor_id):
        connection = self.connect()
        try:
            cursor = connection.execute("""
                UPDATE validation_actors SET active=0, revokedAtUtc=?
                WHERE actorId=? AND active=1
            """, (_now(), actor_id))
            if cursor.rowcount != 1:
                raise NotFoundError("Actor activo no encontrado")
            connection.commit()
        finally:
            connection.close()

    def get_validation(self, maintenance_event_id):
        connection = self.connect()
        try:
            return _row(connection.execute("""
                SELECT * FROM maintenance_validation_current
                WHERE maintenanceEventId=?
            """, (maintenance_event_id,)).fetchone())
        finally:
            connection.close()

    def list_validations(self):
        connection = self.connect()
        try:
            return [
                dict(row) for row in connection.execute(
                    "SELECT * FROM maintenance_validation_current ORDER BY maintenanceEventId"
                )
            ]
        finally:
            connection.close()

    def validation_history(self, maintenance_event_id):
        connection = self.connect()
        try:
            return [
                dict(row) for row in connection.execute("""
                    SELECT * FROM maintenance_validation_history
                    WHERE maintenanceEventId=? ORDER BY historyId
                """, (maintenance_event_id,))
            ]
        finally:
            connection.close()

    def save_validation(self, event, payload, actor, expected_version, request_id):
        if not request_id:
            raise StoreError("Idempotency-Key es obligatorio")
        if payload.get("actor") and payload["actor"] != actor["actorId"]:
            raise StoreError("El actor del payload no coincide con la credencial")
        current_hash = event["sourceEvidenceHash"]
        if payload.get("sourceEvidenceHash") != current_hash:
            raise EvidenceConflictError("La evidencia fuente cambió")
        status = payload.get("validationStatus")
        classification = payload.get("validatedClassification")
        if status not in {
            "PENDING_HUMAN_REVIEW", "HUMAN_VALIDATED", "HUMAN_REJECTED", "SUPERSEDED"
        }:
            raise StoreError("Estado de validación inválido")
        taxonomy = event["taxonomyVersion"]
        from db.aoki_maintenance_events import load_maintenance_taxonomy
        valid_classifications = load_maintenance_taxonomy()["classifications"]
        if classification is not None and classification not in valid_classifications:
            raise StoreError("Clasificación validada inválida")
        if status == "HUMAN_VALIDATED" and classification is None:
            raise StoreError("HUMAN_VALIDATED requiere clasificación")
        start = payload.get("validatedStartUtc")
        end = payload.get("validatedEndUtc")
        if classification == "CORRECTIVE_FAILURE" and status == "HUMAN_VALIDATED" and start is None:
            raise StoreError("Una falla correctiva validada requiere inicio")
        if start is not None:
            start = int(start)
        if end is not None:
            end = int(end)
            if start is None or end <= start:
                raise StoreError("El fin validado debe ser posterior al inicio")
        calculated = (end - start) / 60 if start is not None and end is not None else None
        supplied = payload.get("validatedDowntimeMinutes")
        override_reason = payload.get("durationOverrideReason")
        if supplied is not None:
            supplied = float(supplied)
            if supplied <= 0:
                raise StoreError("La duración validada debe ser positiva")
            if calculated is not None and abs(supplied - calculated) > 1e-6 and not override_reason:
                raise StoreError("Una duración distinta requiere durationOverrideReason")
        duration = supplied if supplied is not None else calculated
        now = _now()
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            duplicate = connection.execute("""
                SELECT newPayloadJson FROM maintenance_validation_history WHERE requestId=?
            """, (request_id,)).fetchone()
            if duplicate:
                connection.rollback()
                return json.loads(duplicate["newPayloadJson"])
            previous = _row(connection.execute("""
                SELECT * FROM maintenance_validation_current WHERE maintenanceEventId=?
            """, (event["maintenanceEventId"],)).fetchone())
            current_version = previous["version"] if previous else 0
            if int(expected_version) != current_version:
                raise ConflictError(f"Versión actual: {current_version}")
            new = {
                "maintenanceEventId": event["maintenanceEventId"],
                "validatedClassification": classification,
                "validationStatus": status,
                "validatedStartUtc": start,
                "validatedEndUtc": end,
                "validatedDowntimeMinutes": duration,
                "durationOverrideReason": override_reason,
                "causeCategory": payload.get("causeCategory"),
                "affectedSystem": payload.get("affectedSystem"),
                "affectedComponent": payload.get("affectedComponent"),
                "interventionDescription": payload.get("interventionDescription"),
                "reviewComment": payload.get("reviewComment"),
                "actorId": actor["actorId"],
                "validatedAtUtc": now,
                "version": current_version + 1,
                "taxonomyVersion": taxonomy,
                "evidenceHashVersion": event["evidenceHashVersion"],
                "sourceEvidenceHash": current_hash,
                "createdAtUtc": previous["createdAtUtc"] if previous else now,
                "updatedAtUtc": now,
            }
            connection.execute("""
                INSERT INTO maintenance_validation_history
                (requestId, maintenanceEventId, previousVersion, newVersion,
                 previousPayloadJson, newPayloadJson, actorId, changedAtUtc,
                 sourceEvidenceHash, taxonomyVersion, changeReason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                request_id, event["maintenanceEventId"], current_version, new["version"],
                _json(previous) if previous else None, _json(new), actor["actorId"], now,
                current_hash, taxonomy, payload.get("changeReason") or "HUMAN_REVIEW",
            ))
            columns = list(new)
            connection.execute(f"""
                INSERT INTO maintenance_validation_current ({','.join(columns)})
                VALUES ({','.join('?' for _ in columns)})
                ON CONFLICT(maintenanceEventId) DO UPDATE SET
                {','.join(f'{column}=excluded.{column}' for column in columns if column not in ('maintenanceEventId','createdAtUtc'))}
            """, [new[column] for column in columns])
            connection.commit()
            return new
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def list_windows(self, start=None, end=None):
        connection = self.connect()
        try:
            where, parameters = "1=1", []
            if start is not None and end is not None:
                where += " AND endUtc>? AND startUtc<?"
                parameters.extend((int(start), int(end)))
            return [
                dict(row) for row in connection.execute(f"""
                    SELECT * FROM validated_operating_windows
                    WHERE {where} ORDER BY startUtc, endUtc, windowId
                """, parameters)
            ]
        finally:
            connection.close()

    def window_history(self, window_id):
        connection = self.connect()
        try:
            return [
                dict(row) for row in connection.execute("""
                    SELECT * FROM validated_operating_window_history
                    WHERE windowId=? ORDER BY historyId
                """, (window_id,))
            ]
        finally:
            connection.close()

    def save_window(self, payload, actor, expected_version, request_id):
        if not request_id:
            raise StoreError("Idempotency-Key es obligatorio")
        if payload.get("actor") and payload["actor"] != actor["actorId"]:
            raise StoreError("El actor del payload no coincide con la credencial")
        window_id = payload.get("windowId")
        window_type = payload.get("windowType")
        if not window_id or window_type not in {
            "SCHEDULED_OPERATION", "PLANNED_STOP", "EXTERNAL_STOP",
            "NON_OPERATING_PERIOD", "UNKNOWN",
        }:
            raise StoreError("windowId y windowType válido son obligatorios")
        start, end = int(payload["startUtc"]), int(payload["endUtc"])
        if end <= start:
            raise StoreError("La ventana debe tener duración positiva")
        status = payload.get("status", "HUMAN_VALIDATED")
        if status not in {"HUMAN_VALIDATED", "SUPERSEDED"}:
            raise StoreError("Estado de ventana inválido")
        if not payload.get("source"):
            raise StoreError("La fuente de la ventana es obligatoria")
        now = _now()
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            duplicate = connection.execute("""
                SELECT newPayloadJson FROM validated_operating_window_history
                WHERE requestId=?
            """, (request_id,)).fetchone()
            if duplicate:
                connection.rollback()
                return json.loads(duplicate["newPayloadJson"])
            previous = _row(connection.execute("""
                SELECT * FROM validated_operating_windows WHERE windowId=?
            """, (window_id,)).fetchone())
            version = previous["version"] if previous else 0
            if int(expected_version) != version:
                raise ConflictError(f"Versión actual: {version}")
            if status == "HUMAN_VALIDATED":
                overlap = connection.execute("""
                    SELECT windowId FROM validated_operating_windows
                    WHERE windowId != ? AND windowType=? AND status='HUMAN_VALIDATED'
                      AND endUtc>? AND startUtc<?
                    LIMIT 1
                """, (window_id, window_type, start, end)).fetchone()
                if overlap:
                    raise ConflictError(
                        f"Solapamiento con ventana {overlap['windowId']} del mismo tipo"
                    )
            new = {
                "windowId": window_id, "startUtc": start, "endUtc": end,
                "windowType": window_type, "source": payload["source"],
                "status": status, "actorId": actor["actorId"],
                "comment": payload.get("comment"), "version": version + 1,
                "policyVersion": payload["policyVersion"],
                "createdAtUtc": previous["createdAtUtc"] if previous else now,
                "updatedAtUtc": now,
            }
            connection.execute("""
                INSERT INTO validated_operating_window_history
                (requestId, windowId, previousVersion, newVersion,
                 previousPayloadJson, newPayloadJson, actorId, changedAtUtc,
                 changeReason, policyVersion)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                request_id, window_id, version, new["version"],
                _json(previous) if previous else None, _json(new), actor["actorId"],
                now, payload.get("changeReason") or "OPERATING_WINDOW_REVIEW",
                payload["policyVersion"],
            ))
            columns = list(new)
            connection.execute(f"""
                INSERT INTO validated_operating_windows ({','.join(columns)})
                VALUES ({','.join('?' for _ in columns)})
                ON CONFLICT(windowId) DO UPDATE SET
                {','.join(f'{column}=excluded.{column}' for column in columns if column not in ('windowId','createdAtUtc'))}
            """, [new[column] for column in columns])
            connection.commit()
            return new
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


def provision_actor_offline(path, actor_id, display_name, role):
    store = MaintenanceValidationStore(path)
    store.initialize()
    return store.provision_actor(actor_id, display_name, role)


def backup_database(path=DEFAULT_DB_PATH, backup_dir=None):
    path = Path(path)
    backup_dir = Path(backup_dir or ROOT / "backup" / "maintenance-validations")
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    destination = backup_dir / f"aoki_maintenance_validations_{timestamp}.db"
    source_connection = sqlite3.connect(str(path))
    destination_connection = sqlite3.connect(str(destination))
    try:
        source_connection.backup(destination_connection)
        if destination_connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise StoreError("El respaldo no superó integrity_check")
    finally:
        destination_connection.close()
        source_connection.close()
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    manifest = destination.with_suffix(".json")
    manifest.write_text(_json({
        "file": destination.name,
        "size": destination.stat().st_size,
        "sha256": digest,
        "integrityCheck": "ok",
        "createdAtUtc": timestamp,
        "schemaVersion": SCHEMA_VERSION,
    }), encoding="utf-8")
    return destination
