import os
import time
import sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta

from flask import Flask, jsonify, request, render_template
from dotenv import load_dotenv

from db.samee200_db import init_db, get_conn, cargar_catalogos_desde_env
from db.kpi_samee200 import resumen_kpi_samee200

from db.linea_base_samee200 import entrenar_linea_base_totalizador
from db.linea_base_samee200 import evaluar_desempeno_actual
from db.linea_base_samee200 import obtener_muestras_linea_base
from db.produccion_samee200 import obtener_produccion_periodos
from db.produccion_samee200 import sumar_produccion_rango
from db.produccion_samee200 import obtener_modulo_produccion

load_dotenv("/home/pi/SAMEE200/scr/.env")

BASE_DIR = Path(__file__).resolve().parent.parent

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static")
)

init_db()
cargar_catalogos_desde_env()


def convertir_utc_a_colombia(timestamp_utc):
    try:
        if timestamp_utc is None:
            return ""

        dt_utc = datetime.fromtimestamp(
            int(timestamp_utc),
            tz=timezone.utc
        )

        dt_col = dt_utc.astimezone(
            timezone(timedelta(hours=-5))
        )

        return dt_col.strftime("%Y-%m-%d %H:%M:%S")

    except Exception:
        return ""


@app.route("/")
def home():
    return {
        "nombre": "SAMEE200 Industrial",
        "estado": "online"
    }


@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/dashboard")
def api_dashboard():
    inicio = request.args.get("inicio", type=int)
    fin = request.args.get("fin", type=int)

    if not fin:
        fin = int(time.time())

    if not inicio:
        inicio = fin - 86400

    data = resumen_kpi_samee200(inicio=inicio, fin=fin)

    return jsonify(data)


@app.route("/api/estado")
def api_estado():
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    ahora = int(time.time())

    estado = {
        "timestamp_actual": ahora,
        "db": "OK",
        "ultima_medicion_utc": None,
        "ultima_medicion_colombia": None,
        "edad_segundos": None,
        "estado_datos": "SIN DATOS",
        "total_gateways": 0,
        "total_dispositivos": 0,
        "total_variables": 0,
        "gateway": None,
        "gateway_id": None,
        "cliente": None,
        "ram": None,
        "cpu": None,
        "ip_usb0": None,
        "ip_ethernet": None,
        "connected_meter": None
    }

    try:
        cur.execute("SELECT COUNT(*) AS total FROM gateways")
        estado["total_gateways"] = cur.fetchone()["total"]

        cur.execute("SELECT COUNT(*) AS total FROM dispositivos")
        estado["total_dispositivos"] = cur.fetchone()["total"]

        cur.execute("SELECT COUNT(*) AS total FROM unidades")
        estado["total_variables"] = cur.fetchone()["total"]

        cur.execute("""
            SELECT gateway_id, nombre, cliente
            FROM gateways
            ORDER BY gateway_id ASC
            LIMIT 1
        """)
        row_gateway = cur.fetchone()

        if row_gateway:
            estado["gateway_id"] = row_gateway["gateway_id"]
            estado["gateway"] = row_gateway["nombre"]
            estado["cliente"] = row_gateway["cliente"]

        cur.execute("""
            SELECT MAX(CAST(timestamp_utc AS INTEGER)) AS ts
            FROM mediciones_detalle
        """)
        row = cur.fetchone()
        ts = row["ts"] if row else None

        if ts:
            ts = int(ts)
            estado["ultima_medicion_utc"] = ts
            estado["ultima_medicion_colombia"] = convertir_utc_a_colombia(ts)
            estado["edad_segundos"] = ahora - ts

            if estado["edad_segundos"] <= 900:
                estado["estado_datos"] = "OK"
            else:
                estado["estado_datos"] = "SIN DATOS RECIENTES"

        def ultimo_valor(unit_id):
            cur.execute("""
                SELECT valor
                FROM mediciones_detalle
                WHERE unit_id = ?
                ORDER BY CAST(timestamp_utc AS INTEGER) DESC, id DESC
                LIMIT 1
            """, (int(unit_id),))
            r = cur.fetchone()
            if not r:
                return None
            return r["valor"]

        estado["connected_meter"] = ultimo_valor(53)
        estado["ram"] = ultimo_valor(135)
        estado["cpu"] = ultimo_valor(136)
        estado["ip_usb0"] = ultimo_valor(137)
        estado["ip_ethernet"] = ultimo_valor(144)

        conn.close()
        return jsonify(estado)

    except Exception as e:
        conn.close()
        return jsonify({
            "db": "ERROR",
            "error": str(e)
        }), 500


@app.route("/api/variables")
def api_variables():
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT
            md.gateway_id,
            COALESCE(g.nombre, 'Gateway ' || md.gateway_id) AS gateway,
            COALESCE(g.cliente, '') AS cliente,

            md.source_type,
            NULLIF(TRIM(md.device_id), '') AS device_id,

            COALESCE(d.nombre, 'Device ' || NULLIF(TRIM(md.device_id), '')) AS dispositivo,
            COALESCE(d.rol, '') AS rol,
            COALESCE(d.tipo, '') AS tipo_dispositivo,
            COALESCE(d.ubicacion, '') AS ubicacion_dispositivo,

            md.unit_id,

            COALESCE(u.name, 'Variable ' || md.unit_id) AS variable,
            COALESCE(u.alias, '') AS alias,
            COALESCE(u.simbol, '') AS simbolo,
            COALESCE(u.descripcion, '') AS descripcion,

            COUNT(*) AS registros,
            datetime(MIN(CAST(md.timestamp_utc AS INTEGER)), 'unixepoch') AS desde_utc,
            datetime(MAX(CAST(md.timestamp_utc AS INTEGER)), 'unixepoch') AS hasta_utc
        FROM mediciones_detalle md
        LEFT JOIN gateways g
            ON md.gateway_id = g.gateway_id
        LEFT JOIN dispositivos d
            ON CAST(NULLIF(TRIM(md.device_id), '') AS INTEGER) = d.device_id
        LEFT JOIN unidades u
            ON md.unit_id = u.unit_id
        WHERE md.device_id IN ('24','25','26')
        GROUP BY
            md.gateway_id,
            g.nombre,
            g.cliente,
            md.source_type,
            NULLIF(TRIM(md.device_id), ''),
            d.nombre,
            d.rol,
            d.tipo,
            d.ubicacion,
            md.unit_id,
            u.name,
            u.alias,
            u.simbol,
            u.descripcion
        HAVING registros > 0
        ORDER BY
            md.gateway_id ASC,
            CAST(NULLIF(TRIM(md.device_id), '') AS INTEGER) ASC,
            md.unit_id ASC
    """)

    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    return jsonify({
        "total": len(rows),
        "variables": rows
    })

@app.route("/api/ultimos")
def api_ultimos():
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT
            md.gateway_id,
            g.nombre AS gateway,
            g.cliente AS cliente,
            md.source_type,
            NULLIF(TRIM(md.device_id), '') AS device_id,
            d.nombre AS dispositivo,
            d.rol AS rol,
            d.tipo AS tipo_dispositivo,
            d.ubicacion AS ubicacion_dispositivo,
            md.unit_id,
            u.name AS variable,
            u.simbol AS simbol,
            md.valor,
            md.timestamp_utc
        FROM mediciones_detalle md
        INNER JOIN (
            SELECT
                gateway_id,
                source_type,
                NULLIF(TRIM(device_id), '') AS device_id,
                unit_id,
                MAX(id) AS max_id
            FROM mediciones_detalle
            GROUP BY
                gateway_id,
                source_type,
                NULLIF(TRIM(device_id), ''),
                unit_id
        ) ult
            ON md.id = ult.max_id
        LEFT JOIN dispositivos d
            ON CAST(NULLIF(TRIM(md.device_id), '') AS INTEGER) = d.device_id
        LEFT JOIN gateways g
            ON md.gateway_id = g.gateway_id
        LEFT JOIN unidades u
            ON md.unit_id = u.unit_id
        ORDER BY
            md.gateway_id ASC,
            md.source_type ASC,
            CAST(NULLIF(TRIM(md.device_id), '') AS INTEGER) ASC,
            md.unit_id ASC
    """)

    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    return jsonify({
        "total": len(rows),
        "datos": rows
    })


@app.route("/api/serie/<int:unit_id>")
def api_serie(unit_id):
    inicio = request.args.get("inicio", "0")
    fin = request.args.get("fin", "9999999999")
    limite = int(request.args.get("limite", "1000"))

    gateway_id = request.args.get("gateway_id")
    device_id = request.args.get("device_id")
    source_type = request.args.get("source_type")

    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    where = """
        md.unit_id = ?
        AND CAST(md.timestamp_utc AS INTEGER) >= ?
        AND CAST(md.timestamp_utc AS INTEGER) <= ?
    """

    params = [
        int(unit_id),
        int(inicio),
        int(fin)
    ]

    if gateway_id:
        where += " AND md.gateway_id = ?"
        params.append(int(gateway_id))

    if source_type:
        where += " AND md.source_type = ?"
        params.append(source_type)

    if device_id:
        where += " AND TRIM(md.device_id) = ?"
        params.append(str(device_id))

    cur.execute(f"""
        SELECT
            md.timestamp_utc,
            md.gateway_id,
            g.nombre AS gateway,
            md.source_type,
            NULLIF(TRIM(md.device_id), '') AS device_id,
            d.nombre AS dispositivo,
            d.rol AS rol,
            md.unit_id,
            u.name AS variable,
            u.simbol AS simbolo,
            md.valor
        FROM mediciones_detalle md
        LEFT JOIN dispositivos d
            ON CAST(NULLIF(TRIM(md.device_id), '') AS INTEGER) = d.device_id
        LEFT JOIN gateways g
            ON md.gateway_id = g.gateway_id
        LEFT JOIN unidades u
            ON md.unit_id = u.unit_id
        WHERE {where}
        ORDER BY CAST(md.timestamp_utc AS INTEGER) ASC, md.id ASC
        LIMIT ?
    """, params + [limite])

    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    return jsonify({
        "unit_id": unit_id,
        "total": len(rows),
        "serie": rows
    })


@app.route("/api/series")
def api_series():
    ids = request.args.get("ids", "")
    inicio = request.args.get("inicio", "0")
    fin = request.args.get("fin", "9999999999")
    limite = int(request.args.get("limite", "1000"))

    gateway_id = request.args.get("gateway_id")
    device_id = request.args.get("device_id")
    source_type = request.args.get("source_type")

    unit_ids = [
        int(x.strip())
        for x in ids.split(",")
        if x.strip().isdigit()
    ]

    resultado = {}

    for uid in unit_ids:
        params = {
            "inicio": inicio,
            "fin": fin,
            "limite": limite,
            "gateway_id": gateway_id,
            "device_id": device_id,
            "source_type": source_type
        }

        conn = get_conn()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        where = """
            md.unit_id = ?
            AND CAST(md.timestamp_utc AS INTEGER) >= ?
            AND CAST(md.timestamp_utc AS INTEGER) <= ?
        """

        sql_params = [uid, int(inicio), int(fin)]

        if gateway_id:
            where += " AND md.gateway_id = ?"
            sql_params.append(int(gateway_id))

        if source_type:
            where += " AND md.source_type = ?"
            sql_params.append(source_type)

        if device_id:
            where += " AND TRIM(md.device_id) = ?"
            sql_params.append(str(device_id))

        cur.execute(f"""
            SELECT
                md.timestamp_utc,
                md.gateway_id,
                md.source_type,
                NULLIF(TRIM(md.device_id), '') AS device_id,
                md.unit_id,
                u.name AS variable,
                u.simbol AS simbolo,
                md.valor
            FROM mediciones_detalle md
            LEFT JOIN unidades u
                ON md.unit_id = u.unit_id
            WHERE {where}
            ORDER BY CAST(md.timestamp_utc AS INTEGER) ASC, md.id ASC
            LIMIT ?
        """, sql_params + [limite])

        resultado[str(uid)] = [dict(r) for r in cur.fetchall()]
        conn.close()

    return jsonify({
        "unit_ids": unit_ids,
        "series": resultado
    })

@app.route("/api/linea-base")
def api_linea_base():
    inicio = request.args.get("inicio", type=int)
    fin = request.args.get("fin", type=int)

    data = evaluar_desempeno_actual(inicio=inicio, fin=fin)

    return jsonify(data)


@app.route("/api/linea-base/entrenar")
def api_linea_base_entrenar():
    dias = request.args.get("dias", default=30, type=int)

    data = entrenar_linea_base_totalizador(dias=dias)

    return jsonify(data)


@app.route("/api/linea-base/muestras")
def api_linea_base_muestras():
    data = obtener_muestras_linea_base()

    return jsonify({
        "total": len(data),
        "muestras": data
    })

@app.route("/api/produccion")
def api_produccion():
    inicio = request.args.get("inicio", type=int)
    fin = request.args.get("fin", type=int)

    data = obtener_produccion_periodos(inicio_utc=inicio, fin_utc=fin)

    return jsonify({
        "total": len(data),
        "periodos": data
    })


@app.route("/api/produccion/resumen")
def api_produccion_resumen():
    inicio = request.args.get("inicio", type=int)
    fin = request.args.get("fin", type=int)

    if not fin:
        fin = int(time.time())

    if not inicio:
        inicio = fin - 86400

    data = sumar_produccion_rango(inicio, fin)

    return jsonify(data)


@app.route("/api/produccion/modulo")
def api_produccion_modulo():
    inicio = request.args.get("inicio", type=int)
    fin = request.args.get("fin", type=int)
    if inicio is None or fin is None or fin <= inicio:
        return jsonify({"error": "Rango de fechas inválido"}), 400
    return jsonify(obtener_modulo_produccion(inicio, fin))


@app.route("/api/produccion/meses")
def api_produccion_meses():
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT
            substr(fecha, 1, 7) AS mes,
            COUNT(*) AS periodos,
            ROUND(SUM(envases_buenos), 0) AS envases_buenos,
            ROUND(SUM(envases_malos), 0) AS envases_malos,
            ROUND(SUM(envases_buenos + envases_malos), 0) AS envases_total,
            ROUND(
                CASE
                    WHEN SUM(envases_buenos + envases_malos) > 0
                    THEN SUM(envases_buenos) / SUM(envases_buenos + envases_malos)
                    ELSE 0
                END,
                5
            ) AS eficiencia_calc
        FROM produccion_periodo
        GROUP BY substr(fecha, 1, 7)
        ORDER BY mes
    """)

    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    return jsonify({
        "total": len(rows),
        "meses": rows
    })

@app.route("/api/serie-agregada/<int:unit_id>")
def api_serie_agregada(unit_id):
    inicio = request.args.get("inicio", type=int)
    fin = request.args.get("fin", type=int)
    granularidad = request.args.get("granularidad", default="muestra")
    gateway_id = request.args.get("gateway_id", type=int)
    device_id = request.args.get("device_id")
    source_type = request.args.get("source_type")

    if not fin:
        fin = int(time.time())

    if not inicio:
        inicio = fin - 86400

    intervalo = None

    if granularidad == "10min":
        intervalo = 600
    elif granularidad == "30min":
        intervalo = 1800
    elif granularidad == "hora":
        intervalo = 3600
    elif granularidad == "dia":
        intervalo = 86400

    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    where = """
        md.unit_id = ?
        AND CAST(md.timestamp_utc AS INTEGER) >= ?
        AND CAST(md.timestamp_utc AS INTEGER) <= ?
    """

    params = [int(unit_id), int(inicio), int(fin)]

    if gateway_id:
        where += " AND md.gateway_id = ?"
        params.append(int(gateway_id))

    if source_type:
        where += " AND md.source_type = ?"
        params.append(source_type)

    if device_id:
        where += " AND TRIM(md.device_id) = ?"
        params.append(str(device_id))

    # Energías acumuladas: se calculan por delta, no por promedio.
    unidades_energia = [97, 98, 99, 100, 101, 102, 103, 104, 108, 112, 116]

    if intervalo is None or granularidad == "muestra":
        cur.execute(f"""
            SELECT
                CAST(md.timestamp_utc AS INTEGER) AS timestamp_utc,
                md.gateway_id,
                md.source_type,
                NULLIF(TRIM(md.device_id), '') AS device_id,
                md.unit_id,
                u.name AS variable,
                u.simbol AS simbolo,
                md.valor
            FROM mediciones_detalle md
            LEFT JOIN unidades u
                ON md.unit_id = u.unit_id
            WHERE {where}
            ORDER BY CAST(md.timestamp_utc AS INTEGER) ASC, md.id ASC
            LIMIT 5000
        """, params)

        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        return jsonify({
            "unit_id": unit_id,
            "granularidad": granularidad,
            "tipo_calculo": "muestra",
            "total": len(rows),
            "serie": rows
        })

    bucket_expr = f"CAST((CAST(md.timestamp_utc AS INTEGER) / {intervalo}) AS INTEGER) * {intervalo}"

    if unit_id in unidades_energia:
        # Para energía acumulada:
        # consumo del bucket = max(valor) - min(valor)
        cur.execute(f"""
            SELECT
                {bucket_expr} AS timestamp_utc,
                md.gateway_id,
                md.source_type,
                NULLIF(TRIM(md.device_id), '') AS device_id,
                md.unit_id,
                u.name AS variable,
                u.simbol AS simbolo,
                MIN(CAST(md.valor AS REAL)) AS valor_min,
                MAX(CAST(md.valor AS REAL)) AS valor_max,
                ROUND(MAX(CAST(md.valor AS REAL)) - MIN(CAST(md.valor AS REAL)), 6) AS valor
            FROM mediciones_detalle md
            LEFT JOIN unidades u
                ON md.unit_id = u.unit_id
            WHERE {where}
            GROUP BY
                {bucket_expr},
                md.gateway_id,
                md.source_type,
                NULLIF(TRIM(md.device_id), ''),
                md.unit_id
            ORDER BY timestamp_utc ASC
            LIMIT 5000
        """, params)

        tipo_calculo = "delta_acumulado"

    else:
        # Para potencia, corriente, voltaje, FP, THD, temperatura:
        # promedio por bucket.
        cur.execute(f"""
            SELECT
                {bucket_expr} AS timestamp_utc,
                md.gateway_id,
                md.source_type,
                NULLIF(TRIM(md.device_id), '') AS device_id,
                md.unit_id,
                u.name AS variable,
                u.simbol AS simbolo,
                ROUND(AVG(CAST(md.valor AS REAL)), 6) AS valor,
                ROUND(MIN(CAST(md.valor AS REAL)), 6) AS valor_min,
                ROUND(MAX(CAST(md.valor AS REAL)), 6) AS valor_max
            FROM mediciones_detalle md
            LEFT JOIN unidades u
                ON md.unit_id = u.unit_id
            WHERE {where}
            GROUP BY
                {bucket_expr},
                md.gateway_id,
                md.source_type,
                NULLIF(TRIM(md.device_id), ''),
                md.unit_id
            ORDER BY timestamp_utc ASC
            LIMIT 5000
        """, params)

        tipo_calculo = "promedio"

    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    return jsonify({
        "unit_id": unit_id,
        "granularidad": granularidad,
        "tipo_calculo": tipo_calculo,
        "total": len(rows),
        "serie": rows
    })
    
    
@app.route("/api/variable-historica")
def api_variable_historica():
    device_id = request.args.get("device_id", default="24")
    unit_id = request.args.get("unit_id", type=int)
    inicio = request.args.get("inicio", type=int)
    fin = request.args.get("fin", type=int)
    limite = request.args.get("limite", default=5000, type=int)

    if unit_id is None:
        return jsonify({
            "ok": False,
            "error": "Falta unit_id"
        }), 400

    if not fin:
        fin = int(time.time())

    if not inicio:
        inicio = fin - 86400

    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT
            CAST(md.timestamp_utc AS INTEGER) AS timestamp_utc,
            CAST(md.valor AS REAL) AS valor,
            COALESCE(u.name, 'Variable ' || md.unit_id) AS nombre,
            COALESCE(u.simbol, '') AS unidad
        FROM mediciones_detalle md
        LEFT JOIN unidades u
            ON md.unit_id = u.unit_id
        WHERE md.device_id = ?
          AND md.unit_id = ?
          AND CAST(md.timestamp_utc AS INTEGER) >= ?
          AND CAST(md.timestamp_utc AS INTEGER) <= ?
        ORDER BY CAST(md.timestamp_utc AS INTEGER) ASC
        LIMIT ?
    """, (
        str(device_id),
        int(unit_id),
        int(inicio),
        int(fin),
        int(limite)
    ))

    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    return jsonify({
        "ok": True,
        "device_id": device_id,
        "unit_id": unit_id,
        "total": len(rows),
        "data": rows
    })

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=8080,
        debug=True
    )
