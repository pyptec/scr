#!/usr/bin/env python3
import RPi.GPIO as GPIO
import time

# Pin del WDT (el mismo que usas en tu código: GPIO23)
WDI_PIN = 4

# Configuración básica de GPIO
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
GPIO.setup(WDI_PIN, GPIO.OUT)

print("WDT keep-alive iniciado. Pulsa Ctrl+C para salir.")

try:
    while True:
        # Pulso al watchdog
        GPIO.output(WDI_PIN, True)
        time.sleep(0.1)
        GPIO.output(WDI_PIN, False)
        time.sleep(1.0)   # Ajusta este tiempo según el timeout del WDT

except KeyboardInterrupt:
    print("\nSaliendo del WDT temporal...")

finally:
    # Dejar el pin en bajo y liberar GPIO
    GPIO.output(WDI_PIN, False)
    GPIO.cleanup()
    print("GPIO limpio, script terminado.")
