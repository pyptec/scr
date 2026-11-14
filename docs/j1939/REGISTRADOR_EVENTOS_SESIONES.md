# Registrador J1939 aislado — eventos y sesiones (Prompt 04)

Fecha: 2026-11-14. SAMEE100-ALKOSTO. Rama feature/samee100-j1939-can, HEAD de partida 761b61c. Implementación local; NO desplegada. RecorderConfig.enabled=False por defecto; ningún servicio actual importa EngineRecorder.

## Auditoría del sistema existente

| Archivo / función | Responsabilidad / evidencia | Decisión |
|---|---|---|
| services/j1939_can_service.py:create_frame_source/main | Recibe con la fuente existente, reconecta a 2 s y llama runtime.process; lanza API interna | No modificar ni crear otro receptor |
| j1939/transport.py:SocketCanFrameSource.read_frame | Bus.recv, ID extendido y adquisición UTC; sin TX | Preservado |
| j1939/parser.py:decode_identifier, parse_slcan_line, parse_capture_record | PGN/SA y formatos existentes | Reutilizados para replay, sin otro decoder |
| j1939/decoder.py:SignalDecoder.decode/_decode_one | F004/SPN 190, bytes 4-5, 0.125 rpm/bit según YAML | Reutilizado por adaptador a través de DecodedSignal |
| j1939/state.py:SignalState.update | Últimos valores por key, cambio/heartbeat, memoria y contadores | No consumir solo publicaciones filtradas: se perderían muestras estables |
| j1939/service.py:J1939Runtime.process/make_handler | Decodificación y API local; cola RAW separada | No conectado al registrador en esta fase |
| api/app.py:_j1939_proxy | Proxy localhost, visualización existente | Sin cambios |
| db/samee100_db.py:get_conn/init_db/guardar_medicion | Compartido SAMEE100/SAMEE200; WAL, busy_timeout=30000, carga de catálogos; init_db ejecuta esquema y recrea vista | No reutilizar inicialización productiva para ensayos/migraciones del registrador; se reutilizan convenciones SQLite y UTC |
| db/schema.sql | gateways, dispositivos, unidades, mediciones, mediciones_detalle, aws_queue | No tiene tablas motor; se conserva intacto |
| j1939/capture.py:CaptureManager.offer/_writer | Cola acotada de RAW, descartes y archivos separados | No guardar cada RAW como evento SQL |
| j1939/engine_detector.py:EngineDetector | Núcleo probado e independiente | Reutilizado; solo se añaden last_valid_timestamp_utc y require_reconciliation |

En el repositorio existe **services**, no **servies**. deploy/samee100-j1939.service usa services y no contiene Requires=can0.service ni ExecStartPre=/bin/sleep 10. La unidad productiva reportada en Prompt 04 contiene esas opciones y la ruta servies: discrepancia documentada, no corregida automáticamente. Confirmar unidad/ruta efectivas antes de desplegar, sin reemplazar la unidad vigente a ciegas.

## Contrato y arquitectura

- EngineStore(path): ruta explícita, sin DB por defecto, sin conexión/migración al importar. migrate(create=False) es acción administrativa independiente; no se llama desde el adaptador.
- EngineRecorder(RecorderConfig(...), clock, store): desactivado por defecto, sin hilo hasta start(). offer_decoded recibe las señales del decoder ANTES de filtrar change/heartbeat; offer recibe RpmSample directamente; ambas sin SQL. No se abre otro receptor.
- Se conserva validación del detector: equipo/SA explícitos, F004/190, UTC, rango, calidad, repeticiones, desorden y plazos. last_valid_timestamp_utc permite detectar aceptación sin repetir su decodificación/validación.
- require_reconciliation invalida baseline/candidatos conservando temporizadores, timestamps e histórico confirmado. Se utiliza ante evidencia inválida nueva, hueco > max_sample_gap_seconds o desbordamiento. No reiniciar el timeout ante inválidos continuos.
- Cola acotada, por defecto 256 lotes más uno en escritura/reintento. Productor no toma el lock de SQLite. Escritor independiente con conexión por transacción, retry por defecto 0.25 s y estado de error expuesto. start inicia el worker; close intenta vaciar con límite de espera y devuelve False si quedan lotes o hilo pendiente. No esconder cierre incompleto.
- drain_once permite pruebas/replay deterministas; pertenece al escritor, no al hilo de adquisición. Errores retienen exactamente el mismo lote/ID/hash y no avanzan al siguiente. Programas de servicio futuros deben exponer status y alertar sobre errores persistentes/colas/descartes.
- Checkpoints estables agregados cada flush_seconds (5 s por defecto), más cambios de estado y eventos. No hay fila de evento por cada muestra RAW. Con ruido/cambios frecuentes puede aumentar la tasa de lotes; dimensionar en validación real.
- Un único escritor por gateway/equipo. begin_run reclama explícitamente una nueva identidad de proceso y excluye comandos nuevos del escritor anterior; no ejecutar dos registradores para el mismo equipo. No se implementó elección distribuida de líder.

La identidad se conserva como texto gateway/equipment para no asumir que una SA es el device_id entero del catálogo compartido. Validar asociación al generador antes de integrar; no crear dispositivos ficticios en las tablas existentes.

## Migración y tablas

Archivo: j1939/migrations/001_engine_recorder.sql; versión/checksum en j1939_schema_migrations. Migración aditiva, BEGIN IMMEDIATE/commit único para DDL+marca de versión. Reejecutar valida checksum y no repite cambios. Tablas J1939 preexistentes sin marca se rechazan para no absorber esquemas incompatibles. No se llama al init_db compartido, no se recrean vistas ni se borran históricos. WAL se configura solo en la preparación explícita, fuera de la transacción DDL; ese PRAGMA administrativo no se revierte si falla el DDL.

| Tabla | Contenido / integridad |
|---|---|
| j1939_engine_events | PK event_id, gateway/equipo, UTC, tipo START/STOP/COMM_LOST/COMM_RECOVERED/STATE_RECONCILED, estados, RPM, SA, PGN/SPN, motivo/calidad, evidencia opcional, adquisición y fecha de registro |
| j1939_engine_sessions | Inicio/fin confirmados nullable, observación conocida, active, estado ABIERTA/CERRADA/INDETERMINADA, RPM/horómetros inicial-final, duración/coverage/huecos, calidad, causa y notas; FKs y eventos START/STOP únicos |
| j1939_observation_gaps | Inicio conservador desde última observación durable, recuperación confirmada, duración nullable, causa y sesión; solo un hueco abierto por equipo |
| j1939_recorder_checkpoint | Último estado, histórico confirmado, última observación, sesión, escritor/secuencia y necesidad de reconciliar; PK gateway/equipo |
| j1939_recorder_batches | ID, identidad/secuencia y hash del lote confirmado; deduplicación transaccional |
| j1939_schema_migrations | Versión/checksum/UTC de aplicación |

Índices de eventos y sesiones por equipo/UTC; índice único parcial de una sesión activa; índice único parcial de un hueco abierto; índice de huecos por sesión. La actualización de huecos se limita a las sesiones afectadas, no recorre todas las sesiones en cada checkpoint. Restricciones de estados, no negativos, cronología y FKs. El ledger de lotes no tiene purga automática: planificar retención segura tras medir carga, sin invalidar idempotencia.

SQLite: URI mode=rw impide crear una DB por error tipográfico; create=True permite creación explícita y exclusiva de archivo, sin crear carpetas. foreign_keys=ON, synchronous=FULL y timeout corto configurable (50 ms por defecto) en el escritor. BEGIN IMMEDIATE; rollback ante cualquier excepción. PRAGMA integrity_check y foreign_key_check se verifican en ensayos. La durabilidad depende también del almacenamiento y la alimentación; no se ensayó corte eléctrico físico.

## Semántica de sesiones y recuperación

- START observado tras baseline STOPPED confirmado: evento y sesión ABIERTA atómicos.
- STOP observado: evento y fin confirmado atómicos. Si inicio y continuidad son conocidos, CERRADA y duration_seconds = UTC STOP − UTC START. Si el inicio es desconocido o hubo huecos, INDETERMINADA y duration_seconds=NULL; se conserva el fin si fue efectivamente observado.
- verified_seconds suma únicamente intervalos de dos muestras aceptadas consecutivas en RUNNING con hueco dentro del máximo. Usa min(delta monotónico, delta adquisición), excluyendo candidatos, inválidos y huecos. Es tiempo observado conservador, NO duración física exacta ni horas calculadas suponiendo continuidad.
- COMM_LOST: nunca STOP ni fin de sesión; mantener active=1, estado INDETERMINADA, quality=INCOMPLETE y hueco abierto.
- COMM_RECOVERED prueba regreso de RPM válidas; no cierra por sí solo la incertidumbre. Esperar reconfirmación estable.
- STATE_RECONCILED registra estado confirmado por nuevas muestras sin inferir transición física. Si reaparece RUNNING, conservar sesión previa como incompleta, sin START duplicado. Si reaparece STOPPED, desactivar la sesión incierta sin inventar ended_at_utc ni evento STOP en el hueco.
- Motor encontrado RUNNING al iniciar: sesión con inicio desconocido, sin START inventado. Una parada observada después puede tener ended_at_utc conocido y duración total desconocida.
- En reinicio, begin_run recupera checkpoint y abre hueco desde última observación durable; se conserva el último estado confirmado como histórico. El detector empieza reconfirmando, no restaura candidatos temporales. recovered_checkpoint contiene la situación previa. Sesiones abiertas nunca se cierran con la hora del reboot.
- time_without_communication es NULL mientras haya un hueco abierto; después suma intervalos de observación desconocida. Incluye reinicios, desbordamientos y evidencia inválida, no solo fallo físico de CAN. No equivale a medir exactamente tiempo de cable desconectado.
- Horómetros quedan NULL salvo hourmeter_validated=True explícito y señal engine_total_hours/FEE5/247/h, GOOD, del mismo SA y fresca. No se convierten en duración de sesión ni se suman al contador local.

## Idempotencia y límites de durabilidad

IDs del lote = UUID de proceso + secuencia; eventos/sesión derivan de ese ID. Todos los cambios más el ledger/checkpoint se confirman juntos. Un reintento del mismo lote verifica hash y no duplica START/STOP/cobertura. Reutilizar ID con otro payload, saltar secuencia o escribir desde propietario anterior se rechaza. Tras reinicio, solo se reconcilian estados nuevos; no se vuelve a emitir START por encontrar motor funcionando.

**La cola y la cobertura aún no confirmadas son volátiles.** Un apagado antes del commit puede perder observaciones pendientes. SQLite inaccesible indefinidamente o una cola llena no permiten garantizar retención ilimitada: se rechazan nuevas muestras, aumenta droppedSamples y se exige reconciliación al retomar, con sesión incompleta. El lote en reintento permanece en memoria hasta recuperación/cierre del proceso; no hay spool durable alternativo. Se protege la integridad de lo confirmado y se evita fabricar hechos durante la laguna; no se promete cero pérdida antes del commit. Si se requiere esa garantía, aprobar una fase de spool durable y dimensionamiento/almacenamiento antes de activar en producción.

Un error persistente de integridad/checksum/orden deja visible lastError y el lote retenido: requiere intervención, no se descarta ni se salta silenciosamente. Un reloj UTC regresivo puede impedir aceptar evidencia; no corregir fechas ni duraciones inventándolas.

## Evidencia real aportada el 14 de noviembre

Fuente: responsable del proyecto, texto íntegro del Prompt 04. Archivo conservado en Raspberry: /home/pi/capturas_j1939/arranque_20261114_131311.log; aproximadamente 11 MB, 220.059 líneas finales, 198.250 muestras RPM válidas reportadas, máximo RPM 0, PGN F004/SPN 190/SA EA; recepción continua reportada en el intervalo analizado, sin transición START/STOP observada. No se afirma haber medido aquí cadencia/jitter ni demostrado continuidad entre todas las muestras.

Refrigerante, voltaje DC reportado como batería y horómetro fueron contrastados con el panel frontal por el responsable y reportados coherentes. No se reinterpreta automáticamente dc_voltage_field_1 como batería ni se asigna SPN nuevo sin identificar contrato/bytes. No se validó una transición física de arranque/parada.

El RAW no está disponible en el workspace Windows examinado. No se accedió por SSH ni se copió a Git. Este trabajo documenta evidencia aportada, NO un análisis del RAW ejecutado por Codex. Replay real preparado y pendiente; ensayos ejecutados usan archivos temporales sintéticos.

## Replay local sin transmisión

Herramienta tools/j1939_recorder_offline.py: subcomandos migrate y replay. No importa transporte CAN, no carga .env ni contacta Raspberry. Lee streaming. CSV reutiliza parse_capture_record; candump acepta únicamente formato absoluto clásico candump -L: (epoch) can0 ID_EXTENDIDO#DATOS. Formatos relativos/humanos/FD o registros malformados fallan explícitamente; verificar primero formato real. Desorden temporal se cuenta y omite; timestamps idénticos los filtra el detector. El EOF no demuestra parada; no se extrapola tiempo futuro.

Ejemplo de ensayo local con rutas **de prueba**, después de revisar configuración y formato:

```powershell
python -B tools/j1939_recorder_offline.py migrate --database D:\ensayos\j1939_replay.sqlite --create
python -B tools/j1939_recorder_offline.py replay --input D:\capturas_protegidas\arranque_20261114_131311.log --format candump --database D:\ensayos\j1939_replay.sqlite --config config/j1939_recorder.example.json --enable-offline-recording
```

No se ejecutaron esos comandos contra la captura real. Preparar previamente directorios/rutas protegidas. El ejemplo JSON lleva identidades y umbrales SINTÉTICOS, enabled=false; la bandera habilita únicamente el proceso offline invocado, no el servicio. Reemplazar identidades/ajustes revisados y no tomar el fixture como calibración Caterpillar. La salida resume muestras/RPM/eventos, no copia RAW ni prueba procedencia real por sí sola. Repetir un replay como nueva ejecución es otra observación con posible historia duplicada: usar DB de ensayo separada por prueba; la idempotencia de lotes no equivale a deduplicar archivos reprocesados en procesos distintos.

## Preparación de despliegue (PROPUESTO, NO EJECUTADO)

1. Windows: verificar raíz/rama/HEAD/status y revisar diff de nombres y código. Conservar cambios visuales ajenos a esta fase. No usar git add indiscriminado.
2. Resolver .env rastreado antes de publicar: conservar copia local protegida, retirar solo del índice mediante git rm --cached -- .env cuando se autorice; mantener exclusiones y ejemplo sin secretos. No imprimir valores ni reescribir historial automáticamente. Evaluar revocación/rotación según exposición; borrar del último commit no borra historial.
3. Ejecutar python -B -m unittest discover -s tests -v y node --test tests/test_j1939_dashboard.js; revisar migración/schema y evidencias. Validar también con RAW real en DB de ensayo protegida, sin transmitir CAN.
4. Solo con aprobación: crear commit y push desde Windows, con archivos seleccionados y sin DB/RAW/secretos. Este trabajo no ejecuta commit/push.
5. En fase aprobada, Raspberry solo descarga código mediante git pull; no editar fuente productiva ni hacer push allí. Verificar unidad real con systemctl cat samee100-j1939.service y ruta services/servies antes de cambiar nada; no reemplazar automáticamente Requires/ExecStartPre ni configuración can0.
6. Revisar esquema real en modo lectura, identidad gateway/equipo, permisos/espacio y backups consistentes mediante API backup de SQLite (no copiar solo .db ignorando WAL). Preferir DB independiente del registrador en su primer ensayo; conservar mediciones históricas. Revisar el archivo SQL y checksums.
7. Aplicar migración explícitamente sobre la ruta aprobada, con copia consistente y ventana controlada. Nunca ejecutar el init_db compartido como atajo. El comando migrate no habilita registrador.
8. Mantener integración deshabilitada: hoy ni siquiera está conectada al servicio. Una fase siguiente debe incorporar oferta de señales antes del filtro, reloj y worker, supervisión de poll/status, cierre y manejo de errores, con activación explícita e identidad/umbrales revisados. No usar configuración sintética en servicio.
9. Observar can0, servicio CAN y medición sin transmitir ni provocar arranques/paradas; contrastar funcionamiento normal autorizado, consultar eventos/sesiones y referencias reales, integridad SQL y métricas de cola/errores. Probar reposo/arranque/parada y pérdida de observación en fase aprobada, con criterio independiente.
10. Rollback: deshabilitar únicamente el hook/registrador nuevo según la fase futura, conservar DB y registros para diagnóstico, regresar código mediante procedimiento Git revisado desde PC. No DROP TABLE, no DELETE histórico, no reset/force push ni cambios de CAN. No reemplazar la DB productiva con una de ensayo.

Pendiente: validar RAW aportado, cadencias/umbrales físicos y transiciones; evaluar corte eléctrico real, retención, carga/RAM/disco de Raspberry y cola; resolver secreto rastreado; aprobar integración controlada. No se modificó ningún servicio ni esquema productivo en Prompt 04.
