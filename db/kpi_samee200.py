import os
import random
import sqlite3
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv

from db.samee200_db import get_conn
from db.samee200_db import get_conn
from db.produccion_samee200 import sumar_produccion_rango

load_dotenv("/home/pi/SAMEE200/scr/.env")


def obtener_config_rol(rol_env):
    """
    Lee desde .env qué CFG cumple un rol.

    Ejemplo:
        DASHBOARD_MEDIDOR_TOTAL=CFG_TOTALIZADOR
        CFG_TOTALIZADOR=/home/pi/SAMEE200/scr/device/meatrolME3372.yml
        CFG_TOTALIZADOR_SECTION=meatrolME337_2

    En esta primera versión no abre el YAML; usa los devices registrados
    en SQLite por rol: totalizador/proceso.
    """

    return os.getenv(rol_env)


def obtener_device_por_rol(rol):
    """
    Busca en SQLite el device_id asociado a un rol del YAML.

    Roles esperados:
        totalizador
        proceso
    """

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT device_id, gateway_id, nombre, rol
        FROM dispositivos
        WHERE LOWER(TRIM(rol)) = LOWER(TRIM(?))
        LIMIT 1
    """, (rol,))

    row = cur.fetchone()
    conn.close()

    if not row:
        return None

    return dict(row)


def obtener_ultimo_valor(unit_id, device_id=None, gateway_id=None, inicio=None, fin=None):
    conn = get_conn()
    cur = conn.cursor()

    where = """
        unit_id = ?
    """

    params = [int(unit_id)]

    if device_id not in [None, "", "None"]:
        where += " AND TRIM(device_id) = ?"
        params.append(str(device_id))

    if gateway_id not in [None, "", "None"]:
        where += " AND gateway_id = ?"
        params.append(int(gateway_id))

    if inicio is not None:
        where += " AND CAST(timestamp_utc AS INTEGER) >= ?"
        params.append(int(inicio))

    if fin is not None:
        where += " AND CAST(timestamp_utc AS INTEGER) <= ?"
        params.append(int(fin))

    cur.execute(f"""
        SELECT valor, timestamp_utc
        FROM mediciones_detalle
        WHERE {where}
        ORDER BY CAST(timestamp_utc AS INTEGER) DESC, id DESC
        LIMIT 1
    """, params)

    row = cur.fetchone()
    conn.close()

    if not row:
        return None

    try:
        return float(row["valor"])
    except Exception:
        return None


def calcular_delta_acumulado(unit_id, device_id, gateway_id=None, inicio=0, fin=None):
    """
    Calcula energía del periodo desde contador acumulado.

    No usa último - primero simple.
    Suma incrementos positivos válidos y descarta saltos anómalos.
    """

    if fin is None:
        fin = int(datetime.now(timezone.utc).timestamp())

    max_delta_kwh = float(os.getenv("MAX_DELTA_KWH_MUESTRA", "200"))

    conn = get_conn()
    cur = conn.cursor()

    where = """
        unit_id = ?
        AND TRIM(device_id) = ?
        AND CAST(timestamp_utc AS INTEGER) BETWEEN ? AND ?
    """

    params = [
        int(unit_id),
        str(device_id),
        int(inicio),
        int(fin)
    ]

    if gateway_id not in [None, "", "None"]:
        where += " AND gateway_id = ?"
        params.append(int(gateway_id))

    cur.execute(f"""
        SELECT
            CAST(valor AS REAL) AS valor,
            CAST(timestamp_utc AS INTEGER) AS ts
        FROM mediciones_detalle
        WHERE {where}
        ORDER BY CAST(timestamp_utc AS INTEGER) ASC, id ASC
    """, params)

    rows = cur.fetchall()
    conn.close()

    if len(rows) < 2:
        return 0.0

    total = 0.0
    anterior = None

    for row in rows:
        actual = float(row["valor"])

        if anterior is None:
            anterior = actual
            continue

        delta = actual - anterior

        if 0 <= delta <= max_delta_kwh:
            total += delta

        anterior = actual

    return round(total, 3)


def generar_produccion_simulada(inicio, fin):
    """
    Fallback de prueba cuando no existe producción real cargada
    para el rango seleccionado.

    Esta función solo debe usarse si produccion_periodo no tiene datos.
    """

    prod_min = int(os.getenv("PRODUCCION_MIN_DIA", "29000"))
    prod_max = int(os.getenv("PRODUCCION_MAX_DIA", "32000"))

    segundos = max(int(fin) - int(inicio), 1)
    dias = segundos / 86400
    horas_programadas = segundos / 3600

    produccion_dia = random.randint(prod_min, prod_max)
    produccion_periodo = int(produccion_dia * dias)

    return {
        "envases_dia_estimado": produccion_dia,
        "envases_periodo": produccion_periodo,
        "envases_buenos": produccion_periodo,
        "envases_malos": 0,
        "envases_total": produccion_periodo,
        "eficiencia_calc": 1,
        "horas_programadas": round(horas_programadas, 3),
        "horas_productivas": round(horas_programadas, 3),
        "periodos_usados": 0,
        "fuente": "simulado"
    }


def obtener_produccion_periodo(inicio, fin):
    """
    Obtiene producción real desde la tabla produccion_periodo.

    Regla:
    - Si hay producción real en el rango, usa envases_buenos.
    - Si no hay producción real, usa simulación como respaldo.

    Para EnPI se recomienda usar envases buenos, porque representan
    producción útil conforme.
    """

    try:
        produccion_real = sumar_produccion_rango(inicio, fin)

        periodos_usados = int(produccion_real.get("periodos_usados", 0) or 0)

        if periodos_usados > 0:
            envases_buenos = float(produccion_real.get("envases_buenos", 0) or 0)
            envases_malos = float(produccion_real.get("envases_malos", 0) or 0)
            envases_total = float(produccion_real.get("envases_total", 0) or 0)

            segundos = max(int(fin) - int(inicio), 1)
            dias = segundos / 86400

            if dias > 0:
                envases_dia_estimado = int(round(envases_buenos / dias))
            else:
                envases_dia_estimado = int(round(envases_buenos))

            return {
                "envases_dia_estimado": envases_dia_estimado,
                "envases_periodo": int(round(envases_buenos)),
                "envases_buenos": round(envases_buenos, 2),
                "envases_malos": round(envases_malos, 2),
                "envases_total": round(envases_total, 2),
                "eficiencia_calc": produccion_real.get("eficiencia_calc", 0),
                "horas_programadas": produccion_real.get("horas_programadas", 0),
                "horas_productivas": produccion_real.get("horas_productivas", 0),
                "periodos_usados": periodos_usados,
                "fuente": "archivo"
            }

    except Exception as e:
        print(f"[KPI] Error leyendo producción real: {e}")

    return generar_produccion_simulada(inicio, fin)

def resumen_kpi_samee200(inicio=None, fin=None):
    """
    KPI principal SAMEE200.

    Totalizador:
        rol = totalizador

    Proceso:
        rol = proceso

    Energía principal:
        unit_id 100 = energía activa importada total kWh

    Potencia principal:
        unit_id 61 = potencia activa total W
    """

    if fin is None:
        fin = int(datetime.now(timezone.utc).timestamp())

    if inicio is None:
        # Por defecto: últimas 24 horas
        inicio = fin - 86400

    tarifa_kwh = float(os.getenv("TARIFA_KWH", "950"))
    factor_co2 = float(os.getenv("FACTOR_CO2_KG_KWH", "0.164"))

    totalizador = obtener_device_por_rol("totalizador")
    proceso = obtener_device_por_rol("proceso")

    resultado = {
        "inicio": int(inicio),
        "fin": int(fin),
        "totalizador": None,
        "proceso": None,
        "produccion": None,
        "enpi": None,
        "impacto": None
    }

    if not totalizador or not proceso:
        resultado["error"] = "No se encontraron dispositivos con rol totalizador/proceso"
        return resultado

    totalizador_device = str(totalizador["device_id"])
    proceso_device = str(proceso["device_id"])

    gateway_id = totalizador["gateway_id"]

    energia_totalizador_kwh = calcular_delta_acumulado(
        unit_id=100,
        device_id=totalizador_device,
        gateway_id=gateway_id,
        inicio=inicio,
        fin=fin
    )

    energia_proceso_kwh = calcular_delta_acumulado(
        unit_id=100,
        device_id=proceso_device,
        gateway_id=proceso["gateway_id"],
        inicio=inicio,
        fin=fin
    )

    potencia_totalizador_w = obtener_ultimo_valor(
        unit_id=61,
        device_id=totalizador_device,
        gateway_id=gateway_id,
        inicio=inicio,
        fin=fin
    )

    potencia_proceso_w = obtener_ultimo_valor(
        unit_id=61,
        device_id=proceso_device,
        gateway_id=proceso["gateway_id"],
        inicio=inicio,
        fin=fin
    )

    potencia_totalizador_kw = round((potencia_totalizador_w or 0) / 1000, 3)
    potencia_proceso_kw = round((potencia_proceso_w or 0) / 1000, 3)

    produccion = obtener_produccion_periodo(inicio, fin)
    envases = produccion["envases_periodo"]

    if envases > 0:
        kwh_por_envase_total = energia_totalizador_kwh / envases
        kwh_por_1000_envases_total = kwh_por_envase_total * 1000

        kwh_por_envase_proceso = energia_proceso_kwh / envases
        kwh_por_1000_envases_proceso = kwh_por_envase_proceso * 1000
    else:
        kwh_por_envase_total = 0
        kwh_por_1000_envases_total = 0
        kwh_por_envase_proceso = 0
        kwh_por_1000_envases_proceso = 0

    costo_totalizador = energia_totalizador_kwh * tarifa_kwh
    costo_proceso = energia_proceso_kwh * tarifa_kwh

    co2_totalizador = energia_totalizador_kwh * factor_co2
    co2_proceso = energia_proceso_kwh * factor_co2

    participacion_proceso = 0.0
    if energia_totalizador_kwh > 0:
        participacion_proceso = energia_proceso_kwh / energia_totalizador_kwh * 100

    resultado["totalizador"] = {
        "device_id": totalizador_device,
        "nombre": totalizador["nombre"],
        "gateway_id": gateway_id,
        "energia_kwh": round(energia_totalizador_kwh, 3),
        "potencia_actual_kw": potencia_totalizador_kw,
        "costo_cop": round(costo_totalizador, 0),
        "co2_kg": round(co2_totalizador, 2)
    }

    resultado["proceso"] = {
        "device_id": proceso_device,
        "nombre": proceso["nombre"],
        "gateway_id": proceso["gateway_id"],
        "energia_kwh": round(energia_proceso_kwh, 3),
        "potencia_actual_kw": potencia_proceso_kw,
        "costo_cop": round(costo_proceso, 0),
        "co2_kg": round(co2_proceso, 2),
        "participacion_totalizador_pct": round(participacion_proceso, 2)
    }

    resultado["produccion"] = produccion

    resultado["enpi"] = {
        "kwh_por_envase_totalizador": round(kwh_por_envase_total, 6),
        "kwh_por_1000_envases_totalizador": round(kwh_por_1000_envases_total, 3),
        "kwh_por_envase_proceso": round(kwh_por_envase_proceso, 6),
        "kwh_por_1000_envases_proceso": round(kwh_por_1000_envases_proceso, 3)
    }

    resultado["impacto"] = {
        "tarifa_kwh": tarifa_kwh,
        "factor_co2_kg_kwh": factor_co2,
        "costo_totalizador_cop": round(costo_totalizador, 0),
        "costo_proceso_cop": round(costo_proceso, 0),
        "co2_totalizador_kg": round(co2_totalizador, 2),
        "co2_proceso_kg": round(co2_proceso, 2)
    }

    return resultado
