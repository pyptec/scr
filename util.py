# util.py unificado para SAMEE200 + maduración de banano

import datetime
import logging
import psutil
import os
import subprocess
import time
import sys
import socket
import threading
import yaml
import json
import shlex
import pathlib

# Import diferido: evita ciclos si algún módulo importa util antes que Temp
try:
    import Temp
except Exception:
    Temp = None


# -----------------------------------------------------------------------------
# LOGGING
# -----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler()
    ]
)

# Ajusta esta ruta según proyecto
ruta = "/home/pi/SAMEE200/scr/log_eventos.txt"


# -----------------------------------------------------------------------------
# ESTADO GLOBAL RED / USB
# -----------------------------------------------------------------------------
_USB_GUARD = {
    "last_dhcp": 0.0,
    "last_pdp": 0.0,
    "last_rebind": 0.0,
    "fails": 0,
}

CD_DHCP = 30.0
CD_PDP = 90.0
CD_REBIND = 180.0

_DNS_GUARD = {"since": 0.0}


def _now():
    return time.monotonic()


# -----------------------------------------------------------------------------
# LOG / TIEMPO
# -----------------------------------------------------------------------------
def log_event(message):
    try:
        with open(ruta, "a") as log_file:
            current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_file.write(f"[{current_time}] {message}\n")
    except Exception as e:
        print(f"Error al escribir en el archivo log_eventos: {e}")


def get__time_utc():
    now = datetime.datetime.now()
    timestamp = datetime.datetime.timestamp(now)
    return str(int(timestamp))


def signal_handler(sig, frame):
    sys.exit(0)


# -----------------------------------------------------------------------------
# CONFIG
# -----------------------------------------------------------------------------
def cargar_configuracion(path, medidor=None):
    """
    Compatible con ambos proyectos.

    Casos:
    1) YAML con:
       medidores:
         equipo_x:
           ...
       -> cargar_configuracion(path, 'equipo_x')

    2) YAML plano:
       key: value
       ...
       -> cargar_configuracion(path)

    3) Si medidor no existe, devuelve {}
    """
    try:
        with open(path, 'r') as file:
            config = yaml.safe_load(file)

        if not isinstance(config, dict):
            logging.warning(f"cargar_configuracion(): YAML vacío o inválido en {path}")
            return {}

        if medidor is None:
            return config

        return config.get('medidores', {}).get(medidor, {})

    except FileNotFoundError:
        logging.error(f"cargar_configuracion(): archivo no encontrado: {path}")
        return {}
    except Exception as e:
        logging.error(f"cargar_configuracion(): error leyendo {path}: {e}")
        return {}


# -----------------------------------------------------------------------------
# COMANDOS / RED
# -----------------------------------------------------------------------------
def _run(cmd, check=False):
    return subprocess.run(shlex.split(cmd), capture_output=True, text=True, check=check)


def _iface_up(iface):
    r = _run(f"ip link show {iface}")
    return r.returncode == 0 and "state UP" in r.stdout


def _has_net(iface=None, host="1.1.1.1", timeout=2):
    cmd = f"ping -c1 -W{timeout} {host}"
    if iface:
        cmd = f"ping -I {iface} -c1 -W{timeout} {host}"
    return _run(cmd).returncode == 0


def _has_net_iface(iface, host="1.1.1.1", timeout=2):
    return subprocess.call(
        ["ping", "-I", iface, "-c", "1", f"-W{timeout}", host],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    ) == 0


def _has_net_any():
    return subprocess.call(
        ["ping", "-c", "1", "-W", "2", "1.1.1.1"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    ) == 0


def _default_is_usb0():
    try:
        s = subprocess.check_output(["ip", "route", "show", "default"], text=True)
        return (" dev usb0 " in s) and (" via " in s)
    except Exception:
        return False


def usb0_ip_fallback():
    try:
        s = subprocess.check_output(["ip", "route", "show", "default"], text=True)
        for line in s.splitlines():
            if " dev usb0 " in line and " src " in line:
                parts = line.split()
                if "src" in parts:
                    return parts[parts.index("src") + 1]
    except Exception:
        pass

    try:
        s = subprocess.check_output(["ip", "route", "show", "dev", "usb0"], text=True)
        for line in s.splitlines():
            if " src " in line:
                parts = line.split()
                if "src" in parts:
                    return parts[parts.index("src") + 1]
    except Exception:
        pass

    return None


def _usb0_ip_quiet():
    try:
        out = subprocess.check_output(
            ["ip", "-4", "-o", "addr", "show", "dev", "usb0"],
            text=True
        )
        for token in out.split():
            if '/' in token and token.count('.') == 3:
                return token.split('/')[0]
    except Exception:
        pass
    return None


def usb0_reenumerate():
    try:
        dev = pathlib.Path("/sys/class/net/usb0")
        if not dev.exists():
            logging.error("usb0_reenumerate(): /sys/class/net/usb0 no existe.")
            return False

        bus = os.path.basename(os.path.realpath(dev / "device")).split(":")[0]
        unbind = "/sys/bus/usb/drivers/usb/unbind"
        bind = "/sys/bus/usb/drivers/usb/bind"

        subprocess.run(
            ["sudo", "tee", unbind],
            input=f"{bus}\n",
            text=True,
            stdout=subprocess.DEVNULL,
            check=False
        )
        time.sleep(1.0)
        subprocess.run(
            ["sudo", "tee", bind],
            input=f"{bus}\n",
            text=True,
            stdout=subprocess.DEVNULL,
            check=False
        )
        time.sleep(3.0)
        return True
    except Exception as e:
        logging.error(f"usb0_reenumerate() error: {e}")
        return False


def _set_default_if_missing_for_usb0():
    try:
        s = subprocess.check_output(["ip", "route", "show", "default"], text=True)
        for line in s.splitlines():
            if line.startswith("default ") and " dev usb0" in line and " via " not in line:
                subprocess.run(["sudo", "ip", "route", "del", "default", "dev", "usb0"], check=False)
                break
    except Exception:
        pass

    try:
        s = subprocess.check_output(["ip", "route", "show", "default"], text=True)
        for line in s.splitlines():
            if line.startswith("default ") and " dev usb0 " in line and " via " in line:
                return True
    except Exception:
        pass

    try:
        s = subprocess.check_output(["ip", "route", "show", "dev", "usb0"], text=True)
        for line in s.splitlines():
            if line.startswith("default ") and " via " in line:
                gw = line.split()[2]
                return subprocess.call(
                    ["sudo", "ip", "route", "replace", "default", "via", gw, "dev", "usb0", "metric", "150"]
                ) == 0
    except Exception:
        pass

    for gw in ("192.168.225.1", "192.168.100.1"):
        if subprocess.call(
            ["sudo", "ip", "route", "replace", "default", "via", gw, "dev", "usb0", "metric", "150"]
        ) == 0:
            return True

    return False


def switch_default_route_to(iface):
    try:
        if iface == "usb0":
            _set_default_if_missing_for_usb0()
        else:
            subprocess.run(["sudo", "ip", "route", "replace", "default", "dev", iface], check=False)
        logging.info(f"Ruta predeterminada ahora por {iface}")
    except Exception as e:
        logging.warning(f"switch_default_route_to({iface}) warn: {e}")


def iface_exists(iface):
    return os.path.isdir(f"/sys/class/net/{iface}")


def iface_operstate(iface):
    try:
        with open(f"/sys/class/net/{iface}/operstate", "r") as f:
            return f.read().strip()
    except Exception:
        return "unknown"


def iface_ip4(iface):
    try:
        out = subprocess.check_output(
            ["ip", "-4", "-o", "addr", "show", "dev", iface],
            text=True
        )
        for tok in out.split():
            if tok.count(".") == 3 and "/" in tok:
                return tok.split("/")[0]
    except Exception:
        pass
    return None


def primera_eth_disponible():
    candidatos = [n for n in psutil.net_if_addrs().keys() if n.startswith(("eth", "en"))]
    for iface in sorted(candidatos):
        if iface_exists(iface):
            return iface
    return "eth0" if iface_exists("eth0") else None


def restaurar_dns():
    logging.info("Restaurando DNS a 8.8.8.8 y 8.8.4.4")
    comando1 = 'echo "nameserver 8.8.8.8" | sudo tee /etc/resolv.conf'
    comando2 = 'echo "nameserver 8.8.4.4" | sudo tee -a /etc/resolv.conf'
    subprocess.run(comando1, shell=True, check=True)
    subprocess.run(comando2, shell=True, check=True)


def dns_ok(host="google.com", timeout=2):
    try:
        socket.setdefaulttimeout(timeout)
        socket.gethostbyname(host)
        return True
    except Exception:
        return False


def icmp_ok(host="1.1.1.1", timeout=2):
    return subprocess.call(
        ["ping", "-c", "1", f"-W{timeout}", host],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    ) == 0


def repair_dns(prefer_iface="usb0"):
    try:
        content = "nameserver 8.8.8.8\nnameserver 1.1.1.1\n"

        try:
            with open("/etc/resolv.conf", "w") as f:
                f.write(content)
            logging.info("DNS restaurado en /etc/resolv.conf")
        except PermissionError:
            try:
                proc = subprocess.run(
                    ["sudo", "tee", "/etc/resolv.conf"],
                    input=content,
                    text=True,
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                if proc.returncode != 0:
                    logging.error("sudo tee /etc/resolv.conf falló")
                    return False
                logging.info("DNS restaurado en /etc/resolv.conf vía sudo tee")
            except Exception as ee:
                logging.error(f"repair_dns(): fallback sudo tee error: {ee}")
                return False

        if prefer_iface:
            subprocess.run(["sudo", "dhcpcd", "-n", prefer_iface], check=False)
            time.sleep(1.0)

        # Sin shutil
        try:
            subprocess.run(["resolvectl", "flush-caches"], check=False)
        except Exception:
            try:
                subprocess.run(["systemd-resolve", "--flush-caches"], check=False)
            except Exception:
                pass

        return True

    except Exception as e:
        logging.error(f"repair_dns() error: {e}")
        return False


def check_usb_connection():
    """
    Si existe usb0, renueva DHCP y asegura default 'via' válida por usb0.
    """
    try:
        out = subprocess.check_output(["ip", "addr", "show", "usb0"], text=True)
        if "usb0:" not in out:
            logging.warning("'usb0' no está presente.")
            return

        logging.info("'usb0' detectado. Renovando DHCP (dhcpcd -n usb0)…")
        subprocess.run(["sudo", "dhcpcd", "-n", "usb0"], check=False)
        time.sleep(1.0)

        s = subprocess.check_output(["ip", "route", "show", "default"], text=True)
        ok = False
        for line in s.splitlines():
            if line.startswith("default ") and " dev usb0 " in line:
                ok = (" via " in line)
                break
        if ok:
            return

        _set_default_if_missing_for_usb0()

    except Exception as e:
        logging.error(f"check_usb_connection() error: {e}")


def heal_usb0():
    try:
        if dns_ok():
            _DNS_GUARD["since"] = 0.0
            _USB_GUARD["fails"] = 0
            return True

        icmp = icmp_ok()
        ip_u = iface_ip4("usb0")

        if icmp and not dns_ok():
            if _DNS_GUARD["since"] == 0.0:
                _DNS_GUARD["since"] = _now()

            logging.warning("ICMP OK pero DNS KO; intentando reparar DNS…")
            repair_dns("usb0")
            if dns_ok():
                _DNS_GUARD["since"] = 0.0
                _USB_GUARD["fails"] = 0
                return True

            if _now() - _DNS_GUARD["since"] > 300.0:
                logging.warning("DNS KO >5 min con IP; re-enumerando SIM7600…")
                if usb0_reenumerate():
                    check_usb_connection()
                    repair_dns("usb0")
                    _DNS_GUARD["since"] = 0.0
                    if dns_ok() or icmp_ok():
                        _USB_GUARD["fails"] = 0
                        return True
        else:
            _DNS_GUARD["since"] = 0.0

        if icmp:
            _USB_GUARD["fails"] = 0
            return True

        if _now() - _USB_GUARD["last_dhcp"] >= CD_DHCP:
            _USB_GUARD["last_dhcp"] = _now()
            check_usb_connection()
            if iface_ip4("usb0") and _has_net_iface("usb0"):
                if not dns_ok() and icmp_ok():
                    repair_dns("usb0")
                _USB_GUARD["fails"] = 0
                logging.info("usb0 OK tras DHCP/route.")
                return True

        if _now() - _USB_GUARD["last_pdp"] >= CD_PDP:
            _USB_GUARD["last_pdp"] = _now()
            logging.warning("usb0 sin salida; reactivando PDP/ECM por AT…")
            for tty in ("/dev/ttyUSB2", "/dev/ttyUSB3"):
                if os.path.exists(tty):
                    try:
                        with open(tty, "wb", buffering=0) as f:
                            for cmd in (
                                b"AT\r",
                                b"AT+CFUN=1\r",
                                b'AT+CGDCONT=1,"IP","internet.comcel.com"\r',
                                b'AT+CGAUTH=1,1,"claro","claro"\r',
                                b"AT+CGACT=1,1\r",
                                b'AT+CUSBPIDSWITCH=9011,1,1\r',
                            ):
                                f.write(cmd)
                                time.sleep(0.3)
                        break
                    except Exception as e:
                        logging.debug(f"AT por {tty} fallo: {e}")
            time.sleep(8)
            check_usb_connection()
            if iface_ip4("usb0") and _has_net_iface("usb0"):
                if not dns_ok() and icmp_ok():
                    repair_dns("usb0")
                _USB_GUARD["fails"] = 0
                logging.info("usb0 volvió tras PDP/ECM.")
                return True

        if _now() - _USB_GUARD["last_rebind"] >= CD_REBIND:
            _USB_GUARD["last_rebind"] = _now()
            if usb0_reenumerate():
                check_usb_connection()
                if iface_ip4("usb0") and _has_net_iface("usb0"):
                    if not dns_ok() and icmp_ok():
                        repair_dns("usb0")
                    _USB_GUARD["fails"] = 0
                    logging.info("usb0 volvió tras rebind USB.")
                    return True

        _USB_GUARD["fails"] = min(_USB_GUARD["fails"] + 1, 999)
        logging.error("usb0 sigue sin Internet (esperando cooldowns).")
        return False

    except Exception as e:
        logging.error(f"heal_usb0() error: {e}")
        return False


def ensure_internet_failover():
    """
    Prioridad: eth0 > usb0.
    """
    try:
        if _has_net_any():
            return True
        if _iface_up("eth0") and _has_net_iface("eth0"):
            switch_default_route_to("eth0")
            return True
        ok = heal_usb0()
        if ok and not _default_is_usb0():
            _set_default_if_missing_for_usb0()
        return ok
    except Exception as e:
        logging.error(f"ensure_internet_failover() error: {e}")
        return False


def check_internet_connection():
    """
    Compatibilidad con SAMEE200.
    Reutiliza la lógica robusta.
    """
    return ensure_internet_failover()


# -----------------------------------------------------------------------------
# UTILIDADES GENERALES
# -----------------------------------------------------------------------------
def reiniciar_puerto_usb(port='/dev/ttyUSB0'):
    try:
        os.system(f"sudo fuser -k {port}")
        os.system("sudo modprobe -r ftdi_sio")
        time.sleep(1)
        os.system("sudo modprobe ftdi_sio")
        logging.info(f"Puerto {port} reiniciado correctamente.")
    except Exception as e:
        logging.error(f"Error al reiniciar el puerto: {e}")


def actualizar_temporizadores(tempRaspberry, tempMedidor, tempQueue, tempPing, tempCheckusb, *extra, sleep_time=1):
    time.sleep(sleep_time)
    vals = [tempRaspberry - 1, tempMedidor - 1, tempQueue - 1, tempPing - 1, tempCheckusb - 1]
    vals.extend([x - 1 for x in extra])
    return tuple(vals)


def enable_interface(interface, hostname="google.com"):
    try:
        interface_status = os.popen(f"ip link show {interface}").read()
        if "state UP" in interface_status:
            logging.info(f"La interfaz {interface} ya está activa.")
        else:
            logging.info(f"Encendiendo la interfaz {interface}...")
            os.system(f"sudo ip link set {interface} up")
            time.sleep(5)

        logging.info(f"Verificando conexión en la interfaz {interface}...")
        response = os.system(f"ping -I {interface} -c 1 {hostname} > /dev/null 2>&1")

        if response == 0:
            logging.info(f"Conexión a internet detectada en {interface}.")
            return True
        else:
            logging.warning(f"No hay conexión a internet en {interface}.")
            return False

    except Exception as e:
        logging.error(f"Error al habilitar o verificar la interfaz {interface}: {e}")
        return False


def run_in_thread(interface):
    thread = threading.Thread(target=enable_interface, args=(interface,))
    thread.start()
    return thread


def ip_a_numero(ip):
    if not ip:
        return "0"
    return "".join(ip.split("."))


def obtener_ip_usb0():
    interfaces = psutil.net_if_addrs()
    if 'usb0' in interfaces:
        for info in interfaces['usb0']:
            if info.family == socket.AF_INET:
                return info.address
    return None


def payload_estado_sistema_y_medidor():
    cpu_temp_c = Temp.cpu_temp() if Temp else 0.0
    memoria = psutil.virtual_memory()
    cpu_usage = psutil.cpu_percent(interval=1)

    eth_iface = primera_eth_disponible() or "eth0"
    eth_up = iface_exists(eth_iface) and iface_operstate(eth_iface) == "up"
    eth_ip = iface_ip4(eth_iface) if eth_up else None

    usb_iface = "usb0"
    usb_exists = iface_exists(usb_iface)
    usb_up = usb_exists and iface_operstate(usb_iface) == "up"
    usb_ip = iface_ip4(usb_iface) if usb_up else None
    if not usb_ip and usb_exists:
        usb_ip = usb0_ip_fallback()

    if eth_up and eth_ip:
        ip_activa = eth_ip
    elif usb_ip:
        ip_activa = usb_ip
    else:
        ip_activa = ""

    ip_usb_report = usb_ip or ""
    ip_eth_report = eth_ip or ""

    ip_sin_puntos = ip_a_numero(ip_activa)
    ip_eth_num = ip_a_numero(ip_eth_report)

    mensurados = [
        str(round(cpu_temp_c, 1)),
        str(memoria.percent),
        str(cpu_usage),
        ip_sin_puntos,
        ip_eth_num,
    ]

    if Temp:
        Temp.check_temp()

    cfg = cargar_configuracion('/home/pi/SAMEE200/scr/device/sistema.yml', 'variables_del_sistema')
    g_id = cfg.get('id_device', 0)
    unidades_cfg = cfg.get('unidades', [])
    codigos_unidades = [u['codigo'] for u in unidades_cfg if 'codigo' in u]

    logging.info(
        f"SISTEMA (g={g_id}) → Temp={cpu_temp_c:.1f}°C | RAM={memoria.percent}% | "
        f"CPU={cpu_usage}% | IP_USB0={ip_usb_report} | IP_Ethernet={ip_eth_report}"
    )

    estado_sistema = {
        "t": get__time_utc(),
        "g": g_id,
        "v": mensurados,
        "u": codigos_unidades
    }
    return {"d": [estado_sistema]}


def _normalize_payload(p):
    if p is None:
        return {}
    if isinstance(p, str):
        try:
            p = json.loads(p)
        except Exception:
            return {}
    if not isinstance(p, dict):
        return {}
    d = p.get("d")
    if isinstance(d, list):
        return {"d": d}
    return {}


def merge_payloads(*payloads):
    merged = []
    for p in payloads:
        norm = _normalize_payload(p)
        dl = norm.get("d", [])
        if isinstance(dl, list):
            merged.extend(dl)
    return {"d": merged}

'''
# Función para registrar eventos en un archivo
import datetime
import logging
import psutil
import os
import subprocess
import time
import sys
import socket
import threading
import yaml
import Temp
import json
import shlex, pathlib

# Configuración básica de logging
logging.basicConfig(
    level=logging.INFO,  # Nivel mínimo de los mensajes que se registrarán
    format='%(asctime)s - %(levelname)s - %(message)s',  # Formato del mensaje
    handlers=[
        logging.FileHandler("app.log"),  # Guardar en un archivo log
        logging.StreamHandler()  # Mostrar en la consola
    ]
)
ruta ="/home/pi/medidor/medidorEastron/log_eventos.txt"
def log_event(message):
    try:
        with open(ruta, "a") as log_file:
            # Registrar la fecha y hora actual
            current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # Escribir el mensaje en el archivo
            log_file.write(f"[{current_time}] {message}\n")
    except Exception as e:
        print(f"Error al escribir en el archivo log_eventos: {e}")
        


#trae el clk en UTC
def get__time_utc():
    now = datetime.datetime.now()
    timestamp = datetime.datetime.timestamp(now)
    return str(int(timestamp))
#
def signal_handler(sig, frame):
    sys.exit(0)


def check_internet_connection():
    try:
        # Definición de parámetros
        hostname = "google.com"
        interfaces = {"eth0": "Ethernet", "usb0": "USB"}

        # Intento de conexión en cada interfaz
        for interface, name in interfaces.items():
            response = os.system(f"ping -I {interface} -c 1 {hostname} > /dev/null 2>&1")
            if response == 0:
                # Si hay conexión en la interfaz actual, cambiar la ruta predeterminada
                if switch_default_route_to(interface):
                    logging.info(f"Internet: Conectado a través de {name}")
                return True

        # Si ninguna interfaz tiene conexión
        logging.warning("Internet: No hay conexión en ninguna interfaz.")
        renovar_ip_usb0()
        return False

    except Exception as e:
        logging.error(f"Error al intentar verificar la conexión: {e}")
        return False
    
def switch_default_route_to(active_interface):
    try:
        # Verificar si eth0 es la interfaz activa y dejarla encendida si tiene conexión
        if active_interface == "eth0":
            inactive_interface = "usb0"
        else:
            # Apaga eth0 solo si no tiene conexión
            inactive_interface = "eth0"
            subprocess.run(["sudo", "ip", "link", "set", inactive_interface, "down"], check=True)
            logging.info(f"Interfaz {inactive_interface} apagada.")
    # Verifica si la interfaz ya es la ruta predeterminada
        current_route = os.popen("ip route show default").read()
        if f"default via" in current_route and active_interface in current_route:
            logging.info(f"La ruta predeterminada ya está en {active_interface}.")
            return False
    # Quitar la ruta predeterminada actual (si existe)
        os.system("sudo ip route del default")
    # Agregar la nueva ruta predeterminada para la interfaz deseada
        os.system(f"sudo ip route add default dev {active_interface}")
     # Funciones adicionales después de cambiar la ruta
        check_usb_connection()
        restaurar_dns()
        logging.info(f"Ruta predeterminada cambiada a {active_interface}") 
        return True 
    except Exception as e:
        logging.error(f"Error al cambiar la ruta predeterminada a {active_interface}: {e}")
        return False
def reiniciar_puerto_usb(port='/dev/ttyUSB0'):
    try:
        # Matar cualquier proceso que esté usando el puerto
        os.system(f"sudo fuser -k {port}")
        
        # Descargar y volver a cargar el módulo del kernel
        os.system("sudo modprobe -r ftdi_sio")  # Cambia "pl2303" según tu controlador
        time.sleep(1)  # Espera un segundo antes de volver a cargar el módulo
        os.system("sudo modprobe ftdi_sio")  # Cambia "pl2303" según tu controlador
        
        logging.info(f"Puerto {port} reiniciado correctamente.")
    except Exception as e:
        logging.error(f"Error al reiniciar el puerto: {e}")
        

def restaurar_dns():
    logging.info("Restaurando DNS a 8.8.8.8 y 8.8.4.4")
    # Comando para sobrescribir el archivo resolv.conf con el DNS primario
    comando1 = 'echo "nameserver 8.8.8.8" | sudo tee /etc/resolv.conf'
    
    # Comando para añadir el DNS secundario al archivo resolv.conf
    comando2 = 'echo "nameserver 8.8.4.4" | sudo tee -a /etc/resolv.conf'
    
    # Ejecutar los comandos
    subprocess.run(comando1, shell=True, check=True)
    subprocess.run(comando2, shell=True, check=True)   
# Función para verificar y conectar usb0 si está presente
def check_usb_connection():
    try:
        ifconfig_output = subprocess.check_output(["ifconfig"], text=True)
        if "usb0" in ifconfig_output:
            logging.info("'usb0' detectado en ifconfig.")
            subprocess.run(["sudo", "dhclient", "-v", "usb0"], check=True)
        else:
            logging.warning("'usb0' no está presente en ifconfig.")
    except Exception as e:
        logging.error(f"Error al ejecutar ifconfig: {e}")
        
def actualizar_temporizadores(tempRaspberry, tempMedidor, tempQueue, tempPing, tempCheckusb, sleep_time=1):

    time.sleep(1)
    tempRaspberry -= 1
    tempMedidor -= 1
    tempQueue -= 1
    tempPing -= 1
    tempCheckusb -= 1
    return tempRaspberry, tempMedidor, tempQueue, tempPing, tempCheckusb

def enable_interface(interface, hostname="google.com"):
    try:
        # Verificar si la interfaz está activa
        interface_status = os.popen(f"ip link show {interface}").read()
        if "state UP" in interface_status:
            logging.info(f"La interfaz {interface} ya está activa.")
        else:
        # Enciende la interfaz
            logging.info(f"Encendiendo la interfaz {interface}...")
            os.system(f"sudo ip link set {interface} up")
        
        # Espera 5 segundos para permitir la reconexión
            time.sleep(5)
        
        # Prueba de conexión a internet a través de la interfaz
        logging.info(f"Verificando conexión en la interfaz {interface}...")
        response = os.system(f"ping -I {interface} -c 1 {hostname} > /dev/null 2>&1")
        
        # Verificar si hay conexión
        if response == 0:
            logging.info(f"Conexión a internet detectada en {interface}.")
            return True
        else:
            logging.warning(f"No hay conexión a internet en {interface}.")
            return False
            
    except Exception as e:
        logging.error(f"Error al habilitar o verificar la interfaz {interface}: {e}")
        return False 
    
def run_in_thread(interface):
    thread = threading.Thread(target=enable_interface, args=(interface,))
    thread.start()
    return thread
def cargar_configuracion(path, medidor='meatrolME337'):
    with open(path, 'r') as file:
        config = yaml.safe_load(file)
        #print(config)  # Imprimir la configuración para verificar la estructura
        return config['medidores'].get(medidor, {})
    
def obtener_ip_usb0():
    # Obtiene las direcciones de todas las interfaces de red
    interfaces = psutil.net_if_addrs()

    # Verifica si 'usb0' existe en las interfaces
    if 'usb0' in interfaces:
        for info in interfaces['usb0']:
            if info.family == socket.AF_INET:  # Solo IPs IPv4
                return info.address  # Devuelve la dirección IP

    return None
def reset_usb0():
    """
    Baja y sube la interfaz usb0, o bien libera y renueva DHCP.
    Ajusta el comando según tu distro.
    """
    logging.warning("No hay IP en usb0: reset de la interfaz usb0")
    # Opción 1: down/up
    subprocess.run(["sudo", "ifconfig", "usb0", "down"], check=False)
    time.sleep(1)
    subprocess.run(["sudo", "ifconfig", "usb0", "up"],   check=False)
    # Opción 2: renovar DHCP
    # subprocess.run(["sudo", "dhclient", "-r", "usb0"], check=False)
    # time.sleep(1)
    # subprocess.run(["sudo", "dhclient", "usb0"], check=False)
    time.sleep(5)  # espera a que vuelva a negociar IP

def ip_a_numero(ip:str) -> str:
    """
    Convierte '192.168.0.5' → '19216805'.
    Si ip es None o cadena vacía, devuelve '0'.
    """
    if not ip:
        return "0"
    return "".join(ip.split("."))


def iface_exists(iface: str) -> bool:
    return os.path.isdir(f"/sys/class/net/{iface}")

def iface_operstate(iface: str) -> str:
    try:
        with open(f"/sys/class/net/{iface}/operstate", "r") as f:
            return f.read().strip()
    except Exception:
        return "unknown"

def iface_ip4(iface: str) -> str | None:
    try:
        out = subprocess.check_output(
            ["ip", "-4", "-o", "addr", "show", "dev", iface],
            text=True
        )
        for tok in out.split():
            if tok.count(".") == 3 and "/" in tok:
                return tok.split("/")[0]
    except Exception:
        pass
    return None
#-----------------------------------------------------------------------------------------------------------

#-----------------------------------------------------------------------------------------------------------
def primera_eth_disponible() -> str | None:
    # Prioriza nombres típicos (eth*, en*)
    candidatos = [n for n in psutil.net_if_addrs().keys() if n.startswith(("eth", "en"))]
    for iface in sorted(candidatos):
        if iface_exists(iface):
            return iface
    return "eth0" if iface_exists("eth0") else None
#-----------------------------------------------------------------------------------------------------------

#-----------------------------------------------------------------------------------------------------------
def payload_estado_sistema_y_medidor():
       # === Métricas del sistema ===
    cpu_temp_c = Temp.cpu_temp()
    memoria = psutil.virtual_memory()
    cpu_usage = psutil.cpu_percent(interval=1)

    # === Ethernet ===
    eth_iface = primera_eth_disponible() or "eth0"
    eth_up    = iface_exists(eth_iface) and iface_operstate(eth_iface) == "up"
    eth_ip    = iface_ip4(eth_iface) if eth_up else None

    # === USB0 (SIM7600) ===
    usb_iface  = "usb0"
    usb_exists = iface_exists(usb_iface)
    usb_up     = usb_exists and iface_operstate(usb_iface) == "up"
    usb_ip     = iface_ip4(usb_iface) if usb_up else None
    if not usb_ip and usb_exists:
        # Si la IP aún no aparece (ventana de renovación), usa fallback desde la tabla de rutas
        usb_ip = usb0_ip_fallback()

    # === IP activa para el campo numérico (prioridad ETH > USB) ===
    if eth_up and eth_ip:
        ip_activa = eth_ip
    elif usb_ip:
        ip_activa = usb_ip
    else:
        ip_activa = ""

    # === Reportes de texto (cada interfaz por separado) ===
    ip_usb_report = usb_ip or ""      # << esto es lo que verás en IP_USB0
    ip_eth_report = eth_ip or ""

    # === Campos numéricos (mantengo tu estructura actual) ===
    ip_sin_puntos = ip_a_numero(ip_activa)     # unidad 137 (IP activa numérica)
    ip_eth_num    = ip_a_numero(ip_eth_report) # unidad 144 (IP Ethernet numérica)

    # === Valores mensurados ===
    mensurados = [
        str(round(cpu_temp_c, 1)),
        str(memoria.percent),
        str(cpu_usage),
        ip_sin_puntos,
        ip_eth_num,
    ]

    # Watchdog térmico
    Temp.check_temp()

    # === YAML de variables del sistema ===
    cfg = cargar_configuracion(
        '/home/pi/SAMEE200/scr/device/sistema.yml',
        'variables_del_sistema'
    )
    g_id = cfg.get('id_device')
    unidades_cfg = cfg.get('unidades', [])
    codigos_unidades = [u['codigo'] for u in unidades_cfg]

    # === Log limpio (sin falsos warnings) con ambas IPs separadas ===
    logging.info(
        f"SISTEMA (g={g_id}) → Temp={cpu_temp_c:.1f}°C | RAM={memoria.percent}% | "
        f"CPU={cpu_usage}% | IP_USB0={ip_usb_report} | IP_Ethernet={ip_eth_report}"
    )

    # === Payload ===
    estado_sistema = {
        "t": get__time_utc(),
        "g": g_id,
        "v": mensurados,
        "u": codigos_unidades
    }
    return {"d": [estado_sistema]} 
    

def renovar_ip_usb0():
    try:
        # Ejecutar dhclient en la interfaz usb0
        subprocess.run(
            ["sudo", "dhclient", "-v", "usb0"],
            check=True
        )
        # Consultar la IP obtenida en usb0
        ip_result = subprocess.run(
            ["ip", "addr", "show", "usb0"],
            capture_output=True,
            text=True
        )
        for line in ip_result.stdout.splitlines():
            line = line.strip()
            if line.startswith("inet "):
                ip_con_mask = line.split()[1]  # Ejemplo: "192.168.1.45/24"
                ip = ip_con_mask.split("/")[0]  # Solo la IP -> "192.168.1.45"
                logging.info(f"Renovar Dirección IP obtenida en usb0: {ip}")
                
                return ip

        logging.warning("No se encontró dirección IP en usb0")
        return None

    except subprocess.CalledProcessError:
        logging.warning("Error al ejecutar dhclient")
        return None
'''