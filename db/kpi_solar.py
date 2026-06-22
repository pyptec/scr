from db.samee100_db import get_conn


UNIT_PTOTAL = 61      # Total Active power
UNIT_EPEXP  = 104     # Total Reverse active energy UInt32
UNIT_EPIMP  = 100     # Total Positive active energy UInt32

FACTOR_CO2_KG_KWH = 0.16438
TARIFA_COP_KWH = 950


def _row_value(sql, params=()):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(sql, params)
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return row[0]


def potencia_actual_kw():
    return _row_value("""
        SELECT valor
        FROM mediciones_detalle
        WHERE unit_id = ?
        ORDER BY timestamp_utc DESC, id DESC
        LIMIT 1
    """, (UNIT_PTOTAL,))


def energia_periodo_kwh(unit_id, fecha_inicio, fecha_fin):
    """
    Calcula energía por diferencia de contador acumulado.
    fecha_inicio y fecha_fin deben ir como timestamp Unix o texto ISO compatible.
    """

    inicial = _row_value("""
        SELECT valor
        FROM mediciones_detalle
        WHERE unit_id = ?
          AND timestamp_utc >= ?
        ORDER BY timestamp_utc ASC, id ASC
        LIMIT 1
    """, (unit_id, fecha_inicio))

    final = _row_value("""
        SELECT valor
        FROM mediciones_detalle
        WHERE unit_id = ?
          AND timestamp_utc <= ?
        ORDER BY timestamp_utc DESC, id DESC
        LIMIT 1
    """, (unit_id, fecha_fin))

    if inicial is None or final is None:
        return 0.0

    energia = final - inicial

    if energia < 0:
        return 0.0

    return round(energia, 3)


def generacion_periodo_kwh(fecha_inicio, fecha_fin):
    return energia_periodo_kwh(
        UNIT_EPEXP,
        fecha_inicio,
        fecha_fin
    )


def consumo_periodo_kwh(fecha_inicio, fecha_fin):
    return energia_periodo_kwh(
        UNIT_EPIMP,
        fecha_inicio,
        fecha_fin
    )


def ahorro_cop(kwh, tarifa_cop_kwh=TARIFA_COP_KWH):
    return round(float(kwh) * tarifa_cop_kwh, 0)


def co2_evitado_kg(kwh, factor=FACTOR_CO2_KG_KWH):
    return round(float(kwh) * factor, 2)


def resumen_periodo(fecha_inicio, fecha_fin):
    generacion = generacion_periodo_kwh(
        fecha_inicio,
        fecha_fin
    )

    consumo = consumo_periodo_kwh(
        fecha_inicio,
        fecha_fin
    )

    potencia = potencia_actual_kw()

    return {
        "potencia_actual_kw": potencia,
        "generacion_kwh": generacion,
        "consumo_kwh": consumo,
        "ahorro_cop": ahorro_cop(generacion),
        "co2_evitado_kg": co2_evitado_kg(generacion)
    }


def serie_variable(unit_id, fecha_inicio, fecha_fin, limite=1000):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT timestamp_utc, valor
        FROM mediciones_detalle
        WHERE unit_id = ?
          AND timestamp_utc >= ?
          AND timestamp_utc <= ?
        ORDER BY timestamp_utc ASC
        LIMIT ?
    """, (
        unit_id,
        fecha_inicio,
        fecha_fin,
        limite
    ))

    rows = [
        {
            "timestamp_utc": r["timestamp_utc"],
            "valor": r["valor"]
        }
        for r in cur.fetchall()
    ]

    conn.close()
    return rows

def energia_diaria_generada(unit_id=UNIT_EPEXP, limite_dias=30):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            date(datetime(CAST(timestamp_utc AS INTEGER), 'unixepoch')) AS dia,
            MIN(valor) AS inicial,
            MAX(valor) AS final,
            ROUND(MAX(valor) - MIN(valor), 3) AS kwh
        FROM mediciones_detalle
        WHERE unit_id = ?
        GROUP BY dia
        ORDER BY dia DESC
        LIMIT ?
    """, (
        unit_id,
        limite_dias
    ))

    rows = [
        {
            "dia": r["dia"],
            "kwh": r["kwh"] if r["kwh"] >= 0 else 0
        }
        for r in cur.fetchall()
    ]

    conn.close()

    return list(reversed(rows))

def valor_inicial_final(unit_id, fecha_inicio, fecha_fin):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT valor, timestamp_utc
        FROM mediciones_detalle
        WHERE unit_id = ?
          AND timestamp_utc >= ?
          AND timestamp_utc <= ?
        ORDER BY timestamp_utc ASC, id ASC
        LIMIT 1
    """, (unit_id, fecha_inicio, fecha_fin))

    inicial = cur.fetchone()

    cur.execute("""
        SELECT valor, timestamp_utc
        FROM mediciones_detalle
        WHERE unit_id = ?
          AND timestamp_utc >= ?
          AND timestamp_utc <= ?
        ORDER BY timestamp_utc DESC, id DESC
        LIMIT 1
    """, (unit_id, fecha_inicio, fecha_fin))

    final = cur.fetchone()

    conn.close()

    if not inicial or not final:
        return {
            "inicial": None,
            "final": None,
            "delta": 0.0,
            "timestamp_inicial": None,
            "timestamp_final": None
        }

    delta = float(final["valor"]) - float(inicial["valor"])

    if delta < 0:
        delta = 0.0

    return {
        "inicial": round(float(inicial["valor"]), 3),
        "final": round(float(final["valor"]), 3),
        "delta": round(delta, 3),
        "timestamp_inicial": inicial["timestamp_utc"],
        "timestamp_final": final["timestamp_utc"]
    }


def estadisticas_variable(unit_id, fecha_inicio, fecha_fin):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            MIN(valor) AS minimo,
            MAX(valor) AS maximo,
            AVG(valor) AS promedio,
            COUNT(*) AS muestras
        FROM mediciones_detalle
        WHERE unit_id = ?
          AND timestamp_utc >= ?
          AND timestamp_utc <= ?
    """, (unit_id, fecha_inicio, fecha_fin))

    row = cur.fetchone()
    conn.close()

    if not row or row["muestras"] == 0:
        return {
            "minimo": 0.0,
            "maximo": 0.0,
            "promedio": 0.0,
            "muestras": 0
        }

    return {
        "minimo": round(float(row["minimo"]), 3),
        "maximo": round(float(row["maximo"]), 3),
        "promedio": round(float(row["promedio"]), 3),
        "muestras": int(row["muestras"])
    }


def reporte_kpi_energetico(fecha_inicio, fecha_fin):
    exportada = valor_inicial_final(UNIT_EPEXP, fecha_inicio, fecha_fin)
    importada = valor_inicial_final(UNIT_EPIMP, fecha_inicio, fecha_fin)

    potencia = estadisticas_variable(UNIT_PTOTAL, fecha_inicio, fecha_fin)
    potencia_actual = potencia_actual_kw()

    energia_exportada = exportada["delta"]
    energia_importada = importada["delta"]

    balance_neto = energia_exportada - energia_importada

    return {
        "energia": {
            "exportada_kwh": energia_exportada,
            "importada_kwh": energia_importada,
            "balance_neto_kwh": round(balance_neto, 3),
            "exportada_inicial_kwh": exportada["inicial"],
            "exportada_final_kwh": exportada["final"],
            "importada_inicial_kwh": importada["inicial"],
            "importada_final_kwh": importada["final"]
        },
        "potencia": {
            "actual_kw": potencia_actual,
            "maxima_kw": potencia["maximo"],
            "minima_kw": potencia["minimo"],
            "promedio_kw": potencia["promedio"],
            "muestras": potencia["muestras"]
        },
        "impacto": {
            "ahorro_cop": ahorro_cop(energia_exportada),
            "co2_evitado_kg": co2_evitado_kg(energia_exportada)
        }
    }
    
    def rango_real_datos(fecha_inicio="0", fecha_fin="9999999999"):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            MIN(timestamp_utc) AS inicio_real,
            MAX(timestamp_utc) AS fin_real
        FROM mediciones_detalle
        WHERE timestamp_utc >= ?
          AND timestamp_utc <= ?
    """, (fecha_inicio, fecha_fin))

    row = cur.fetchone()
    conn.close()

    if not row:
        return {
            "inicio_real": None,
            "fin_real": None
        }

    return {
        "inicio_real": row["inicio_real"],
        "fin_real": row["fin_real"]
    }