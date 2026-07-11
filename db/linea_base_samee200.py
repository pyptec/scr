import os
import math
import random
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv

from db.samee200_db import get_conn
from db.kpi_samee200 import resumen_kpi_samee200

load_dotenv("/home/pi/SAMEE200/scr/.env")

MODELO_OFICIAL_AOKI = {
    "nombre_modelo": "LB_AOKI_ENVASES_HORAS_PRODUCTIVAS",
    "variable_dependiente": "kwh_proceso_aoki",
    "variables_independientes": ["envases_buenos", "horas_productivas"],
    "intercepto": 514.50,
    "coef_envases_buenos": 0.005018,
    "coef_horas_productivas": 16.5198,
    "r2": 0.9278,
    "r2_ajustado": 0.9248,
    "cv_rmse_pct": 3.64,
    "oficial": True
}


def init_linea_base_db():
    """
    Crea tabla de muestras diarias para línea base energética.

    Esta tabla permite trabajar la línea base ISO 50001 aunque todavía
    no se tenga cargado el Excel real de producción diaria.
    """

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS linea_base_muestras (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL UNIQUE,
            linea TEXT,
            producto TEXT,
            envases INTEGER,
            kwh_totalizador REAL,
            kwh_proceso REAL,
            fuente TEXT DEFAULT 'simulado',
            observacion TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


def generar_muestras_base_simuladas(dias=30):
    """
    Genera datos diarios simulados para línea base.

    Supuesto industrial:
    - Producción: 29.000 a 32.000 envases/día
    - Totalizador: energía diaria asociada a producción + carga base
    - Proceso Aoki: energía diaria del proceso principal

    Estos datos son preliminares para validar el método.
    Después se reemplazan por datos reales de producción.
    """

    init_linea_base_db()

    prod_min = int(os.getenv("PRODUCCION_MIN_DIA", "29000"))
    prod_max = int(os.getenv("PRODUCCION_MAX_DIA", "32000"))

    linea = os.getenv("LINEA_PRODUCCION", "AOKI")
    producto = os.getenv("PRODUCTO_BASE", "Botella_1L")

    hoy = datetime.now(timezone.utc).date()

    conn = get_conn()
    cur = conn.cursor()

    muestras_insertadas = 0

    for i in range(dias, 0, -1):
        fecha = hoy - timedelta(days=i)

        envases = random.randint(prod_min, prod_max)

        # Modelo simulado:
        # Totalizador = carga base + consumo variable por envase + ruido
        # Aproximadamente 32 a 38 kWh / 1000 envases
        carga_base_totalizador = random.uniform(70, 120)
        kwh_por_envase_totalizador = random.uniform(0.030, 0.036)
        ruido_totalizador = random.uniform(-35, 35)

        kwh_totalizador = (
            carga_base_totalizador
            + kwh_por_envase_totalizador * envases
            + ruido_totalizador
        )

        # Proceso = consumo principal del proceso Aoki
        # Aproximadamente 19 a 24 kWh / 1000 envases
        carga_base_proceso = random.uniform(35, 70)
        kwh_por_envase_proceso = random.uniform(0.019, 0.024)
        ruido_proceso = random.uniform(-20, 20)

        kwh_proceso = (
            carga_base_proceso
            + kwh_por_envase_proceso * envases
            + ruido_proceso
        )

        cur.execute("""
            INSERT OR IGNORE INTO linea_base_muestras (
                fecha,
                linea,
                producto,
                envases,
                kwh_totalizador,
                kwh_proceso,
                fuente,
                observacion
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            fecha.isoformat(),
            linea,
            producto,
            int(envases),
            round(kwh_totalizador, 3),
            round(kwh_proceso, 3),
            "simulado",
            "Muestra simulada para validación de línea base ISO 50001"
        ))

        if cur.rowcount > 0:
            muestras_insertadas += 1

    conn.commit()
    conn.close()

    return muestras_insertadas


def obtener_muestras_linea_base():
    init_linea_base_db()

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            fecha,
            linea,
            producto,
            envases,
            kwh_totalizador,
            kwh_proceso,
            fuente
        FROM linea_base_muestras
        ORDER BY fecha ASC
    """)

    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    return rows


def calcular_regresion_lineal(x, y):
    """
    Calcula regresión lineal simple:
        y = beta0 + beta1*x

    Retorna:
        beta0, beta1, r2, mae, rmse
    """

    n = len(x)

    if n < 2:
        return None

    x = [float(v) for v in x]
    y = [float(v) for v in y]

    media_x = sum(x) / n
    media_y = sum(y) / n

    sxx = sum((xi - media_x) ** 2 for xi in x)
    sxy = sum((xi - media_x) * (yi - media_y) for xi, yi in zip(x, y))

    if sxx == 0:
        return None

    beta1 = sxy / sxx
    beta0 = media_y - beta1 * media_x

    y_pred = [beta0 + beta1 * xi for xi in x]

    ss_res = sum((yi - yp) ** 2 for yi, yp in zip(y, y_pred))
    ss_tot = sum((yi - media_y) ** 2 for yi in y)

    if ss_tot == 0:
        r2 = 0
    else:
        r2 = 1 - (ss_res / ss_tot)

    errores_abs = [abs(yi - yp) for yi, yp in zip(y, y_pred)]
    mae = sum(errores_abs) / n

    rmse = math.sqrt(ss_res / n)

    return {
        "beta0": round(beta0, 6),
        "beta1": round(beta1, 9),
        "r2": round(r2, 5),
        "mae": round(mae, 5),
        "rmse": round(rmse, 5)
    }


def entrenar_linea_base_totalizador(dias=30):
    """
    Entrena la línea base energética del totalizador:

        kWh_totalizador = beta0 + beta1 * envases

    Guarda el modelo activo en tabla linea_base_energia.
    """

    init_linea_base_db()

    generar_muestras_base_simuladas(dias=dias)

    muestras = obtener_muestras_linea_base()

    if len(muestras) < 2:
        return {
            "ok": False,
            "error": "No hay suficientes muestras para entrenar línea base"
        }

    x = [m["envases"] for m in muestras]
    y = [m["kwh_totalizador"] for m in muestras]

    modelo = calcular_regresion_lineal(x, y)

    if modelo is None:
        return {
            "ok": False,
            "error": "No fue posible calcular la regresión"
        }

    fecha_inicio = muestras[0]["fecha"]
    fecha_fin = muestras[-1]["fecha"]

    conn = get_conn()
    cur = conn.cursor()

    # Desactiva modelos anteriores
    cur.execute("""
        UPDATE linea_base_energia
        SET activo = 0
        WHERE nombre_modelo = 'LB_TOTALIZADOR_ENVASES'
    """)

    cur.execute("""
        INSERT INTO linea_base_energia (
            nombre_modelo,
            fecha_inicio_base,
            fecha_fin_base,
            variable_dependiente,
            variable_independiente,
            beta0,
            beta1,
            r2,
            mae,
            rmse,
            activo
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "LB_TOTALIZADOR_ENVASES",
        fecha_inicio,
        fecha_fin,
        "kwh_totalizador",
        "envases",
        modelo["beta0"],
        modelo["beta1"],
        modelo["r2"],
        modelo["mae"],
        modelo["rmse"],
        1
    ))

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "modelo": {
            "nombre_modelo": "LB_TOTALIZADOR_ENVASES",
            "fecha_inicio_base": fecha_inicio,
            "fecha_fin_base": fecha_fin,
            "variable_dependiente": "kwh_totalizador",
            "variable_independiente": "envases",
            **modelo
        },
        "muestras": len(muestras)
    }


def obtener_modelo_activo():
    """Retorna la línea base oficial validada para el proceso Aoki."""
    return dict(MODELO_OFICIAL_AOKI)


def evaluar_desempeno_actual(inicio=None, fin=None):
    """
    Evalúa el desempeño energético actual contra la línea base.

    Compara:
        Energía real medida en SQLite
        vs
        Energía esperada por modelo ISO 50001
    """

    modelo = obtener_modelo_activo()

    kpi = resumen_kpi_samee200(inicio=inicio, fin=fin)

    energia_real = float(kpi["proceso"]["energia_kwh"])
    envases_buenos = float(kpi["produccion"].get("envases_buenos", 0) or 0)
    horas_productivas = float(kpi["produccion"].get("horas_productivas", 0) or 0)
    horas_programadas = float(kpi["produccion"].get("horas_programadas", 0) or 0)
    jornadas_equivalentes = horas_programadas / 24

    energia_esperada = (
        modelo["intercepto"] * jornadas_equivalentes
        + modelo["coef_envases_buenos"] * envases_buenos
        + modelo["coef_horas_productivas"] * horas_productivas
    )

    desviacion_kwh = energia_real - energia_esperada

    if energia_esperada != 0:
        desviacion_pct = desviacion_kwh / energia_esperada * 100
    else:
        desviacion_pct = 0

    tarifa_kwh = float(os.getenv("TARIFA_KWH", "950"))
    factor_co2 = float(os.getenv("FACTOR_CO2_KG_KWH", "0.164"))

    # Si desviación es negativa, hay ahorro frente a línea base.
    ahorro_kwh = max(energia_esperada - energia_real, 0)
    sobreconsumo_kwh = max(energia_real - energia_esperada, 0)

    resultado = {
        "modelo": modelo,
        "periodo": {
            "inicio": kpi["inicio"],
            "fin": kpi["fin"]
        },
        "produccion": kpi["produccion"],
        "variables_modelo": {
            "envases_buenos": round(envases_buenos, 2),
            "horas_productivas": round(horas_productivas, 3),
            "horas_programadas": round(horas_programadas, 3),
            "jornadas_equivalentes_24h": round(jornadas_equivalentes, 5)
        },
        "energia": {
            "real_kwh": round(energia_real, 3),
            "esperada_kwh": round(energia_esperada, 3),
            "desviacion_kwh": round(desviacion_kwh, 3),
            "desviacion_pct": round(desviacion_pct, 2),
            "ahorro_kwh": round(ahorro_kwh, 3),
            "sobreconsumo_kwh": round(sobreconsumo_kwh, 3)
        },
        "impacto": {
            "ahorro_cop": round(ahorro_kwh * tarifa_kwh, 0),
            "sobreconsumo_cop": round(sobreconsumo_kwh * tarifa_kwh, 0),
            "co2_evitable_kg": round(ahorro_kwh * factor_co2, 2),
            "co2_adicional_kg": round(sobreconsumo_kwh * factor_co2, 2),
            "tarifa_kwh": tarifa_kwh,
            "factor_co2_kg_kwh": factor_co2
        }
    }

    if desviacion_pct <= -5:
        resultado["clasificacion"] = "MEJORA_ENERGETICA"
        resultado["mensaje"] = "El consumo real está por debajo de la línea base."
    elif desviacion_pct >= 5:
        resultado["clasificacion"] = "DESVIACION_SIGNIFICATIVA"
        resultado["mensaje"] = "El consumo real supera la línea base esperada."
    else:
        resultado["clasificacion"] = "DESEMPEÑO_NORMAL"
        resultado["mensaje"] = "El consumo está dentro del rango esperado."

    return resultado
