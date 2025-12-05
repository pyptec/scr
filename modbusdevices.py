import minimalmodbus
import serial
import util  # si usas util.get__time_utc() o logging


'''
Parametros del pto serie modbus
'''
serialPort= "/dev/ttyS0"

#-----------------------------------------------------------------------------------------------------------

#-----------------------------------------------------------------------------------------------------------
def payload_event_modbus(config):
    """
    Lee temperatura y humedad del sensor THT03R (Modbus RTU) usando la configuración YAML.
    Espera en config:
      - slave_id, baudrate, bytesize, parity, stopbits, timeout
      - opcional: port (si no está, usa variable global serialPort)
      - registers: lista de dicts con:
          { "name": "...", "alias": "...", "address": 0, "unit": 1,
            "fc": 3, "decimals": 1, "signed": false }
    """
    """
    Lee temperatura y humedad del sensor THT03R (Modbus RTU).
    Compatible con tu YAML reducido (sin fc ni decimals definidos).
    """
    valores, unidades = [], []
    port = config.get('port', None)
    if port is None:
        port = serialPort
    # leer flag debug desde el YAML (default: false)
    debug_enabled = config.get('debug', False)
    try:
        #print("\n=== Iniciando lectura THT03R ===")
        #print(f"Puerto: {serialPort}")
        #print(f"Slave ID: {config['slave_id']}")
        #print(f"Baudios: {config['baudrate']}, Paridad: {config['parity']}, Timeout: {config['timeout']}\n")
        instrumento = minimalmodbus.Instrument(port, config['slave_id'])
        instrumento.serial.baudrate = config['baudrate']
        instrumento.serial.bytesize = config['bytesize']
        instrumento.serial.stopbits = config['stopbits']
        instrumento.serial.timeout = config['timeout']
        instrumento.serial.inter_byte_timeout = 0.2
        instrumento.mode = minimalmodbus.MODE_RTU
        instrumento.clear_buffers_before_each_transaction = True
        instrumento.close_port_after_each_call = True
        # Paridad
        parity_map = {
            'N': serial.PARITY_NONE,
            'E': serial.PARITY_EVEN,
            'O': serial.PARITY_ODD
        }
        instrumento.serial.parity = parity_map.get(config['parity'].upper(), serial.PARITY_NONE)
        # nombre para logs (desde el YAML)
        device_name = config.get('device_name') 

        
        instrumento.debug = debug_enabled
        # Leer cada registro del sensor
        for reg in config['registers']:
            address = reg['address']
            # valores por defecto para este sensor
            fc  = reg.get('fc')
            decimals = reg.get('decimals')
            signed = False
            #print(f"→ Leyendo dirección {address} (función {fc}) ...")
             
            val = instrumento.read_register(address, decimals, functioncode=fc, signed=signed)
            #print(f"   Valor leído bruto: {val}")
            
            # Redondeo suave
            val = round(val, 1)

            valores.append(str(val))
            unidades.append(str(reg['unit']))
            #print(f"\nValores finales leídos: {valores}")
            #print(f"Unidades asociadas: {unidades}")
            #print("==============================\n")
        return {
            "d": [{
                "t": util.get__time_utc(),
                "g": config['id_device'],
                "v": valores,
                "u": unidades
            }]
        }

    except Exception as e:
        util.logging.error(f"[{device_name}] Error general al leer el equipo "
            f"(slave={config.get('slave_id')}, port={port}): {type(e).__name__}: {e}")
        return None
    