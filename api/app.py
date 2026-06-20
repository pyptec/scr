from flask import Flask
from db.kpi_solar import resumen_periodo

app = Flask(__name__)

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

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=8080,
        debug=True
    )