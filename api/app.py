from flask import Flask, request
from db.kpi_solar import resumen_periodo
from db.kpi_solar import potencia_actual_kw
from db.samee100_db import get_conn
from flask import Flask, request, render_template
from pathlib import Path
from db.kpi_solar import energia_diaria_generada
from db.kpi_solar import reporte_kpi_energetico
from db.kpi_solar import rango_real_datos
from flask import send_file
from db.reporte_excel import crear_reporte_excel


BASE_DIR = Path(__file__).resolve().parent.parent

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static")
)


@app.route("/api/variable/<int:unit_id>")
def api_variable(unit_id):
    fecha_inicio = request.args.get("inicio", "0")
    fecha_fin = request.args.get("fin", "9999999999")
    limite = int(request.args.get("limite", 500))

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            timestamp_utc,
            device_id,
            nombre,
            unit_id,
            name,
            simbol,
            valor
        FROM vw_mediciones
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

    datos = [dict(r) for r in cur.fetchall()]
    conn.close()

    return {
        "unit_id": unit_id,
        "total": len(datos),
        "datos": datos
    }

@app.route("/api/dashboard")
def api_dashboard():

    fecha_inicio = request.args.get("inicio", "0")
    fecha_fin = request.args.get("fin", "9999999999")

    from db.kpi_solar import resumen_periodo

    return resumen_periodo(
        fecha_inicio,
        fecha_fin
    )
@app.route("/")
def home():

    return {
        "nombre": "SAMEE100 Solar",
        "estado": "online"
    }


@app.route("/api/resumen")
def api_resumen():

    return resumen_periodo(
        "0",
        "9999999999"
    )

@app.route("/api/potencia")
def api_potencia():

    from db.kpi_solar import potencia_actual_kw

    return {
        "potencia_kw": potencia_actual_kw()
    }
    
@app.route("/api/serie/<int:unit_id>")
def api_serie(unit_id):
    inicio = request.args.get("inicio", "0")
    fin = request.args.get("fin", "9999999999")
    limite = int(request.args.get("limite", "500"))

    gateway_id = request.args.get("gateway_id")
    device_id = request.args.get("device_id")
    source_type = request.args.get("source_type")

    conn = get_conn()
    cur = conn.cursor()

    where = """
        md.unit_id = ?
        AND md.timestamp_utc >= ?
        AND md.timestamp_utc <= ?
    """

    params = [
        unit_id,
        inicio,
        fin
    ]

    if source_type:
        where += """
            AND (
                md.source_type = ?
                OR (
                    md.source_type IS NULL
                    AND ? = 'device'
                    AND md.device_id IS NOT NULL
                    AND TRIM(md.device_id) <> ''
                )
            )
        """
        params.extend([source_type, source_type])

    if gateway_id:
        where += """
            AND COALESCE(md.gateway_id, d.gateway_id) = ?
        """
        params.append(int(gateway_id))

    if device_id and device_id not in ["null", "None", ""]:
        where += """
            AND TRIM(md.device_id) = ?
        """
        params.append(str(device_id))

    if source_type == "gateway":
        where += """
            AND (md.device_id IS NULL OR TRIM(md.device_id) = '')
        """

    cur.execute(f"""
        SELECT
            md.timestamp_utc,
            md.valor,
            md.unit_id,
            COALESCE(md.gateway_id, d.gateway_id) AS gateway_id,
            g.nombre AS gateway,
            md.source_type,
            NULLIF(TRIM(md.device_id), '') AS device_id,
            d.nombre AS dispositivo,
            u.name AS variable,
            u.simbol AS simbolo
        FROM mediciones_detalle md
        LEFT JOIN dispositivos d
            ON CAST(NULLIF(TRIM(md.device_id), '') AS INTEGER) = d.device_id
        LEFT JOIN gateways g
            ON COALESCE(md.gateway_id, d.gateway_id) = g.gateway_id
        LEFT JOIN unidades u
            ON md.unit_id = u.unit_id
        WHERE {where}
        ORDER BY md.timestamp_utc ASC
        LIMIT ?
    """, params + [limite])

    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    return {
        "total": len(rows),
        "serie": rows
    }
@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")    

@app.route("/api/energia/dia")
def api_energia_dia():
    limite = int(request.args.get("limite", 30))

    return {
        "unit_id": 104,
        "total": limite,
        "datos": energia_diaria_generada(limite_dias=limite)
    }
   
@app.route("/api/series")
def api_series():
    ids = request.args.get("ids", "")
    fecha_inicio = request.args.get("inicio", "0")
    fecha_fin = request.args.get("fin", "9999999999")
    limite = int(request.args.get("limite", 1000))

    unit_ids = [
        int(x.strip())
        for x in ids.split(",")
        if x.strip().isdigit()
    ]

    conn = get_conn()
    cur = conn.cursor()

    resultado = {}

    for unit_id in unit_ids:
        cur.execute("""
            SELECT
                timestamp_utc,
                unit_id,
                variable,
                simbol,
                valor
            FROM vw_mediciones
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

        rows = [dict(r) for r in cur.fetchall()]
        resultado[str(unit_id)] = rows

    conn.close()

    return {
        "unit_ids": unit_ids,
        "series": resultado
    }  

@app.route("/api/variables")
def api_variables():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT DISTINCT
            COALESCE(md.gateway_id, d.gateway_id) AS gateway_id,
            g.nombre AS gateway,
            g.cliente AS cliente,

            CASE
                WHEN md.source_type IS NOT NULL AND TRIM(md.source_type) <> ''
                    THEN md.source_type
                WHEN md.gateway_id IS NOT NULL
                     AND (md.device_id IS NULL OR TRIM(md.device_id) = '')
                    THEN 'gateway'
                WHEN md.device_id IS NOT NULL
                     AND TRIM(md.device_id) <> ''
                    THEN 'device'
                ELSE 'unknown'
            END AS source_type,

            NULLIF(TRIM(md.device_id), '') AS device_id,
            d.nombre AS dispositivo,
            d.tipo AS tipo_dispositivo,
            d.ubicacion AS ubicacion_dispositivo,

            md.unit_id,
            u.name AS variable,
            u.simbol AS simbolo

        FROM mediciones_detalle md

        LEFT JOIN dispositivos d
            ON CAST(NULLIF(TRIM(md.device_id), '') AS INTEGER) = d.device_id

        LEFT JOIN gateways g
            ON COALESCE(md.gateway_id, d.gateway_id) = g.gateway_id

        LEFT JOIN unidades u
            ON md.unit_id = u.unit_id

        ORDER BY
            COALESCE(md.gateway_id, d.gateway_id) ASC,
            source_type ASC,
            CAST(NULLIF(TRIM(md.device_id), '') AS INTEGER) ASC,
            md.unit_id ASC
    """)

    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    return {
        "total": len(rows),
        "variables": rows
    }
 
@app.route("/api/ultimos")
def api_ultimos():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            COALESCE(md.gateway_id, d.gateway_id) AS gateway_id,
            g.nombre AS gateway,
            g.cliente AS cliente,

            CASE
                WHEN md.source_type IS NOT NULL AND TRIM(md.source_type) <> ''
                    THEN md.source_type
                WHEN md.gateway_id IS NOT NULL
                     AND (md.device_id IS NULL OR TRIM(md.device_id) = '')
                    THEN 'gateway'
                WHEN md.device_id IS NOT NULL
                     AND TRIM(md.device_id) <> ''
                    THEN 'device'
                ELSE 'unknown'
            END AS source_type,

            NULLIF(TRIM(md.device_id), '') AS device_id,
            d.nombre AS dispositivo,
            d.tipo AS tipo_dispositivo,
            d.ubicacion AS ubicacion_dispositivo,

            md.unit_id,
            u.name AS variable,
            u.simbol,
            md.valor,
            md.timestamp_utc

        FROM mediciones_detalle md

        INNER JOIN (
            SELECT
                COALESCE(md2.gateway_id, d2.gateway_id) AS gateway_id_resuelto,

                CASE
                    WHEN md2.source_type IS NOT NULL AND TRIM(md2.source_type) <> ''
                        THEN md2.source_type
                    WHEN md2.gateway_id IS NOT NULL
                         AND (md2.device_id IS NULL OR TRIM(md2.device_id) = '')
                        THEN 'gateway'
                    WHEN md2.device_id IS NOT NULL
                         AND TRIM(md2.device_id) <> ''
                        THEN 'device'
                    ELSE 'unknown'
                END AS source_type_resuelto,

                NULLIF(TRIM(md2.device_id), '') AS device_id_resuelto,
                md2.unit_id,
                MAX(md2.id) AS max_id

            FROM mediciones_detalle md2

            LEFT JOIN dispositivos d2
                ON CAST(NULLIF(TRIM(md2.device_id), '') AS INTEGER) = d2.device_id

            GROUP BY
                COALESCE(md2.gateway_id, d2.gateway_id),
                source_type_resuelto,
                NULLIF(TRIM(md2.device_id), ''),
                md2.unit_id
        ) ult
            ON md.id = ult.max_id

        LEFT JOIN dispositivos d
            ON CAST(NULLIF(TRIM(md.device_id), '') AS INTEGER) = d.device_id

        LEFT JOIN gateways g
            ON COALESCE(md.gateway_id, d.gateway_id) = g.gateway_id

        LEFT JOIN unidades u
            ON md.unit_id = u.unit_id

        ORDER BY
            COALESCE(md.gateway_id, d.gateway_id) ASC,
            source_type ASC,
            CAST(NULLIF(TRIM(md.device_id), '') AS INTEGER) ASC,
            md.unit_id ASC
    """)

    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    return {
        "total": len(rows),
        "datos": rows
    }
@app.route("/api/reporte/kpi")
def api_reporte_kpi():
    fecha_inicio = request.args.get("inicio", "0")
    fecha_fin = request.args.get("fin", "9999999999")

    data = reporte_kpi_energetico(fecha_inicio, fecha_fin)
    rango_real = rango_real_datos(fecha_inicio, fecha_fin)

    inicio_real = rango_real.get("inicio_real")
    fin_real = rango_real.get("fin_real")

    data["periodo"] = {
        "inicio_consulta_utc": fecha_inicio,
        "fin_consulta_utc": fecha_fin,

        "inicio_real_utc": inicio_real,
        "fin_real_utc": fin_real,

        "inicio_colombia": convertir_utc_a_colombia(inicio_real),
        "fin_colombia": convertir_utc_a_colombia(fin_real)
    }

    return data
     
from datetime import datetime, timezone, timedelta

def convertir_utc_a_colombia(timestamp_utc):
    try:
        if timestamp_utc is None:
            return ""

        if str(timestamp_utc).isdigit():
            dt_utc = datetime.fromtimestamp(
                int(timestamp_utc),
                tz=timezone.utc
            )
        else:
            texto = str(timestamp_utc).replace("Z", "+00:00")
            dt_utc = datetime.fromisoformat(texto)

            if dt_utc.tzinfo is None:
                dt_utc = dt_utc.replace(tzinfo=timezone.utc)

        dt_col = dt_utc.astimezone(
            timezone(timedelta(hours=-5))
        )

        return dt_col.strftime("%Y-%m-%d %H:%M:%S")

    except Exception:
        return ""
 
@app.route("/api/reporte/excel")
def api_reporte_excel():
    fecha_inicio = request.args.get("inicio", "0")
    fecha_fin = request.args.get("fin", "9999999999")
    variables = request.args.get("variables", "61,104,100")

    output = crear_reporte_excel(
        fecha_inicio,
        fecha_fin,
        variables
    )

    nombre_archivo = f"samee100_reporte_{fecha_inicio}_{fecha_fin}.xlsx"

    return send_file(
        output,
        as_attachment=True,
        download_name=nombre_archivo,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )   
    
    
if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=8080,
        debug=True
    )