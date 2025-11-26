import time
import os
import util

# Nombre del archivo que almacenará los eventos
archivo_eventos = '/home/pi/medidor/eventos/eventos.txt'

# Función para agregar eventos al archivo
def agregar_evento(evento):
    with open(archivo_eventos, 'a') as archivo:
        archivo.write(f'{evento}\n')
    util.logging.info("Agregado: evento")

# Función para leer y procesar el primer evento del archivo
def procesar_evento():
    if os.path.exists(archivo_eventos):
        with open(archivo_eventos, 'r') as archivo:
            lineas = archivo.readlines()
        
        if lineas:
            # Eliminar el primer evento de la lista
            primer_evento = lineas[0].strip()
            lineas_restantes = lineas[1:]

            # Sobrescribir el archivo sin el primer evento
            with open(archivo_eventos, 'w') as archivo:
                archivo.writelines(lineas_restantes)

            return primer_evento
        else:
            return None #print("No hay eventos para procesar.")
    else:
        print(f"El archivo {archivo_eventos} no existe.")
        return None
# Función para procesar todos los eventos
def procesar_todos_los_eventos():
    while True:
        if os.path.exists(archivo_eventos):
            with open(archivo_eventos, 'r') as archivo:
                lineas = archivo.readlines()
            if not lineas:
                print("Todos los eventos han sido procesados.")
                break
        procesar_evento()
#se procesan 8horas de cola
def procesar_eventos_de_uno_en_uno(cantidad=48):
    if os.path.exists(archivo_eventos):
        with open(archivo_eventos, 'r') as archivo:
            lineas = archivo.readlines()

        if lineas:
            # Obtener hasta 'cantidad' eventos o menos si hay menos eventos disponibles
            eventos_a_procesar = lineas[:cantidad]
            lineas_restantes = lineas[cantidad:]

            # Sobrescribir el archivo sin los eventos procesados
            with open(archivo_eventos, 'w') as archivo:
                archivo.writelines(lineas_restantes)

            # Usar un generador para retornar los eventos uno por uno
            for evento in eventos_a_procesar:
                yield evento.strip()  # Retorna cada evento uno por uno
        else:
            return  # No hay eventos para procesar
    else:
        print(f"El archivo {archivo_eventos} no existe.")
        return  # El archivo no existe
def contar_eventos():
    if os.path.exists(archivo_eventos):
        with open(archivo_eventos, 'r') as archivo:
            lineas = archivo.readlines()  # Lee todas las líneas del archivo
            cantidad_eventos = len(lineas)  # Cuenta cuántas líneas hay
            return cantidad_eventos
    else:
        return 0  # Devuelve 0 si el archivo no existe