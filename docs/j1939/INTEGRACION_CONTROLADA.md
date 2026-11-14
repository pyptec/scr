# Integración controlada SAMEE100-ALKOSTO — Prompt 05

Implementada solo en Windows; desactivada por defecto. No se ha intervenido Raspberry, CAN, GPIO, watchdog, medidor.service ni bases productivas. No hay validación física de START/STOP.

## A. Servicio y contrato auditado

El repositorio contiene `services/j1939_can_service.py`, no `servies/`. La unidad local apunta a services; el responsable reporta servies y dependencias can0/sleep no presentes en la unidad local. Comprobar ExecStart real antes de publicar: no sustituir la unidad productiva a ciegas.

El único origen de tramas sigue siendo create_frame_source (SocketCAN/serial/replay). SocketCAN solo recibe: timestamps UTC del mensaje cuando existen, recepción UTC como alternativa; serial usa UTC de recepción. El replay del servicio usa reloj real: para capturas históricas usar tools/j1939_recorder_offline.py con reloj de replay, no habilitar el registrador del servicio con fechas históricas.

J1939Runtime.process ofrece RAW después de registrar la trama y antes de decodificar. SignalDecoder se ejecuta una sola vez; las señales se ofrecen antes de SignalState.update y su filtro de cambios/heartbeat. RPM exige engine_speed, PGN F004/SPN190, unidad rpm, SA configurada, calidad GOOD, valor finito/en rango y UTC reciente/en orden. Se conservan los criterios temporales del detector. El trabajador del registrador llama poll incluso sin recepción y durante reconexión. COMM_LOST nunca equivale a STOP.

## B–D. Adaptador y configuración

`j1939/integration.py` conecta EngineRecorder y AutoEvidence existentes, sin otro lector, candump, red o transmisiones. `j1939/config.py` agrega:

```ini
J1939_ENGINE_EVENTS_ENABLED=false
J1939_AUTO_EVIDENCE_ENABLED=false
# Solo al preparar activación, ruta absoluta a archivo local revisado:
# J1939_ENGINE_CONFIG=/etc/samee100-j1939/engine.json
```

Ambos false: no se importa el adaptador desde runtime, no se lee su JSON, no se abren DB/RAW, no hay trabajadores ni migraciones. RAW true exige eventos true; combinación incorrecta desactiva el adaptador y deja adquirir CAN. Eventos true/RAW false permite solo SQLite.

`config/j1939_integration.example.json` tiene límites y umbrales SINTÉTICOS, no calibrados. Las opciones del entorno gobiernan activación; no se duplica enabled dentro del JSON. Revisar gateway/equipo, umbrales/histeresis/tiempos, rutas absolutas externas al repositorio y signal_sources por variable. EA es la dirección reportada para RPM; no universal. El ejemplo usa EA para otras señales SOLO como ejemplo: reemplazar o quitar las no confirmadas. Fuentes explícitas separadas impiden mezclar ECU en el registrador. SignalState histórico del dashboard continúa indexando por clave; no se cambia ese contrato.

## E. SQLite y señales disponibles

Se exige DB exclusiva para J1939, existente y migrada por un operador; se rechazan tablas ajenas a j1939_ (excepto sqlite_sequence), rutas relativas y rutas dentro del repo. Verificación de checksums 001 y, con RAW, 002 en apertura de solo lectura; nunca se ejecuta migración al arrancar. No se cambian schema.sql ni tablas de mediciones eléctricas. Las transacciones, lotes idempotentes, fencing de escritor, reconciliación tras reinicio y reintentos proceden del Prompt 04.

En eventos originados por muestras se conserva un snapshot JSON acotado en evidence_ref (`kind=j1939_signal_snapshot_v1`). Incluye PGN/SPN disponible, SA, UTC, unidad, calidad, confidence declarada y valor solo si GOOD/finito/reciente. La frescura usa max_sample_age_seconds del detector: conservadora, podría ocultar horómetro de baja frecuencia. Máximo cuatro señales con fuente explícita; muestras fuera de orden no sustituyen la última. Señales nunca recibidas se omiten; stale/invalid se marcan available=false/value=null. Los eventos temporales COMM_LOST no tienen un snapshot nuevo. Se asocian a la sesión mediante start_event_id/stop_event_id; no es una serie histórica continua ni se añaden nuevas tablas de telemetría. RAW seleccionado sí conserva todas las tramas que admite su cola durante las ventanas.

FEEE refrigerante; FEF7 dc_voltage_field_1 conserva significado probable, no se renombra batería; FEE5 horómetro; F004 RPM. Confidence del catálogo es declaración histórica, no validación física. La coherencia con panel fue reportada por planta. hourmeter_validated sigue false: las columnas de horómetro de sesión solo se usan tras validación explícita y actualmente requieren la misma SA del motor; un horómetro de otra ECU queda en snapshot/RAW, no se fuerza esa asociación.

## F–G. RAW, fallos y cierre

Se reutiliza AutoEvidence: pre60 desde primer candidato, durante funcionamiento y post60; cola2048, búfer10000, rotación50MiB/1h, cuota1GiB/200archivos, reserva100MiB, retención automática false. Todos configurables según disco y tasa real; 10000 tramas podrían no cubrir60s. Esa insuficiencia se marca INCOMPLETE, no se oculta. El directorio debe estar precreado y ser escribible, fuera del repo. Selecciones PGN/SA derivadas de signal_sources, sin asumir SA común.

Migración002 enlaza metadatos al lote/sesión real, incluso si SQLite llega tarde; manifiestos, SHA256, parciales, recuperación y cuotas se mantienen. Una falla de RAW no detiene SQLite/mediciones, y una falla SQLite no bloquea RX. Colas llenas cuentan pérdidas y obligan a reconciliar; RAM pendiente se pierde al terminar proceso. No se promete captura sin pérdidas. Escrituras RAW/SQLite no son una única transacción entre archivos y DB.

`GET /api/j1939/status` añade engineIntegration con estado de colas, errores y contadores; el dashboard y API existentes se conservan. Configuración inválida impide activar solo el adaptador y expone tipo de error, sin imprimir secretos. No reintenta cargar configuración: corregir y reiniciar servicio autorizado. Fallos de escritura reintentan en trabajadores. Shutdown cierra registrador antes de RAW, con espera acotada; pendientes o hilo activo se registran, no se fabrica STOP. Si no arranca API local se cierran también los trabajadores.

## H–I. Validación local

Ejecutar en Windows: `python -B -m unittest discover -s tests -v` y `node --test tests/test_j1939_dashboard.js`. Los casos nuevos conectan runtime real, decoder, recorder, DB y RAW temporales externos. Incluyen desactivación, START/STOP, duplicados, fuentes distintas, silencio/recovery, polling de trabajador sin RX, reinicio abierto, bloqueo SQLite/cola, falla RAW, rotación/asociación, desorden temporal, checksums y rechazo de DB de mediciones. La regresión previa cubre API/dashboard, captura manual, RX sin TX y módulos aislados. Benchmark sintético instrumentado de10000 ofertas, sin I/O en RX, mide CPU del proceso y pico de asignaciones Python: no es RSS ni consumo Raspberry ni prueba sostenida con disco. Resultados exactos en bitácora.

## J. Procedimiento operativo PROPUESTO; no ejecutado

### Prevalidación

1. En Windows revisar git status/diff, rama feature/samee100-j1939-can, archivos concretos y pruebas. `.env` sigue rastreado: ignorarlo no lo elimina del índice/historial. Antes de autorizar publicación revisar credenciales/historial y rotar si corresponde; proponer `git rm --cached -- .env` solo con revisión/autorización separada. No publicar ese archivo ni DB/RAW. Revisar listado staged antes de commit; no usar git add . a ciegas.
2. En Raspberry, después de autorización operativa: `systemctl cat samee100-j1939.service`, `systemctl status samee100-j1939.service medidor.service can0.service --no-pager`, `git status --short`, `git rev-parse HEAD`, `df -h`, `ip -details -statistics link show can0`. No cambiar bitrate/GPIO; no abrir un segundo lector. Revisar versión Python/dependencias y registros del servicio. No copiar secretos a la bitácora.
3. Respaldar configuración local fuera del repo, con permisos restrictivos y propietario del servicio, antes de pull: .env rastreado puede colisionar con cambios locales. Resolver mediante revisión, nunca reset/clean/stash ciego. Respaldar DB existente con SQLite backup coherente si corresponde, no copiar únicamente un .db activo en WAL.
4. Elegir DB NUEVA dedicada `/var/lib/samee100-j1939/engine.sqlite` y RAW `/var/lib/samee100-j1939/raw`, verificar espacio/propietario/permisos para usuario real de unidad (localmente pi), crear directorios con permisos mínimos. Configuración revisada en `/etc/samee100-j1939/engine.json`. No reutilizar samee100.db/samee200.db. Estimar retención/cuota con tasa real y prever respaldo externo.

### Despliegue posterior a autorización

1. Commit/push únicamente Windows con archivos revisados y sin sensibles. Registrar hash publicado. Raspberry solo pull del commit aprobado, con árbol limpio/revisado y configuración respaldada. No copiar cambios manuales de código a Raspberry.
2. Mantener ambas opciones false. Verificar configuración efectiva y ruta real services/servies; no reemplazar unidades ni dependencias como parte del pull.
3. Migración administrativa explícita, SOLO nueva DB dedicada, directorio ya creado y permisos revisados; comando propuesto desde raíz del código con Python del venv de la unidad:

```sh
/home/pi/medidorsamee100/bin/python -B -c "from j1939.evidence_store import EvidenceStore; EvidenceStore('/var/lib/samee100-j1939/engine.sqlite').migrate_evidence(create=True)"
```

create=True solo primera creación: si ya existe usar migrate_evidence() sin create; verificar checksums/versiones y tablas mediante conexión de solo lectura. No ejecutar sobre base de mediciones. 001/002 son las existentes; no hay rollback destructivo ni migración en recepción.
4. Prueba de laboratorio separada con copias temporales/config sintética y replay offline existente, sin SocketCAN ni generador y sin competir por el directorio/escritor productivo. Confirmar pruebas y ruta importada.
5. Solo con autorización para reiniciar samee100-j1939.service comprobar primero ambas false tras reinicio; API, RPM, captura manual y medidor siguen operativos. Comparar frames/errores/latencia/CPU/RSS/disco con línea base. No reiniciar medidor.service ni can0.service.
6. Tras calibración física supervisada y autorización posterior: configurar archivo revisado, eventos true y RAW true, reiniciar SOLO samee100-j1939.service. Verificar engineIntegration.enabled, lastError, colas/drops, cuotas, metadatos/sesión/RAW y horas UTC. No arrancar/parar generador desde software; pruebas físicas las coordina personal autorizado. Si no se puede comprobar ruta/SA/umbrales, no activar.

### Recuperación no destructiva

Si aparecen fallos sostenidos: conservar logs/manifiestos/DB/RAW; poner AMBAS opciones false en configuración local y reiniciar únicamente samee100-j1939.service con autorización. Así continúa receptor anterior y dashboard. No eliminar tablas, no revertir migraciones, no borrar WAL ni parciales, no restaurar una DB vieja sobre una activa. Las sesiones incompletas conservan su evidencia y se reconcilian en una activación posterior. Revisar volumen/cuotas/permisos y recuperar metadatos antes de reactivar. El reinicio interrumpe brevemente la adquisición: planificar ventana; no prometer continuidad durante parada del proceso.

## K–L. Evidencia y pendientes

Bitácora append-only: docs/bitacora/2026-11-14_samee100_j1939_arranque.md, entrada Prompt05 y prompt completo. Ningún commit/push/pull/reinicio/despliegue se ejecuta con esta implementación.

Pendientes físicos: resolver ruta real de unidad; confirmar SA por señal, timestamps/frecuencia, umbrales/counts/duraciones y horómetro; observar START/STOP reales con personal de planta; medir CPU/RSS/latencias y tasa/disco/cuotas en Raspberry; verificar recuperación tras corte, permisos y respaldos. El archivo reportado con RPM0 no prueba transiciones. `.env` rastreado es un pendiente previo a publicación, no se ha leído ni desindexado aquí.
