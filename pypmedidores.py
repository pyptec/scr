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
from db.samee100_db import init_db
from db.samee100_db import guardar_medicion
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
        simular = str(config.get("simular", False)).lower() == "true"
        
        if simular:
            medicion = payload_event_modbus_simulado(config)
        else:
            medicion = modbusdevices.payload_event_modbus(config)
        datos ['medidor_eastron'] = json.dumps(medicion)
    elif medidor_activo == "meatrol":
        # PRIMER medidor ME337
        config = util.cargar_configuracion(os.getenv("CFG_MEATROL1"), os.getenv("CFG_MEATROL1_SECTION"))
        medicion = modbusdevices.payload_event_modbus(config)  # Obtener la medición como JSON
        datos ['medicionME337'] = json.dumps(medicion)  # Convertir a JSON con formato legible
        #print(medicionME337)

        # Configurar el segundo medidor ME3372
        config2 = util.cargar_configuracion(os.getenv("CFG_MEATROL2"), os.getenv("CFG_MEATROL2_SECTION"))
        medicion2 = modbusdevices.payload_event_modbus(config2)  # Obtener la medición como JSON
        datos ['medicionME3372'] = json.dumps(medicion2)  # Convertir a JSON con formato legible
        #print(medicionME3372)
    
    
    
    # Configurar el sensor SHT20
    config_sht20 = util.cargar_configuracion(os.getenv("CFG_SHT20"),os.getenv("CFG_SHT20_SECTION"))
    simular_sht20 = str(config_sht20.get("simular", False)).lower() == "true"
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
# Lógica principal
def main_loop():
    #global ssh_process  
    init_db()
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
        
    if  util.check_internet_connection():
         # Conectar al cliente MQTT
        mqtt_client = awsaccess.connect_to_mqtt()
        if mqtt_client:
                                        
            awsaccess.publish_mediciones(mqtt_client, conneced_meter)
            guardar_medicion(conneced_meter, sent_aws=1)
            #util.logging.INFO("[SQLITE] Conectado a AWS:")
            for payload in datos.values():
                guardar_medicion(payload, sent_aws=1)
                awsaccess.publish_mediciones(mqtt_client, payload)
            awsaccess.disconnect_from_aws_iot(mqtt_client)# Mantener la conexión activa y recibir mensajes
            
            
        else:
            # Hay internet, pero falla conectar MQTT:
            util.logging.error("No hay Conexion a AWS, almacena en la cola, las mediciones del medidor, Temp, Humedad y la hora de encendido.")
            guardar_medicion(conneced_meter, sent_aws=0)
            #util.logging.INFO("[SQLITE] NO Conectado a AWS:")
            fileventqueue.agregar_evento(conneced_meter)
            for payload in datos.values():
                guardar_medicion(payload, sent_aws=0)
                fileventqueue.agregar_evento(payload)
            
    else:
        # No hay internet:
        util.logging.error("No hay internet, almacena en la cola, las mediciones del medidor, Temp, Humedad y la hora de encendido.")
        guardar_medicion(conneced_meter, sent_aws=0)
        fileventqueue.agregar_evento(conneced_meter)
        
        for payload in datos.values():
            guardar_medicion(payload, sent_aws=0)
            fileventqueue.agregar_evento(payload)
        
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
            if contador_envio >= 3:
                contador_envio = 0  # Reiniciar después de enviar
                if  util.check_internet_connection():
                    mqtt_client = awsaccess.connect_to_mqtt()
                    if mqtt_client:
                        try:
                            awsaccess.publish_mediciones(mqtt_client, Sistema)
                            guardar_medicion(Sistema, sent_aws=1)
                            
                        except Exception as e:
                            guardar_medicion(Sistema, sent_aws=0)
                            fileventqueue.agregar_evento(Sistema)
                            util.logging.error(f"[SISTEMA] Error al publicar AWS: {e}")
                            
                        awsaccess.disconnect_from_aws_iot(mqtt_client)
                    else:
                        guardar_medicion(Sistema, sent_aws=0)
                        fileventqueue.agregar_evento(Sistema)
                else:
                    guardar_medicion(Sistema, sent_aws=0)
                    fileventqueue.agregar_evento(Sistema)    
             
        # Mediciones cada 10 minutos
        #if tempMedidor == 0:
        if (not USAR_HILO_MEDIDOR_10MIN) and tempMedidor == 0:
            tempMedidor = TIMERMEDICION
            # mediciones de los medidores ME337 y el  sensor SHT20
            datos = obtener_datos_medidores_y_sensor()
            if  util.check_internet_connection():
                mqtt_client = awsaccess.connect_to_mqtt()
                if mqtt_client:
                    for payload in datos.values():
                        awsaccess.publish_mediciones(mqtt_client, payload)
                        guardar_medicion(payload, sent_aws=1)
                    
                    awsaccess.disconnect_from_aws_iot(mqtt_client)
                   
                else:
                    # Hay internet, pero falla conectar MQTT:
                    for payload in datos.values():
                        guardar_medicion(payload, sent_aws=0)
                        fileventqueue.agregar_evento(payload)
            else:
                # No hay internet:
                #for key in ('medidor_1', 'medidor_2', 'sensor_sht20'):
                #    fileventqueue.agregar_evento(datos[key])
                for payload in datos.values():
                    guardar_medicion(payload, sent_aws=0)
                    fileventqueue.agregar_evento(payload)
               
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
