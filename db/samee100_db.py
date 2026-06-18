import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path


DB_PATH = Path("data/samee100.db")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS mediciones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp_utc TEXT NOT NULL,
        device_id TEXT,
        payload_json TEXT NOT NULL,
        sent_aws INTEGER DEFAULT 0,
        sent_at TEXT,
        created_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS aws_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        medicion_id INTEGER,
        topic TEXT,
        payload_json TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        attempts INTEGER DEFAULT 0,
        last_error TEXT,
        created_at TEXT NOT NULL,
        sent_at TEXT,
        FOREIGN KEY(medicion_id) REFERENCES mediciones(id)
    )
    """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_mediciones_time
    ON mediciones(timestamp_utc)
    """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_queue_status
    ON aws_queue(status)
    """)

    conn.commit()
    conn.close()


def guardar_medicion(payload, device_id=None, sent_aws=0):
    """
    Guarda cualquier payload JSON enviado a AWS.
    El payload puede venir como dict o como string JSON.
    """

    if isinstance(payload, dict):
        payload_json = json.dumps(payload)
    else:
        payload_json = str(payload)

    timestamp_utc = utc_now()

    try:
        data = json.loads(payload_json)
        d = data.get("d", [])
        if d and isinstance(d[0], dict):
            timestamp_utc = d[0].get("t", timestamp_utc)
            device_id = device_id or str(d[0].get("g", ""))
    except Exception:
        pass

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO mediciones (
        timestamp_utc,
        device_id,
        payload_json,
        sent_aws,
        created_at
    )
    VALUES (?, ?, ?, ?, ?)
    """, (
        timestamp_utc,
        device_id,
        payload_json,
        int(sent_aws),
        utc_now()
    ))

    medicion_id = cur.lastrowid
    conn.commit()
    conn.close()

    return medicion_id


def agregar_a_cola(payload, topic=None, medicion_id=None):
    if isinstance(payload, dict):
        payload_json = json.dumps(payload)
    else:
        payload_json = str(payload)

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO aws_queue (
        medicion_id,
        topic,
        payload_json,
        status,
        attempts,
        created_at
    )
    VALUES (?, ?, ?, 'pending', 0, ?)
    """, (
        medicion_id,
        topic,
        payload_json,
        utc_now()
    ))

    queue_id = cur.lastrowid
    conn.commit()
    conn.close()

    return queue_id


def obtener_pendientes(limit=50):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    SELECT *
    FROM aws_queue
    WHERE status = 'pending'
    ORDER BY id ASC
    LIMIT ?
    """, (limit,))

    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    return rows


def marcar_enviado(queue_id, medicion_id=None):
    conn = get_conn()
    cur = conn.cursor()
    now = utc_now()

    cur.execute("""
    UPDATE aws_queue
    SET status = 'sent',
        sent_at = ?
    WHERE id = ?
    """, (now, queue_id))

    if medicion_id:
        cur.execute("""
        UPDATE mediciones
        SET sent_aws = 1,
            sent_at = ?
        WHERE id = ?
        """, (now, medicion_id))

    conn.commit()
    conn.close()


def marcar_error(queue_id, error):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    UPDATE aws_queue
    SET attempts = attempts + 1,
        last_error = ?
    WHERE id = ?
    """, (str(error), queue_id))

    conn.commit()
    conn.close()