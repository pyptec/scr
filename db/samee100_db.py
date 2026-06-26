import sqlite3
import json
import csv
from datetime import datetime, timezone
from pathlib import Path


DB_PATH = Path("data/samee100.db")
SCHEMA_PATH = Path(__file__).with_name("schema.sql")
UNIDADES_CSV_PATH = Path(__file__).with_name("catalogos_unidades.csv")

def utc_now():
    return datetime.now(timezone.utc).isoformat()


def get_conn():
    """
    Abre la conexión SQLite oficial del proyecto SAMEE100/SAMEE200.

    La base oficial debe estar en:
        /home/pi/SAMEE100/scr/data/samee100.db

    Se activa WAL para permitir que el recolector escriba mientras
    el dashboard consulta datos o genera reportes Excel.
    """

    # Asegura que exista la carpeta data/
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH, timeout=30)

    # Permite acceder a columnas por nombre: row["campo"]
    conn.row_factory = sqlite3.Row

    # Modo recomendado para un sistema con un proceso escribiendo
    # y otro proceso leyendo/reportando.
    conn.execute("PRAGMA journal_mode=WAL;")

    # Reduce bloqueos y mejora desempeño en Raspberry.
    conn.execute("PRAGMA synchronous=NORMAL;")

    # Espera hasta 30 segundos si la base está ocupada.
    conn.execute("PRAGMA busy_timeout=30000;")

    # Activa llaves foráneas si el esquema las usa.
    conn.execute("PRAGMA foreign_keys=ON;")

    return conn

def asegurar_columnas_unidades(conn):
    """
    Asegura compatibilidad con bases antiguas donde la tabla unidades
    no tenía la columna description.
    """

    cur = conn.cursor()

    cur.execute("PRAGMA table_info(unidades)")
    columnas = [row["name"] for row in cur.fetchall()]

    if "description" not in columnas:
        cur.execute("""
        ALTER TABLE unidades
        ADD COLUMN description TEXT
        """)

        cur.execute("""
        UPDATE unidades
        SET description = name
        WHERE description IS NULL
           OR TRIM(description) = ''
        """)

        print("[SQLITE] Columna description agregada a tabla unidades.")


def cargar_unidades_desde_csv(conn):
    """
    Carga el catálogo de unidades desde:
        db/catalogos_unidades.csv

    Formato esperado:
        UnitId;Name;Simbol

    No borra datos existentes.
    Si una unidad ya existe, actualiza nombre, símbolo y descripción.
    """

    if not UNIDADES_CSV_PATH.exists():
        print(f"[SQLITE] No existe catálogo de unidades: {UNIDADES_CSV_PATH}")
        return

    cur = conn.cursor()

    with open(UNIDADES_CSV_PATH, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")

        for row in reader:
            try:
                unit_id = int(str(row.get("UnitId", "")).strip())
            except Exception:
                continue

            name = str(row.get("Name", "")).strip()
            simbol = str(row.get("Simbol", "")).strip()

            if not name:
                name = f"Unit {unit_id}"

            cur.execute("""
            INSERT INTO unidades (
                unit_id,
                name,
                simbol,
                description
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(unit_id) DO UPDATE SET
                name = excluded.name,
                simbol = excluded.simbol,
                description = excluded.description
            """, (
                unit_id,
                name,
                simbol,
                name
            ))


def cargar_catalogos_base(conn):
    """
    Carga catálogos base necesarios para operar.

    - Gateways conocidos.
    - Dispositivos conocidos.
    - Unidades desde db/catalogos_unidades.csv.
    """

    cur = conn.cursor()

    cur.execute("""
    INSERT OR IGNORE INTO gateways (
        gateway_id,
        nombre,
        tipo,
        ubicacion,
        cliente
    )
    VALUES (
        8,
        'SAMEE100-ALKOSTO',
        'Gateway energético',
        'Tablero solar',
        'ALKOSTO'
    )
    """)

    cur.executemany("""
    INSERT OR IGNORE INTO dispositivos (
        device_id,
        gateway_id,
        nombre,
        tipo,
        ubicacion
    )
    VALUES (?, ?, ?, ?, ?)
    """, [
        (31, 8, 'Eastron SDM630', 'Medidor eléctrico trifásico', 'Tablero solar'),
        (7,  8, 'SHT20', 'Sensor temperatura y humedad', 'Gabinete SAMEE100'),
        (13, 8, 'Sistema SAMEE100', 'Variables internas del gateway', 'Raspberry Pi / Gateway')
    ])

    cargar_unidades_desde_csv(conn)


def asegurar_catalogos_detalle(cur, gateway_id=None, device_id=None, unit_id=None):
    """
    Asegura las referencias antes de insertar en mediciones_detalle.

    Evita:
        FOREIGN KEY constraint failed

    Si llega una unidad nueva no incluida en el CSV, se crea como Unit <id>.
    Si llega un gateway nuevo, se crea automáticamente.
    Si llega un device nuevo, se crea automáticamente.
    """

    if gateway_id not in [None, "", "None"]:
        try:
            gateway_id_int = int(gateway_id)

            cur.execute("""
            INSERT OR IGNORE INTO gateways (
                gateway_id,
                nombre,
                tipo,
                ubicacion,
                cliente
            )
            VALUES (?, ?, ?, ?, ?)
            """, (
                gateway_id_int,
                f"Gateway {gateway_id_int}",
                "Gateway detectado automáticamente",
                "Sin ubicación",
                "Sin cliente"
            ))
        except Exception:
            pass

    if device_id not in [None, "", "None"]:
        try:
            device_id_int = int(device_id)

            cur.execute("""
            INSERT OR IGNORE INTO dispositivos (
                device_id,
                gateway_id,
                nombre,
                tipo,
                ubicacion
            )
            VALUES (?, ?, ?, ?, ?)
            """, (
                device_id_int,
                None,
                f"Device {device_id_int}",
                "Dispositivo detectado automáticamente",
                "Sin ubicación"
            ))
        except Exception:
            pass

    if unit_id not in [None, "", "None"]:
        try:
            unit_id_int = int(unit_id)

            cur.execute("""
            INSERT OR IGNORE INTO unidades (
                unit_id,
                name,
                simbol,
                description
            )
            VALUES (?, ?, ?, ?)
            """, (
                unit_id_int,
                f"Unit {unit_id_int}",
                "",
                "Unidad detectada automáticamente"
            ))
        except Exception:
            pass

def init_db():
    """
    Inicializa la base local.

    - Crea carpeta data/ si no existe.
    - Ejecuta schema.sql.
    - Aplica migraciones compatibles con bases antiguas.
    - Carga gateways, dispositivos y unidades desde catálogo CSV.
    """

    conn = get_conn()

    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    conn.executescript(schema_sql)

    asegurar_columnas_unidades(conn)

    cargar_catalogos_base(conn)

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

                asegurar_catalogos_detalle(
                    cur,
                    gateway_id=gateway_det,
                    device_id=device_det,
                    unit_id=unit_id_int
                )

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
    
    
def contar_pendientes():
    """
    Cuenta eventos pendientes en la cola AWS.
    """

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    SELECT COUNT(*) AS total
    FROM aws_queue
    WHERE status = 'pending'
    """)

    row = cur.fetchone()
    conn.close()

    return row["total"] if row else 0


def resumen_cola_aws():
    """
    Retorna un resumen de la cola AWS agrupado por estado.
    Útil para diagnóstico, dashboard o logs.
    """

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    SELECT
        status,
        COUNT(*) AS total
    FROM aws_queue
    GROUP BY status
    ORDER BY status
    """)

    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    return rows


def obtener_pendientes_reintento(limit=50, max_attempts=20):
    """
    Obtiene eventos pendientes que todavía no superan el máximo
    de intentos permitidos.
    """

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    SELECT *
    FROM aws_queue
    WHERE status = 'pending'
      AND attempts < ?
    ORDER BY id ASC
    LIMIT ?
    """, (
        max_attempts,
        limit
    ))

    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    return rows


def descartar_eventos_agotados(max_attempts=20):
    """
    Marca como descartados los eventos que ya superaron el número
    máximo de intentos de envío.
    No los elimina, solo cambia el estado a discarded.
    """

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    UPDATE aws_queue
    SET status = 'discarded',
        last_error = COALESCE(last_error, 'Máximo número de intentos alcanzado')
    WHERE status = 'pending'
      AND attempts >= ?
    """, (
        max_attempts,
    ))

    afectados = cur.rowcount

    conn.commit()
    conn.close()

    return afectados


def limpiar_enviados_antiguos(dias=7):
    """
    Elimina eventos enviados antiguos para evitar crecimiento excesivo
    de la base local.

    Por defecto elimina eventos con status='sent' enviados hace más de 7 días.
    """

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    DELETE FROM aws_queue
    WHERE status = 'sent'
      AND sent_at IS NOT NULL
      AND datetime(sent_at) < datetime('now', ?)
    """, (
        f'-{int(dias)} days',
    ))

    eliminados = cur.rowcount

    conn.commit()
    conn.close()

    return eliminados


def obtener_ultimo_error_cola():
    """
    Retorna el último error registrado en la cola AWS.
    """

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    SELECT
        id,
        topic,
        attempts,
        last_error,
        created_at
    FROM aws_queue
    WHERE last_error IS NOT NULL
      AND TRIM(last_error) <> ''
    ORDER BY id DESC
    LIMIT 1
    """)

    row = cur.fetchone()
    conn.close()

    return dict(row) if row else None

