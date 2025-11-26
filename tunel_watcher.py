# Archivo: tunel_watcher.py
import subprocess
import time
import threading
import util

TUNEL_PUERTO = 2222
DESTINO_SSH = ""  # Reemplaza con tu IP si es dinámica ubuntu@52.54.214.8
ssh_process = None
def set_destino(ip):
    global DESTINO_SSH
    DESTINO_SSH = f"ubuntu@{ip}"
def verificar_tunel_activo():
    try:
        salida = subprocess.check_output(["ss", "-tulnp"], stderr=subprocess.DEVNULL).decode()
        return f":{TUNEL_PUERTO} " in salida or f":{TUNEL_PUERTO}\n" in salida
    except Exception as e:
        util.logging.error(f"Error al verificar túnel SSH: {e}")
        return False
def cerrar_tunel():
    global ssh_process
    if ssh_process:
        util.logging.warning("Cerrando túnel SSH...")
        ssh_process.terminate()
        ssh_process = None
#def lanzar_tunel():
def run_ssh():
    global ssh_process
    if ssh_process:
        ssh_process.terminate()
        ssh_process = None
        time.sleep(0.5)

    comando = [
        "ssh", "-N", "-R", f"{TUNEL_PUERTO}:localhost:22",
        DESTINO_SSH,
        "-o", "StrictHostKeyChecking=no"
    ]
    util.logging.info(f"Lanzando túnel SSH hacia {DESTINO_SSH} en puerto {TUNEL_PUERTO}...")
    try:
        ssh_process = subprocess.Popen(comando, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Esperamos 5 segundos para ver si crashea al inicio
        time.sleep(5)
        if ssh_process.poll() is not None:
            # Falló al iniciar
            stderr_output = ssh_process.stderr.read().decode()
            util.logging.error(f"Túnel SSH falló al iniciar:\n{stderr_output}")
            ssh_process = None

    except Exception as e:
            util.logging.error(f"Error al lanzar el túnel SSH: {e}")
            ssh_process = None
            
hilo = threading.Thread(target=run_ssh, daemon=True)
hilo.start()

def iniciar_watchdog(intervalo=60):
    def loop():
        while True:
            if not verificar_tunel_activo():
                util.logging.warning("Túnel SSH no activo. Intentando relanzarlo...")
                lanzar_tunel()
            else:
                util.logging.info("Túnel SSH verificado: activo.")
            time.sleep(intervalo)

    hilo = threading.Thread(target=loop, daemon=True)
    hilo.start()
'''
# Lógica principal
def main_loop():   
    iniciar_watchdog(intervalo=90)  # revisa cada 90 segundos
    lanzar_tunel()
if __name__ == '__main__':
    main_loop()
'''