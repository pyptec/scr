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

    Espera encabezados:
    utc_date, utc_received_date, gateway_id_prueba, device_id_prueba,
    concentrator_id_original, concentrator_name, gauge_id_original,
    gauge_name, unit_id, unit_name, value
    """

    delimitador = detectar_delimitador(ruta_csv)

    with open(ruta_csv, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=delimitador)

        if not reader.fieldnames:
            raise RuntimeError("El CSV no tiene encabezados. Exporta de nuevo con encabezados.")

        fieldnames_normalizados = [
            normalizar_header(h)
            for h in reader.fieldnames
        ]

        filas = []

        for row in reader:
            fila = {}

            for original, normalizado in zip(reader.fieldnames, fieldnames_normalizados):
                fila[normalizado] = row.get(original)

            filas.append(fila)

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

    filas = leer_csv_mediciones(ruta)

    conn = get_conn()
    #conn.row_factory = None

    insertados = 0
    duplicados = 0
    omitidos = 0
    errores = []

    origen = f"HISTORICO_IOTCOLLECTOR/{ruta.name}"

    for idx, fila in enumerate(filas, start=2):
        try:
            utc_date = fila.get("utc_date")
            gateway_id = parse_entero(fila.get("gateway_id_prueba"), default=10)
            device_id = parse_entero(fila.get("device_id_prueba"), default=None)
            unit_id = parse_entero(fila.get("unit_id"), default=None)
            valor = parse_numero(fila.get("value"), default=None)

            if device_id is None or unit_id is None or valor is None:
                omitidos += 1
                continue

            timestamp_utc = parse_fecha_utc(utc_date)

            if timestamp_utc is None:
                omitidos += 1
                continue

            # Evitar importar dos veces la misma medición.
            if existe_detalle(
                conn,
                timestamp_utc=timestamp_utc,
                gateway_id=gateway_id,
                device_id=device_id,
                unit_id=unit_id
            ):
                duplicados += 1
                continue

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

            medicion_id = insertar_medicion(
                conn=conn,
                timestamp_utc=timestamp_utc,
                gateway_id=gateway_id,
                device_id=device_id,
                source_type="device",
                origen=origen,
                payload_json=json.dumps(payload, ensure_ascii=False)
            )

            insertar_detalle(
                conn=conn,
                medicion_id=medicion_id,
                timestamp_utc=timestamp_utc,
                gateway_id=gateway_id,
                device_id=device_id,
                source_type="device",
                unit_id=unit_id,
                valor=valor,
                origen=origen
            )

            insertados += 1

            if insertados % 1000 == 0:
                conn.commit()
                print(f"[IMPORT] Insertados: {insertados}")

        except Exception as e:
            errores.append(f"Fila {idx}: {e}")
            omitidos += 1

            if len(errores) <= 10:
                print(f"[IMPORT][ERROR] Fila {idx}: {e}")

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