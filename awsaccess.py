from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient
import random
import util
import os
import Temp
import threading
import shared
import fileventqueue
mensaje_lock = threading.Lock()
mensaje_recibido = None

def on_connect(client, userdata, flags, rc):
    """Callback para confirmar la conexión exitosa a AWS IoT."""
    if rc == 0:
        util.logging.info("Conexión exitosa con AWS IoT.")
        # Suscribirse al tópico después de la conexión
        topic = os.getenv('TOPIC')  # Suponiendo que el tópico está configurado en tu .env
        client.subscribe(topic)
        util.logging.info(f"Suscripción al tópico {topic} exitosa.")
    else:
        util.logging.error(f"Conexión fallida con AWS IoT. Código de error: {rc}")

def on_disconnect(client, userdata, rc):
    """Callback para manejar la desconexión del cliente MQTT."""
    if rc != 0:
        util.logging.error(f"Desconexión inesperada de AWS IoT. Código de error: {rc}")
    else:
        util.logging.info("Desconexión exitosa de AWS IoT.")
        
def on_message(client, userdata, message):
    """Callback cuando se recibe un mensaje en un tópico."""
    global tunel
    # Decodificar el mensaje recibido
    payload = message.payload.decode("utf-8")
    util.logging.info(f"Mensaje recibido en el tópico {message.topic}: {payload}")
    
    # Aquí puedes procesar el mensaje, por ejemplo:
    try:
        recibir_mensaje(payload)  # Guardar el mensaje recibido en la variable compartida
        #data = json.loads(payload)  # Si el mensaje es JSON
        #with mensaje_lock:
        #    tunel = data 
            
    except Exception as e:
        util.logging.error(f"Error al procesar el mensaje: {e}")
        
def recibir_mensaje(payload):
    with shared.mensaje_lock:
        shared.mensaje_recibido = payload
        print("Mensaje recibido y guardado.")

def connect_to_aws_iot(client_id, endpoint, root_ca, private_key, certificate, port=8883):
    # Crear el cliente MQTT con el ID del cliente
    mqtt_client = AWSIoTMQTTClient(client_id + str(random.randrange(255)))

    # Configurar el endpoint (el host o dirección de AWS IoT)
    mqtt_client.configureEndpoint(endpoint, port)

    # Configurar los certificados y la clave privada
    mqtt_client.configureCredentials(root_ca, private_key, certificate)

    # Configurar algunos parámetros adicionales del cliente MQTT
    mqtt_client.configureAutoReconnectBackoffTime(1, 32, 20)
    mqtt_client.configureOfflinePublishQueueing(-1)  # Número ilimitado de publicaciones en cola
    mqtt_client.configureDrainingFrequency(2)  # Draining: 2 publicaciones/segundo
    mqtt_client.configureConnectDisconnectTimeout(30)  # Tiempo de espera de conexión (10 segundos)
    mqtt_client.configureMQTTOperationTimeout(5)  # Tiempo de espera de las operaciones MQTT (5 segundos)

     # Configurar callbacks
    mqtt_client.onConnect = on_connect
    
    #mqtt_client.onDisconnect = on_disconnect
    
    # Intentar conectar al cliente
    try:
        mqtt_client.connect()
        util.logging.info(f"Conexión exitosa con AWS IoT con el ID de cliente: {client_id}")
    except Exception as e:
        #util.log_event(f"Error: al conectar con AWS IoT: {str(e)}")
        util.logging.error(f"Error al conectar con AWS IoT: {str(e)}")
        mqtt_client = None

    return mqtt_client
def on_publish(client, userdata, mid):
    """Callback que se ejecuta cuando un mensaje es publicado correctamente."""
    util.logging.info(f"Mensaje publicado con ID {mid}.")

def publish_to_topic(mqtt_client, topic, message, qos=1):
    if mqtt_client:
        try:
            # Configurar el callback para la publicación
            mqtt_client.on_publish = on_publish
            mqtt_client.publish(topic, message, qos)
            util.logging.info("Mensaje publicado ")
        except Exception as e:
            util.logging.error(f"Error: al publicar mensaje: {str(e)}")
            #print(f"Error al publicar mensaje: {str(e)}")
    else:
        util.logging.info("El cliente MQTT no está conectado.")

 
    
def disconnect_from_aws_iot(mqtt_client):
    if mqtt_client:
        try:
            mqtt_client.disconnect()
            util.logging.info("Cliente MQTT desconectado con éxito.")
        except Exception as e:
            util.logging.error(f"Error: al desconectar el cliente MQTT: {str(e)}")
            #print(f"Error al desconectar el cliente MQTT: {str(e)}")
    else:
        print("El cliente MQTT no está conectado.")
    
# Función para manejar la conexión a AWS IoT
def connect_to_mqtt():
    return connect_to_aws_iot(
        os.getenv('CLIENT_ID'),
        os.getenv('ENDPOINT'),
        os.getenv('ROOT_CA'),
        os.getenv('PRIVATE_KEY'),
        os.getenv('CERTIFICATE'),
        int(os.getenv('PORT'))
    )

# Función para publicar mediciones en AWS IoT
def publish_mediciones(mqtt_client, mediciones):
    hilo_medidor = threading.Thread(target=Temp.parpadear_led_500ms)
    hilo_medidor.start()
    try:
        # Configurar el callback para la publicación
        mqtt_client.on_publish = on_publish
        publish_to_topic(mqtt_client, os.getenv('TOPIC'), mediciones)
        hilo_medidor.join()
    except Exception as e:
        # En caso de error, loguear el error y almacenar el mensaje en la cola
        util.logging.error(f"Error al publicar mensaje: {str(e)}")
        fileventqueue.agregar_evento(mediciones)  # Guardar el mensaje en la cola para reintento
def iniciar_recepcion_mensajes():
    client_id = os.getenv("CLIENT_ID") + str(random.randrange(255)) #+ str(random.randrange(255))
    endpoint = os.getenv("ENDPOINT")
    root_ca = os.getenv("ROOT_CA")
    private_key = os.getenv("PRIVATE_KEY")
    certificate = os.getenv("CERTIFICATE")
    topic = os.getenv("TUTOPIC")

    mqtt_client = AWSIoTMQTTClient(client_id + str(random.randint(0, 100)))
    mqtt_client.configureEndpoint(endpoint, 8883)
    mqtt_client.configureCredentials(root_ca, private_key, certificate)
    mqtt_client.configureOfflinePublishQueueing(-1)
    mqtt_client.configureDrainingFrequency(2)
    mqtt_client.configureConnectDisconnectTimeout(10)
    mqtt_client.configureMQTTOperationTimeout(5)

    #mqtt_client.onMessage = on_message

    try:
        mqtt_client.connect()
        util.logging.info("[MQTT] Conectado y escuchando en segundo plano.")
        mqtt_client.subscribe(topic, 1, on_message)
    except Exception as e:
        util.logging.error(f"[MQTT] Error al conectar o suscribirse: {e}")
        return