import os
import csv
import math
import unicodedata
from pathlib import Path
from datetime import datetime, date, time, timedelta, timezone

from dotenv import load_dotenv

from db.samee200_db import get_conn

load_dotenv("/home/pi/SAMEE200/scr/.env")

TZ_COLOMBIA = timezone(timedelta(hours=-5))


def normalizar_columna(texto):
    if texto is None:
        return ""

    texto = str(texto).strip()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = texto.upper()
    texto = texto.replace("°", "")
    texto = texto.replace("º", "")
    texto = texto.replace("%", "PORCENTAJE")
    texto = texto.replace(".", "")
    texto = texto.replace("_", " ")
    texto = " ".join(texto.split())

    return texto


def init_produccion_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS produccion_periodo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT,
            fecha_hora_inicio_local TEXT NOT NULL,
            fecha_hora_fin_local TEXT NOT NULL,
            fecha_hora_inicio_utc INTEGER NOT NULL,
            fecha_hora_fin_utc INTEGER NOT NULL,
            linea TEXT,
            producto TEXT,
            envases_buenos REAL,
            envases_malos REAL,
            eficiencia REAL,
            turnos REAL,
            observaciones TEXT,
            fuente TEXT DEFAULT 'archivo',
            archivo_origen TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_produccion_periodo_unique
        ON produccion_periodo (
            fecha_hora_inicio_utc,
            fecha_hora_fin_utc,
            linea,
            producto
        )
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_produccion_periodo_rango
        ON produccion_periodo (
            fecha_hora_inicio_utc,
            fecha_hora_fin_utc
        )
    """)

    conn.commit()
    conn.close()


def excel_serial_a_datetime(valor):
    """
    Convierte serial Excel a datetime.
    Excel usa días desde 1899-12-30.
    """

    return datetime(1899, 12, 30) + timedelta(days=float(valor))


def parse_fecha(valor):
    if valor is None or valor == "":
        return None

    if isinstance(valor, datetime):
        return valor.date()

    if isinstance(valor, date):
        return valor

    if isinstance(valor, (int, float)):
        return excel_serial_a_datetime(valor).date()

    texto = str(valor).strip()

    formatos = [
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%m/%d/%Y",
        "%Y/%m/%d"
    ]

    for fmt in formatos:
        try:
            return datetime.strptime(texto, fmt).date()
        except Exception:
            pass

    return None


def parse_hora(valor):
    if valor is None or valor == "":
        return time(0, 0, 0)

    if isinstance(valor, datetime):
        return valor.time().replace(microsecond=0)

    if isinstance(valor, time):
        return valor.replace(microsecond=0)

    if isinstance(valor, (int, float)):
        segundos = int(round(float(valor) * 24 * 3600))
        segundos = segundos % (24 * 3600)

        h = segundos // 3600
        m = (segundos % 3600) // 60
        s = segundos % 60

        return time(h, m, s)

    texto = str(valor).strip()

    formatos = [
        "%H:%M:%S",
        "%H:%M",
        "%I:%M %p",
        "%I:%M:%S %p"
    ]

    for fmt in formatos:
        try:
            return datetime.strptime(texto, fmt).time()
        except Exception:
            pass

    return time(0, 0, 0)


def parse_numero(valor, default=0.0):
    if valor is None or valor == "":
        return default

    if isinstance(valor, (int, float)):
        if isinstance(valor, float) and math.isnan(valor):
            return default
        return float(valor)

    texto = str(valor).strip()
    texto = texto.replace("%", "")
    texto = texto.replace(".", "")
    texto = texto.replace(",", ".")

    try:
        return float(texto)
    except Exception:
        return default


def construir_periodo(fecha_valor, hora_inicio_valor, hora_fin_valor):
    fecha_base = parse_fecha(fecha_valor)

    if fecha_base is None:
        return None

    hora_inicio = parse_hora(hora_inicio_valor)
    hora_fin = parse_hora(hora_fin_valor)

    inicio_local = datetime.combine(fecha_base, hora_inicio).replace(tzinfo=TZ_COLOMBIA)
    fin_local = datetime.combine(fecha_base, hora_fin).replace(tzinfo=TZ_COLOMBIA)

    # Si termina igual o antes de la hora inicial, se interpreta como día siguiente.
    if fin_local <= inicio_local:
        fin_local = fin_local + timedelta(days=1)

    inicio_utc = int(inicio_local.astimezone(timezone.utc).timestamp())
    fin_utc = int(fin_local.astimezone(timezone.utc).timestamp())

    return {
        "fecha": fecha_base.isoformat(),
        "inicio_local": inicio_local.strftime("%Y-%m-%d %H:%M:%S"),
        "fin_local": fin_local.strftime("%Y-%m-%d %H:%M:%S"),
        "inicio_utc": inicio_utc,
        "fin_utc": fin_utc
    }


def mapear_fila(headers, values):
    fila = {}

    for idx, header in enumerate(headers):
        key = normalizar_columna(header)
        fila[key] = values[idx] if idx < len(values) else None

    return fila


def extraer_valor(fila, posibles):
    for nombre in posibles:
        key = normalizar_columna(nombre)

        if key in fila:
            return fila[key]

    return None


def importar_excel_produccion(ruta_archivo, linea="AOKI", producto="Botella_1L"):
    """
    Importa el formato enviado por producción:

        FECHA
        HORA INICIO
        HORA FINAL
        ENVASES BUENOS
        ENVASES MALOS
        % Eficiencia
        N° TURNOS
        OBSERVACIONES
    """

    try:
        from openpyxl import load_workbook
    except Exception:
        raise RuntimeError("Falta instalar openpyxl. Ejecuta: pip install openpyxl")

    init_produccion_db()

    ruta = Path(ruta_archivo)

    wb = load_workbook(ruta, data_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))

    if not rows:
        return {
            "ok": False,
            "error": "El archivo no contiene filas"
        }

    headers = list(rows[0])

    conn = get_conn()
    cur = conn.cursor()

    insertados = 0
    omitidos = 0
    errores = []

    for numero_fila, values in enumerate(rows[1:], start=2):
        if not values or all(v is None or v == "" for v in values):
            continue

        fila = mapear_fila(headers, list(values))

        fecha = extraer_valor(fila, ["FECHA"])
        hora_inicio = extraer_valor(fila, ["HORA INICIO", "HORA_INICIO"])
        hora_fin = extraer_valor(fila, ["HORA FINAL", "HORA FIN", "HORA_FINAL"])

        periodo = construir_periodo(fecha, hora_inicio, hora_fin)

        if periodo is None:
            errores.append(f"Fila {numero_fila}: fecha inválida")
            omitidos += 1
            continue

        envases_buenos = parse_numero(
            extraer_valor(fila, ["ENVASES BUENOS", "ENVASES_BUENOS"]),
            default=0
        )

        envases_malos = parse_numero(
            extraer_valor(fila, ["ENVASES MALOS", "ENVASES_MALOS"]),
            default=0
        )

        eficiencia = parse_numero(
            extraer_valor(fila, ["% EFICIENCIA", "EFICIENCIA", "PORCENTAJE EFICIENCIA"]),
            default=0
        )

        turnos = parse_numero(
            extraer_valor(fila, ["N° TURNOS", "N TURNOS", "NUMERO TURNOS", "TURNOS"]),
            default=0
        )

        observaciones = extraer_valor(fila, ["OBSERVACIONES", "OBSERVACION"])

        try:
            cur.execute("""
                INSERT INTO produccion_periodo (
                    fecha,
                    fecha_hora_inicio_local,
                    fecha_hora_fin_local,
                    fecha_hora_inicio_utc,
                    fecha_hora_fin_utc,
                    linea,
                    producto,
                    envases_buenos,
                    envases_malos,
                    eficiencia,
                    turnos,
                    observaciones,
                    fuente,
                    archivo_origen
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(
                    fecha_hora_inicio_utc,
                    fecha_hora_fin_utc,
                    linea,
                    producto
                )
                DO UPDATE SET
                    fecha = excluded.fecha,
                    fecha_hora_inicio_local = excluded.fecha_hora_inicio_local,
                    fecha_hora_fin_local = excluded.fecha_hora_fin_local,
                    envases_buenos = excluded.envases_buenos,
                    envases_malos = excluded.envases_malos,
                    eficiencia = excluded.eficiencia,
                    turnos = excluded.turnos,
                    observaciones = excluded.observaciones,
                    fuente = excluded.fuente,
                    archivo_origen = excluded.archivo_origen
            """, (
                periodo["fecha"],
                periodo["inicio_local"],
                periodo["fin_local"],
                periodo["inicio_utc"],
                periodo["fin_utc"],
                linea,
                producto,
                envases_buenos,
                envases_malos,
                eficiencia,
                turnos,
                str(observaciones or ""),
                "excel",
                ruta.name
            ))

            if cur.rowcount > 0:
                insertados += 1
            else:
                omitidos += 1

        except Exception as e:
            errores.append(f"Fila {numero_fila}: {e}")
            omitidos += 1

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "archivo": str(ruta),
        "insertados": insertados,
        "omitidos": omitidos,
        "errores": errores[:20]
    }


def importar_csv_produccion(ruta_archivo, linea="AOKI", producto="Botella_1L"):
    init_produccion_db()

    ruta = Path(ruta_archivo)

    with open(ruta, "r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(2048)
        f.seek(0)

        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=";,|\t")
            delimiter = dialect.delimiter
        except Exception:
            delimiter = ","

        reader = csv.reader(f, delimiter=delimiter)
        rows = list(reader)

    if not rows:
        return {
            "ok": False,
            "error": "El archivo CSV está vacío"
        }

    headers = rows[0]

    conn = get_conn()
    cur = conn.cursor()

    insertados = 0
    omitidos = 0
    errores = []

    for numero_fila, values in enumerate(rows[1:], start=2):
        if not values or all(v is None or v == "" for v in values):
            continue

        fila = mapear_fila(headers, values)

        fecha = extraer_valor(fila, ["FECHA"])
        hora_inicio = extraer_valor(fila, ["HORA INICIO", "HORA_INICIO"])
        hora_fin = extraer_valor(fila, ["HORA FINAL", "HORA FIN", "HORA_FINAL"])

        periodo = construir_periodo(fecha, hora_inicio, hora_fin)

        if periodo is None:
            errores.append(f"Fila {numero_fila}: fecha inválida")
            omitidos += 1
            continue

        envases_buenos = parse_numero(
            extraer_valor(fila, ["ENVASES BUENOS", "ENVASES_BUENOS"]),
            default=0
        )

        envases_malos = parse_numero(
            extraer_valor(fila, ["ENVASES MALOS", "ENVASES_MALOS"]),
            default=0
        )

        eficiencia = parse_numero(
            extraer_valor(fila, ["% EFICIENCIA", "EFICIENCIA", "PORCENTAJE EFICIENCIA"]),
            default=0
        )

        turnos = parse_numero(
            extraer_valor(fila, ["N° TURNOS", "N TURNOS", "NUMERO TURNOS", "TURNOS"]),
            default=0
        )

        observaciones = extraer_valor(fila, ["OBSERVACIONES", "OBSERVACION"])

        try:
            cur.execute("""
                INSERT OR IGNORE INTO produccion_periodo (
                    fecha,
                    fecha_hora_inicio_local,
                    fecha_hora_fin_local,
                    fecha_hora_inicio_utc,
                    fecha_hora_fin_utc,
                    linea,
                    producto,
                    envases_buenos,
                    envases_malos,
                    eficiencia,
                    turnos,
                    observaciones,
                    fuente,
                    archivo_origen
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                periodo["fecha"],
                periodo["inicio_local"],
                periodo["fin_local"],
                periodo["inicio_utc"],
                periodo["fin_utc"],
                linea,
                producto,
                envases_buenos,
                envases_malos,
                eficiencia,
                turnos,
                str(observaciones or ""),
                "csv",
                ruta.name
            ))

            if cur.rowcount > 0:
                insertados += 1
            else:
                omitidos += 1

        except Exception as e:
            errores.append(f"Fila {numero_fila}: {e}")
            omitidos += 1

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "archivo": str(ruta),
        "insertados": insertados,
        "omitidos": omitidos,
        "errores": errores[:20]
    }


def importar_archivo_produccion(ruta_archivo, linea="AOKI", producto="Botella_1L"):
    ruta = Path(ruta_archivo)
    ext = ruta.suffix.lower()

    if ext in [".xlsx", ".xlsm"]:
        return importar_excel_produccion(ruta, linea=linea, producto=producto)

    if ext in [".csv", ".txt"]:
        return importar_csv_produccion(ruta, linea=linea, producto=producto)

    return {
        "ok": False,
        "error": f"Extensión no soportada: {ext}"
    }


def obtener_produccion_periodos(inicio_utc=None, fin_utc=None):
    init_produccion_db()

    conn = get_conn()
    cur = conn.cursor()

    where = "1=1"
    params = []

    if inicio_utc is not None:
        where += " AND fecha_hora_fin_utc >= ?"
        params.append(int(inicio_utc))

    if fin_utc is not None:
        where += " AND fecha_hora_inicio_utc <= ?"
        params.append(int(fin_utc))

    cur.execute(f"""
        SELECT
            id,
            fecha,
            fecha_hora_inicio_local,
            fecha_hora_fin_local,
            fecha_hora_inicio_utc,
            fecha_hora_fin_utc,
            linea,
            producto,
            envases_buenos,
            envases_malos,
            eficiencia,
            turnos,
            observaciones,
            fuente,
            archivo_origen
        FROM produccion_periodo
        WHERE {where}
        ORDER BY fecha_hora_inicio_utc ASC
    """, params)

    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    return rows


def sumar_produccion_rango(inicio_utc, fin_utc):
    """
    Suma producción dentro de un rango.

    Si el rango corta parcialmente un periodo productivo, se prorratea
    según el porcentaje de traslape temporal.
    """

    periodos = obtener_produccion_periodos(inicio_utc, fin_utc)

    total_buenos = 0.0
    total_malos = 0.0
    total_horas_programadas = 0.0
    total_horas_productivas = 0.0
    total_periodos = 0

    detalle = []

    for p in periodos:
        p_ini = int(p["fecha_hora_inicio_utc"])
        p_fin = int(p["fecha_hora_fin_utc"])

        overlap_ini = max(int(inicio_utc), p_ini)
        overlap_fin = min(int(fin_utc), p_fin)

        if overlap_fin <= overlap_ini:
            continue

        duracion_periodo = max(p_fin - p_ini, 1)
        duracion_overlap = overlap_fin - overlap_ini
        factor = duracion_overlap / duracion_periodo

        buenos = float(p["envases_buenos"] or 0) * factor
        malos = float(p["envases_malos"] or 0) * factor
        horas_programadas = duracion_overlap / 3600

        eficiencia = float(p["eficiencia"] or 0)
        if eficiencia > 1:
            eficiencia /= 100
        eficiencia = min(max(eficiencia, 0), 1)

        horas_productivas = horas_programadas * eficiencia

        total_buenos += buenos
        total_malos += malos
        total_horas_programadas += horas_programadas
        total_horas_productivas += horas_productivas
        total_periodos += 1

        detalle.append({
            "id": p["id"],
            "inicio_local": p["fecha_hora_inicio_local"],
            "fin_local": p["fecha_hora_fin_local"],
            "factor_overlap": round(factor, 4),
            "envases_buenos_aplicados": round(buenos, 2),
            "envases_malos_aplicados": round(malos, 2),
            "horas_programadas": round(horas_programadas, 3),
            "horas_productivas": round(horas_productivas, 3)
        })

    total = total_buenos + total_malos

    eficiencia_calc = 0
    if total > 0:
        eficiencia_calc = total_buenos / total

    return {
        "envases_buenos": round(total_buenos, 2),
        "envases_malos": round(total_malos, 2),
        "envases_total": round(total, 2),
        "eficiencia_calc": round(eficiencia_calc, 5),
        "horas_programadas": round(total_horas_programadas, 3),
        "horas_productivas": round(total_horas_productivas, 3),
        "periodos_usados": total_periodos,
        "detalle": detalle
    }
