
# SAMEE100 — Integración CAN J1939 para lectura de grupos electrógenos

## Contexto

Proyecto actual:

```text
SAMEE100
```

Rama actual:

```text
feature/samee100-sqlite-dashboard
```

Objetivo:

Agregar al SAMEE100 un subsistema CAN/J1939 independiente para leer variables de grupos electrógenos, reutilizando como referencia el código existente del proyecto de simulación J1939 desarrollado previamente para Raspberry Pi.

El subsistema CAN debe:

1. escuchar tramas CAN/J1939;
2. decodificar PGN/SPN/variables conocidas;
3. mantener las definiciones de señales en archivos YAML;
4. ejecutar como servicio independiente del resto de SAMEE100;
5. publicar los últimos valores decodificados;
6. detectar cambios;
7. publicar inmediatamente cuando una señal cambie;
8. si no cambia, volver a publicar como máximo cada 10 minutos;
9. exponer la información en el dashboard web de SAMEE100;
10. permitir pruebas iniciales mediante un convertidor CAN conectado por puerto serial/USB;
11. no romper adquisición Modbus, SQLite, dashboard ni servicios existentes.

---

# 1. Regla principal de seguridad

El CAN/J1939 debe ser un módulo separado.

No modificar la lógica Modbus existente salvo los puntos mínimos de integración.

No modificar estructuras SQLite existentes destructivamente.

No eliminar tablas, columnas ni datos.

No cambiar contratos actuales del dashboard sin compatibilidad hacia atrás.

Arquitectura preferida:

```text
                 ┌──────────────────────┐
CAN / Serial --->│ servicio J1939 CAN   │
                 └──────────┬───────────┘
                            │
                            v
                   estado/cola/API local
                            │
                            v
                 ┌──────────────────────┐
                 │ backend SAMEE100     │
                 │ Flask / API          │
                 └──────────┬───────────┘
                            │
                            v
                     Dashboard web

Modbus ----------> servicios SAMEE100 existentes
SQLite ----------> persistencia existente
```

El fallo del servicio CAN no debe detener:

```text
Modbus
SQLite
dashboard
MQTT
otros sensores
```

---

# 2. Auditoría obligatoria antes de implementar

Antes de modificar código:

Ruta obligatoria del código CAN/J1939 de referencia:

```text
D:\promate\raspberry\alkosto\03_Can\scr
```

Codex debe inspeccionar esa ruta completa y usarla como fuente técnica para identificar:
- PGN realmente usados;
- CAN IDs;
- source address;
- payloads;
- escalas;
- offsets;
- byte order;
- frecuencias;
- voltajes;
- batería;
- estados/shutdown;
- comandos ya identificados;
- protocolo del convertidor CAN/serial si existe allí.

No copiar el proyecto de referencia completo dentro de SAMEE100.
No copiar rutas absolutas, simuladores, bases de prueba ni dashboard del proyecto CAN.
Reutilizar únicamente lógica genérica, validada y aplicable a recepción real.


1. inspeccionar la estructura del repositorio SAMEE100;
2. identificar:
   - backend;
   - frontend;
   - servicios;
   - SQLite;
   - systemd existentes;
   - configuración;
   - logging;
   - tests;
3. inspeccionar el código existente del proyecto J1939 de referencia ubicado en `D:\\promate\\raspberry\\alkosto\\03_Can\\scr`;
4. reutilizar de ese proyecto únicamente:
   - parser de tramas;
   - extracción de CAN ID de 29 bits;
   - PGN;
   - source address;
   - decodificación ya validada;
   - fórmulas/escala/offset confirmados;
5. no copiar código obsoleto ni específico del simulador si no aplica a SAMEE100;
6. presentar un resumen del código de referencia encontrado.

La ruta de referencia ya está definida: `D:\\promate\\raspberry\\alkosto\\03_Can\\scr`. Si no es accesible, detenerse y reportar el error sin inventar información.

No inventar PGN, SPN, escalas ni direcciones.

---

# 3. CAN/J1939 conocido del proyecto anterior

Usar como punto de referencia únicamente lo ya confirmado en el proyecto anterior.

Características del bus:

```text
J1939
CAN 2.0B
29-bit extended ID
250 kbit/s
```

Señales previamente trabajadas/confirmadas incluyen, entre otras:

```text
frecuencia del generador
voltajes AC trifásicos
voltaje de batería
estado/shutdown
```

También existen comandos/PGN adicionales identificados en el código de referencia.

No asumir que esta lista es completa.

Codex debe extraer del proyecto de referencia la lista real y construir el YAML a partir de lo efectivamente validado.

---

# 4. Archivo YAML de señales

Crear una estructura versionada, por ejemplo:

```text
config/j1939_signals.yml
```

o la ubicación de configuración que ya use SAMEE100.

Cada señal debe soportar como mínimo:

```text
key
name
pgn
spn opcional
start_byte/start_bit o definición equivalente
bit_length
byte_order
signed
scale
offset
unit
min/max opcional
source
enabled
change_threshold opcional
change_threshold_pct opcional
invalid_raw_values opcional
enum opcional
description opcional
```

IMPORTANTE:

No inventar valores. Codex debe llenar el YAML únicamente con datos reales obtenidos del código J1939 de referencia.

---

# 5. Parser J1939

Crear un módulo independiente, adaptado a la estructura real del proyecto.

Debe soportar:

```text
29-bit CAN ID
priority
DP
PF
PS
source address
PDU1
PDU2
PGN
8-byte payload
```

No asumir que todos los PGN son PDU2.

El cálculo de PGN debe cumplir J1939.

Crear pruebas para:

```text
PDU1
PDU2
source address
priority
PGN
payload corto
payload inválido
ID no extendido
```

---

# 6. Capa de transporte CAN

Diseñar una interfaz abstracta:

```python
class CanFrameSource:
    def open(self): ...
    def read_frame(self): ...
    def close(self): ...
```

Implementaciones previstas:

```text
SerialCanFrameSource
SocketCanFrameSource
```

Para la primera prueba, priorizar:

```text
SerialCanFrameSource
```

porque el usuario probará con un convertidor CAN conectado por puerto serial/USB.

No inventar el protocolo serial del convertidor.

Primero auditar el código de referencia para determinar:

- formato de línea;
- baudrate;
- delimitadores;
- representación del CAN ID;
- DLC;
- bytes de datos;
- comandos de inicialización;
- si usa SLCAN, LAWICEL, formato ASCII propio u otro.

Si el formato no está definido, dejarlo configurable y documentar qué dato falta.

Ejemplo conceptual:

```yaml
transport:
  type: serial
  device: /dev/ttyUSB0
  baudrate: 115200
  protocol: slcan
```

No fijar `/dev/ttyUSB0` de manera irreversible.

Permitir override por `.env` o configuración.

---

# 7. Modelo interno

Definir contratos internos estables para:

```text
CanFrame
J1939Frame
DecodedSignal
```

Cada señal decodificada debe conservar:

```text
key
name
value
unit
pgn
sourceAddress
timestampUtc
quality
rawValue
```

---

# 8. Política de publicación por cambio y heartbeat

Cada señal debe mantener:

```text
lastValue
lastChangeTimestamp
lastPublishTimestamp
quality
```

Regla:

```text
si valor cambia
→ publicar inmediatamente
```

Si no cambia:

```text
si now - lastPublishTimestamp >= 10 minutos
→ volver a publicar
```

Configurar:

```yaml
publish:
  heartbeat_seconds: 600
```

No hardcodear 600 en múltiples archivos.

Para señales discretas:

```text
changed = new_value != previous_value
```

Para analógicas:

usar tolerancia configurable por señal.

No generar tormenta por ruido.

Registrar el motivo de publicación:

```text
initial
changed
heartbeat
quality_change
```

---

# 9. Estado actual en memoria

Crear un registro seguro para:

```text
latestSignals
```

Cada entrada:

```text
key
value
unit
timestamp
lastChangedAt
lastPublishedAt
pgn
sourceAddress
quality
publishReason
```

No usar variables globales no protegidas si existen threads.

---

# 10. Persistencia

Primera fase:

No crear una base histórica nueva sin necesidad.

Auditar primero si SAMEE100 ya tiene infraestructura genérica de telemetría.

Si existe y es adecuada, proponer integración no destructiva.

Si no existe, esta primera integración puede operar únicamente con:

```text
estado actual en memoria
logs
API
```

La persistencia histórica CAN queda para una subfase posterior salvo que exista infraestructura reutilizable.

---

# 11. Servicio independiente

Crear un entrypoint tipo:

```text
services/j1939_can_service.py
```

Debe:

1. cargar YAML;
2. abrir transporte;
3. leer tramas;
4. validar;
5. extraer PGN;
6. decodificar;
7. actualizar estado;
8. aplicar política cambio/10 min;
9. publicar hacia SAMEE100;
10. reconectar ante fallo.

No hacer busy loop.

Manejar:

```text
serial desconectado
reconexión
frame malformado
timeout
PGN desconocido
señal inválida
YAML inválido
```

sin tumbar el servicio por una única trama inválida.

---

# 12. Integración servicio CAN ↔ backend

Auditar qué mecanismo es más eficiente con la arquitectura existente.

Preferencias:

1. API localhost ligera;
2. infraestructura local existente;
3. Unix socket;
4. cola local existente.

No introducir:

```text
Redis
RabbitMQ
Kafka
Node.js runtime
```

Si se usa HTTP local:

```text
127.0.0.1
```

No exponer públicamente el puerto de ingestión.

---

# 13. API web

Agregar endpoints de lectura, por ejemplo:

```text
GET /api/j1939/status
GET /api/j1939/signals
GET /api/j1939/signals/{key}
GET /api/j1939/frames/recent
```

`frames/recent` debe usar buffer limitado configurable.

Respuesta de status debe incluir al menos:

```text
connected
transport
device
lastFrameAt
framesReceived
framesDecoded
unknownPgnCount
decodeErrorCount
serialReconnectCount
signalsChanged
heartbeatPublishes
```

---

# 14. Dashboard SAMEE100

Agregar sección:

```text
Grupo electrógeno / J1939
```

Mostrar:

```text
estado del bus
última trama
source address
PGN
frecuencia
voltajes
batería
shutdown/estado
otras señales definidas en YAML
```

Idealmente:

```text
YAML → metadata → API → tarjetas dinámicas
```

Mostrar por señal:

```text
nombre
valor
unidad
última actualización
calidad
```

Estados:

```text
GOOD
STALE
INVALID
NO_DATA
UNKNOWN_PGN
```

No confundir `NO_DATA` con cero.

---

# 15. Refresco del dashboard

No hacer polling excesivo.

Preferencia inicial:

```text
2–5 segundos
```

solo mientras la vista J1939 esté visible.

Si ya existe WebSocket, reutilizarlo.

El heartbeat de 10 minutos es de publicación de señal, no del refresco visual.

---

# 16. systemd

Preparar, pero no instalar automáticamente:

```text
samee100-j1939.service
```

Con:

```text
Restart=on-failure
RestartSec=5
```

Usuario no root cuando sea posible.

Variables mediante:

```text
EnvironmentFile=
```

El servicio CAN debe ser independiente del web y Modbus.

---

# 17. Configuración

Crear o extender:

```text
J1939_ENABLED
J1939_TRANSPORT
J1939_SERIAL_DEVICE
J1939_SERIAL_BAUDRATE
J1939_BITRATE
J1939_HEARTBEAT_SECONDS
J1939_RECENT_FRAME_LIMIT
J1939_LOG_RAW_FRAMES
```

Si:

```text
J1939_ENABLED=false
```

SAMEE100 debe comportarse exactamente como antes.

---

# 18. Logging y salud

Usar logging existente.

Eventos mínimos:

```text
service_started
transport_connected
transport_disconnected
transport_reconnect
unknown_pgn
decode_error
signal_changed
signal_heartbeat
service_stopped
```

No imprimir cada trama en producción por defecto.

---

# 19. Prueba con convertidor CAN serial

Crear herramienta:

```text
tools/j1939_serial_monitor.py
```

Debe permitir:

```bash
python tools/j1939_serial_monitor.py --port COMx
```

y:

```bash
python tools/j1939_serial_monitor.py --port /dev/ttyUSB0
```

Debe mostrar:

```text
timestamp
CAN ID
PGN
source address
payload
señales decodificadas
```

No modificar bases.

---

# 20. Modo replay

Agregar modo offline:

```text
--replay archivo.log
```

o fixture equivalente.

El mismo decoder debe funcionar con:

```text
CAN real
serial
replay
tests
```

sin duplicar lógica.

---

# 21. Rendimiento Raspberry Pi 4 de 2 GB

Diseñar para bajo consumo.

No introducir:

```text
React
Node.js runtime
Redis
Kafka
RabbitMQ
Docker obligatorio
```

Usar Python y stack actual.

Buffers acotados.

Sin busy loops.

No guardar todas las tramas en RAM.

Medir y reportar RAM/CPU al finalizar.

---

# 22. Pruebas obligatorias

Agregar pruebas para:

1. YAML válido;
2. YAML inválido;
3. PGN PDU1;
4. PGN PDU2;
5. source address;
6. señal 8-bit;
7. señal 16-bit;
8. endianess;
9. signed/unsigned;
10. escala;
11. offset;
12. valores inválidos;
13. PGN desconocido;
14. frame corto;
15. frame malformado;
16. cambio de señal;
17. señal sin cambio;
18. heartbeat a 600 s;
19. threshold analógico;
20. calidad;
21. desconexión serial;
22. reconexión;
23. buffer limitado;
24. J1939 deshabilitado;
25. SAMEE100 arranca con J1939 deshabilitado;
26. API status;
27. API signals;
28. dashboard sin datos;
29. dashboard con señales;
30. no regresión Modbus;
31. no regresión SQLite;
32. no regresión dashboard.

---

# 23. Entrega esperada

Primero presentar auditoría:

1. rama actual;
2. estructura SAMEE100;
3. código J1939 de referencia encontrado;
4. variables/PGN reales identificados;
5. formato real del convertidor CAN serial;
6. arquitectura propuesta;
7. archivos a crear/modificar;
8. riesgos.

Luego implementar únicamente si la información necesaria está disponible y no requiere inventar datos.

Al finalizar presentar:

1. rama de trabajo;
2. archivos creados;
3. archivos modificados;
4. YAML completo;
5. PGN/señales incorporadas;
6. transporte serial;
7. parser J1939;
8. política cambio/heartbeat;
9. API;
10. dashboard;
11. systemd;
12. herramienta serial;
13. replay;
14. pruebas ejecutadas;
15. resultados;
16. consumo RAM/CPU observado;
17. limitaciones;
18. instrucciones de prueba en Windows;
19. instrucciones de prueba en Raspberry;
20. comando de merge recomendado, sin ejecutarlo.

---

# 24. Restricciones finales

No:

```text
inventar PGN/SPN
inventar escalas
inventar formato serial
borrar datos
migrar destructivamente SQLite
romper Modbus
romper dashboard
trabajar sobre main/master
hacer merge automático
subir cambios a Raspberry sin autorización
```

La integración debe poder desactivarse completamente con:

```text
J1939_ENABLED=false
```

y SAMEE100 debe comportarse como antes.


## Control de no regresión obligatorio

Antes de tocar SAMEE100:

1. ejecutar la suite de pruebas existente;
2. registrar cuántas pruebas pasan;
3. guardar `git status`;
4. guardar `git diff --stat`;
5. identificar archivos sensibles:
   - adquisición Modbus;
   - acceso SQLite;
   - API actual;
   - dashboard actual;
   - servicios systemd;
   - MQTT;
6. no modificar estos módulos salvo integración mínima documentada.

Después de implementar:

1. repetir exactamente la suite existente;
2. ejecutar las nuevas pruebas J1939;
3. verificar que SAMEE100 arranca con `J1939_ENABLED=false`;
4. confirmar que Modbus sigue leyendo;
5. confirmar que SQLite no cambió de esquema destructivamente;
6. confirmar que el dashboard actual sigue funcionando;
7. presentar `git diff --stat`;
8. listar cada archivo existente modificado y justificarlo.

Si aparece una regresión, detenerse y corregirla antes de continuar.



# Extensión autorizada — Captura RAW CAN/J1939 para diagnóstico

Además de la integración J1939 definida en este prompt, se autoriza implementar un modo de captura manual para diagnóstico y decodificación posterior.

## Objetivo

Permitir que el usuario, desde el dashboard SAMEE100, pueda iniciar y detener una captura de tramas CAN/J1939 RAW sin afectar la operación normal.

La captura debe servir para analizar señales todavía no identificadas y correlacionarlas con eventos físicos observados en el grupo electrógeno.

## Comportamiento normal

Con captura desactivada:

```text
- no guardar todas las tramas en disco;
- mantener únicamente el buffer acotado definido para diagnóstico;
- decodificar señales;
- publicar cambios;
- publicar heartbeat cada 10 minutos;
- no generar crecimiento continuo de archivos.
```

## Comportamiento durante captura

Con captura activada:

```text
- seguir decodificando normalmente;
- seguir publicando cambios/heartbeat;
- además guardar las tramas RAW recibidas;
- no bloquear el hilo de adquisición;
- escribir mediante cola o mecanismo desacoplado;
- detener automáticamente si se alcanza límite de tiempo o tamaño.
```

## Controles del dashboard

Agregar en la sección:

```text
Grupo electrógeno / J1939
```

controles visibles:

```text
Iniciar captura CAN
Detener captura
Marcar evento
Descargar captura
```

Opcionalmente incluir selector de duración:

```text
5 min
10 min
30 min
60 min
```

y campo:

```text
Nota de captura
```

Ejemplos:

```text
Arranque del generador
Prueba de sobrevelocidad
Entrada de carga 50 %
Alarma de frecuencia
Prueba con interruptor cerrado
```

## Marcadores manuales

Mientras una captura esté activa, el botón:

```text
Marcar evento
```

debe insertar un marcador textual con timestamp UTC, por ejemplo:

```text
# MARKER 2026-08-28T19:12:15.123Z "Se activó alarma de sobrevelocidad"
```

No modificar ni reinterpretar las tramas alrededor del marcador.

## Formato de archivo

Preferir texto plano UTF-8, extensión:

```text
.txt
```

o:

```text
.log
```

Formato mínimo por trama:

```text
timestamp_utc,can_id,extended,dlc,data,pgn,source_address
```

Ejemplo:

```text
2026-08-28T19:10:01.231Z,0CF004EA,true,8,FF FF FF 40 38 FF FF FF,F004,EA
```

La información derivada:

```text
pgn
source_address
```

puede incluirse para facilitar análisis, pero el payload RAW debe conservarse exactamente.

No incluir una interpretación física no validada dentro del archivo RAW.

## Cabecera del archivo

Cada captura debe comenzar con comentarios:

```text
# SAMEE100 J1939 capture
# capture_version: samee100-j1939-capture-v1
# started_at_utc: ...
# stopped_at_utc: ...
# operator_note: ...
# transport: ...
# device: ...
# serial_baudrate: ...
# can_bitrate: 250000
# signal_config_version: ...
```

No incluir secretos ni tokens.

## Nombre de archivo

Usar nombre estable y seguro:

```text
j1939_capture_YYYYMMDD_HHMMSSZ.txt
```

Ejemplo:

```text
j1939_capture_20260828_191530Z.txt
```

No aceptar rutas arbitrarias desde el navegador.

## Carpeta

Crear una carpeta local específica, por ejemplo:

```text
data/j1939_captures/
```

o una ruta configurable equivalente.

No guardar capturas en:

```text
data/samee100.db
```

No modificar el esquema SQLite por esta función.

## Límites obligatorios

Evitar desgaste y llenado de la microSD.

Configurar:

```text
J1939_CAPTURE_MAX_DURATION_SECONDS
J1939_CAPTURE_MAX_FILE_MB
J1939_CAPTURE_MAX_FILES
```

Valores por defecto conservadores sugeridos:

```text
max_duration = 3600 s
max_file_mb = 50
max_files = 20
```

Los valores son configurables.

No eliminar archivos silenciosamente en la primera versión.

Si se alcanza el máximo de archivos:

```text
rechazar nueva captura
```

y mostrar:

```text
CAPTURE_STORAGE_LIMIT
```

hasta que el usuario elimine/gestione capturas manualmente.

## Escritura no bloqueante

La adquisición CAN no debe esperar escrituras lentas en disco.

Usar:

```text
cola acotada
+
writer thread/process independiente
```

Si la cola de captura se llena:

```text
CAPTURE_DROPPED_FRAMES
```

debe registrarse y contabilizarse.

No bloquear el receptor CAN.

## Estado de captura

Exponer:

```text
captureActive
captureStartedAt
captureFileName
captureElapsedSeconds
captureBytesWritten
capturedFrames
droppedCaptureFrames
captureNote
captureLimitReason
```

## Endpoints autorizados

Agregar:

```text
GET  /api/j1939/capture/status
GET  /api/j1939/captures
POST /api/j1939/capture/start
POST /api/j1939/capture/stop
POST /api/j1939/capture/marker
GET  /api/j1939/captures/{captureId}/download
```

No aceptar nombres de archivo o paths arbitrarios.

Usar `captureId` generado por backend.

## Seguridad

Antes de habilitar endpoints POST, auditar el mecanismo de escritura actual del SAMEE100.

Si no existe autenticación:

- permitir solo acceso local o red confiable;
- documentar claramente la limitación;
- no abrir un puerto adicional público;
- no reutilizar el endpoint para enviar tramas CAN.

Esta función es exclusivamente:

```text
captura pasiva
```

No debe transmitir ninguna trama CAN.

## No transmisión

Queda explícitamente prohibido implementar en esta fase:

```text
send frame
request PGN
address claim
control remoto
start/stop generador
write CAN
```

El servicio debe permanecer:

```text
listen-only / passive receive
```

cuando el hardware lo permita.

## Descarga

El botón:

```text
Descargar captura
```

debe entregar el archivo generado tal cual.

No convertirlo automáticamente a CSV ni modificarlo al descargar.

Una conversión posterior puede implementarse en herramientas offline.

## Análisis posterior

El archivo debe ser compatible con:

```text
tools/j1939_serial_monitor.py --replay ...
```

o una herramienta equivalente.

El mismo parser/decoder debe poder reproducir la captura offline sin duplicar lógica.

## Pruebas obligatorias de captura

Agregar pruebas para:

1. iniciar captura;
2. detener captura;
3. doble start rechazado;
4. stop sin captura activa;
5. creación de archivo;
6. cabecera;
7. formato RAW;
8. timestamp;
9. marker;
10. note;
11. duración máxima;
12. tamaño máximo;
13. máximo de archivos;
14. cola acotada;
15. dropped frames;
16. nombre seguro;
17. prevención path traversal;
18. download por captureId;
19. replay del archivo generado;
20. adquisición CAN no bloqueada;
21. no transmisión CAN;
22. J1939 deshabilitado;
23. no modificación SQLite;
24. no regresión Modbus;
25. no regresión dashboard.

## Entrega específica de captura

Al finalizar, además presentar:

```text
- carpeta de capturas;
- formato exacto del archivo;
- límites configurados;
- endpoints;
- controles del dashboard;
- comportamiento ante saturación;
- prueba de replay;
- confirmación de que no se transmite CAN;
- consumo adicional de RAM;
- impacto de escritura en disco.
```



# Instrucción vigente para continuar

Objetivo:

```text
Integrar CAN J1939 en SAMEE100 como servicio edge independiente, configurable por YAML, con publicación por cambio y heartbeat de 10 minutos, prueba por convertidor CAN serial y visualización web.
```

Antes de modificar, auditar el proyecto SAMEE100 y el código J1939 de referencia.
