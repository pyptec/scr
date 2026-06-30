from flask import Flask, request
from db.kpi_solar import resumen_periodo
from db.kpi_solar import potencia_actual_kw
from db.samee100_db import get_conn, init_db
from flask import Flask, request, render_template
from pathlib import Path
from db.kpi_solar import energia_diaria_generada
from db.kpi_solar import reporte_kpi_energetico
from db.kpi_solar import rango_real_datos
from flask import send_file
from db.reporte_excel import crear_reporte_excel
import time
import sqlite3
from flask import jsonify
import os
from dotenv import load_dotenv
import util

load_dotenv("/home/pi/SAMEE100/scr/.env")

BASE_DIR = Path(__file__).resolve().parent.parent

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static")
)

init_db()


def obtener_config_dashboard_desde_yml():
    """
    Lee la configuración activa del dashboard desde el YAML indicado en .env.

    .env:
        DASHBOARD_MEDIDOR_CONFIG=CFG_EASTRON

    Luego usa:
        CFG_EASTRON=/ruta/eastronSDm630.yml
        CFG_EASTRON_SECTION=samee100

    El YAML debe traer:
        gateway:
          gateway_id: 10
          nombre: SAMEE100-PANELES

        device:
          device_id: 39
          nombre: Eastron SDM630
    """

    cfg_name = os.getenv("DASHBOARD_MEDIDOR_CONFIG", "CFG_EASTRON").strip()

    cfg_path = os.getenv(cfg_name)
    cfg_section = os.getenv(f"{cfg_name}_SECTION")

    if not cfg_path or not cfg_section:
        return {
            "gateway_id": None,
            "device_id": "",
            "source_type": "device",
            "medidor_nombre": "Medidor principal",
            "gateway_nombre": "Gateway",
            "cliente": "",
            "ubicacion": "",
            "config_origen": cfg_name,
            "error": f"Config incompleta: {cfg_name}={cfg_path}, {cfg_name}_SECTION={cfg_section}"
        }

    try:
        config = util.cargar_configuracion(cfg_path, cfg_section)

        if not isinstance(config, dict):
            raise ValueError(f"Config YAML inválida: {cfg_path} / {cfg_section}")

        gateway_cfg = config.get("gateway", {}) or {}
        device_cfg = config.get("device", {}) or {}

        source_type = str(config.get("source_type", "device")).lower().strip()

        gateway_id = (
            gateway_cfg.get("gateway_id")
            or config.get("gateway_id")
            or config.get("i")
        )

        device_id = None

        if source_type != "gateway":
            device_id = (
                device_cfg.get("device_id")
                or config.get("id_device")
                or config.get("device_id")
            )

        return {
            "gateway_id": int(gateway_id) if gateway_id not in [None, "", "None"] else None,
            "device_id": str(device_id) if device_id not in [None, "", "None"] else "",
            "source_type": source_type,
            "medidor_nombre": device_cfg.get("nombre", config.get("device_name", "Medidor principal")),
            "gateway_nombre": gateway_cfg.get("nombre", f"Gateway {gateway_id}"),
            "cliente": gateway_cfg.get("cliente", ""),
            "ubicacion": device_cfg.get("ubicacion", gateway_cfg.get("ubicacion", "")),
            "config_origen": cfg_name,
            "cfg_path": cfg_path,
            "cfg_section": cfg_section
        }

    except Exception as e:
        return {
            "gateway_id": None,
            "device_id": "",
            "source_type": "device",
            "medidor_nombre": "Medidor principal",
            "gateway_nombre": "Gateway",
            "cliente": "",
            "ubicacion": "",
            "config_origen": cfg_name,
            "cfg_path": cfg_path,
            "cfg_section": cfg_section,
            "error": str(e)
        }



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
    """
    KPIs principales del dashboard.

    Correcciones:
    - Energía importada/exportada se calcula como delta del acumulado.
    - Potencia se convierte de W a kW.
    - Se filtra por gateway usando COALESCE(md.gateway_id, d.gateway_id).
    """

    inicio = request.args.get("inicio", type=int)
    fin = request.args.get("fin", type=int)

    if not inicio:
        inicio = 0

    if not fin:
        fin = int(time.time())

    cfg_dashboard = obtener_config_dashboard_desde_yml()

    gateway_id = cfg_dashboard.get("gateway_id")
    device_id = str(cfg_dashboard.get("device_id") or "")
    source_type = cfg_dashboard.get("source_type", "device")

    tarifa_kwh = float(os.getenv("TARIFA_KWH", "950"))
    factor_co2 = float(os.getenv("FACTOR_CO2_KG_KWH", "0.164"))

    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        if gateway_id is None or not device_id:
            return jsonify({
                "potencia_actual_kw": 0,
                "generacion_kwh": 0,
                "consumo_kwh": 0,
                "ahorro_cop": 0,
                "co2_evitado_kg": 0,
                "error": "No hay gateway_id/device_id configurado para dashboard"
            })

        # unit_id 61 = potencia activa total.
        # En este medidor el valor viene en W, por eso se divide entre 1000.
        potencia_w = obtener_ultimo_valor_periodo(
            cur=cur,
            unit_id=61,
            inicio=inicio,
            fin=fin,
            gateway_id=gateway_id,
            device_id=device_id,
            source_type=source_type
        )

        potencia_actual_kw = 0.0

        if potencia_w is not None:
            potencia_actual_kw = round(potencia_w / 1000.0, 3)

        # unit_id 100 = energía importada acumulada
        consumo_kwh = calcular_delta_acumulado(
            cur=cur,
            unit_id=100,
            inicio=inicio,
            fin=fin,
            gateway_id=gateway_id,
            device_id=device_id,
            source_type=source_type
        )

        # unit_id 104 = energía exportada/generada acumulada
        generacion_kwh = calcular_delta_acumulado(
            cur=cur,
            unit_id=104,
            inicio=inicio,
            fin=fin,
            gateway_id=gateway_id,
            device_id=device_id,
            source_type=source_type
        )

        ahorro_cop = round(generacion_kwh * tarifa_kwh, 0)
        co2_evitado_kg = round(generacion_kwh * factor_co2, 2)

        conn.close()

        return jsonify({
            "potencia_actual_kw": potencia_actual_kw,
            "generacion_kwh": generacion_kwh,
            "consumo_kwh": consumo_kwh,
            "ahorro_cop": ahorro_cop,
            "co2_evitado_kg": co2_evitado_kg,
            "tarifa_kwh": tarifa_kwh,
            "factor_co2_kg_kwh": factor_co2,
            "gateway_id": gateway_id,
            "device_id": device_id,
            "source_type": source_type,
            "inicio": inicio,
            "fin": fin
        })

    except Exception as e:
        conn.close()

        return jsonify({
            "error": str(e),
            "potencia_actual_kw": 0,
            "generacion_kwh": 0,
            "consumo_kwh": 0,
            "ahorro_cop": 0,
            "co2_evitado_kg": 0
        }), 500
        
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
    """
    Generación diaria calculada desde el contador acumulado unit_id 104.

    Corrección:
    - No usa MAX - MIN directo.
    - No usa acumulado bruto.
    - Usa calcular_delta_acumulado(), que suma incrementos válidos
      y descarta saltos anómalos.
    """

    inicio = request.args.get("inicio", type=int)
    fin = request.args.get("fin", type=int)
    limite = request.args.get("limite", default=30, type=int)

    if not inicio:
        inicio = 0

    if not fin:
        fin = int(time.time())

    cfg_dashboard = obtener_config_dashboard_desde_yml()

    gateway_id = cfg_dashboard.get("gateway_id")
    device_id = str(cfg_dashboard.get("device_id") or "")
    source_type = cfg_dashboard.get("source_type", "device")

    if gateway_id is None or not device_id:
        return jsonify({
            "unit_id": 104,
            "total": 0,
            "datos": [],
            "error": "No hay gateway_id/device_id configurado para dashboard"
        })

    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        # Obtener días reales con datos dentro del rango consultado.
        cur.execute("""
            SELECT DISTINCT
                date(datetime(CAST(md.timestamp_utc AS INTEGER), 'unixepoch', '-5 hours')) AS dia
            FROM mediciones_detalle md
            LEFT JOIN dispositivos d
                ON CAST(NULLIF(TRIM(md.device_id), '') AS INTEGER) = d.device_id
            WHERE md.unit_id = 104
              AND COALESCE(md.gateway_id, d.gateway_id) = ?
              AND md.source_type = ?
              AND TRIM(md.device_id) = ?
              AND CAST(md.timestamp_utc AS INTEGER) BETWEEN ? AND ?
            ORDER BY dia DESC
            LIMIT ?
        """, (
            int(gateway_id),
            str(source_type),
            str(device_id),
            int(inicio),
            int(fin),
            int(limite)
        ))

        dias = [row["dia"] for row in cur.fetchall()]
        dias = list(reversed(dias))

        datos = []

        tz_colombia = timezone(timedelta(hours=-5))

        for dia in dias:
            inicio_dia_col = datetime.fromisoformat(
                f"{dia}T00:00:00"
            ).replace(tzinfo=tz_colombia)

            fin_dia_col = datetime.fromisoformat(
                f"{dia}T23:59:59"
            ).replace(tzinfo=tz_colombia)

            inicio_dia_utc = int(
                inicio_dia_col.astimezone(timezone.utc).timestamp()
            )

            fin_dia_utc = int(
                fin_dia_col.astimezone(timezone.utc).timestamp()
            )

            # Recortar contra el rango solicitado por el usuario.
            inicio_periodo = max(inicio_dia_utc, int(inicio))
            fin_periodo = min(fin_dia_utc, int(fin))

            kwh = calcular_delta_acumulado(
                cur=cur,
                unit_id=104,
                inicio=inicio_periodo,
                fin=fin_periodo,
                gateway_id=gateway_id,
                device_id=device_id,
                source_type=source_type
            )

            datos.append({
                "dia": dia,
                "kwh": round(kwh, 3),
                "inicio": inicio_periodo,
                "fin": fin_periodo
            })

        conn.close()

        return jsonify({
            "unit_id": 104,
            "gateway_id": gateway_id,
            "device_id": device_id,
            "source_type": source_type,
            "total": len(datos),
            "datos": datos
        })

    except Exception as e:
        conn.close()

        return jsonify({
            "unit_id": 104,
            "total": 0,
            "datos": [],
            "error": str(e)
        }), 500
   
@app.route("/api/series")
def api_series():
    ids = request.args.get("ids", "")
    fecha_inicio = request.args.get("inicio", "0")
    fecha_fin = request.args.get("fin", "9999999999")
    limite = int(request.args.get("limite", 1000))

    gateway_id = request.args.get("gateway_id")
    device_id = request.args.get("device_id")
    source_type = request.args.get("source_type")

    unit_ids = [
        int(x.strip())
        for x in ids.split(",")
        if x.strip().isdigit()
    ]

    conn = get_conn()
    cur = conn.cursor()

    resultado = {}

    for unit_id in unit_ids:
        where = """
            md.unit_id = ?
            AND md.timestamp_utc >= ?
            AND md.timestamp_utc <= ?
        """

        params = [
            unit_id,
            fecha_inicio,
            fecha_fin
        ]

        if gateway_id:
            where += """
                AND COALESCE(md.gateway_id, d.gateway_id) = ?
            """
            params.append(int(gateway_id))

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
 
@app.route("/api/estado")
def api_estado():
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    ahora = int(time.time())

    cfg_dashboard = obtener_config_dashboard_desde_yml()

    gateway_activo = cfg_dashboard.get("gateway_id")
    device_principal = str(cfg_dashboard.get("device_id") or "")
    source_type_principal = cfg_dashboard.get("source_type", "device")
    nombre_medidor_principal = cfg_dashboard.get("medidor_nombre", "Medidor principal")

    estado = {
        "timestamp_actual": ahora,
        "db": "OK",

        "config_dashboard": cfg_dashboard,

        "gateway_id": gateway_activo,
        "gateway": cfg_dashboard.get("gateway_nombre"),
        "cliente": cfg_dashboard.get("cliente"),

        "medidor_principal_id": device_principal,
        "medidor_principal_nombre": nombre_medidor_principal,
        "medidor_principal_source_type": source_type_principal,

        "ultima_medicion_utc": None,
        "ultima_medicion_colombia": None,
        "edad_segundos": None,
        "estado_datos": "SIN DATOS",

        "ram": None,
        "cpu": None,
        "ip_usb0": None,
        "ip_ethernet": None,
        "connected_meter": None,

        "ultimo_dato_medidor_principal": None,
        "edad_medidor_principal_segundos": None,
        "estado_medidor_principal": "SIN DATOS",

        # Alias temporales para compatibilidad con dashboard.js viejo
        "ultimo_dato_medidor_31": None,
        "edad_medidor_31_segundos": None,
        "estado_medidor_31": "SIN DATOS",

        "total_gateways": 0,
        "total_dispositivos": 0,
        "total_variables": 0
    }

    try:
        # Datos del gateway activo, leído desde YAML
        if gateway_activo is not None:
            cur.execute("""
                SELECT gateway_id, nombre, cliente
                FROM gateways
                WHERE gateway_id = ?
                LIMIT 1
            """, (gateway_activo,))

            row = cur.fetchone()
            if row:
                estado["gateway_id"] = row["gateway_id"]
                estado["gateway"] = row["nombre"]
                estado["cliente"] = row["cliente"]

        # Conteos generales
        cur.execute("SELECT COUNT(*) AS total FROM gateways")
        estado["total_gateways"] = cur.fetchone()["total"]

        cur.execute("SELECT COUNT(*) AS total FROM dispositivos")
        estado["total_dispositivos"] = cur.fetchone()["total"]

        cur.execute("SELECT COUNT(*) AS total FROM unidades")
        estado["total_variables"] = cur.fetchone()["total"]

        # Última medición general
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

        # Última medición del medidor principal configurado por YAML
        ts_medidor = None

        if gateway_activo is not None and device_principal:
            cur.execute("""
                SELECT MAX(CAST(md.timestamp_utc AS INTEGER)) AS ts
                FROM mediciones_detalle md
                LEFT JOIN dispositivos d
                    ON CAST(NULLIF(TRIM(md.device_id), '') AS INTEGER) = d.device_id
                WHERE COALESCE(md.gateway_id, d.gateway_id) = ?
                  AND md.source_type = ?
                  AND TRIM(md.device_id) = ?
            """, (
                gateway_activo,
                source_type_principal,
                device_principal
            ))

            row = cur.fetchone()
            ts_medidor = row["ts"] if row else None

        if ts_medidor:
            ts_medidor = int(ts_medidor)

            estado["ultimo_dato_medidor_principal"] = ts_medidor
            estado["edad_medidor_principal_segundos"] = ahora - ts_medidor

            if estado["edad_medidor_principal_segundos"] <= 900:
                estado["estado_medidor_principal"] = "OK"
            else:
                estado["estado_medidor_principal"] = "SIN DATOS RECIENTES"

        # Alias de compatibilidad para frontend viejo
        estado["ultimo_dato_medidor_31"] = estado["ultimo_dato_medidor_principal"]
        estado["edad_medidor_31_segundos"] = estado["edad_medidor_principal_segundos"]
        estado["estado_medidor_31"] = estado["estado_medidor_principal"]

        def ultimo_valor(unit_id, source_type=None, device_id=None, gateway_id=None):
            sql = """
                SELECT md.valor, md.timestamp_utc
                FROM mediciones_detalle md
                LEFT JOIN dispositivos d
                    ON CAST(NULLIF(TRIM(md.device_id), '') AS INTEGER) = d.device_id
                WHERE md.unit_id = ?
            """
            params = [unit_id]

            if gateway_id is not None:
                sql += " AND COALESCE(md.gateway_id, d.gateway_id) = ?"
                params.append(int(gateway_id))

            if source_type:
                sql += " AND md.source_type = ?"
                params.append(source_type)

            if device_id:
                sql += " AND TRIM(md.device_id) = ?"
                params.append(str(device_id))

            sql += " ORDER BY CAST(md.timestamp_utc AS INTEGER) DESC LIMIT 1"

            cur.execute(sql, params)
            r = cur.fetchone()

            if not r:
                return None

            return r["valor"]

        # Variables internas del sistema. Se toman del gateway activo.
        estado["ram"] = ultimo_valor(135, gateway_id=gateway_activo)
        estado["cpu"] = ultimo_valor(136, gateway_id=gateway_activo)
        estado["ip_usb0"] = ultimo_valor(137, gateway_id=gateway_activo)
        estado["ip_ethernet"] = ultimo_valor(144, gateway_id=gateway_activo)

        # Variable gateway Connected_Meter
        estado["connected_meter"] = ultimo_valor(
            53,
            source_type="gateway",
            gateway_id=gateway_activo
        )

        conn.close()
        return jsonify(estado)

    except Exception as e:
        conn.close()
        return jsonify({
            "db": "ERROR",
            "error": str(e),
            "config_dashboard": cfg_dashboard
        }), 500


@app.route("/api/config_dashboard")
def api_config_dashboard():
    """
    Configuración activa del dashboard leída desde YAML.

    El .env solo indica cuál configuración YAML se usa como medidor principal:
        DASHBOARD_MEDIDOR_CONFIG=CFG_EASTRON
    """

    return jsonify(obtener_config_dashboard_desde_yml())

def obtener_primer_ultimo_valor(cur, unit_id, inicio, fin, gateway_id, device_id, source_type="device"):
    """
    Obtiene primer y último valor de una variable acumulativa dentro del periodo.

    Se usa para energía acumulada:
        energia_periodo = ultimo - primero

    Usa COALESCE(md.gateway_id, d.gateway_id) porque en mediciones_detalle
    algunos registros de device tienen gateway_id vacío.
    """

    params = [
        int(unit_id),
        int(gateway_id),
        str(source_type),
        str(device_id),
        int(inicio),
        int(fin)
    ]

    cur.execute("""
        SELECT
            CAST(md.valor AS REAL) AS valor,
            CAST(md.timestamp_utc AS INTEGER) AS ts
        FROM mediciones_detalle md
        LEFT JOIN dispositivos d
            ON CAST(NULLIF(TRIM(md.device_id), '') AS INTEGER) = d.device_id
        WHERE md.unit_id = ?
          AND COALESCE(md.gateway_id, d.gateway_id) = ?
          AND md.source_type = ?
          AND TRIM(md.device_id) = ?
          AND CAST(md.timestamp_utc AS INTEGER) BETWEEN ? AND ?
        ORDER BY CAST(md.timestamp_utc AS INTEGER) ASC
        LIMIT 1
    """, params)

    primero = cur.fetchone()

    cur.execute("""
        SELECT
            CAST(md.valor AS REAL) AS valor,
            CAST(md.timestamp_utc AS INTEGER) AS ts
        FROM mediciones_detalle md
        LEFT JOIN dispositivos d
            ON CAST(NULLIF(TRIM(md.device_id), '') AS INTEGER) = d.device_id
        WHERE md.unit_id = ?
          AND COALESCE(md.gateway_id, d.gateway_id) = ?
          AND md.source_type = ?
          AND TRIM(md.device_id) = ?
          AND CAST(md.timestamp_utc AS INTEGER) BETWEEN ? AND ?
        ORDER BY CAST(md.timestamp_utc AS INTEGER) DESC
        LIMIT 1
    """, params)

    ultimo = cur.fetchone()

    return primero, ultimo


def calcular_delta_acumulado(cur, unit_id, inicio, fin, gateway_id, device_id, source_type="device"):
    """
    Calcula energía de periodo a partir de un contador acumulado.

    No usa simplemente último - primero, porque si el rango incluye una
    lectura inicial errónea o una mala decodificación antigua, el KPI se infla.

    Estrategia:
    - Lee todas las muestras del periodo.
    - Suma incrementos positivos entre muestras consecutivas.
    - Ignora deltas negativos.
    - Ignora saltos absurdos configurables.
    """

    max_delta_kwh = float(os.getenv("MAX_DELTA_KWH_MUESTRA", "50"))

    cur.execute("""
        SELECT
            CAST(md.valor AS REAL) AS valor,
            CAST(md.timestamp_utc AS INTEGER) AS ts
        FROM mediciones_detalle md
        LEFT JOIN dispositivos d
            ON CAST(NULLIF(TRIM(md.device_id), '') AS INTEGER) = d.device_id
        WHERE md.unit_id = ?
          AND COALESCE(md.gateway_id, d.gateway_id) = ?
          AND md.source_type = ?
          AND TRIM(md.device_id) = ?
          AND CAST(md.timestamp_utc AS INTEGER) BETWEEN ? AND ?
        ORDER BY CAST(md.timestamp_utc AS INTEGER) ASC
    """, (
        int(unit_id),
        int(gateway_id),
        str(source_type),
        str(device_id),
        int(inicio),
        int(fin)
    ))

    filas = cur.fetchall()

    if len(filas) < 2:
        return 0.0

    total = 0.0
    valor_anterior = None

    for fila in filas:
        valor_actual = float(fila["valor"])

        if valor_anterior is None:
            valor_anterior = valor_actual
            continue

        delta = valor_actual - valor_anterior

        # Contador normal: suma incremento positivo razonable
        if 0 <= delta <= max_delta_kwh:
            total += delta

        # Si delta es negativo, puede ser reset o dato malo: se ignora.
        # Si delta es muy grande, puede ser salto por mala decodificación: se ignora.

        valor_anterior = valor_actual

    return round(total, 3)

def obtener_ultimo_valor_periodo(cur, unit_id, inicio, fin, gateway_id, device_id, source_type="device"):
    """
    Obtiene el último valor de una variable dentro del periodo.
    """

    cur.execute("""
        SELECT
            CAST(md.valor AS REAL) AS valor,
            CAST(md.timestamp_utc AS INTEGER) AS ts
        FROM mediciones_detalle md
        LEFT JOIN dispositivos d
            ON CAST(NULLIF(TRIM(md.device_id), '') AS INTEGER) = d.device_id
        WHERE md.unit_id = ?
          AND COALESCE(md.gateway_id, d.gateway_id) = ?
          AND md.source_type = ?
          AND TRIM(md.device_id) = ?
          AND CAST(md.timestamp_utc AS INTEGER) BETWEEN ? AND ?
        ORDER BY CAST(md.timestamp_utc AS INTEGER) DESC
        LIMIT 1
    """, (
        int(unit_id),
        int(gateway_id),
        str(source_type),
        str(device_id),
        int(inicio),
        int(fin)
    ))

    row = cur.fetchone()

    if not row:
        return None

    return float(row["valor"])
    
if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=8080,
        debug=True
    )