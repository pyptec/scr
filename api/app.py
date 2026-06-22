from flask import Flask, request
from db.kpi_solar import resumen_periodo
from db.kpi_solar import potencia_actual_kw
from db.samee100_db import get_conn
from flask import Flask, request, render_template
from pathlib import Path
from db.kpi_solar import energia_diaria_generada


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
    fecha_inicio = request.args.get("inicio", "0")
    fecha_fin = request.args.get("fin", "9999999999")
    limite = int(request.args.get("limite", 1000))

    conn = get_conn()
    cur = conn.cursor()

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
    conn.close()

    return {
        "unit_id": unit_id,
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
            md.unit_id,
            u.name AS variable,
            u.simbol As simbolo
        FROM mediciones_detalle md
        LEFT JOIN unidades u
            ON md.unit_id = u.unit_id
        ORDER BY md.unit_id ASC
    """)

    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    return {
        "total": len(rows),
        "variables": rows
    }
 
 
if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=8080,
        debug=True
    )