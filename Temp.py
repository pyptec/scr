import os
import subprocess
import time
import json
import threading
import signal

import RPi.GPIO as GPIO

import util
import awsaccess
import fileventqueue
import modbusdevices

from db.samee100_db import guardar_medicion


# =============================================================================
# CONSTANTES
# =============================================================================

FORMATO_DATE = "%d/%m/%Y %H:%M "

GPIO11_VENTILADOR = 11
GPIO5_PILOTO = 5
GPIO23_WDI = 23
GPIO6_DOOR = 6


# =============================================================================
# GPIO
# =============================================================================
#
# IMPORTANTE:
#
# NO inicializar GPIO a nivel global.
#
# SAMEE100 tiene varios procesos independientes:
#
#   - medidor.service
#   - samee100-dashboard
#   - samee100-j1939
#
# api/app.py importa util.py y util.py importa Temp.py.
#
# Si hacemos GPIO.setup() durante "import Temp", el dashboard termina
# reclamando GPIO5/GPIO11/GPIO23 aunque no sea el proceso encargado
# del hardware.
#
# Los GPIO de salida se inicializan solamente cuando una función
# de hardware realmente los necesita.
#
# =============================================================================

_gpio_outputs_initialized = False
_gpio_lock = threading.Lock()


def setup_gpio_outputs():
    """
    Inicializa una sola vez los GPIO de salida utilizados por SAMEE100.

    Debe ser llamado únicamente cuando alguna función de hardware
    realmente vaya a utilizar ventilador, piloto o watchdog.

    Importar Temp.py NO reclama GPIO.
    """

    global _gpio_outputs_initialized

    if _gpio_outputs_initialized:
        return

    with _gpio_lock:

        if _gpio_outputs_initialized:
            return

        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)

        # Con rpi-lgpio se especifica estado inicial explícitamente.
        GPIO.setup(
            GPIO11_VENTILADOR,
            GPIO.OUT,
            initial=GPIO.LOW
        )

        GPIO.setup(
            GPIO5_PILOTO,
            GPIO.OUT,
            initial=GPIO.LOW
        )

        GPIO.setup(
            GPIO23_WDI,
            GPIO.OUT,
            initial=GPIO.LOW
        )

        _gpio_outputs_initialized = True


# =============================================================================
# ESTADO INTERNO PUERTA
# =============================================================================

_door_state = {
    "active": None,
    "changed_ts": None,
}


# =============================================================================
# TEMPERATURA RASPBERRY
# =============================================================================

def cpu_temp():
    """
    Lee únicamente la temperatura de CPU.

    Esta función NO utiliza GPIO y puede ser llamada desde el dashboard
    sin reclamar GPIO5/GPIO11/GPIO23.
    """

    thermal_zone = subprocess.Popen(
        ["cat", "/sys/class/thermal/thermal_zone0/temp"],
        stdout=subprocess.PIPE
    )

    out, err = thermal_zone.communicate()

    cpu_temperature = int(out.decode()) / 1000

    return cpu_temperature


# =============================================================================
# CONTROL VENTILADOR
# =============================================================================

def check_temp():
    """
    Comprueba temperatura de CPU y controla ventilador GPIO11.
    """

    setup_gpio_outputs()

    cpu = cpu_temp()

    if cpu > 48.0:

        GPIO.output(GPIO11_VENTILADOR, True)

        util.logging.info(
            f"CPU ALTA: {cpu:.1f} ºC"
        )

    else:

        GPIO.output(GPIO11_VENTILADOR, False)

        util.logging.info(
            f"CPU BAJA: {cpu:.1f} ºC"
        )


# =============================================================================
# PILOTO
# =============================================================================

def parpadear_led_500ms():
    """
    Hace parpadear el piloto GPIO5 durante 500 ms.
    """

    setup_gpio_outputs()

    GPIO.output(GPIO5_PILOTO, True)

    time.sleep(0.5)

    GPIO.output(GPIO5_PILOTO, False)


# =============================================================================
# WATCHDOG
# =============================================================================

def wdt():
    """
    Genera pulso de watchdog en GPIO23.
    """

    setup_gpio_outputs()

    util.logging.info("WDT:INICIADO")

    GPIO.output(GPIO23_WDI, True)

    time.sleep(0.2)

    GPIO.output(GPIO23_WDI, False)

    time.sleep(0.2)


def iniciar_wdt():
    """
    Ejecuta el pulso watchdog en un hilo independiente.
    """

    hilo_wdt = threading.Thread(
        target=wdt,
        daemon=True
    )

    hilo_wdt.start()


# =============================================================================
# PUERTA
# =============================================================================

def door():

    return GPIO.input(GPIO6_DOOR)


# -----------------------------------------------------------------------------
# Lee el pin de puerta con inversión
# -----------------------------------------------------------------------------

def _door_read_active(invert_low: bool) -> bool:
    """
    Lee el pin de puerta y aplica inversión.

    invert_low=True:
        activo si GPIO lee 0

    invert_low=False:
        activo si GPIO lee 1
    """

    raw = GPIO.input(GPIO6_DOOR)

    return (raw == 0) if invert_low else (raw == 1)


# -----------------------------------------------------------------------------
# Informa si la puerta está abierta
# -----------------------------------------------------------------------------

def door_is_open() -> bool:
    """
    True si la puerta está ABIERTA.

    Usa inversión definida en door.yml.
    No publica información.
    """

    door_cfg = _door_cfg()

    invert = bool(
        door_cfg.get(
            "invert_active_low",
            True
        )
    )

    try:

        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)

        GPIO.setup(
            GPIO6_DOOR,
            GPIO.IN,
            pull_up_down=GPIO.PUD_UP
        )

    except Exception:
        pass

    return _door_read_active(invert)


# -----------------------------------------------------------------------------
# Carga configuración puerta
# -----------------------------------------------------------------------------

def _door_cfg():

    try:

        cfg = util.cargar_configuracion(
            os.getenv("CFG_DOOR"),
            os.getenv("CFG_DOOR_SECTION")
        )

        if not isinstance(cfg, dict):

            util.logging.error(
                "[DOOR] door.yml no devolvió un dict válido"
            )

            return {}

        if isinstance(cfg.get("medidores"), dict):

            door_cfg = cfg["medidores"].get(
                "door_sensor"
            )

            if isinstance(door_cfg, dict):
                return door_cfg

        door_cfg = cfg.get("door_sensor")

        if isinstance(door_cfg, dict):
            return door_cfg

        if (
            "i" in cfg
            or "debounce_ms" in cfg
            or "invert_active_low" in cfg
        ):
            return cfg

        util.logging.error(
            f"[DOOR] Estructura no reconocida en door.yml: {cfg}"
        )

        return {}

    except Exception as e:

        util.logging.error(
            "[DOOR] No se pudo cargar door.yml: "
            f"{type(e).__name__}: {e}"
        )

        return {}


# -----------------------------------------------------------------------------
# Configura interrupción GPIO puerta
# -----------------------------------------------------------------------------

def setup_door_interrupt():

    door_cfg = _door_cfg()

    debounce_ms = int(
        door_cfg.get("debounce_ms") or 80
    )

    invert = bool(
        door_cfg.get("invert_active_low")
        if door_cfg.get("invert_active_low") is not None
        else True
    )

    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)

    try:

        GPIO.remove_event_detect(
            GPIO6_DOOR
        )

    except Exception:
        pass

    try:

        GPIO.cleanup(
            GPIO6_DOOR
        )

    except Exception:
        pass

    GPIO.setup(
        GPIO6_DOOR,
        GPIO.IN,
        pull_up_down=GPIO.PUD_UP
    )

    time.sleep(0.02)

    _door_state["active"] = _door_read_active(
        invert
    )

    _door_state["changed_ts"] = time.monotonic()

    try:

        GPIO.add_event_detect(
            GPIO6_DOOR,
            GPIO.BOTH,
            callback=_door_callback,
            bouncetime=debounce_ms
        )

        util.logging.info(
            f"[DOOR] Interrupción lista en GPIO{GPIO6_DOOR} "
            f"(debounce={debounce_ms} ms)"
        )

        return

    except RuntimeError as e:

        util.logging.error(
            f"[DOOR] add_event_detect falló: {e}. "
            "Activando fallback por polling…"
        )

    def _door_poll_worker():

        last = _door_state["active"]

        while True:

            cur = _door_read_active(
                invert
            )

            if cur != last:

                _door_callback(
                    GPIO6_DOOR
                )

                last = cur

            time.sleep(
                max(
                    0.05,
                    debounce_ms / 1000.0
                )
            )

    t = threading.Thread(
        target=_door_poll_worker,
        daemon=True
    )

    t.start()

    util.logging.info(
        "[DOOR] Fallback por polling activado."
    )


# -----------------------------------------------------------------------------
# Callback puerta
# -----------------------------------------------------------------------------

def _door_callback(channel):

    door_cfg = _door_cfg()

    raw_i = door_cfg.get("i")

    if raw_i is None:

        util.logging.warning(
            "[DOOR] 'i' no definido en door.yml; "
            "usando 12 por defecto"
        )

        raw_i = 12

    i_value = int(raw_i)

    regs = door_cfg.get(
        "registers",
        []
    )

    u_open = _get_unit(
        regs,
        {
            "door_open",
            "estado_puerta"
        },
        "138"
    )

    u_dur = _get_unit(
        regs,
        {
            "door_open_duration_s",
            "duracion_abierta"
        },
        "145"
    )

    invert = bool(
        door_cfg.get("invert_active_low")
        if door_cfg.get("invert_active_low") is not None
        else True
    )

    active = _door_read_active(
        invert
    )

    now = time.monotonic()

    last = _door_state.get(
        "active"
    )

    if last is None:

        _door_state["active"] = active

        _door_state["changed_ts"] = now

        if active:

            util.logging.warning(
                "[DOOR] ABIERTA"
            )

            _publish_ivu(
                i_value,
                ["1"],
                [u_open]
            )

        else:

            util.logging.info(
                "[DOOR] CERRADA"
            )

            _publish_ivu(
                i_value,
                ["0"],
                [u_open]
            )

        return

    if active == last:
        return

    prev_ts = _door_state["changed_ts"]

    _door_state["active"] = active

    _door_state["changed_ts"] = now

    if active:

        util.logging.warning(
            "[DOOR] ABIERTA"
        )

        _publish_ivu(
            i_value,
            ["1"],
            [u_open]
        )

    else:

        dur = round(
            now - prev_ts,
            1
        )

        util.logging.info(
            f"[DOOR] CERRADA. Abierta {dur}s"
        )

        _publish_ivu(
            i_value,
            [
                "0",
                str(dur)
            ],
            [
                u_open,
                u_dur
            ]
        )


# -----------------------------------------------------------------------------
# Busca unidad
# -----------------------------------------------------------------------------

def _get_unit(
    regs,
    candidates,
    default_str
):

    cand = set(
        str(x)
        for x in candidates
    )

    for r in (regs or []):

        alias = str(
            r.get("alias")
            or r.get("name")
            or ""
        )

        if alias in cand:

            u = r.get("u")

            if u is not None:

                return str(u)

    util.logging.warning(
        f"[CFG] u-code no encontrado para "
        f"{candidates}; usando {default_str}"
    )

    return str(default_str)


# -----------------------------------------------------------------------------
# Payload puerta
# -----------------------------------------------------------------------------

def _payload_ivu(
    i_value: int,
    v_list,
    u_list
):

    v_norm = [
        None if v is None else str(v)
        for v in v_list
    ]

    u_norm = [
        None if u is None else str(u)
        for u in u_list
    ]

    return {
        "d": [
            {
                "t": util.get__time_utc(),
                "i": int(i_value),
                "v": v_norm,
                "u": u_norm
            }
        ]
    }


# -----------------------------------------------------------------------------
# Publicación puerta
# -----------------------------------------------------------------------------

def _publish_ivu(
    i_value: int,
    v_list,
    u_list
):

    try:

        msg = json.dumps(
            _payload_ivu(
                i_value,
                v_list,
                u_list
            )
        )

        if util.ensure_internet_failover():

            cli = awsaccess.connect_to_mqtt()

            if cli:

                guardar_medicion(
                    msg,
                    sent_aws=1
                )

                awsaccess.publish_mediciones(
                    cli,
                    msg
                )

                awsaccess.disconnect_from_aws_iot(
                    cli
                )

                util.logging.info(
                    f"[DOOR] Dato enviado "
                    f"(i={i_value}, "
                    f"v={v_list}, "
                    f"u={u_list})"
                )

            else:

                guardar_medicion(
                    msg,
                    sent_aws=0
                )

                fileventqueue.agregar_evento(
                    msg
                )

        else:

            guardar_medicion(
                msg,
                sent_aws=0
            )

            fileventqueue.agregar_evento(
                msg
            )

    except Exception as e:

        util.logging.error(
            "[DOOR] Error publicando IVU: "
            f"{type(e).__name__}: {e}"
        )