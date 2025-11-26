import RPi.GPIO as GPIO
import time

# Configurar el modo de numeración de los pines
GPIO.setmode(GPIO.BCM)

# Configurar el pin GPIO 18 como salida
GPIO.setup(18, GPIO.OUT)
try:
    while True:
   
        # Encender el LED
        GPIO.output(18, GPIO.HIGH)
        print("LED ENCENDIDO")
        time.sleep(5)  # Espera 2 segundos

        # Apagar el LED
        GPIO.output(18, GPIO.LOW)
        print("LED APAGADO")
        time.sleep(5)  # Espera 2 segundos

except KeyboardInterrupt:
    print("Programa interrumpido")

finally:
    GPIO.cleanup()  # Limpiar la configuración de los pines GPIO al finalizar el programa
    