# Evidencia automática CAN J1939 — ampliación aislada Prompt 04A

Fecha: 2026-11-14. SAMEE100-ALKOSTO, rama feature/samee100-j1939-can, HEAD inicial 761b61c. NO desplegada. EvidenceConfig.enabled=False por defecto. No se modificaron el receptor, can0, servicios, AWS, dashboard ni mediciones eléctricas.

## Auditoría y reutilización del Prompt 04

- EngineRecorder.offer_decoded/offer valida con EngineDetector y encola RecordingBatch; drain_once escribe mediante EngineStore. Se conserva ese flujo y se añade únicamente batch_observer opcional, no bloqueante, tras encolar el lote. Errores del observador se cuentan y no cambian la persistencia base.
- EngineStore mantiene las transacciones, idempotencia, sesiones y migración 001 existentes. No se reemplaza ni se modifica su archivo SQL. EvidenceStore hereda la conexión/transacción y agrega migrate_evidence/save_segment/session_closed.
- CanFrame.public_dict y parse_capture_record se reutilizan para escribir/recuperar el formato existente. No hay otro receptor ni otro decodificador de RPM. CaptureManager manual conserva funciones, API, archivos y límites; no se intenta hacerle compartir una única captura manual con varias sesiones automáticas.
- El servicio del repositorio es services/j1939_can_service.py; servies reportado para Raspberry sigue pendiente de verificación operativa. No se corrige ni se sobrescribe una unidad productiva.

## Flujo preparado

```text
Fuente CAN existente (sin modificar en esta fase)
  ├─ CanFrame → offer_frame (solo cola RAM) → worker de evidencia → deque / RAW / manifiestos
  └─ señales del decoder existente → EngineRecorder → lote SQL
                                    └─ batch_observer → misma cola de evidencia
SQLite 001 + extensión 002 → asociación durable lote-sesión → upsert eventual de metadatos
```

En la integración futura, ofrecer cada CanFrame antes de entregar sus señales decodificadas al registrador. Usar UNA decodificación ya existente, antes del filtro cambio/heartbeat. No volver a llamar al receptor ni duplicar la decodificación para conseguir las muestras. Las ofertas de frame y lote se serializan por cola; SQLite/archivos/hash/retención nunca se ejecutan en esos callbacks.

Constructor de ejemplo, deliberadamente apagado; rutas/identidades deben revisarse:

```python
store = EvidenceStore(r"D:\ensayos\registrador.sqlite")
config = EvidenceConfig(
    directory=Path(r"D:\evidencia_samee100"),
    selections=((0xF004, 0xEA),),  # RPM EA reportadas; otras parejas solo tras verificar origen
    gateway_id="ID_GATEWAY_PENDIENTE", equipment_id="ID_EQUIPO_PENDIENTE",
    engine_source_address=0xEA, enabled=False,
)
evidence = AutoEvidence(config, clock, store)
recorder = EngineRecorder(recorder_config, clock, store,
                          batch_observer=evidence.observe_batch)
```

No ejecutar start ni cambiar enabled en servicio durante esta fase. La migración administrativa explícita es store.migrate_evidence(create=True) solo en una DB de ensayo nueva o ruta aprobada; no migra automáticamente al importar, construir o iniciar workers. La herramienta offline del Prompt 04 conserva su migración 001; no se cambió para habilitar captura inadvertidamente.

## Búfer y disparo

- Deque por tiempo monotónico y cantidad; ventana previa solicitada 60 s por defecto, ampliada en RAM por max_confirmation_seconds (30 s por defecto) para cubrir retraso de confirmación. Máximo 10.000 frames por defecto. Un índice de duplicados tiene igual límite y la cola 2.048 posiciones, dos reservadas a controles. Secuencias de control se deduplican con memoria limitada a 64 escritores.
- El primer lote STARTING aporta la fecha de candidatura. Al confirmar START se vuelcan las tramas desde candidatura − pre_seconds, incluidas las RPM de transición previas al evento confirmado. No se afirma conocer la hora física exacta del arranque.
- La ventana efectiva puede ser menor por inicio reciente, límite de frames, cola llena o confirmación más larga que el margen. Se marca prebuffer_short/queue_drop/otros avisos e INCOMPLETE; nunca prometer 60 s si no se conservaron. Dimensionar cantidad/margen con cadencia y memoria reales antes de producción.
- Deduplicación de ofertas RAW por UTC/ID/payload dentro de una memoria limitada: valores iguales con timestamps distintos sí se conservan. No existe número de secuencia de bus; validar resolución del timestamp, ya que dos recepciones físicas indistinguibles podrían ser suprimidas. No equivale a conteo certificado del tráfico físico.

## Señales seleccionadas e identidad

No hay PGN/SA predeterminados: se exigen parejas explícitas, gateway/equipo y SA del motor. Los lotes de otro gateway/equipo/SA se rechazan. Las tramas de generación u otras ECU solo se añaden como parejas explícitas; nunca se presupone que todas pertenezcan al motor EA.

| Señal disponible | PGN / SPN declarado | Decodificación del repositorio | Uso de evidencia |
|---|---|---|---|
| RPM | F004 / 190 | Bytes4-5 LE, ×0.125 rpm; GOOD/rango según decoder | Reconstruir giro y transición, no producción eléctrica |
| Refrigerante | FEEE / 110 | Byte1 −40 °C | Contexto térmico, si PGN/SA seleccionado |
| Horómetro | FEE5 / 247 | Bytes1-4 LE ×0.05 h | Contexto de horas ECU; no duración de sesión inferida |
| Campo DC1 | FEF7 / sin SPN asignado | Bytes5-6 LE ×0.05 V | Contexto DC; NO etiquetar automáticamente como batería |
| DC2/frecuencia candidata | FEF7 / FE06, SPN no asignado | Definiciones deshabilitadas | No se incorporan como señales validadas; RAW FEF7 conserva bytes completos sin reinterpretarlos |

No se añadieron PGN/SPN para estados EMCP3, alarmas o variables AC no confirmadas. La captura selecciona tramas completas; no vuelve a escalar números ni descarta RAW por calidad del decoder. La configuración de ensayo de los tests usa cuatro PGN de SA EA y es sintética; solo RPM EA fue reportada como observada en el RAW por el responsable.

## Funcionamiento, STOP y comunicación

Desde START se escribe toda trama seleccionada aceptada. COMM_LOST/COMM_RECOVERED se anotan como comentarios de evento y no cierran la captura. Si el programa encuentra RUNNING sin START observado, abre segmento con unconfirmed_start, enlazable a la sesión incompleta del Prompt 04.

STOP confirmado fija el plazo monotónico post_seconds (60 s por defecto) ANTES de cualquier I/O: el disco lleno no puede perder ese plazo. La captura sigue durante la ventana y se cierra al vencer, aun sin nuevas tramas. Si falta recepción en la parte final, post_window_no_rx marca incompletitud. max_frame_gap_seconds (5 s por defecto) es un criterio de integridad de evidencia, configurable y pendiente de calibración, NO un comando ni detector físico de parada.

Cuando se reconfirma STOPPED sin observar transición tras una laguna, puede terminarse la ventana como captura incompleta (unobserved_stop_transition), sin fabricar evento STOP. Un nuevo START durante la cola posterior divide capturas/sesiones, conservando candidatura y prebuffer del nuevo ciclo; la cola truncada anterior queda INCOMPLETE. Puede haber solapamiento legítimo de prebuffer entre capturas distintas; no son duplicados de un mismo reintento.

## Formato y metadatos

RAW externo al repositorio:

```text
j1939_auto_<capture_uuid32>_<segment_uuid32>.txt.partial
j1939_auto_<capture_uuid32>_<segment_uuid32>.txt
j1939_auto_<segment_uuid32>.json
```

El RAW tiene comentarios de versión/metadatos iniciales, cabecera CSV y las siete columnas existentes:

```text
timestamp_utc,can_id,extended,dlc,data,pgn,source_address
```

UTC normalizado con zona, CAN ID de 29 bits en ocho hex, bytes RAW, PGN y origen. Los comentarios # EVENT incluyen ID estable del evento, tipo, UTC, RPM y SA; parse_capture_record/replay existentes ignoran comentarios. No hay RAW completo dentro de SQLite. El orden del archivo conserva recepción; los timestamps permiten análisis posterior, sin inventar ni reordenar datos silenciosamente.

Los .partial se abren exclusivamente, se vacían/sincronizan al cerrar y se renombran a .txt en cierre normal. SHA-256 se calcula leyendo en bloques de 64 KiB al finalizar; contadores/rango/PGN/SA/tamaño y motivo/integridad se guardan en un manifiesto JSON con archivo temporal + fsync + os.replace. El hash corresponde al RAW, no al manifiesto mutable. Los manifiestos se limitan a 64 KiB.

COMPLETE significa segmento íntegro dentro de selección/observación configuradas; NO certifica una sesión física completa. Sesiones siguen bajo las reglas del Prompt 04. INCOMPLETE preserva lo recuperable con motivos; OPEN, MISSING y DELETED reflejan estados de archivo. La integridad se hace conservadora tras descartes observados; no se ocultan límites como si hubiera continuidad garantizada.

## SQLite: migración 002

EvidenceStore.migrate_evidence aplica/verifica 001 y después 002 en transacción con checksum, sin alterar el SQL de 001 ni recrear tablas históricas.

- j1939_evidence_batch_sessions: referencia inmutable de lote confirmado a sesión, con FKs e índice por sesión.
- Trigger AFTER INSERT del ledger de lotes: recoge la sesión después de la actualización del checkpoint (o mediante STOP), DENTRO de la misma transacción original. Así una cola de metadatos retrasada no asocia archivos al ciclo equivocado consultando el último estado actual.
- j1939_evidence_segments: ID segmento/captura, lote ancla, sesión nullable, ruta única, UTC inicial/final, cantidad, PGN/SA, tamaño, integridad, causa, SHA256 y manifiesto; índice sesión/tiempo.
- save_segment usa upsert transaccional por segment_id. Si SQLite aún no confirmó el lote, la referencia queda pendiente; synchronize reintenta desde manifiestos sin reescribir RAW. No se asocia por aproximación de timestamp.

RAW y SQL no comparten una transacción física única. Los manifiestos son el mecanismo de recuperación eventual. Si un lote base se perdió antes de commit y su ancla nunca aparece, la evidencia puede permanecer sin sesión; se conserva como incompleta/pendiente en vez de inventar vinculación.

## Almacenamiento y retención

- Directorio dedicado obligatorio fuera del repositorio y distinto de la raíz del volumen. Se rechazan rutas internas; prefijos/UUIDs y resolución de rutas protegen operaciones individuales.
- Defaults: 50 MiB por RAW, segmentación de 3.600 s de recepción, mínimo libre100 MiB, cuota1 GiB y máximo200 RAW. Límites configurables, no dimensionamiento validado en Raspberry. Contabiliza RAW, manifiestos y temporales propios; reserva espacio para escrituras de manifiestos. Tamaño/tiempo rotan segmentos, NO borran antiguos.
- Disco lleno, cuota o cantidad agotada: se interrumpe evidencia escribible y se registran errores/avisos; el receptor/telemetría/SQL base no se detienen. Al volver espacio se puede continuar en otro segmento incompleto de la misma captura. No se reintenta ciegamente la fila RAW que pudo escribirse parcialmente.
- Conteos de una escritura incierta se recalculan leyendo las filas recuperables. Se conserva el .partial, su hash y motivos; reintentar metadatos no vuelve a añadir las tramas.
- Retención desactivada por defecto y nunca invocada por el worker. prune exige retention_enabled=True Y authorized=True, edad mínima, hash comprobado, atestación explícita de backup y sesión CERRADA/inactiva. Protege evidencia sin respaldo, incompleta, abierta o de sesión incierta. Mantiene manifiesto/registro DELETED como trazabilidad. acknowledge_backup es una atestación del operador, no prueba automática de que exista una copia remota.
- Antes de unlink se valida archivo individual propio, ruta absoluta dentro del directorio autorizado, extensión final y hash. No hay borrado recursivo ni borrado al alcanzar cuotas. Si cae el proceso entre autorización de borrado y actualización final, la recuperación diferencia la intención autorizada de una desaparición no explicada.

## Recuperación y límites

DirectoryLease usa lock del SO (Windows msvcrt/Linux flock), liberado al morir el proceso; prohíbe dos escritores en la misma carpeta. No se borra un lock suponiendo obsoleto un PID. Nunca ejecutar recuperación de un directorio que otro escritor tenga bloqueado.

Al inicializar el worker:

1. Recuperar OPEN/.partial; leer solo filas parseables, detectar truncamiento y calcular SHA256. Si el rename ocurrió antes del manifiesto final, localizar el .txt correspondiente y marcar cierre incierto.
2. Recuperar huérfanos sin inventar sesión; manifiestos corruptos se preservan, se reportan y no sobrescriben al recuperar su RAW.
3. Detectar RAW faltante; no reconstruir datos. La asociación original se reintenta por lote ancla.
4. Tras nuevas muestras RUNNING, los nuevos segmentos pueden enlazarse a la misma sesión persistida recuperada; quedan incompletos por reinicio. No generar STOP.

Memoria y recuperación limitadas: 128 parejas seleccionadas y listas de PGN/SA acotadas; como máximo max_files×4 manifiestos y max_files huérfanos durante recuperación. Superar límites requiere archivado/revisión explícita; no se borra automáticamente. synchronize en worker ocioso reintenta hasta ocho manifiestos cada5s de reloj; metadatos pueden estar pendientes sin detener RAW.

Los frames en cola y prebuffer son RAM volátil: un apagado puede perder lo no escrito. fsync/rename y WAL no sustituyen validación de alimentación/almacenamiento real. SQLite caído no bloquea ofertas, pero I/O/hash o velocidad insuficiente pueden llenar la cola y causar descartes visibles. No se garantiza cero pérdida ni captura física completa bajo fallos. close confirma terminación del worker/cola, no que una sesión tenga STOP ni que todo metadato esté ya asociado en SQL.

## Pruebas y revisión pendiente

Comandos: python -B -m unittest discover -s tests -v; node --test tests/test_j1939_dashboard.js. El archivo tests/test_j1939_auto_evidence.py prueba ventanas, límites, eventos, reinicios, archivo truncado, manifiesto corrupto, SHA, asociación tardía, fallo de disco, escrituras inciertas, retención y observador aislado con datos y rutas temporales. No son maniobras físicas ni análisis del RAW real reportado.

Plan de integración futura: revisar diff y evidencia; resolver .env rastreado antes de publicar; verificar unidad/ruta services frente a servies reportado; validar identidad/PGN/SA, cadencias, ventanas/capacidades y RAW real offline; backup SQLite consistente; migraciones001/002 explícitas en ruta aprobada; configurar directorio externo/permisos/espacio; conectar UNA oferta RAW y las señales ya decodificadas en el orden indicado; empezar apagado; aprobar activación y supervisar colas/errores/integridad/hash y asociación real sin TX ni provocar maniobras. No habilitar retención sin respaldo/aceptación separada. Rollback desconecta observador/captura conservando SQL, RAW y manifiestos; nunca DROP ni borrar históricos como mecanismo de vuelta atrás. No se ejecutó commit, push, pull, despliegue o modificación de servicios en Prompt 04A.
