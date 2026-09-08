#!/bin/bash
# Activar entorno virtual
source /home/pi/SAMEE100/bin/activate

# Esperar 5 segundos antes de ejecutar el script en Python
sleep 5

# Ejecutar el script en Python

python /home/pi/SAMEE100/scr/pypmedidores.py
