import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path


DB_PATH = Path("data/samee100.db")
SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()

    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    conn.executescript(schema_sql)

    conn.commit()
    conn.close()


def extraer_origen_item(item, device_id_respaldo=None):
    """
    Detecta el origen de una medición.

    Caso 1:
    Payload de gateway:
        {
            "t": "...",
            "i": 8,
            "v": [...],
            "u": [...]
        }

        gateway_id  = 8
        device_id   = None
        source_type = gateway

    Caso 2:
    Payload de dispositivo:
        {
            "t": "...",
            "g": 31,
            "v": [...],
            "u": [...]
        }

        gateway_id  = None
        device_id   = 31
        source_type = device

    El gateway de los dispositivos se resuelve después por JOIN
    usando la tabla dispositivos.
    """

    gateway_id = None
    device_id = None
    source_type = "unknown"

    if not isinstance(item, dict):
        return gateway_id, device_id, source_type

    if "i" in item:
        try:
            gateway_id = int(item.get("i"))
        except Exception:
            gateway_id = None

        device_id = None
        source_type = "gateway"

    elif "g" in item:
        try:
            device_id = str(item.get("g"))
        except Exception:
            device_id = None

        gateway_id = None
        source_type = "device"

    else:
        if device_id_respaldo not in [None, "", "None"]:
            device_id = str(device_id_respaldo)

        gateway_id = None
        source_type = "unknown"

    return gateway_id, device_id, source_type


def guardar_medicion(payload, device_id=None, sent_aws=0):
    if isinstance(payload, dict):
        payload_json = json.dumps(payload)
    else:
        payload_json = str(payload)

    timestamp_utc = utc_now()
    device_id_raw = device_id
    gateway_id_raw = None
    source_type_raw = "unknown"

    try:
        data = json.loads(payload_json)
        d = data.get("d", [])

        if d and isinstance(d[0], dict):
            item = d[0]
            timestamp_utc = item.get("t", timestamp_utc)

            gateway_id_raw, device_id_raw, source_type_raw = extraer_origen_item(
                item,
                device_id
            )

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
        device_id_raw,
        payload_json,
        int(sent_aws),
        utc_now()
    ))

    medicion_id = cur.lastrowid

    # Normalizar v[] y u[] en mediciones_detalle
    try:
        data = json.loads(payload_json)
        d = data.get("d", [])

        if d and isinstance(d[0], dict):
            item = d[0]

            timestamp_det = item.get("t", timestamp_utc)

            gateway_det, device_det, source_type = extraer_origen_item(
                item,
                device_id_raw
            )

            valores = item.get("v", [])
            unidades = item.get("u", [])

            for valor, unit_id in zip(valores, unidades):
                if valor in [None, "", "None"]:
                    continue

                try:
                    valor_float = float(valor)
                    unit_id_int = int(unit_id)
                except Exception:
                    continue

                cur.execute("""
                INSERT INTO mediciones_detalle (
                    raw_id,
                    timestamp_utc,
                    gateway_id,
                    device_id,
                    source_type,
                    unit_id,
                    valor,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    medicion_id,
                    timestamp_det,
                    gateway_det,
                    device_det,
                    source_type,
                    unit_id_int,
                    valor_float,
                    utc_now()
                ))

    except Exception as e:
        print(f"[SQLITE] Error normalizando medicion detalle: {e}")

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