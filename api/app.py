from flask import Flask, request
from db.kpi_solar import resumen_periodo
from db.kpi_solar import potencia_actual_kw
from db.samee100_db import get_conn
from flask import Flask, request, render_template
from pathlib import Path



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

    from db.kpi_solar import resumen_periodo

    return resumen_periodo(
        "0",
        "9999999999"
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
            name AS variable,
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
    
if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=8080,
        debug=True
    )