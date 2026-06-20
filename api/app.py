from flask import Flask
from db.kpi_solar import resumen_periodo

app = Flask(__name__)


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


if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=8080,
        debug=True
    )