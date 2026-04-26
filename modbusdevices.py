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
     # nombre para logs (desde el YAML)
    device_name = config.get('device_name') 

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
        instrumento.debug = debug_enabled
        
        device_name = config.get('device_name', device_name)
        # Leer cada registro del sensor
        for reg in config['registers']:
            address = reg['address']
            # valores por defecto para este sensor
            fc  = reg.get('fc',3)
            data_type = str(reg.get('type', '')).lower().strip()
            decimals = reg.get('decimals',0)
            signed = False #bool(reg.get('signed', False))
            #print(f"→ Leyendo dirección {address} (función {fc}) ...")
            try:
                if data_type == "float32":
                    val = instrumento.read_float(address, functioncode=fc, number_of_registers=2)
                elif data_type == "uint32":
                    #val = instrumento.read_long(address,functioncode=fc,signed=False,byteorder=minimalmodbus.BYTEORDER_BIG)
                    raw = instrumento.read_registers(address, 2, functioncode=fc)
                    val = (raw[0] << 16) + raw[1]
                    val = float(val)
                    if debug_enabled:
                        
                        util.logging.info(
                        f"[{device_name}] UINT32 addr={address} raw={raw} valor={val}"
                        )
                elif data_type == "int32": 
                    #no se a probado
                    val = instrumento.read_long(address,functioncode=fc,signed=True,byteorder=minimalmodbus.BYTEORDER_BIG)
                else: 
                    val = instrumento.read_register(address, decimals, functioncode=fc, signed=signed)
                #print(f"   Valor leído bruto: {val}")
                if debug_enabled:
                    util.logging.info( f"[{device_name}] addr={address} fc={fc} type={data_type or 'register'} valor bruto={val}")

                # Redondeo suave
                if isinstance(val, float):
                    val = round(val, 1)
            
                valores.append(str(val))
                #unidades.append(int(reg['unit'])) #ojo no funciona bien
                unidades.append(str(reg['unit']))
                #print(f"\nValores finales leídos: {valores}")
                #print(f"Unidades asociadas: {unidades}")
                #print("==============================\n")
            except Exception as e:
                util.logging.error(
                    f"[{device_name}] ERROR registro {reg.get('alias', reg.get('name'))} "
                    f"addr={address} type={data_type}: {type(e).__name__}: {e}"
                )
                valores.append("0")
                unidades.append(int(reg['unit']))
        util.logging.info(
        f"[{device_name}] Payload armado: valores={len(valores)} unidades={len(unidades)}")        
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
    