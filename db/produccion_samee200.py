import os
import csv
import hashlib
import math
import re
import unicodedata
from pathlib import Path
from datetime import datetime, date, time, timedelta, timezone

from dotenv import load_dotenv

from db.samee200_db import get_conn

load_dotenv("/home/pi/SAMEE200/scr/.env")

TZ_COLOMBIA = timezone(timedelta(hours=-5))


PATRON_MENCION_PARADA = re.compile(
    r"\b(?:"
    r"se\s+(?:para|detiene)(?:\s+(?:la\s+)?m[aá]quina)?"
    r"|(?:la\s+)?m[aá]quina\s+(?:parada|detenida)"
    r"|parada"
    r")\b",
    re.IGNORECASE,
)
PATRON_HORA = re.compile(
    r"\ba\s+la(?:s)?\s+(?P<hora>[01]?\d|2[0-3]):(?P<minuto>[0-5]\d)",
    re.IGNORECASE,
)
PATRON_REINICIO = re.compile(
    r"\b(?:se\s+)?(?:inicia|reinicia|reibicia|arranca|reanuda)"
    r"(?:\s+(?:la\s+)?m[aá]quina|\s+producci[oó]n)?\b",
    re.IGNORECASE,
)
PATRON_DURACION_PARADA = re.compile(
    r"(?P<duracion>\d+(?:[.,]\d+)?)\s*(?:minutos?|min\b)",
    re.IGNORECASE,
)
PATRONES_CAUSA = (
    (re.compile(r"\bfalta\s+de\s+(?:materia\s+prima|material)\b", re.IGNORECASE), "falta de material"),
    (re.compile(r"\bcambio\s+de\s+molde\b", re.IGNORECASE), "cambio de molde"),
    (re.compile(r"\blimpieza\b", re.IGNORECASE), "limpieza"),
    (re.compile(r"\bmantenimiento\b", re.IGNORECASE), "mantenimiento"),
    (re.compile(r"\bajustes?\b", re.IGNORECASE), "ajuste"),
    (re.compile(r"\bfallas?\b", re.IGNORECASE), "falla"),
)


def _normalizar_texto_evento(texto):
    texto = unicodedata.normalize("NFD", str(texto or ""))
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return " ".join(texto.casefold().split())


def _hora_normalizada(match):
    if match is None:
        return None
    return f"{int(match.group('hora')):02d}:{match.group('minuto')}"


def _minutos_hora(valor):
    hora, minuto = valor.split(":")
    return int(hora) * 60 + int(minuto)


def _extraer_causa(texto):
    for patron, causa in PATRONES_CAUSA:
        if patron.search(texto):
            return causa
    return None


def _event_id(fecha, posicion, inicio, fin, duracion, texto):
    payload = "|".join((
        str(fecha or ""), str(posicion), str(inicio or ""), str(fin or ""),
        str(duracion if duracion is not None else ""), _normalizar_texto_evento(texto),
    ))
    return f"reported-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:20]}"


def _evento_parada(fecha, observacion, fragmento, posicion):
    reinicio = PATRON_REINICIO.search(fragmento)
    limite_inicio = reinicio.start() if reinicio else len(fragmento)
    inicio_match = PATRON_HORA.search(fragmento, 0, limite_inicio)
    fin_match = PATRON_HORA.search(fragmento, reinicio.end()) if reinicio else None
    duracion_match = PATRON_DURACION_PARADA.search(fragmento)

    inicio = _hora_normalizada(inicio_match)
    fin = _hora_normalizada(fin_match)
    duracion_explicita = None
    if duracion_match:
        duracion_explicita = float(duracion_match.group("duracion").replace(",", "."))
        if duracion_explicita.is_integer():
            duracion_explicita = int(duracion_explicita)

    crosses_midnight = False
    duracion_intervalo = None
    if inicio is not None and fin is not None:
        inicio_minutos = _minutos_hora(inicio)
        fin_minutos = _minutos_hora(fin)
        if fin_minutos < inicio_minutos:
            fin_minutos += 24 * 60
            crosses_midnight = True
        duracion_intervalo = fin_minutos - inicio_minutos

    if duracion_intervalo is not None:
        duracion = duracion_intervalo
        fuente_temporal = "START_END"
    elif duracion_explicita is not None:
        duracion = duracion_explicita
        fuente_temporal = "EXPLICIT_DURATION"
    elif inicio is not None or fin is not None:
        duracion = None
        fuente_temporal = "PARTIAL_TIME"
    else:
        duracion = None
        fuente_temporal = "TEXT_ONLY"

    if duracion is not None and 0 < duracion <= 24 * 60:
        estado = "VALID"
    elif duracion is not None:
        estado = "PENDING_REVIEW"
    elif inicio is not None or fin is not None:
        estado = "PARTIAL"
    else:
        estado = "PENDING_REVIEW"

    return {
        "eventId": _event_id(fecha, posicion, inicio, fin, duracion, observacion),
        "productionDate": fecha,
        # Alias temporal para consumidores históricos; productionDate es el campo canónico.
        "date": fecha,
        "startTime": inicio,
        "endTime": fin,
        "durationMinutes": duracion,
        "crossesMidnight": crosses_midnight,
        "rawText": observacion,
        "matchedText": fragmento.strip(" \t\r\n.;"),
        "cause": _extraer_causa(fragmento),
        "temporalSource": fuente_temporal,
        "status": estado,
    }


def extraer_paradas_reportadas(observacion, fecha=None):
    """Normaliza menciones de parada sin inventar componentes temporales."""
    texto_original = "" if observacion is None else str(observacion)
    if not texto_original.strip():
        return []

    menciones = list(PATRON_MENCION_PARADA.finditer(texto_original))
    candidatos = []
    for indice, mencion in enumerate(menciones):
        fin = menciones[indice + 1].start() if indice + 1 < len(menciones) else len(texto_original)
        if indice + 1 < len(menciones):
            inicio_linea_siguiente = texto_original.rfind("\n", mencion.end(), fin) + 1
            prefijo_siguiente = texto_original[inicio_linea_siguiente:fin]
            if re.fullmatch(r"\s*T\d+\s*", prefijo_siguiente, re.IGNORECASE):
                fin = inicio_linea_siguiente
        fragmento = texto_original[mencion.start():fin]
        candidatos.append(_evento_parada(fecha, texto_original, fragmento, mencion.start()))

    eventos = []
    vistos = set()
    for evento in candidatos:
        clave = (
            evento["productionDate"], evento["startTime"], evento["endTime"],
            evento["durationMinutes"], _normalizar_texto_evento(evento["matchedText"]),
        )
        if clave not in vistos:
            vistos.add(clave)
            eventos.append(evento)
    return eventos


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


def calcular_modulo_produccion(periodos, inicio_utc, fin_utc):
    """Calcula indicadores de producción sin usar la eficiencia importada.

    La extracción de duraciones desde observaciones pertenece a la subfase 1.3.
    Por ello, una observación no vacía deja la parada y sus indicadores derivados
    pendientes de revisión en vez de asumir cero minutos.
    """
    inicio_utc = int(inicio_utc)
    fin_utc = int(fin_utc)
    if fin_utc <= inicio_utc:
        raise ValueError("El fin del periodo debe ser posterior al inicio")

    diarios = {}
    total_buenos = 0.0
    total_malos = 0.0
    total_horas_programadas = 0.0
    total_parada_minutos = 0.0
    hay_paradas_pendientes = False

    for periodo in periodos:
        periodo_inicio = int(periodo["fecha_hora_inicio_utc"])
        periodo_fin = int(periodo["fecha_hora_fin_utc"])
        overlap_inicio = max(inicio_utc, periodo_inicio)
        overlap_fin = min(fin_utc, periodo_fin)
        if overlap_fin <= overlap_inicio or periodo_fin <= periodo_inicio:
            continue

        factor = (overlap_fin - overlap_inicio) / (periodo_fin - periodo_inicio)
        buenos = max(float(periodo.get("envases_buenos") or 0), 0) * factor
        malos = max(float(periodo.get("envases_malos") or 0), 0) * factor
        total = buenos + malos
        horas_programadas = (overlap_fin - overlap_inicio) / 3600
        observaciones = str(periodo.get("observaciones") or "").strip()
        eventos_parada = extraer_paradas_reportadas(observaciones, periodo.get("fecha"))
        parada_pendiente = any(e["status"] != "VALID" for e in eventos_parada)
        # Una duración sin ubicación temporal no se distribuye en un corte parcial.
        if factor < 1 and eventos_parada:
            parada_pendiente = True
        minutos_parada = None if parada_pendiente else sum(
            float(e["durationMinutes"] or 0) for e in eventos_parada
        )
        if minutos_parada is not None and minutos_parada > horas_programadas * 60:
            parada_pendiente = True
            minutos_parada = None
        horas_reales = None if parada_pendiente else horas_programadas
        if horas_reales is not None:
            horas_reales = max(horas_programadas - minutos_parada / 60, 0)
        buenos_hora = buenos / horas_reales if horas_reales and horas_reales > 0 else None

        total_buenos += buenos
        total_malos += malos
        total_horas_programadas += horas_programadas
        if parada_pendiente:
            hay_paradas_pendientes = True
        else:
            total_parada_minutos += minutos_parada

        fecha = periodo.get("fecha") or "Sin fecha"
        diario = diarios.setdefault(fecha, {
            "fecha": fecha, "envases_buenos": 0.0, "envases_malos": 0.0,
            "turnos": 0.0, "horas_programadas": 0.0,
            "minutos_parada": 0.0, "parada_pendiente": False,
            "observaciones": [],
            "eventos_parada": [],
        })
        diario["envases_buenos"] += buenos
        diario["envases_malos"] += malos
        diario["turnos"] += max(float(periodo.get("turnos") or 0), 0) * factor
        diario["horas_programadas"] += horas_programadas
        diario["parada_pendiente"] = diario["parada_pendiente"] or parada_pendiente
        if minutos_parada is not None:
            diario["minutos_parada"] += minutos_parada
        if observaciones and observaciones not in diario["observaciones"]:
            diario["observaciones"].append(observaciones)
        diario["eventos_parada"].extend(eventos_parada)

    detalle = []
    for fecha in sorted(diarios):
        diario = diarios[fecha]
        total = diario["envases_buenos"] + diario["envases_malos"]
        minutos_parada = None if diario["parada_pendiente"] else diario["minutos_parada"]
        horas_reales = None if minutos_parada is None else max(
            diario["horas_programadas"] - minutos_parada / 60, 0
        )
        buenos_hora = diario["envases_buenos"] / horas_reales if horas_reales and horas_reales > 0 else None
        detalle.append({
            "fecha": fecha,
            "envases_buenos": round(diario["envases_buenos"], 2),
            "envases_malos": round(diario["envases_malos"], 2),
            "produccion_total": round(total, 2),
            "turnos": round(diario["turnos"], 2),
            "horas_programadas": round(diario["horas_programadas"], 3),
            "minutos_parada_reportados": minutos_parada,
            "estado_parada": "DATO_PENDIENTE" if diario["parada_pendiente"] else "VALIDO",
            "horas_reales_trabajo": round(horas_reales, 3) if horas_reales is not None else None,
            "produccion_buena_hora_real": round(buenos_hora, 3) if buenos_hora is not None else None,
            "observaciones": " | ".join(diario["observaciones"]),
            "paradas_reportadas": diario["eventos_parada"],
        })

    produccion_total = total_buenos + total_malos
    horas_parada = None if hay_paradas_pendientes else total_parada_minutos / 60
    horas_reales = None if horas_parada is None else max(total_horas_programadas - horas_parada, 0)
    productividad_buena = total_buenos / horas_reales if horas_reales and horas_reales > 0 else None
    productividad_total = produccion_total / horas_reales if horas_reales and horas_reales > 0 else None
    eficiencia_calidad = total_buenos / produccion_total * 100 if produccion_total > 0 else None
    tasa_rechazo = total_malos / produccion_total * 100 if produccion_total > 0 else None
    rechazos_por_1000 = total_malos / produccion_total * 1000 if produccion_total > 0 else None

    return {
        "periodo": {"inicio_utc": inicio_utc, "fin_utc": fin_utc},
        "envases_buenos": round(total_buenos, 2),
        "envases_malos": round(total_malos, 2),
        "produccion_total": round(produccion_total, 2),
        "horas_programadas": round(total_horas_programadas, 3),
        "horas_parada_reportadas": round(horas_parada, 3) if horas_parada is not None else None,
        "horas_reales_trabajo": round(horas_reales, 3) if horas_reales is not None else None,
        "produccion_buena_hora_real": round(productividad_buena, 3) if productividad_buena is not None else None,
        "produccion_total_hora_real": round(productividad_total, 3) if productividad_total is not None else None,
        "eficiencia_calidad_pct": round(eficiencia_calidad, 3) if eficiencia_calidad is not None else None,
        "tasa_rechazo_pct": round(tasa_rechazo, 3) if tasa_rechazo is not None else None,
        "rechazos_por_1000": round(rechazos_por_1000, 3) if rechazos_por_1000 is not None else None,
        "dias_produccion_incluidos": len(detalle),
        "estado_paradas": "DATO_PENDIENTE" if hay_paradas_pendientes else "VALIDO",
        "detalle_diario": detalle,
    }


def obtener_modulo_produccion(inicio_utc, fin_utc):
    periodos = obtener_produccion_periodos(inicio_utc, fin_utc)
    return calcular_modulo_produccion(periodos, inicio_utc, fin_utc)


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
