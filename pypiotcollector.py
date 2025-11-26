import minimalmodbus
import serial
import time
import json
import awsaccess
import os
import Temp
import fileventqueue
import util
import threading
import eventHandler
from dotenv import load_dotenv



'''
Parametros del pto serie modbus
'''
serialPort= "/dev/ttyUSB0"
slave_id = 1
slave_idsht20 = 8
'''
Tiempos de muestreo
'''
#Tiempo de temperatura de la raspberry
TIMERCHEQUEOTEMPERATURA = 60
TIMERCOLAEVENTOS = 60
TIMERMEDICION =600
TIMERPING = 120
TIMECHECKUSBETHERNET = 600
TIMECHECK_USB_ETHERNET_TIME =6




def payload_event():
    params = {}
    voltages =[]        # Lista para almacenar los valores de voltaje leídos
    units_list =[]      # Lista para almacenar las unidades correspondientes
    for dp  in range(len(register)):
            try:
                value = instrument.read_float(register[dp],4,2)
                voltages.append (str(round(value,3)))
                units_list.append(str(units[dp]))
            except Exception as e:  # Manejo específico de excepciones
                #util.reiniciar_puerto_usb()
                util.logging.error(f"Error al intentar leer el registro: {register[dp]}: {e}")
                os.system('sudo reboot')
                
    # Crear el diccionario con los parámetros
    params = {
        "t": util.get__time_utc(),   # Añade la hora en UTC
        "i": 8,                 # Número de identificación o índice
        "v": voltages,          # Lista de voltajes leídos
        "u": units_list         # Lista de unidades
    }  
    return params

def payloadMedicion():
    # Retorna un diccionario con la estructura deseada
    return {
        "d": [payload_event()]  # Contiene los eventos dentro de una lista
    }    

   


# Función para procesar eventos en la cola
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

# Función para leer la temperatura y la humedad del SHT20
def read_sht20():
    mensurados =[]
    try:
        # Leer la temperatura y la humedad desde registros Modbus del SHT20
        temperature = sht20.read_register(1, 1, functioncode=4)  # Ejemplo: Reg: 1, decimales: 1
        humidity = sht20.read_register(2, 1, functioncode=4)     # Ejemplo: Reg: 2, decimales: 1
        
        util.logging.info(f"SHT20 - Temperatura: {temperature:.1f} °C, Humedad: {humidity:.1f} %")
        mensurados.append (str(temperature))
        mensurados.append (str(humidity))
        return eventHandler.sht20_conectado(mensurados)
    except Exception as e:
        util.logging.error(f"Error de comunicación con el dispositivo SHT20. {e}")


register = [0x00,0x02,0x04,
            0x06,0x08,0x0A,
            0x0C,0X0E,0X10,
            0X12,0X14,0X16,
            0X18,0X1A,0X1C,
            0X1E,0X20,0X22,
            0X34,0X3E,0X46,
            0X50,0XC8,0XCA,
            0XCC,0XEA,0XEC,
            0XEE,0XF0,0XF2,
            0XF4,0XF8,0X154,
            0X156,0X158,0X48,
            0X4A,0X4C,0X15A,
            0X15C,0X15E,0X16C,
            0X16E,0X170,0X38,
            0X3C]
names =['VL1','VL2','VL3','AL1','AL2','AL3','FAP1','FAP2','FAP3','FAPP1','FAPP2','FAPP3','FRP1','FRP2','FRP3','FPF1','FPF2','FPF3',
        'FPF2','FPF3','TSP','TSPF1','HZ','TAPE','VL1L2','VL2L3','VL1L3','THDL1','THDL2','THDL3','THDA1','THDA2','THDA3','THDLN',
        'THDLL','TAE3','TRE3','TIAE','TEAE','TIRE','L1IAE','L2IAE','L3IAE','L1IRE','L2IRE','L1IRE','TSVA','TSVAR']
units =[7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,
        41,42,43,44,45,46,47,48,49,50,51,52]
try:
        instrument = minimalmodbus.Instrument(serialPort,slave_id,True)
        instrument.serial.baudrate= 19200
        instrument.serial.bytesize = 8
        instrument.serial.parity   = serial.PARITY_NONE
        instrument.serial.stopbits = 1
        instrument.serial.timeout  = 1  
        instrument.mode = minimalmodbus.MODE_RTU
        
except:
        util.logging.error(f"no conectado {serialPort} reset ")
        #reiniciar_puerto_usb()
        os.system('sudo reboot')
        
try:
        sht20 = minimalmodbus.Instrument(serialPort,slave_idsht20,True)
        sht20.serial.baudrate= 19200
        sht20.serial.bytesize = 8
        sht20.serial.parity   = serial.PARITY_NONE
        sht20.serial.stopbits = 1
        sht20.serial.timeout  = 1  
        sht20.mode = minimalmodbus.MODE_RTU
except:
        util.logging.error(f"no conectado {serialPort} reset ")
        #reiniciar_puerto_usb()
        os.system('sudo reboot')       
load_dotenv(dotenv_path="/home/pi/medidor/medidorEastron/.env")

   
    

   
        
# Lógica principal
def main_loop():
    tempRaspberry = TIMERCHEQUEOTEMPERATURA
    tempMedidor   = TIMERMEDICION
    tempQueue     = TIMERCOLAEVENTOS
    tempPing      = TIMERPING
    tempCheckusb  = TIMECHECKUSBETHERNET 
    tempHora      = TIMECHECK_USB_ETHERNET_TIME
  
    # Publicar el encendido del sistema
    util.logging.info("Sistema encendido.")
    # mediciones de los sensores 
    conneced_meter = json.dumps(eventHandler.medidor_conectado())
    medidiones = json.dumps(payloadMedicion())
    time.sleep(0.5)
    sht20mediciones = json.dumps(read_sht20())
    
    if  util.check_internet_connection():
         # Conectar al cliente MQTT
        mqtt_client = awsaccess.connect_to_mqtt()
        if mqtt_client:
            awsaccess.publish_mediciones(mqtt_client, conneced_meter)
            awsaccess.publish_mediciones(mqtt_client, medidiones)
            awsaccess.publish_mediciones(mqtt_client,sht20mediciones)
            awsaccess.disconnect_from_aws_iot(mqtt_client)
        else:
            util.logging.error("No hay Conexion a AWS, almacena en la cola, las mediciones del medidor, Temp, Humedad y la hora de encendido.")
            fileventqueue.agregar_evento(medidiones)
            fileventqueue.agregar_evento(conneced_meter)
            fileventqueue.agregar_evento(sht20mediciones)
    else:
        util.logging.error("No hay internet, almacena en la cola, las mediciones del medidor, Temp, Humedad y la hora de encendido.")
        fileventqueue.agregar_evento(medidiones)
        fileventqueue.agregar_evento(conneced_meter)
        fileventqueue.agregar_evento(sht20mediciones)
    # Verificar la temperatura al inicio
    Temp.check_temp()

    # Bucle principal
    while True:
        tempRaspberry, tempMedidor, tempQueue, tempPing, tempCheckusb = util.actualizar_temporizadores(
        tempRaspberry, tempMedidor, tempQueue, tempPing, tempCheckusb)

        if tempRaspberry == 0:
            tempRaspberry = TIMERCHEQUEOTEMPERATURA
            Temp.check_temp()
            util.mostrar_estado_memoria()
        # Mediciones cada 10 minutos
        if tempMedidor == 0:
            tempMedidor = TIMERMEDICION
            medidiones = json.dumps(payloadMedicion())
            time.sleep(0.5)
            sht20mediciones = json.dumps(read_sht20())
            if  util.check_internet_connection():
                mqtt_client = awsaccess.connect_to_mqtt()
                if mqtt_client:
                    awsaccess.publish_mediciones(mqtt_client, medidiones)
                    awsaccess.publish_mediciones(mqtt_client,sht20mediciones)
                    awsaccess.disconnect_from_aws_iot(mqtt_client)
                else:
                    fileventqueue.agregar_evento(medidiones)
                    fileventqueue.agregar_evento(sht20mediciones)
            else:
                fileventqueue.agregar_evento(medidiones)
                fileventqueue.agregar_evento(sht20mediciones)
        if tempQueue == 0:
            tempQueue = TIMERCOLAEVENTOS
            process_event_queue()

        if tempPing == 0:
            interfaz = "eth0"
            tempPing = TIMERPING
            util.run_in_thread(interfaz)
            #if util.enable_interface(interfaz):
                #util.logging.info(f"Conexión a internet disponible en {interfaz}.")
            #else:
                #util.logging.info(f"Sin conexión a internet en {interfaz}.")    
            

        if tempCheckusb == 0:
            tempcheckusb = TIMECHECKUSBETHERNET
            tempHora -= 1
            if tempHora == 0:
                tempHora = TIMECHECK_USB_ETHERNET_TIME
                util.check_usb_connection()

# Punto de entrada principal
if __name__ == '__main__':
    main_loop()