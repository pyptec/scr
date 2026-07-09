import csv
import json
import math
from pathlib import Path
from datetime import datetime, timezone

from db.samee200_db import get_conn, init_db, cargar_catalogos_desde_env


def normalizar_header(texto):
    if texto is None:
        return ""

    return str(texto).strip().lower().replace(" ", "_")


def parse_fecha_utc(valor):
    """
    Convierte fecha UTC del CSV a timestamp Unix.

    Acepta formatos como:
    2026-05-01 00:09:54.000
    2026-05-01 00:09:54
    2026-05-01T00:09:54
    """

    if valor is None or str(valor).strip() == "":
        return None

    texto = str(valor).strip()

    formatos = [
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
    ]

    for fmt in formatos:
        try:
            dt = datetime.strptime(texto, fmt)
            dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except Exception:
            pass

    raise ValueError(f"Fecha UTC no reconocida: {valor}")


def parse_numero(valor, default=None):
    if valor is None or str(valor).strip() == "":
        return default

    if isinstance(valor, (int, float)):
        if isinstance(valor, float) and math.isnan(valor):
            return default
        return float(valor)

    texto = str(valor).strip()

    # Manejo de formato colombiano/europeo y formato SQL normal.
    # Si viene "1.234,56" -> 1234.56
    # Si viene "1234.56" -> 1234.56
    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif "," in texto and "." not in texto:
        texto = texto.replace(",", ".")

    try:
        return float(texto)
    except Exception:
        return default


def parse_entero(valor, default=None):
    numero = parse_numero(valor, default=default)

    if numero is None:
        return default

    return int(numero)


def detectar_delimitador(ruta_csv):
    with open(ruta_csv, "r", encoding="utf-8-sig", newline="") as f:
        muestra = f.read(4096)
        f.seek(0)

        try:
            dialect = csv.Sniffer().sniff(muestra, delimiters=";,|\t")
            return dialect.delimiter
        except Exception:
            return ","


def columnas_tabla(conn, tabla):
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({tabla})")
    return [row["name"] for row in cur.fetchall()]


def existe_detalle(conn, timestamp_utc, gateway_id, device_id, unit_id):
    """
    Evita duplicados si se importa el mismo CSV varias veces.
    """

    cur = conn.cursor()

    cur.execute("""
        SELECT COUNT(*) AS total
        FROM mediciones_detalle
        WHERE CAST(timestamp_utc AS INTEGER) = ?
          AND CAST(gateway_id AS INTEGER) = ?
          AND TRIM(device_id) = ?
          AND CAST(unit_id AS INTEGER) = ?
    """, (
        int(timestamp_utc),
        int(gateway_id),
        str(device_id),
        int(unit_id)
    ))

    row = cur.fetchone()

    return int(row["total"]) > 0


def insertar_medicion(conn, timestamp_utc, gateway_id, device_id, source_type, origen, payload_json):
    """
    Inserta un registro padre en mediciones.

    La función detecta columnas existentes para no romperse si la tabla
    tiene más o menos campos.
    """

    cols_existentes = columnas_tabla(conn, "mediciones")

    datos = {
        "timestamp_utc": int(timestamp_utc),
        "gateway_id": int(gateway_id),
        "device_id": str(device_id),
        "source_type": source_type,
        "origen": origen,
        "payload_json": payload_json,
        "created_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    }

    cols_insert = [
        col for col in datos.keys()
        if col in cols_existentes
    ]

    if not cols_insert:
        return None

    placeholders = ", ".join(["?"] * len(cols_insert))
    cols_sql = ", ".join(cols_insert)
    valores = [datos[col] for col in cols_insert]

    cur = conn.cursor()

    cur.execute(f"""
        INSERT INTO mediciones ({cols_sql})
        VALUES ({placeholders})
    """, valores)

    return cur.lastrowid


def insertar_detalle(
    conn,
    medicion_id,
    timestamp_utc,
    gateway_id,
    device_id,
    source_type,
    unit_id,
    valor,
    origen
):
    """
    Inserta una variable en mediciones_detalle.

    Detecta columnas existentes para ajustarse al esquema actual.
    """

    cols_existentes = columnas_tabla(conn, "mediciones_detalle")

    datos = {
        "medicion_id": medicion_id,
        "timestamp_utc": int(timestamp_utc),
        "gateway_id": int(gateway_id),
        "device_id": str(device_id),
        "source_type": source_type,
        "unit_id": int(unit_id),
        "valor": float(valor),
        "origen": origen,
        "created_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    }

    cols_insert = [
        col for col in datos.keys()
        if col in cols_existentes and datos[col] is not None
    ]

    placeholders = ", ".join(["?"] * len(cols_insert))
    cols_sql = ", ".join(cols_insert)
    valores = [datos[col] for col in cols_insert]

    cur = conn.cursor()

    cur.execute(f"""
        INSERT INTO mediciones_detalle ({cols_sql})
        VALUES ({placeholders})
    """, valores)


def leer_csv_mediciones(ruta_csv):
    """
    Lee CSV exportado desde SQL Server.

    Soporta dos formatos:

    1) Con encabezados:
        utc_date, utc_received_date, gateway_id_prueba, device_id_prueba,
        concentrator_id_original, concentrator_name, gauge_id_original,
        gauge_name, unit_id, unit_name, value

    2) Sin encabezados, en este orden:
        utc_date,
        utc_received_date,
        gateway_id_prueba,
        device_id_prueba,
        concentrator_id_original,
        concentrator_name,
        gauge_id_original,
        gauge_name,
        unit_id,
        unit_name,
        value
    """

    delimitador = detectar_delimitador(ruta_csv)

    columnas_esperadas = [
        "utc_date",
        "utc_received_date",
        "gateway_id_prueba",
        "device_id_prueba",
        "concentrator_id_original",
        "concentrator_name",
        "gauge_id_original",
        "gauge_name",
        "unit_id",
        "unit_name",
        "value",
    ]

    with open(ruta_csv, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f, delimiter=delimitador)
        filas_raw = list(reader)

    if not filas_raw:
        raise RuntimeError("El CSV está vacío.")

    primera_fila = [
        normalizar_header(x)
        for x in filas_raw[0]
    ]

    tiene_encabezado = any(
        col in primera_fila
        for col in ["utc_date", "gateway_id_prueba", "device_id_prueba", "unit_id", "value"]
    )

    filas = []

    if tiene_encabezado:
        headers = primera_fila
        datos = filas_raw[1:]
    else:
        headers = columnas_esperadas
        datos = filas_raw

    for row in datos:
        if not row or len(row) < 5:
            continue

        fila = {}

        for idx, header in enumerate(headers):
            if idx < len(row):
                fila[header] = row[idx]
            else:
                fila[header] = None

        filas.append(fila)

    print(f"[IMPORT] Delimitador detectado: {repr(delimitador)}")
    print(f"[IMPORT] CSV con encabezado: {tiene_encabezado}")
    print(f"[IMPORT] Filas leídas: {len(filas)}")

    if filas:
        print("[IMPORT] Primera fila normalizada:")
        print(json.dumps(filas[0], indent=2, ensure_ascii=False))

    return filas


def importar_csv_mediciones_historicas(ruta_csv, confirmar=True):
    """
    Importa mediciones históricas reales desde CSV a SQLite SAMEE200.

    Mapeo esperado ya aplicado desde SQL Server:
        gateway_id_prueba = 10
        device_id_prueba:
            15 = Sistema
            26 = SensorTempHum
            24 = ME337_1 Proceso Aoki
            25 = ME337_2 Totalizador general
    """

    ruta = Path(ruta_csv)

    if not ruta.exists():
        return {
            "ok": False,
            "error": f"No existe el archivo: {ruta}"
        }

    init_db()
    cargar_catalogos_desde_env()

    # Fase 2: variables eléctricas ampliadas para análisis de operación,
    # validación de medición, huecos de datos, paros y calidad de energía.
    dispositivos_permitidos = {24, 25}

    unidades_permitidas = {
        

        # Voltajes fase-neutro y línea-línea
        7, 8, 9,
        29, 30, 31,
        56, 57,

        # Corrientes
        10, 11, 12,
        54, 55,

        # Potencias activas, reactivas y aparentes
        58, 59, 60, 61,
        62, 63, 64, 65,
        66, 67, 68, 69,

        # Factor de potencia y frecuencia
        27,
        70, 71, 72, 73,
        74, 75, 76,

        # Energías acumuladas
        97, 98, 99, 100,
        101, 102, 103, 104,
        108, 112, 116,

        # Armónicos THD corriente y voltaje
        117, 118, 119,
        120, 121, 122,
    }
    conn = get_conn()
    cur = conn.cursor()

    insertados = 0
    duplicados = 0
    omitidos = 0
    errores = []

    origen = f"HISTORICO_IOTCOLLECTOR/{ruta.name}"

    delimitador = detectar_delimitador(ruta)

    columnas_esperadas = [
        "utc_date",
        "utc_received_date",
        "gateway_id_prueba",
        "device_id_prueba",
        "concentrator_id_original",
        "concentrator_name",
        "gauge_id_original",
        "gauge_name",
        "unit_id",
        "unit_name",
        "value",
    ]

    with open(ruta, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f, delimiter=delimitador)

        primera_fila = next(reader, None)

        if not primera_fila:
            conn.close()
            return {
                "ok": False,
                "error": "El CSV está vacío."
            }

        primera_normalizada = [
            normalizar_header(x)
            for x in primera_fila
        ]

        tiene_encabezado = any(
            col in primera_normalizada
            for col in ["utc_date", "gateway_id_prueba", "device_id_prueba", "unit_id", "value"]
        )

        if tiene_encabezado:
            headers = primera_normalizada
            datos_iter = reader
            fila_inicio = 2
        else:
            headers = columnas_esperadas
            datos_iter = [primera_fila]
            fila_inicio = 1

        print(f"[IMPORT] Delimitador detectado: {repr(delimitador)}")
        print(f"[IMPORT] CSV con encabezado: {tiene_encabezado}")
        print(f"[IMPORT] Dispositivos permitidos: {sorted(dispositivos_permitidos)}")
        print(f"[IMPORT] Unidades permitidas: {sorted(unidades_permitidas)}")

        def procesar_row(row, idx):
            nonlocal insertados, duplicados, omitidos, errores

            try:
                fila = {}

                for i, header in enumerate(headers):
                    fila[header] = row[i] if i < len(row) else None

                utc_date = fila.get("utc_date")
                gateway_id = parse_entero(fila.get("gateway_id_prueba"), default=10)
                device_id = parse_entero(fila.get("device_id_prueba"), default=None)
                unit_id = parse_entero(fila.get("unit_id"), default=None)
                valor = parse_numero(fila.get("value"), default=None)

                if device_id is None or unit_id is None or valor is None:
                    omitidos += 1
                    return

                if device_id not in dispositivos_permitidos:
                    omitidos += 1
                    return

                if unit_id not in unidades_permitidas:
                    omitidos += 1
                    return

                timestamp_utc = parse_fecha_utc(utc_date)

                if timestamp_utc is None:
                    omitidos += 1
                    return

                # Evita duplicados solo para las variables clave.
                cur.execute("""
                    SELECT COUNT(*) AS total
                    FROM mediciones_detalle
                    WHERE CAST(timestamp_utc AS INTEGER) = ?
                      AND CAST(gateway_id AS INTEGER) = ?
                      AND TRIM(device_id) = ?
                      AND CAST(unit_id AS INTEGER) = ?
                """, (
                    int(timestamp_utc),
                    int(gateway_id),
                    str(device_id),
                    int(unit_id)
                ))

                row_dup = cur.fetchone()

                if row_dup:
                    duplicados += 1
                    return

                payload = {
                    "origen": origen,
                    "utc_date": utc_date,
                    "utc_received_date": fila.get("utc_received_date"),
                    "gateway_id_prueba": gateway_id,
                    "device_id_prueba": device_id,
                    "concentrator_id_original": fila.get("concentrator_id_original"),
                    "concentrator_name": fila.get("concentrator_name"),
                    "gauge_id_original": fila.get("gauge_id_original"),
                    "gauge_name": fila.get("gauge_name"),
                    "unit_id": unit_id,
                    "unit_name": fila.get("unit_name"),
                    "value": valor
                }

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
                    int(timestamp_utc),
                    int(gateway_id),
                    str(device_id),
                    "device",
                    origen,
                    json.dumps(payload, ensure_ascii=False)
                ))

                medicion_id = cur.lastrowid

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
                    int(timestamp_utc),
                    int(gateway_id),
                    str(device_id),
                    "device",
                    int(unit_id),
                    str(valor)
                ))

                insertados += 1

                if insertados % 2000 == 0:
                    if confirmar:
                        conn.commit()

                    print(
                        f"[IMPORT] Insertados={insertados} "
                        f"omitidos={omitidos} "
                        f"duplicados={duplicados}",
                        flush=True
                    )

            except Exception as e:
                errores.append(f"Fila {idx}: {e}")
                omitidos += 1

                if len(errores) <= 10:
                    print(f"[IMPORT][ERROR] Fila {idx}: {e}")

        if tiene_encabezado:
            for idx, row in enumerate(datos_iter, start=fila_inicio):
                procesar_row(row, idx)
        else:
            procesar_row(primera_fila, 1)

            for idx, row in enumerate(reader, start=2):
                procesar_row(row, idx)
    if confirmar:
        conn.commit()
    else:
        conn.rollback()

    conn.close()

    return {
        "ok": True,
        "archivo": str(ruta),
        "insertados": insertados,
        "duplicados": duplicados,
        "omitidos": omitidos,
        "errores": errores[:20],
        "confirmado": confirmar
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Importar mediciones históricas SAMEE200 desde CSV"
    )

    parser.add_argument(
        "archivo",
        help="Ruta del CSV histórico exportado desde SQL Server"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Lee y procesa, pero no confirma los cambios en SQLite"
    )

    args = parser.parse_args()

    resultado = importar_csv_mediciones_historicas(
        args.archivo,
        confirmar=not args.dry_run
    )

    print(json.dumps(resultado, indent=2, ensure_ascii=False))