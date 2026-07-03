from dotenv import load_dotenv
import os
import minimalmodbus
import serial
import time
import json
import util
import struct
import awsaccess
import Temp
import fileventqueue
import threading
import eventHandler
import shared
import subprocess
import modbusdevices
import random

from db.samee200_db import init_db
from db.samee200_db import cargar_catalogos_desde_env
from db.samee200_db import guardar_medicion


'''
Parametros del pto serie modbus
'''
serialPort= "/dev/ttyS0"

# Ruta al archivo .env
load_dotenv(dotenv_path="/home/pi/SAMEE200/scr/.env")

# Leer variables como enteros
TIMERCHEQUEOTEMPERATURA = int(os.getenv('TIMERCHEQUEOTEMPERATURA', 60))
TIMERCOLAEVENTOS = int(os.getenv('TIMERCOLAEVENTOS', 60))
TIMERMEDICION = int(os.getenv('TIMERMEDICION', 600))
TIMERPING = int(os.getenv('TIMERPING', 120))
TIMECHECKUSBETHERNET = int(os.getenv('TIMECHECKUSBETHERNET', 600))
TIMECHECK_USB_ETHERNET_TIME = int(os.getenv('TIMECHECK_USB_ETHERNET_TIME', 6))

USAR_HILO_MEDIDOR_10MIN = os.getenv("USAR_HILO_MEDIDOR_10MIN", "true").lower() in ["true", "1", "yes", "si"]

# Estado interno de simulación para mantener acumulados crecientes por device_id
SIM_STATE = {}


def obtener_perfil_simulacion(config):
    """
    Define parámetros internos de simulación según el rol del dispositivo.

    El YAML queda limpio:
        simular: true
        device:
          rol: Proceso
    o
        device:
          rol: Totalizador

    Si algún día se necesita un caso especial, se puede sobrescribir
    opcionalmente desde YAML con un bloque 'simulacion'.
    """

    device_cfg = config.get("device", {}) or {}
    rol = str(device_cfg.get("rol", "")).lower().strip()

    perfiles = {
        "totalizador": {
            "perfil": "industrial_totalizador",
            "potencia_kw_min": 35,
            "potencia_kw_max": 85,
            "fp_min": 0.88,
            "fp_max": 0.98,
            "voltaje_ln_min": 215,
            "voltaje_ln_max": 225,
            "energia_importada_base_kwh": 12000,
            "energia_exportada_base_kwh": 0,
            "incremento_kwh_min": 5,
            "incremento_kwh_max": 14,
            "fases_activas": [1, 2, 3]
        },
        "proceso": {
            "perfil": "industrial_proceso_aoki",
            "potencia_kw_min": 18,
            "potencia_kw_max": 45,
            "fp_min": 0.85,
            "fp_max": 0.97,
            "voltaje_ln_min": 215,
            "voltaje_ln_max": 225,
            "energia_importada_base_kwh": 6000,
            "energia_exportada_base_kwh": 0,
            "incremento_kwh_min": 2,
            "incremento_kwh_max": 8,
            "fases_activas": [1, 2, 3]
        },
        "default": {
            "perfil": "generico",
            "potencia_kw_min": 5,
            "potencia_kw_max": 20,
            "fp_min": 0.88,
            "fp_max": 0.98,
            "voltaje_ln_min": 215,
            "voltaje_ln_max": 225,
            "energia_importada_base_kwh": 1000,
            "energia_exportada_base_kwh": 0,
            "incremento_kwh_min": 1,
            "incremento_kwh_max": 5,
            "fases_activas": [1, 2, 3]
        }
    }

    sim_cfg = perfiles.get(rol, perfiles["default"]).copy()

    # Opcional: permite sobrescribir desde YAML solo si algún día lo necesitas.
    # Si no existe el bloque 'simulacion', no pasa nada.
    sim_cfg.update(config.get("simulacion", {}) or {})

    return sim_cfg
#---------------------------------------------------------------------------------------------------
# Diagnóstico de modo real / simulación
#---------------------------------------------------------------------------------------------------
def es_simulacion_activa(config):
    """
    Retorna True si el YAML tiene simular: true.

    No cambia la lógica de lectura; solo centraliza la validación
    para poder dejar trazabilidad clara en el log.
    """

    if not isinstance(config, dict):
        return False

    return str(config.get("simular", False)).lower().strip() in [
        "true",
        "1",
        "yes",
        "si",
        "sí",
        "on"
    ]


def obtener_ids_config(config):
    """
    Extrae gateway_id y device_id desde el YAML para mostrarlos en logs.
    """

    if not isinstance(config, dict):
        return None, None

    gateway_cfg = config.get("gateway", {}) or {}
    device_cfg = config.get("device", {}) or {}

    gateway_id = (
        gateway_cfg.get("gateway_id")
        or config.get("gateway_id")
        or config.get("i")
    )

    device_id = (
        device_cfg.get("device_id")
        or config.get("id_device")
        or config.get("device_id")
    )

    return gateway_id, device_id


def log_modo_lectura(nombre, config):
    """
    Escribe en el log si el dispositivo está en lectura real o simulación.

    Ejemplos:
        [SIMULACION ACTIVA] EASTRON | gateway_id=10 | device_id=39
        [LECTURA REAL] SHT20 | gateway_id=10 | device_id=26
    """

    gateway_id, device_id = obtener_ids_config(config)

    source_type = "unknown"
    if isinstance(config, dict):
        source_type = str(config.get("source_type", "device")).lower().strip()

    if es_simulacion_activa(config):
        util.logging.warning(
            f"[SIMULACION ACTIVA] {nombre} | "
            f"source_type={source_type} | "
            f"gateway_id={gateway_id} | "
            f"device_id={device_id} | "
            f"Se generarán datos simulados desde payload_event_modbus_simulado()"
        )
    else:
        util.logging.info(
            f"[LECTURA REAL] {nombre} | "
            f"source_type={source_type} | "
            f"gateway_id={gateway_id} | "
            f"device_id={device_id} | "
            f"Lectura por Modbus/dispositivo real"
        )

def guardar_payload_local(payload, origen):
    """
    Guarda una medición en SQLite local.
    No detiene el programa si hay error.
    """

    try:
        ok = guardar_medicion(payload, origen=origen)

        if ok:
            util.logging.info(f"[SQLITE] Medición guardada localmente: {origen}")
        else:
            util.logging.warning(f"[SQLITE] No se pudo guardar medición: {origen}")

    except Exception as e:
        util.logging.error(f"[SQLITE] Error guardando {origen}: {e}")
#---------------------------------------------------------------------------------------------------    
# simulador de datos del medidor eastron
#---------------------------------------------------------------------------------------------------  
def payload_event_modbus_simulado(config):
    """
    Simula payload Modbus para SAMEE200.

    Genera datos coherentes para:
    - Totalizador general
    - Proceso Aoki / compresor
    - SHT20
    - Variables eléctricas principales

    Puntos clave:
    - La energía acumulada siempre crece.
    - La potencia se entrega en W, igual que el medidor real.
    - La corriente se calcula desde P, V y FP.
    - Los perfiles salen del rol definido en YAML.
    """

    valores = []
    unidades = []

    device_id = (
        (config.get("device", {}) or {}).get("device_id")
        or config.get("id_device")
        or config.get("device_id")
    )

    sim_cfg = obtener_perfil_simulacion(config)

    potencia_kw_min = float(sim_cfg.get("potencia_kw_min", 5))
    potencia_kw_max = float(sim_cfg.get("potencia_kw_max", 20))

    fp_min = float(sim_cfg.get("fp_min", 0.88))
    fp_max = float(sim_cfg.get("fp_max", 0.98))

    voltaje_ln_min = float(sim_cfg.get("voltaje_ln_min", 215))
    voltaje_ln_max = float(sim_cfg.get("voltaje_ln_max", 225))

    incremento_kwh_min = float(sim_cfg.get("incremento_kwh_min", 1))
    incremento_kwh_max = float(sim_cfg.get("incremento_kwh_max", 5))

    energia_importada_base = float(sim_cfg.get("energia_importada_base_kwh", 1000.0))
    energia_exportada_base = float(sim_cfg.get("energia_exportada_base_kwh", 0.0))

    fases_activas = sim_cfg.get("fases_activas", [1, 2, 3])
    fases_activas = [int(f) for f in fases_activas]
    num_fases = max(len(fases_activas), 1)

    if device_id not in SIM_STATE:
        SIM_STATE[device_id] = {
            "energia_importada_l1": energia_importada_base / 3,
            "energia_importada_l2": energia_importada_base / 3,
            "energia_importada_l3": energia_importada_base / 3,
            "energia_importada_total": energia_importada_base,
            "energia_exportada_l1": energia_exportada_base / 3,
            "energia_exportada_l2": energia_exportada_base / 3,
            "energia_exportada_l3": energia_exportada_base / 3,
            "energia_exportada_total": energia_exportada_base,
        }

    estado = SIM_STATE[device_id]

    # Incremento energético acumulado por ciclo de medición
    incremento_total = random.uniform(incremento_kwh_min, incremento_kwh_max)
    incremento_fase = incremento_total / num_fases

    if 1 in fases_activas:
        estado["energia_importada_l1"] += incremento_fase

    if 2 in fases_activas:
        estado["energia_importada_l2"] += incremento_fase

    if 3 in fases_activas:
        estado["energia_importada_l3"] += incremento_fase

    estado["energia_importada_total"] = (
        estado["energia_importada_l1"]
        + estado["energia_importada_l2"]
        + estado["energia_importada_l3"]
    )

    # Variables eléctricas simuladas
    vl1 = round(random.uniform(voltaje_ln_min, voltaje_ln_max), 1) if 1 in fases_activas else 0
    vl2 = round(random.uniform(voltaje_ln_min, voltaje_ln_max), 1) if 2 in fases_activas else 0
    vl3 = round(random.uniform(voltaje_ln_min, voltaje_ln_max), 1) if 3 in fases_activas else 0

    u12 = round(vl1 * 1.732, 1) if vl1 and vl2 else 0
    u23 = round(vl2 * 1.732, 1) if vl2 and vl3 else 0
    u31 = round(vl3 * 1.732, 1) if vl3 and vl1 else 0

    fp1 = round(random.uniform(fp_min, fp_max), 3) if 1 in fases_activas else 0
    fp2 = round(random.uniform(fp_min, fp_max), 3) if 2 in fases_activas else 0
    fp3 = round(random.uniform(fp_min, fp_max), 3) if 3 in fases_activas else 0

    ptotal_kw = round(random.uniform(potencia_kw_min, potencia_kw_max), 3)
    p_fase_kw = ptotal_kw / num_fases

    p1_w = round(p_fase_kw * 1000, 1) if 1 in fases_activas else 0
    p2_w = round(p_fase_kw * 1000, 1) if 2 in fases_activas else 0
    p3_w = round(p_fase_kw * 1000, 1) if 3 in fases_activas else 0
    ptotal_w = round(p1_w + p2_w + p3_w, 1)

    q1_var = round(p1_w * random.uniform(0.15, 0.45), 1) if 1 in fases_activas else 0
    q2_var = round(p2_w * random.uniform(0.15, 0.45), 1) if 2 in fases_activas else 0
    q3_var = round(p3_w * random.uniform(0.15, 0.45), 1) if 3 in fases_activas else 0
    qtotal_var = round(q1_var + q2_var + q3_var, 1)

    s1_va = round(abs(p1_w) / max(fp1, 0.01), 1) if 1 in fases_activas else 0
    s2_va = round(abs(p2_w) / max(fp2, 0.01), 1) if 2 in fases_activas else 0
    s3_va = round(abs(p3_w) / max(fp3, 0.01), 1) if 3 in fases_activas else 0
    stotal_va = round(s1_va + s2_va + s3_va, 1)

    i1 = round(abs(p1_w) / max(vl1 * fp1, 1), 2) if 1 in fases_activas else 0
    i2 = round(abs(p2_w) / max(vl2 * fp2, 1), 2) if 2 in fases_activas else 0
    i3 = round(abs(p3_w) / max(vl3 * fp3, 1), 2) if 3 in fases_activas else 0
    i_avg = round((i1 + i2 + i3) / num_fases, 2)

    fp_total = round((fp1 + fp2 + fp3) / num_fases, 3)

    # Mapa de valores por Unit ID usado por los YAML ME337
    valores_por_unit = {
        # Voltajes
        7: vl1,
        8: vl2,
        9: vl3,
        13: u12,
        14: u23,
        15: u31,
        16: round((vl1 + vl2 + vl3) / num_fases, 1),

        # Corrientes
        10: i1,
        11: i2,
        12: i3,
        54: i_avg,
        55: round(random.uniform(0, 5), 2),

        # Potencia activa W
        58: p1_w,
        59: p2_w,
        60: p3_w,
        61: ptotal_w,

        # Potencia reactiva VAr
        62: q1_var,
        63: q2_var,
        64: q3_var,
        65: qtotal_var,

        # Potencia aparente VA
        66: s1_va,
        67: s2_va,
        68: s3_va,
        69: stotal_va,

        # Factor de potencia
        70: fp1,
        71: fp2,
        72: fp3,
        73: fp_total,

        # Frecuencia
        27: round(random.uniform(59.8, 60.2), 2),

        # Energía activa importada kWh
        97: round(estado["energia_importada_l1"], 3),
        98: round(estado["energia_importada_l2"], 3),
        99: round(estado["energia_importada_l3"], 3),
        100: round(estado["energia_importada_total"], 3),

        # Energía activa exportada kWh
        101: round(estado["energia_exportada_l1"], 3),
        102: round(estado["energia_exportada_l2"], 3),
        103: round(estado["energia_exportada_l3"], 3),
        104: round(estado["energia_exportada_total"], 3),

        # THD corriente / voltaje
        117: round(random.uniform(2, 8), 2),
        118: round(random.uniform(2, 8), 2),
        119: round(random.uniform(2, 8), 2),
        120: round(random.uniform(1, 4), 2),
        121: round(random.uniform(1, 4), 2),
        122: round(random.uniform(1, 4), 2),
    }

    for reg in config.get("registers", []):
        unit_id = int(reg.get("unit"))
        alias = str(reg.get("alias", reg.get("name", ""))).lower()
        name = str(reg.get("name", "")).lower()

        if unit_id in valores_por_unit:
            val = valores_por_unit[unit_id]

        elif "temp" in alias or "temperature" in name:
            val = round(random.uniform(18.0, 32.0), 1)

        elif "hum" in alias or "humidity" in name:
            val = round(random.uniform(45.0, 90.0), 1)

        elif "kwh" in alias or "kwh" in name:
            val = round(estado["energia_importada_total"], 3)

        elif "angle" in name or "angulo" in alias:
            val = round(random.uniform(0, 30), 2)

        else:
            val = round(random.uniform(0, 100), 2)

        valores.append(str(val))
        unidades.append(str(unit_id))

    return {
        "d": [{
            "t": util.get__time_utc(),
            "g": device_id,
            "v": valores,
            "u": unidades
        }]
    }
#---------------------------------------------------------------------------------------------------    
# Función para procesar eventos en la cola
#---------------------------------------------------------------------------------------------------
def process_event_queue():
    if fileventqueue.contar_eventos() != 0:
        if  util.check_internet_connection():
            mqtt_client = awsaccess.connect_to_mqtt()
            if mqtt_client:
                eventos = fileventqueue.procesar_eventos_de_uno_en_uno()
                for evento in eventos:
                    hilo_queue = threading.Thread(target=Temp.parpadear_led_500ms)
                    hilo_queue.start()
                    awsaccess.publish_to_topic(mqtt_client, os.getenv('TOPIC'), evento)
                    time.sleep(0.2)
                    hilo_queue.join()
                awsaccess.disconnect_from_aws_iot(mqtt_client)
                
            else:
                util.logging.info("No se pudo conectar a AWS IoT para procesar la cola de eventos.")
        else:
            util.logging.info("No hay internet para procesar la cola de eventos.")
    else:
        util.logging.info("No hay eventos para procesar.")
        
#-----------------------------------------------------------------------------------------------------------   
# Rutina de lectura de sensores Modbus RTU y devuelve datos en formato JSON 
#-----------------------------------------------------------------------------------------------------------        
def obtener_datos_medidores_y_sensor():
    
    medidor_activo = os.getenv("MEDIDOR_ACTIVO", "meatrol").lower()
    datos = {}
    if medidor_activo == "eastron":
         # Medidor Eastron SDM630MCT
        cfg_path = os.getenv("CFG_EASTRON")
        cfg_section = os.getenv("CFG_EASTRON_SECTION")
        config = util.cargar_configuracion(cfg_path, cfg_section)
        #registrar_gateway_dispositivo_desde_config(config)
                
        simular = es_simulacion_activa(config)
        log_modo_lectura("EASTRON", config)
        
        if simular:
            medicion = payload_event_modbus_simulado(config)
        else:
            medicion = modbusdevices.payload_event_modbus(config)
            
        datos ['medidor_eastron'] = json.dumps(medicion)
    elif medidor_activo == "meatrol":
        # Medidor de proceso: ME337 Máquina inyecto-soplado Aoki / compresor
        cfg_meatrol1 = os.getenv("CFG_MEATROL1")
        cfg_meatrol1_section = os.getenv("CFG_MEATROL1_SECTION")
        config = util.cargar_configuracion(cfg_meatrol1, cfg_meatrol1_section)

        log_modo_lectura("ME337 PROCESO", config)

        if es_simulacion_activa(config):
            medicion = payload_event_modbus_simulado(config)
        else:
            medicion = modbusdevices.payload_event_modbus(config)

        medicionME337 = json.dumps(medicion)


        # Medidor totalizador: ME3372 Tablero general / alimentación principal
        cfg_meatrol2 = os.getenv("CFG_MEATROL2")
        cfg_meatrol2_section = os.getenv("CFG_MEATROL2_SECTION")
        config2 = util.cargar_configuracion(cfg_meatrol2, cfg_meatrol2_section)

        log_modo_lectura("ME337 TOTALIZADOR", config2)

        if es_simulacion_activa(config2):
            medicion2 = payload_event_modbus_simulado(config2)
        else:
            medicion2 = modbusdevices.payload_event_modbus(config2)

        medicionME3372 = json.dumps(medicion2)
        # Configurar el sensor SHT20 Sensor temperatura y humedad
        cfg_sht20 = os.getenv("CFG_SHT20")
        cfg_sht20_section = os.getenv("CFG_SHT20_SECTION")
        config_sht20 = util.cargar_configuracion(cfg_sht20, cfg_sht20_section)
        
        simular_sht20 = es_simulacion_activa(config_sht20)
        log_modo_lectura("SHT20", config_sht20)
        
        if simular_sht20:
            medicion_sht20 = payload_event_modbus_simulado(config_sht20)
        else:
            medicion_sht20 = modbusdevices.payload_event_modbus(config_sht20)  # Obtener la medición como JSON
            
        medicionSensorSHT20 = json.dumps(medicion_sht20)  # Convertir a JSON con formato legible
        #print(medicionSensorSHT20)
        # Devolver los tres JSON en un diccionario
        return {
            'medidor_1': medicionME337,
            'medidor_2': medicionME3372,
            'sensor_sht20': medicionSensorSHT20
        }
    

# Lógica principal
def main_loop():
    #global ssh_process  
    init_db()
    cargar_catalogos_desde_env()
    
    tempRaspberry = TIMERCHEQUEOTEMPERATURA
    tempMedidor   = TIMERMEDICION
    tempQueue     = TIMERCOLAEVENTOS
    tempPing      = TIMERPING
    tempCheckusb  = TIMECHECKUSBETHERNET 
    tempHora      = TIMECHECK_USB_ETHERNET_TIME
    
    #threading.Thread(target=awsaccess.iniciar_recepcion_mensajes, daemon=True).start()
    # Interrupciones
    Temp.setup_door_interrupt()
    # Publicar el encendido del sistema
    util.logging.info("Sistema encendido.")
    # conexion a AWS
    conneced_meter = json.dumps(eventHandler.pyp_Conect())
    # mediciones de los medidores ME337 y el  sensor SHT20
    datos = obtener_datos_medidores_y_sensor()
    Temp.iniciar_wdt()
    
    guardar_payload_local(conneced_meter, "ARRANQUE/connect")

    for key in ('medidor_1', 'medidor_2', 'sensor_sht20'):
        guardar_payload_local(datos[key], f"ARRANQUE/{key}")
    
    
    if  util.check_internet_connection():
         # Conectar al cliente MQTT
        mqtt_client = awsaccess.connect_to_mqtt()
        if mqtt_client:
                                        
            awsaccess.publish_mediciones(mqtt_client, conneced_meter)
            awsaccess.publish_mediciones(mqtt_client, datos['medidor_1'])
            awsaccess.publish_mediciones(mqtt_client, datos['medidor_2'])
            awsaccess.publish_mediciones(mqtt_client, datos['sensor_sht20'])
            awsaccess.disconnect_from_aws_iot(mqtt_client)# Mantener la conexión activa y recibir mensajes
            
            
        else:
            # Hay internet, pero falla conectar MQTT:
            util.logging.error("No hay Conexion a AWS, almacena en la cola, las mediciones del medidor, Temp, Humedad y la hora de encendido.")
            fileventqueue.agregar_evento(conneced_meter)
            for key in ('medidor_1', 'medidor_2', 'sensor_sht20'):
                fileventqueue.agregar_evento(datos[key])
            
    else:
        # No hay internet:
        util.logging.error("No hay internet, almacena en la cola, las mediciones del medidor, Temp, Humedad y la hora de encendido.")
        fileventqueue.agregar_evento(conneced_meter)
        for key in ('medidor_1', 'medidor_2', 'sensor_sht20'):
            fileventqueue.agregar_evento(datos[key])
        
    # Verificar la temperatura al inicio
    #Temp.check_temp()
    # Bucle principal
    contador_envio = 0  # Inicialízalo fuera del loop principal
    while True:
        tempRaspberry, tempMedidor, tempQueue, tempPing, tempCheckusb = util.actualizar_temporizadores(
        tempRaspberry, tempMedidor, tempQueue, tempPing, tempCheckusb)
       
        if tempRaspberry == 0:
            tempRaspberry = TIMERCHEQUEOTEMPERATURA
            json_estado = util.payload_estado_sistema_y_medidor()
            Sistema =json.dumps(json_estado)
            
            guardar_payload_local(Sistema, "SISTEMA")
            
            #se inicia el wdt 
            Temp.iniciar_wdt()
            # Si la puerta está abierta, forzar transmisión inmediata
           
            # lógica normal de envío cada 3 ciclos
            contador_envio += 1
            if contador_envio >= 3:
                contador_envio = 0  # Reiniciar después de enviar
                if  util.check_internet_connection():
                    mqtt_client = awsaccess.connect_to_mqtt()
                    if mqtt_client:
                        awsaccess.publish_mediciones(mqtt_client, Sistema)
                        awsaccess.disconnect_from_aws_iot(mqtt_client)
                else:
                    fileventqueue.agregar_evento(Sistema)
                
             
        # Mediciones cada 10 minutos
        if tempMedidor == 0:
            tempMedidor = TIMERMEDICION
            # mediciones de los medidores ME337 y el  sensor SHT20
            datos = obtener_datos_medidores_y_sensor()
            
            for key in ('medidor_1', 'medidor_2', 'sensor_sht20'):
                guardar_payload_local(datos[key], f"MEDICION/{key}")
            
            if  util.check_internet_connection():
                mqtt_client = awsaccess.connect_to_mqtt()
                if mqtt_client:
                    awsaccess.publish_mediciones(mqtt_client, datos['medidor_1'])
                    awsaccess.publish_mediciones(mqtt_client, datos['medidor_2'])
                    awsaccess.publish_mediciones(mqtt_client,datos['sensor_sht20'])
                    awsaccess.disconnect_from_aws_iot(mqtt_client)
                   
                else:
                    # Hay internet, pero falla conectar MQTT:
                    for key in ('medidor_1', 'medidor_2', 'sensor_sht20'):
                        fileventqueue.agregar_evento(datos[key])
                    
            else:
                # No hay internet:
                for key in ('medidor_1', 'medidor_2', 'sensor_sht20'):
                    fileventqueue.agregar_evento(datos[key])
               
        if tempQueue == 0:
            tempQueue = TIMERCOLAEVENTOS
            process_event_queue()

        if tempPing == 0:
            tempPing = TIMERPING
            ok = util.ensure_internet_failover()
            if ok:
                util.logging.info("Internet OK por al menos una interfaz.")
            else:
                util.logging.warning("Sin Internet por eth0 ni usb0.")
            

        if tempCheckusb == 0:
            tempCheckusb = TIMECHECKUSBETHERNET
            tempHora -= 1
            if tempHora == 0:
                tempHora = TIMECHECK_USB_ETHERNET_TIME
                util.check_usb_connection()
                
        '''
        with shared.mensaje_lock:
            if shared.mensaje_recibido:
                mensaje = shared.mensaje_recibido
                shared.mensaje_recibido = None
                try:
                    data = json.loads(mensaje)
                    comando_mensaje = data.get("message", "")
                    util.logging.warning("Msj MQTT: "+ comando_mensaje )
                    
                    if comando_mensaje == "disconnect":
               #         tunel_watcher.cerrar_tunel()
                        util.logging.info("Túnel cerrado correctamente.")
                        
                    elif comando_mensaje.startswith("connect|"):
                  #      ip = comando_mensaje.split("|")[1]
                   #     tunel_watcher.set_destino(ip)
                    #    tunel_watcher.run_ssh()
                        util.logging.info(f"msj mqtt ...")
                    else:
                       util.logging.warning(f"Comando no reconocido: {comando_mensaje}")
                except Exception as e:
                    util.logging.error(f"Error al procesar el mensaje MQTT: {e}")
'''
# Punto de entrada principal
if __name__ == '__main__':
    main_loop()
