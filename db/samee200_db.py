import os
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

from dotenv import load_dotenv
import util

load_dotenv("/home/pi/SAMEE200/scr/.env")

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "samee200.db"


def get_db_path():
    return os.getenv("DB_PATH", str(DEFAULT_DB_PATH))


def get_conn():
    db_path = Path(get_db_path())
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    conn.execute("PRAGMA foreign_keys=ON;")

    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS gateways (
            gateway_id INTEGER PRIMARY KEY,
            nombre TEXT,
            tipo TEXT,
            ubicacion TEXT,
            cliente TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS dispositivos (
            device_id INTEGER PRIMARY KEY,
            gateway_id INTEGER,
            nombre TEXT,
            tipo TEXT,
            ubicacion TEXT,
            rol TEXT,
            source_type TEXT DEFAULT 'device',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(gateway_id) REFERENCES gateways(gateway_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS unidades (
            unit_id INTEGER PRIMARY KEY,
            name TEXT,
            alias TEXT,
            simbol TEXT,
            descripcion TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS mediciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp_utc INTEGER,
            gateway_id INTEGER,
            device_id TEXT,
            source_type TEXT,
            origen TEXT,
            payload_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS mediciones_detalle (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            medicion_id INTEGER,
            timestamp_utc INTEGER,
            gateway_id INTEGER,
            device_id TEXT,
            source_type TEXT,
            unit_id INTEGER,
            valor TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(medicion_id) REFERENCES mediciones(id),
            FOREIGN KEY(unit_id) REFERENCES unidades(unit_id)
        )
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_mediciones_detalle_ts
        ON mediciones_detalle(timestamp_utc)
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_mediciones_detalle_unit
        ON mediciones_detalle(unit_id)
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_mediciones_detalle_device
        ON mediciones_detalle(device_id)
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_mediciones_detalle_gateway
        ON mediciones_detalle(gateway_id)
    """)

    # Producción para línea base ISO 50001 / EnPI
    cur.execute("""
        CREATE TABLE IF NOT EXISTS produccion_diaria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            linea TEXT,
            producto TEXT,
            envases INTEGER,
            fuente TEXT DEFAULT 'simulado',
            observacion TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Modelos de línea base energética
    cur.execute("""
        CREATE TABLE IF NOT EXISTS linea_base_energia (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre_modelo TEXT,
            fecha_inicio_base TEXT,
            fecha_fin_base TEXT,
            variable_dependiente TEXT,
            variable_independiente TEXT,
            beta0 REAL,
            beta1 REAL,
            r2 REAL,
            mae REAL,
            rmse REAL,
            activo INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Mantenimiento: MTBF, MTTR, disponibilidad
    cur.execute("""
        CREATE TABLE IF NOT EXISTS eventos_mantenimiento (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipo TEXT,
            tipo_evento TEXT,
            fecha_inicio_utc INTEGER,
            fecha_fin_utc INTEGER,
            duracion_min REAL,
            causa TEXT,
            accion TEXT,
            responsable TEXT,
            afecta_disponibilidad INTEGER DEFAULT 1,
            observacion TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Alertas automáticas
    cur.execute("""
        CREATE TABLE IF NOT EXISTS alertas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp_utc INTEGER,
            gateway_id INTEGER,
            device_id TEXT,
            unit_id INTEGER,
            tipo_alerta TEXT,
            severidad TEXT,
            valor TEXT,
            umbral TEXT,
            mensaje TEXT,
            estado TEXT DEFAULT 'activa',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


def registrar_gateway_dispositivo_desde_config(config):
    if not isinstance(config, dict):
        return

    enabled = config.get("enabled", True)

    if str(enabled).lower().strip() in ["false", "0", "no", "off"]:
        return

    source_type = str(config.get("source_type", "device")).lower().strip()

    gateway_cfg = config.get("gateway", {}) or {}
    device_cfg = config.get("device", {}) or {}

    gateway_id = (
        gateway_cfg.get("gateway_id")
        or config.get("gateway_id")
        or config.get("i")
    )

    if source_type == "gateway":
        device_id = None
    else:
        device_id = (
            device_cfg.get("device_id")
            or config.get("id_device")
            or config.get("device_id")
        )

    conn = get_conn()
    cur = conn.cursor()

    try:
        gateway_id_int = None

        if gateway_id not in [None, "", "None"]:
            gateway_id_int = int(gateway_id)

            cur.execute("""
                INSERT INTO gateways (
                    gateway_id,
                    nombre,
                    tipo,
                    ubicacion,
                    cliente,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(gateway_id) DO UPDATE SET
                    nombre = excluded.nombre,
                    tipo = excluded.tipo,
                    ubicacion = excluded.ubicacion,
                    cliente = excluded.cliente,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                gateway_id_int,
                gateway_cfg.get("nombre", f"Gateway {gateway_id_int}"),
                gateway_cfg.get("tipo", "Gateway"),
                gateway_cfg.get("ubicacion", ""),
                gateway_cfg.get("cliente", "")
            ))

        if device_id not in [None, "", "None"]:
            device_id_int = int(device_id)

            cur.execute("""
                INSERT INTO dispositivos (
                    device_id,
                    gateway_id,
                    nombre,
                    tipo,
                    ubicacion,
                    rol,
                    source_type,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(device_id) DO UPDATE SET
                    gateway_id = excluded.gateway_id,
                    nombre = excluded.nombre,
                    tipo = excluded.tipo,
                    ubicacion = excluded.ubicacion,
                    rol = excluded.rol,
                    source_type = excluded.source_type,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                device_id_int,
                gateway_id_int,
                device_cfg.get("nombre", f"Device {device_id_int}"),
                device_cfg.get("tipo", "Dispositivo"),
                device_cfg.get("ubicacion", ""),
                device_cfg.get("rol", ""),
                source_type
            ))

        conn.commit()

    except Exception as e:
        print(f"[SQLITE] Error registrando gateway/dispositivo: {e}")

    finally:
        conn.close()


def registrar_unidades_desde_config(config):
    if not isinstance(config, dict):
        return

    registers = config.get("registers", []) or []

    conn = get_conn()
    cur = conn.cursor()

    try:
        for reg in registers:
            unit_id = reg.get("unit")

            if unit_id in [None, "", "None"]:
                continue

            try:
                unit_id_int = int(unit_id)
            except Exception:
                continue

            name = reg.get("name", f"Unit {unit_id_int}")
            alias = reg.get("alias", "")
            simbol = (
                reg.get("simbol")
                or reg.get("symbol")
                or reg.get("unidad")
                or ""
            )

            cur.execute("""
                INSERT INTO unidades (
                    unit_id,
                    name,
                    alias,
                    simbol,
                    descripcion,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(unit_id) DO UPDATE SET
                    name = excluded.name,
                    alias = excluded.alias,
                    simbol = excluded.simbol,
                    descripcion = excluded.descripcion,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                unit_id_int,
                name,
                alias,
                simbol,
                reg.get("description", "")
            ))

        conn.commit()

    except Exception as e:
        print(f"[SQLITE] Error registrando unidades desde YAML: {e}")

    finally:
        conn.close()


def cargar_catalogos_desde_env():
    configs_activas = os.getenv("CONFIGS_ACTIVAS", "")

    if not configs_activas.strip():
        print("[SQLITE] CONFIGS_ACTIVAS no está definido en .env")
        return

    for cfg_name in configs_activas.split(","):
        cfg_name = cfg_name.strip()

        if not cfg_name:
            continue

        cfg_path = os.getenv(cfg_name)
        cfg_section = os.getenv(f"{cfg_name}_SECTION")

        if not cfg_path or not cfg_section:
            print(f"[SQLITE] Config incompleta: {cfg_name}")
            continue

        try:
            config = util.cargar_configuracion(cfg_path, cfg_section)

            if not isinstance(config, dict):
                print(f"[SQLITE] YAML inválido: {cfg_path} / {cfg_section}")
                continue

            registrar_gateway_dispositivo_desde_config(config)
            registrar_unidades_desde_config(config)

            print(f"[SQLITE] Catálogo cargado: {cfg_name} -> {cfg_path} / {cfg_section}")

        except Exception as e:
            print(f"[SQLITE] Error cargando {cfg_name}: {e}")


def resolver_gateway_por_device(device_id):
    if device_id in [None, "", "None"]:
        return None

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT gateway_id
        FROM dispositivos
        WHERE device_id = ?
        LIMIT 1
    """, (int(device_id),))

    row = cur.fetchone()
    conn.close()

    if not row:
        return None

    return row["gateway_id"]


def guardar_medicion(payload, origen=""):
    """
    Guarda payload tipo:
        {"d":[{"t":"...","g":24,"v":[...],"u":[...]}]}

    También soporta gateway:
        {"d":[{"t":"...","i":10,"v":[...],"u":[...]}]}
    """

    if payload is None:
        return False

    if isinstance(payload, str):
        try:
            data = json.loads(payload)
        except Exception as e:
            print(f"[SQLITE] Payload inválido JSON en {origen}: {e}")
            return False
    elif isinstance(payload, dict):
        data = payload
    else:
        print(f"[SQLITE] Payload tipo no soportado en {origen}: {type(payload)}")
        return False

    if "d" not in data or not isinstance(data["d"], list):
        print(f"[SQLITE] Payload sin campo d en {origen}")
        return False

    conn = get_conn()
    cur = conn.cursor()

    try:
        payload_json = json.dumps(data, ensure_ascii=False)

        for item in data["d"]:
            timestamp_utc = item.get("t")

            try:
                timestamp_utc = int(float(timestamp_utc))
            except Exception:
                timestamp_utc = int(datetime.now(timezone.utc).timestamp())

            device_id = item.get("g")
            gateway_id = item.get("i")

            if gateway_id not in [None, "", "None"]:
                source_type = "gateway"
                gateway_id_int = int(gateway_id)
                device_id_txt = ""
            else:
                source_type = "device"
                device_id_txt = str(device_id) if device_id not in [None, "", "None"] else ""
                gateway_id_resuelto = resolver_gateway_por_device(device_id_txt)
                gateway_id_int = int(gateway_id_resuelto) if gateway_id_resuelto is not None else None

            valores = item.get("v", []) or []
            unidades = item.get("u", []) or []

            cur.execute("""
                INSERT INTO mediciones (
                    timestamp_utc,
                    gateway_id,
                    device_id,
                    source_type,
                    origen,
                    payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                timestamp_utc,
                gateway_id_int,
                device_id_txt,
                source_type,
                origen,
                payload_json
            ))

            medicion_id = cur.lastrowid

            for valor, unit_id in zip(valores, unidades):
                try:
                    unit_id_int = int(unit_id)
                except Exception:
                    continue

                cur.execute("""
                    INSERT INTO mediciones_detalle (
                        medicion_id,
                        timestamp_utc,
                        gateway_id,
                        device_id,
                        source_type,
                        unit_id,
                        valor
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    medicion_id,
                    timestamp_utc,
                    gateway_id_int,
                    device_id_txt,
                    source_type,
                    unit_id_int,
                    str(valor)
                ))

        conn.commit()
        return True

    except Exception as e:
        conn.rollback()
        print(f"[SQLITE] Error guardando medición {origen}: {e}")
        return False

    finally:
        conn.close()