import subprocess
import time, json
import RPi.GPIO as GPIO
import util
import threading
import signal
import  awsaccess, fileventqueue, modbusdevices
# constantes de programa
FORMATO_DATE="%d/%m/%Y %H:%M "
GPIO11_VENTILADOR=11 #11 18
GPIO5_PILOTO=5 #5 22
GPIO23_WDI=23
GPIO6_DOOR=6  #puerta  del gabinete



#Definiciones de GPIO
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
GPIO.setup(GPIO11_VENTILADOR, GPIO.OUT)
GPIO.setup(GPIO5_PILOTO, GPIO.OUT)
GPIO.setup(GPIO23_WDI, GPIO.OUT)
#GPIO.setup(GPIO6_DOOR, GPIO.IN)


# Estado interno puerta
_door_state = {
    "active": None,          # True=abierta (con invert_active_low=True)
    "changed_ts": None,      # time.monotonic() del último cambio
}
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
	
#-----------------------------------------------------------------------------------------------------------
#Lee el pin de puerta con inversión
#-----------------------------------------------------------------------------------------------------------
def _door_read_active(invert_low: bool) -> bool:
    """
    Lee el pin de puerta y aplica la inversión:
    - invert_low=True  => activo si GPIO lee 0 (pull-up + contacto a GND)
    - invert_low=False => activo si GPIO lee 1
    """
    raw = GPIO.input(GPIO6_DOOR)  # 0/1
    return (raw == 0) if invert_low else (raw == 1)

#-----------------------------------------------------------------------------------------------------------
# Informa si la puerta está abierta
#-----------------------------------------------------------------------------------------------------------
def door_is_open() -> bool:
    """
    True si la puerta está ABIERTA. Usa inversión definida en door.yml.
    NO publica nada; sólo lectura.
    """
    door = _door_cfg()
    invert = bool(door.get('invert_active_low', True))
    try:
        # Asegura modo/entrada (idempotente)
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(GPIO6_DOOR, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    except Exception:
        pass
    return _door_read_active(invert)
#-----------------------------------------------------------------------------------------------------------
#Carga configuración de la puerta desde door.yml
#-----------------------------------------------------------------------------------------------------------
def _door_cfg():
    try:
        cfg = util.cargar_configuracion('/home/pi/SAMEE200/scr/device/door.yml')
        return cfg.get('medidores', {}).get('door_sensor', {}) if isinstance(cfg, dict) else {}
    except Exception as e:
        util.logging.error(f"[DOOR] No se pudo cargar door.yml: {e}")
        return {}
#-----------------------------------------------------------------------------------------------------------
#Configura interrupción GPIO de puerta solo una vez
#-----------------------------------------------------------------------------------------------------------
def setup_door_interrupt():
    """
    Configura GPIO6_DOOR=6 como entrada con pull-up y registra interrupción BOTH.
    Si add_event_detect falla (pin ya tomado/permisos), activa fallback por polling.
    """
    door = _door_cfg()
    debounce_ms = int(door.get('debounce_ms', 80))
    invert = bool(door.get('invert_active_low', True))

    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)

    # Limpieza defensiva: quita detección previa y limpia SOLO este pin
    try:
        GPIO.remove_event_detect(GPIO6_DOOR)
    except Exception:
        pass
    try:
        GPIO.cleanup(GPIO6_DOOR)
    except Exception:
        pass

    # Re-configura y estabiliza
    GPIO.setup(GPIO6_DOOR, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    time.sleep(0.02)

    # Inicializa estado
    _door_state["active"] = _door_read_active(invert)
    _door_state["changed_ts"] = time.monotonic()

    # Intenta edge detection
    try:
        GPIO.add_event_detect(
            GPIO6_DOOR,
            GPIO.BOTH,
            callback=_door_callback,
            bouncetime=debounce_ms
        )
        util.logging.info(f"[DOOR] Interrupción lista en GPIO{GPIO6_DOOR} (debounce={debounce_ms} ms)")
        return
    except RuntimeError as e:
        util.logging.error(f"[DOOR] add_event_detect falló: {e}. Activando fallback por polling…")

    # Fallback por polling (50 ms o el debounce configurado)
    def _door_poll_worker():
        last = _door_state["active"]
        while True:
            cur = _door_read_active(invert)
            if cur != last:
                _door_callback(GPIO6_DOOR)  # dispara la misma lógica
                last = cur
            time.sleep(max(0.05, debounce_ms / 1000.0))

    t = threading.Thread(target=_door_poll_worker, daemon=True)
    t.start()
    util.logging.info("[DOOR] Fallback por polling activado.")
    
#-----------------------------------------------------------------------------------------------------------
# Callback de interrupción de puerta
#-----------------------------------------------------------------------------------------------------------
def _door_callback(channel):
    door = _door_cfg()
    i_value = int(door.get('i', 12))
    regs = door.get('registers', [])
    # usa lo que venga en YAML; defaults: abierta=145, duración=138
    u_open = _get_unit(regs, {"door_open", "estado_puerta"}, "138")
    u_dur  = _get_unit(regs, {"door_open_duration_s", "duracion_abierta"}, "145")

    invert = bool(door.get('invert_active_low', True))
    active = _door_read_active(invert)  # True = abierta
    now = time.monotonic()

    last = _door_state.get("active")
    if last is None:
        _door_state["active"] = active
        _door_state["changed_ts"] = now
        # opcional: publicar estado inicial solo si está abierta
        if active:
            _publish_ivu(i_value, ["1"], [u_open])
        return

    if active == last:
        return

    prev_ts = _door_state["changed_ts"]
    _door_state["active"] = active
    _door_state["changed_ts"] = now

    if active:
        util.logging.warning("[DOOR] ABIERTA → apagar relés Modbus.")
        #restablecer_sistema_post_puerta()
        _publish_ivu(i_value, ["1"], [u_open])  # v=1, u=138
        #_man_state["last_pressed"] = _btn_read_active(True)  # activo-bajo
    else:
        global _door_restored
        _door_restored = False
        dur = round(now - prev_ts, 1)
        util.logging.info(f"[DOOR] CERRADA. Abierta {dur}s")
        _publish_ivu(i_value, [str(dur)], [u_dur])  # evento “cerrada” (solo duración)
        
#-----------------------------------------------------------------------------------------------------------
# Busca en registers por alias o name; devuelve u en str.
#-----------------------------------------------------------------------------------------------------------
def _get_unit(regs, candidates, default_str):
    cand = set(str(x) for x in candidates)
    for r in (regs or []):
        alias = str(r.get('alias') or r.get('name') or '')
        if alias in cand:
            u = r.get('u')
            if u is not None:
                return str(u)  # << importante: devolver str
    util.logging.warning(f"[CFG] u-code no encontrado para {candidates}; usando {default_str}")
    return str(default_str)
#-----------------------------------------------------------------------------------------------------------
# Prepara el payload JSON para IVU puerta esta abierta
#-----------------------------------------------------------------------------------------------------------
def _payload_ivu(i_value: int, v_list, u_list):
    v_norm = [(None if v is None else str(v)) for v in v_list]
    u_norm = [(None if u is None else str(u)) for u in u_list]
    return {"d": [{"t": util.get__time_utc(), "i": int(i_value), "v": v_norm, "u": u_norm}]}
#-----------------------------------------------------------------------------------------------------------
# Publica IVU puerta abierta o cerrada
#-----------------------------------------------------------------------------------------------------------
def _publish_ivu(i_value: int, v_list, u_list):
    try:
        msg = json.dumps(_payload_ivu(i_value, v_list, u_list))
        if util.ensure_internet_failover():
            cli = awsaccess.connect_to_mqtt()
            if cli:
                awsaccess.publish_mediciones(cli, msg)
                awsaccess.disconnect_from_aws_iot(cli)
                util.logging.info(f"[DOOR] Dato enviado (i={i_value}, v={v_list}, u={u_list})")
            else:
                #util.logging.error("[DOOR] MQTT no disponible. Cola local.")
                fileventqueue.agregar_evento(msg)
        else:
            #util.logging.error("[DOOR] Sin internet. Cola local.")
            fileventqueue.agregar_evento(msg)
    except Exception as e:
        util.logging.error(f"[DOOR] Error publicando IVU: {type(e).__name__}: {e}")
        
