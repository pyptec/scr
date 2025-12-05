import subprocess
import time
import RPi.GPIO as GPIO
import util
import threading
import signal

# constantes de programa
FORMATO_DATE="%d/%m/%Y %H:%M "
GPIO11_VENTILADOR=11 #11 18
GPIO5_PILOTO=5 #5 22
GPIO23_WDI=23
GPIO6_DOOR=6 



#Definiciones de GPIO
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
GPIO.setup(GPIO11_VENTILADOR, GPIO.OUT)
GPIO.setup(GPIO5_PILOTO, GPIO.OUT)
GPIO.setup(GPIO23_WDI, GPIO.OUT)
GPIO.setup(GPIO6_DOOR, GPIO.IN)



#######################################
#Mantenimiento raspberry Temperatura
########################################
def cpu_temp():
	thermal_zone = subprocess.Popen(['cat', '/sys/class/thermal/thermal_zone0/temp'], stdout=subprocess.PIPE)
	out, err = thermal_zone.communicate()
	cpu_temp = int(out.decode())/1000
	return cpu_temp

########################################################
#Se chequea Temperatura y se apaga/prende el ventilador
########################################################
def check_temp():
	cpu = cpu_temp()
	#on_hardware("Temperatura: "+str(cpu))
	if cpu > 48.0  :
		#GPIO.output(GPIO18_VENTILADOR, False)
		GPIO.output(GPIO11_VENTILADOR, True)
		util.logging.info(f"CPU ALTA: {cpu:.1f} ºC")
		
	else: 
		#GPIO.output(GPIO18_VENTILADOR, True)
		GPIO.output(GPIO11_VENTILADOR, False)
		util.logging.info(f"CPU BAJA: {cpu:.1f} ºC")
		
# Función para hacer titilar el LED usando PWM
def parpadear_led_500ms():
    GPIO.output(GPIO5_PILOTO, True)
    time.sleep(0.5)  # Mantén el parpadeo durante 500 milisegundos
    GPIO.output(GPIO5_PILOTO, False)
   
def wdt():
    util.logging.info("WDT:INICIADO")
    GPIO.output(GPIO23_WDI, True)
    time.sleep(0.2)
    GPIO.output(GPIO23_WDI, False)
    time.sleep(0.2)
def iniciar_wdt():
    # Crear y empezar el hilo que ejecutará la función wdt
    hilo_wdt = threading.Thread(target=wdt)
    hilo_wdt.daemon = True  # El hilo se cerrará automáticamente cuando termine el programa principal
    hilo_wdt.start()
    
def door():
    return GPIO.input(GPIO6_DOOR)  # 1 = cerrada, 0 = abierta (o viceversa según conexión)
	
