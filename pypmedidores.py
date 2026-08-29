from db.samee100_db import init_db
from db.samee100_db import guardar_medicion
from db.samee100_db import registrar_gateway_dispositivo_desde_config
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
   

#import tunel_watcher

'''
Parametros del pto serie modbus
'''
serialPort= "/dev/ttyS0"

# Ruta al archivo .env
load_dotenv(dotenv_path="/home/pi/SAMEE100/scr/.env")

# Leer variables como enteros
TIMERCHEQUEOTEMPERATURA = int(os.getenv('TIMERCHEQUEOTEMPERATURA', 60))
TIMERCOLAEVENTOS = int(os.getenv('TIMERCOLAEVENTOS', 60))
TIMERMEDICION = int(os.getenv('TIMERMEDICION', 600))
TIMERPING = int(os.getenv('TIMERPING', 120))
TIMECHECKUSBETHERNET = int(os.getenv('TIMECHECKUSBETHERNET', 600))
TIMECHECK_USB_ETHERNET_TIME = int(os.getenv('TIMECHECK_USB_ETHERNET_TIME', 6))


USAR_HILO_MEDIDOR_10MIN = os.getenv("USAR_HILO_MEDIDOR_10MIN", "true").lower() in ["true", "1", "yes", "si"]


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

#---------------------------------------------------------------------------------------------------    
# Función para procesar eventos en la cola
#---------------------------------------------------------------------------------------------------
def process_event_queue():
    """
    Procesa únicamente la cola AWS en SQLite.

    Cola oficial:
        data/samee100.db -> tabla aws_queue

    La cola antigua fileventqueue queda deshabilitada en flujo normal.
    """

    try:
        from db.samee100_db import contar_pendientes, resumen_cola_aws

        pendientes = contar_pendientes()
        util.logging.info(f"[AWS_QUEUE] Eventos pendientes SQLite: {pendientes}")

        if pendientes <= 0:
            util.logging.info("[AWS_QUEUE] No hay eventos pendientes en SQLite.")
            return

        if not util.check_internet_connection():
            util.logging.info("[AWS_QUEUE] No hay internet. La cola SQLite queda pendiente.")
            return

        mqtt_client = awsaccess.connect_to_mqtt()

        if not mqtt_client:
            util.logging.info("[AWS_QUEUE] Hay internet, pero no se pudo conectar a AWS IoT.")
            return

        enviados = awsaccess.reenviar_pendientes_aws(
            mqtt_client,
            limit=50
        )

        util.logging.info(
            f"[AWS_QUEUE] Reenvío finalizado. "
            f"Eventos enviados: {enviados}. "
            f"Resumen cola: {resumen_cola_aws()}"
        )

        awsaccess.disconnect_from_aws_iot(mqtt_client)

    except Exception as e:
        util.logging.error(f"[AWS_QUEUE] Error general procesando cola SQLite: {str(e)}")
        
#---------------------------------------------------------------------------------------------------    
# simulador de datos del medidor eastron
#---------------------------------------------------------------------------------------------------  
def payload_event_modbus_simulado(config):
    valores = []
    unidades = []

    energia_base = float(config.get("sim_energy_base", 1500.0))

    for reg in config.get("registers", []):
        alias = str(reg.get("alias", reg.get("name", ""))).lower()
        name = str(reg.get("name", "")).lower()

        if "temp" in alias or "temperature" in name:
            val = round(random.uniform(18.0, 30.0), 1)

        elif "hum" in alias or "humidity" in name:
            val = round(random.uniform(50.0, 95.0), 1)

        elif alias.startswith("vl") or "line to neutral volts" in name:
            val = round(random.uniform(215, 225), 1)

        elif alias in ["u12", "u23", "u31"] or "line l" in name:
            val = round(random.uniform(370, 390), 1)

        elif alias.startswith("al") or "current" in name:
            val = round(random.uniform(2, 15), 2)

        elif alias.startswith("p") or "power" in name:
            val = round(random.uniform(2.5, 6.5), 2)

        elif "kwh" in alias or "kwh" in name:
            val = round(energia_base + random.uniform(0, 50), 2)

        elif "freq" in alias or "frequency" in name:
            val = round(random.uniform(59.8, 60.2), 2)

        elif "pf" in alias or "factor" in name:
            val = round(random.uniform(0.92, 1.0), 3)

        else:
            val = round(random.uniform(0, 100), 2)

        valores.append(str(val))
        unidades.append(str(reg.get("unit")))

    return {
        "d": [{
            "t": util.get__time_utc(),
            "g": config.get("id_device"),
            "v": valores,
            "u": unidades
        }]
    }
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
        registrar_gateway_dispositivo_desde_config(config)
                
        simular = es_simulacion_activa(config)
        log_modo_lectura("EASTRON", config)
        
        if simular:
            medicion = payload_event_modbus_simulado(config)
        else:
            medicion = modbusdevices.payload_event_modbus(config)
            
        datos ['medidor_eastron'] = json.dumps(medicion)
    elif medidor_activo == "meatrol":
        # PRIMER medidor ME337
        config = util.cargar_configuracion(os.getenv("CFG_MEATROL1"), os.getenv("CFG_MEATROL1_SECTION"))
        registrar_gateway_dispositivo_desde_config(config)
        log_modo_lectura("MEATROL1", config)
        medicion = modbusdevices.payload_event_modbus(config)  # Obtener la medición como JSON
        datos ['medicionME337'] = json.dumps(medicion)  # Convertir a JSON con formato legible
        #print(medicionME337)

        # Configurar el segundo medidor ME3372
        config2 = util.cargar_configuracion(os.getenv("CFG_MEATROL2"), os.getenv("CFG_MEATROL2_SECTION"))
        registrar_gateway_dispositivo_desde_config(config2)
        log_modo_lectura("MEATROL2", config2)
        medicion2 = modbusdevices.payload_event_modbus(config2)  # Obtener la medición como JSON
        datos ['medicionME3372'] = json.dumps(medicion2)  # Convertir a JSON con formato legible
        #print(medicionME3372)
    
    
    
    # Configurar el sensor SHT20
    config_sht20 = util.cargar_configuracion(os.getenv("CFG_SHT20"),os.getenv("CFG_SHT20_SECTION"))
    registrar_gateway_dispositivo_desde_config(config_sht20)
    
    simular_sht20 = es_simulacion_activa(config_sht20)
    log_modo_lectura("SHT20", config_sht20)

    if simular_sht20:
        medicion_sht20 = payload_event_modbus_simulado(config_sht20)
    else:
        medicion_sht20 = modbusdevices.payload_event_modbus(config_sht20)  # Obtener la medición como JSON
        
    datos ['medicionSHT20'] = json.dumps(medicion_sht20)  # Convertir a JSON con formato legible
    #print(medicionSensorSHT20)
    # Devolver los tres JSON en un diccionario
    return datos
    
#---------------------------------------------------------------------------------------------------
# Publicación/almacenamiento ordenado usando SQLite + cola AWS
#---------------------------------------------------------------------------------------------------
def publicar_o_encolar_payload(payload, origen="medicion"):
    """
    Guarda la medición en SQLite y publica a AWS si hay conexión.

    Si no hay internet o no se puede conectar a AWS IoT:
        - Guarda la medición con sent_aws=0.
        - Envía el payload a awsaccess.publish_mediciones(None, payload),
          que lo guarda en aws_queue SQLite.

    Si hay conexión MQTT:
        - Publica con awsaccess.publish_mediciones().
        - Guarda la medición con sent_aws=1.
    """

    mqtt_client = None

    try:
        if util.check_internet_connection():
            mqtt_client = awsaccess.connect_to_mqtt()

        if mqtt_client:
            awsaccess.publish_mediciones(mqtt_client, payload)
            guardar_medicion(payload, sent_aws=1)
            util.logging.info(f"[{origen}] Publicado en AWS y guardado en SQLite.")
        else:
            guardar_medicion(payload, sent_aws=0)
            awsaccess.publish_mediciones(None, payload)
            util.logging.warning(f"[{origen}] Sin conexión MQTT. Guardado en SQLite y enviado a cola AWS.")

    except Exception as e:
        util.logging.error(f"[{origen}] Error publicando/encolando payload: {str(e)}")

        try:
            guardar_medicion(payload, sent_aws=0)
        except Exception as db_error:
            util.logging.error(f"[{origen}] Error guardando medición SQLite: {str(db_error)}")

        try:
            awsaccess.publish_mediciones(None, payload)
        except Exception as cola_error:
            util.logging.error(f"[{origen}] Error guardando en cola AWS SQLite: {str(cola_error)}")

    finally:
        if mqtt_client:
            try:
                awsaccess.disconnect_from_aws_iot(mqtt_client)
            except Exception as e:
                util.logging.error(f"[{origen}] Error desconectando MQTT: {str(e)}")


#---------------------------------------------------------------------------------------------------
# Hilo independiente para mediciones de medidor y SHT20 cada TIMERMEDICION
#---------------------------------------------------------------------------------------------------
def hilo_mediciones_medidor_10min():
    """
    Hilo dedicado para enviar medidor/SHT20 cada TIMERMEDICION segundos.

    Ventaja:
        - No depende del ciclo principal ni de otros temporizadores.
        - Evita que la lectura del medidor se retrase por otras tareas.
        - Usa la misma función obtener_datos_medidores_y_sensor().
        - Guarda en SQLite y usa cola AWS si no hay conexión.
    """

    util.logging.info(
        f"[HILO_MEDIDOR_10MIN] Iniciado. Periodo: {TIMERMEDICION} segundos."
    )

    # Espera el primer periodo para no duplicar la medición inicial del arranque
    time.sleep(TIMERMEDICION)

    while True:
        inicio_ciclo = time.time()

        try:
            util.logging.info("[HILO_MEDIDOR_10MIN] Iniciando lectura periódica de medidor/SHT20.")

            datos = obtener_datos_medidores_y_sensor()

            if not datos:
                util.logging.warning("[HILO_MEDIDOR_10MIN] No se obtuvieron datos de medidor/SHT20.")
            else:
                for nombre, payload in datos.items():
                    publicar_o_encolar_payload(
                        payload,
                        origen=f"HILO_MEDIDOR_10MIN/{nombre}"
                    )

            util.logging.info("[HILO_MEDIDOR_10MIN] Ciclo de medición finalizado.")

        except Exception as e:
            util.logging.error(f"[HILO_MEDIDOR_10MIN] Error general en ciclo: {str(e)}")

        duracion = time.time() - inicio_ciclo
        espera = max(5, TIMERMEDICION - duracion)

        util.logging.info(
            f"[HILO_MEDIDOR_10MIN] Próxima medición en {round(espera, 1)} segundos."
        )

        time.sleep(espera)
        
def registrar_catalogos_iniciales_desde_env():
    """
    Registra solo los YAML activos para este equipo.

    La lista activa se define en .env:

        CONFIGS_ACTIVAS=CFG_EASTRON,CFG_SHT20,CFG_SISTEMA,CFG_PYP_CONNECT

    Cada CFG debe tener su SECTION:
        CFG_EASTRON
        CFG_EASTRON_SECTION
    """

    configs_activas = os.getenv("CONFIGS_ACTIVAS", "")

    if not configs_activas.strip():
        util.logging.warning("[CATALOGO] CONFIGS_ACTIVAS no está definido en .env")
        return

    for cfg_name in configs_activas.split(","):
        cfg_name = cfg_name.strip()

        if not cfg_name:
            continue

        section_name = f"{cfg_name}_SECTION"

        cfg_path = os.getenv(cfg_name)
        cfg_section = os.getenv(section_name)

        if not cfg_path or not cfg_section:
            util.logging.warning(
                f"[CATALOGO] Config incompleta: {cfg_name}={cfg_path}, {section_name}={cfg_section}"
            )
            continue

        try:
            config = util.cargar_configuracion(cfg_path, cfg_section)

            if not config:
                util.logging.warning(
                    f"[CATALOGO] YAML vacío o sección no encontrada: {cfg_path} / {cfg_section}"
                )
                continue

            enabled = config.get("enabled", True)
            if str(enabled).lower() in ["false", "0", "no", "off"]:
                util.logging.info(
                    f"[CATALOGO] YAML deshabilitado: {cfg_path} / {cfg_section}"
                )
                continue

            registrar_gateway_dispositivo_desde_config(config)

            util.logging.info(
                f"[CATALOGO] Registrado: {cfg_name}={cfg_path}, section={cfg_section}"
            )

        except Exception as e:
            util.logging.error(
                f"[CATALOGO] Error cargando {cfg_name}/{section_name}: {str(e)}"
            )     
        
        
# Lógica principal
def main_loop():
    #global ssh_process  
    init_db()
    registrar_catalogos_iniciales_desde_env()
    
    tempRaspberry = TIMERCHEQUEOTEMPERATURA
    tempMedidor   = TIMERMEDICION
    tempQueue     = TIMERCOLAEVENTOS
    tempPing      = TIMERPING
    tempCheckusb  = TIMECHECKUSBETHERNET 
    tempHora      = TIMECHECK_USB_ETHERNET_TIME
    
    # Interrupciones
    Temp.setup_door_interrupt()
    # Publicar el encendido del sistema
    util.logging.info("Sistema encendido.")
    # conexion a AWS
    conneced_meter = json.dumps(eventHandler.pyp_Conect())
    # mediciones de los medidores ME337 y el  sensor SHT20
    datos = obtener_datos_medidores_y_sensor()
    Temp.iniciar_wdt()
        # Hilo independiente para mediciones cada 10 minutos
    if USAR_HILO_MEDIDOR_10MIN:
        hilo_medidor_10min = threading.Thread(
            target=hilo_mediciones_medidor_10min,
            daemon=True
        )
        hilo_medidor_10min.start()
        util.logging.info("[HILO_MEDIDOR_10MIN] Hilo de medición periódica iniciado.")
        
        # Publicación inicial usando flujo unificado SQLite + AWS_QUEUE
    publicar_o_encolar_payload(conneced_meter, origen="ARRANQUE/connected_meter")

    for nombre, payload in datos.items():
        publicar_o_encolar_payload(payload, origen=f"ARRANQUE/{nombre}")
        
    
    if (not USAR_HILO_MEDIDOR_10MIN) and tempMedidor == 0:
        tempMedidor = TIMERMEDICION

        datos = obtener_datos_medidores_y_sensor()

        for nombre, payload in datos.items():
            publicar_o_encolar_payload(
                payload,
                origen=f"TEMPORIZADOR_MEDIDOR/{nombre}"
            )
        
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
            #se inicia el wdt 
            Temp.iniciar_wdt()
            # Si la puerta está abierta, forzar transmisión inmediata
           
            # lógica normal de envío cada 3 ciclos
            contador_envio += 1
            if contador_envio >= 5:
                contador_envio = 0

                publicar_o_encolar_payload(
                    Sistema,
                    origen="SISTEMA"
                )
            
        # Mediciones cada 10 minutos
                # Mediciones cada 10 minutos usando temporizador anterior.
        # Si USAR_HILO_MEDIDOR_10MIN=True, este bloque queda desactivado
        # para evitar duplicar mediciones.
        if (not USAR_HILO_MEDIDOR_10MIN) and tempMedidor == 0:
            tempMedidor = TIMERMEDICION

            datos = obtener_datos_medidores_y_sensor()

            for nombre, payload in datos.items():
                publicar_o_encolar_payload(
                    payload,
                    origen=f"TEMPORIZADOR_MEDIDOR/{nombre}"
                )
        
                       
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
                
        
# Punto de entrada principal
if __name__ == '__main__':
    main_loop()
