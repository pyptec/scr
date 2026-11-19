
# Prompt 06 — Preparación de activación automática J1939

Estado: procedimiento preparado en Windows; activación y autonomía en Raspberry NO comprobadas por Codex. No ejecutar este documento como un único script. Cada bloque [CAMBIO] exige revisión del operador; reinicios requieren autorización expresa para esa etapa. No arrancar/parar el grupo, no transmitir CAN, no reiniciar medidor/can0/dashboard, no editar código en Raspberry.

## 1. Diagnóstico y condiciones de paso

HEAD local inicial74797c5, rama feature/samee100-j1939-can, árbol limpio. El responsable reporta el mismo commit instalado en Raspberry, services/j1939_can_service.py, venv /home/pi/medidorsamee100, servicios activos, can0 ERROR-ACTIVE/250000bit/s, unos50GB libres, F004/SAEA, trama0CF004EA#FFFFFF0000FFFFFF y RPM0. Son evidencias reportadas, no consultas ejecutadas aquí. Queda resuelta documentalmente la discrepancia antigua services/servies; comprobar ExecStart efectivo igualmente.

El adaptador ya existe: config.py lee tres variables; integration.py valida DB dedicada y checksum, crea EngineRecorder y opcional AutoEvidence; runtime ofrece RAW del único lector y señales antes de publicar. Detector confirma por cantidad Y tiempo y rechaza RPM inválida/otraSA/vieja/futura/fuera de orden. El trabajador poll detecta silencio sin recepción; COMM_LOST no genera STOP. Store conserva sesiones y huecos, sin inventar arranque/parada tras reinicio. RAW recupera parciales como incompletos; retención automática no se llama. No se duplica ni cambia código productivo en este prompt.

**Requisitos obligatorios antes de habilitar A:** identificación revisada, umbrales aprobados como provisionales o calibrados sin declararlos calibrados falsamente, hora UTC correcta, SA234/RPM recientes, permisos pi, DB exclusiva con001/002 verificadas, configuración fuera del repo, servicio con código esperado y autorización de reinicio. **Antes de B:** A estable, tasa y límites dimensionados, RAW escribible/cuotas libres, reinicio autorizado. No afirmar grabación automática hasta verificar estado efectivo, DB y trabajador RAW.

## 2. Referencia del equipo y parámetros

Archivo `config/samee100_alkosto_j1939.reference.json`. Identificadores candidatos samee100-alkosto y samee100-alkosto-grupo-01, pendientes de confirmación del inventario; no son synthetic-* ni una afirmación de identidad física. `_activation_review` es información para el operador: el runtime la ignora y NO bloquea activación. No instalar sin revisarla.

| Parámetro | Referencia | Sustento / pendiente |
|---|---|---|
| RPM | F004/SPN190/SA234 | Confirmado por reporte del operador; recepción0rpm, sin transición física |
| Otras fuentes | No seleccionadas | FEEE/FEF7/FEE5: faltan pares PGN/SA en evidencia disponible |
| START/STOP/máximo | 600/100/3000rpm | Ejemplo pendiente de calibración, nunca atribuir ajuste Caterpillar validado |
| Confirmación | 3 muestras Y2s para ambos | Pendiente de frecuencia y prueba física; puede requerir más de3 muestras a alta tasa |
| Timeout / gap / edad | 5s /2s /1s | Provisionales; comprobar latencia UTC y frecuencia real |
| SQLite | /var/lib/samee100-j1939/engine.sqlite | DB nueva dedicada, nunca base de mediciones |
| RAW | /var/lib/samee100-j1939/raw | Externo; pre60/post60, margen confirmación30s |
| Búfer/cola RAW | 10000/2048 | Acotados, suficiencia NO demostrada sin tasa |
| Cola/eventos/flush/retry | 256 /5s /0.25s | Reintento en trabajador; busy SQLite50ms; RX no hace SQL |
| Rotación/cuota/reserva | 50MiB o1h /1GiB /100MiB | Iniciales; unos50GB reportados no equivalen a capacidad garantizada |
| Archivos / retención | 200 /false | Cuota se detiene con errores visibles; no elimina evidencia |
| Horómetro validado | false | No activar sin validación y contrato de SA; FEF7 conserva significado DC probable |

No asignar EA a las otras variables por proximidad ni por coherencia visual reportada. Adjuntar tabla de PGN/SA/UTC/valores decodificados de una captura existente. Tras confirmarlas, cambiar la referencia EN WINDOWS, revisar/publicar autorizado, recibir por pull; únicamente JSON operativo local se adapta como configuración. El prebuffer arranca vacío al reiniciar: no garantiza60s anteriores a un arranque inmediato.

## A. Inspección previa [SOLO LECTURA]

Ejecutar interactivamente en Bash en Raspberry, usuario con sudo. No usar set -x ni pegar salidas con credenciales. Los logs/unidades pueden contener datos privados: revisar localmente antes de compartir.

```bash
cd /home/pi/SAMEE100/scr
PY=/home/pi/medidorsamee100/bin/python
pwd
git branch --show-current
git rev-parse HEAD
git status --short
git ls-files -- .env app.log
systemctl is-active can0.service medidor.service samee100-dashboard.service samee100-j1939.service
systemctl is-enabled samee100-j1939.service
systemctl show samee100-j1939.service -p User -p Group -p ExecStart -p WorkingDirectory -p Restart -p RestartUSec -p EnvironmentFiles -p DropInPaths -p MainPID -p NRestarts -p ProtectSystem -p ReadWritePaths
systemctl cat samee100-j1939.service
ip -details -statistics link show can0
df -h /var/lib /home/pi
date -u --iso-8601=seconds
timedatectl show -p NTPSynchronized -p TimeUSec
"$PY" --version
"$PY" -B -c "import sqlite3,yaml,dotenv; print('dependencias disponibles; sqlite',sqlite3.sqlite_version)"
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8765/api/j1939/status
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8765/api/j1939/signals
```

Confirmar puerto efectivo si difiere8765, servicio User=pi y Python>=3.10 (slots/is_relative_to), no asumirlo solo por unidad versionada. `.env` y app.log modificados en Raspberry se conservan: no git restore/reset/clean, no subirlos. En este prompt no hace falta pull:74797c5 ya contiene adaptador. Para recibir esta documentación/config de referencia tras revisión, commit/push Windows únicamente autorizados y pull Raspberry revisado; si Git advierte conflicto con archivos locales, detener y resolver sin restauraciones destructivas.

## B. Rutas y permisos [SOLO LECTURA]

```bash
namei -l /var/lib/samee100-j1939/engine.sqlite
namei -l /var/lib/samee100-j1939/raw
namei -l /etc/samee100-j1939/engine.json
id pi
sudo -u pi test -x /home/pi/medidorsamee100/bin/python
```

Es normal que las rutas nuevas no existan todavía. Si ya existen, revisar propietario/modo y comprobar si contienen datos antes de cambiar nada. No seguir si son enlaces inesperados o si el sandbox systemd impide escribir. No corregir permisos ajenos con chown recursivo. No modificar unidad protectora sin revisión específica.

## C. Directorios nuevos [CAMBIO; solo si no existen]

```bash
sudo test ! -e /var/lib/samee100-j1939
sudo install -d -o pi -g pi -m 0750 /var/lib/samee100-j1939
sudo install -d -o pi -g pi -m 0750 /var/lib/samee100-j1939/raw
sudo test ! -e /etc/samee100-j1939
sudo install -d -o root -g pi -m 0750 /etc/samee100-j1939
sudo -u pi test -w /var/lib/samee100-j1939
sudo -u pi test -w /var/lib/samee100-j1939/raw
```

Cada `test ! -e` que falle es una orden de detenerse y revisar, no una invitación a continuar ni a borrar. Los bloques no usan encadenamiento automático; en ejecución interactiva detener ante CUALQUIER error. Si directorios ya preparados, solo pruebas read/write/access y ninguna recreación. Servicio/escritores del registrador deben seguir desactivados durante preparación. No aplicar migraciones mientras exista un escritor activo.

## D. Preparación SQLite explícita [CAMBIO acotado + verificaciones de lectura]

No ejecutar el antiguo comando de migrate sin revisar primero el destino: EngineStore.migrate por sí solo no prohíbe bases de mediciones. El siguiente bloque añade guardas administrativas, reutiliza EvidenceStore y SQL001/002 SIN duplicar sus migraciones. Exige nombre/ruta exclusiva, sin symlinks, directorio existente y escritura. DB con versión2 correcta solo se verifica (idempotencia, sin migrarla); DBv1 solo migra si no contiene datos operativos. DB ajena, vacía desconocida o esquema alterado se rechaza. Las migraciones no se aplican a bases productivas existentes. Una falla entre001/002 permite repetir si v1 sigue vacía y correcta; no borrar archivos para resolverla.

<!-- SQLITE_PREPARE_TESTABLE -->
```bash
sudo -u pi "$PY" -B - <<'PY'
from contextlib import closing
from pathlib import Path
import hashlib, os, re, sqlite3
from j1939.evidence_store import EvidenceStore
from j1939.integration import REPO_ROOT

MIGRATIONS = Path(REPO_ROOT) / 'j1939/migrations'
FILES = {1:'001_engine_recorder.sql', 2:'002_auto_evidence.sql'}
SQL = {v:(MIGRATIONS / n).read_text(encoding='utf-8') for v,n in FILES.items()}
EXPECTED = {v:hashlib.sha256(s.encode()).hexdigest() for v,s in SQL.items()}

def schema(c):
    return {(kind,name):(table,re.sub(r'\s+', ' ', ddl.strip().rstrip(';')))
            for kind,name,table,ddl in c.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' AND sql IS NOT NULL")}

def reference(version):
    with closing(sqlite3.connect(':memory:')) as c:
        c.execute('CREATE TABLE IF NOT EXISTS j1939_schema_migrations(version INTEGER PRIMARY KEY, checksum TEXT NOT NULL, applied_at_utc TEXT NOT NULL)')
        for v in range(1,version+1): c.executescript(SQL[v])
        return schema(c)

def check(p):
    with closing(sqlite3.connect(p.as_uri()+'?mode=ro', uri=True)) as c:
        c.execute('PRAGMA query_only=ON')
        versions = dict(c.execute('SELECT version,checksum FROM j1939_schema_migrations'))
        if versions not in ({1:EXPECTED[1]}, EXPECTED):
            raise RuntimeError('Version/checksum desconocido: detener')
        version = max(versions)
        if schema(c) != reference(version): raise RuntimeError('Esquema distinto del SQL auditado')
        if c.execute('PRAGMA quick_check').fetchall() != [('ok',)]: raise RuntimeError('quick_check fallo')
        if c.execute('PRAGMA foreign_key_check').fetchall(): raise RuntimeError('FK fallo')
        if version == 1:
            for table in ('j1939_engine_events','j1939_engine_sessions','j1939_observation_gaps',
                          'j1939_recorder_checkpoint','j1939_recorder_batches'):
                if c.execute('SELECT 1 FROM '+table+' LIMIT 1').fetchone():
                    raise RuntimeError('DBv1 con datos: no migrar en este procedimiento')
        return version

def prepare(path):
    p=Path(path)
    if (not p.is_absolute() or p.name != 'engine.sqlite' or p.parent.name != 'samee100-j1939'
            or not p.parent.is_dir() or p.resolve()!=p or p.resolve().is_relative_to(REPO_ROOT)
            or not os.access(p.parent,os.W_OK|os.X_OK)):
        raise RuntimeError('Ruta/directorio/permisos no aprobados')
    existing=p.exists()
    if existing and (not p.is_file() or not os.access(p,os.R_OK|os.W_OK)):
        raise RuntimeError('Archivo/permisos no aprobados')
    if existing and check(p)==2:
        print('SQLite v2 ya verificada: sin migracion'); return
    EvidenceStore(p).migrate_evidence(create=not existing)
    if check(p)!=2: raise RuntimeError('Preparacion incompleta')
    print('SQLite dedicada verificada, versiones001/002 y checksums correctos')

if __name__ == '__main__':
    prepare('/var/lib/samee100-j1939/engine.sqlite')
PY
```

Se ejecuta como pi para crear DB/WAL/SHM con su propietario. Usa lectura normal WAL, NO immutable sobre DB activa. No es backup ni elimina WAL. Primera preparación es una acción administrativa aprobada; verificar que la DB no está abierta por otro escritor. Guardar solo mensaje de éxito/checksums si se requiere evidencia, no contenido de mediciones.

## E. JSON revisado [CAMBIO de configuración; nunca código fuente]

Cuando este archivo de referencia llegue mediante Git pull autorizado y existan IDs/umbrales revisados:

```bash
sudo test ! -e /etc/samee100-j1939/engine.json
sudo install -o root -g pi -m 0640 config/samee100_alkosto_j1939.reference.json /etc/samee100-j1939/engine.json
sudoedit /etc/samee100-j1939/engine.json
```

Confirmar/reemplazar IDs con inventario; mantener engine_source234 implícito en detector.source_address, solo engine_speed234 en signal_sources mientras falte evidencia de las otras ECU. Documentar qué valores siguen provisionales y su aceptación operativa. Marcar revisión en `_activation_review` de manera veraz; esos campos no son un interlock del runtime. No modificar el JSON versionado directamente en Raspberry. Para editar configuración ya existente, respaldarla primero igual que en F; nunca reinstalar la referencia encima.

Validación de estructura y apertura DB de lectura SIN iniciar detector/trabajadores, CAN ni archivos RAW:

```bash
sudo -u pi "$PY" -B - <<'PY'
import json
from j1939.integration import build_integration
p='/etc/samee100-j1939/engine.json'
r=json.load(open(p,encoding='utf-8'))
assert r['gateway_id'] and not r['gateway_id'].startswith('synthetic-')
assert not r['detector']['equipment_id'].startswith('synthetic-')
assert r['detector']['source_address']==234
assert r['signal_sources']['engine_speed']==234
assert r['evidence']['pre_seconds']==r['evidence']['post_seconds']==60
assert r['evidence']['retention_enabled'] is False
assert r['_activation_review']['identifiers_confirmed'] is True, 'Confirmar inventario'
stage='A'  # Cambiar a B solo despues de validar A
assert stage in ('A','B')
if stage=='B':
    assert r['_activation_review']['field_rate_validated'] is True, 'Dimensionar tasa'
s=build_integration(dict(engine_events_enabled=True,auto_evidence_enabled=stage=='B',engine_config=p),start=False)
print('Configuracion valida; NO iniciada. Umbrales calibrados:',r['_activation_review']['thresholds_calibrated'])
PY
```

La revisión de umbrales puede aceptar un ensayo provisional documentado; no marcar calibrated=true sin evidencia. La validación estructural no demuestra permisos/escritura RAW ni recepción: comprobar B/I.

### Dimensionamiento RAW y confirmación PGN/SA [SOLO LECTURA, archivo existente]

El reporte actual no aporta duración/tasa de F004 ni PGN/SA de otras variables. No es posible certificar capacidad con un conteo sin intervalo UTC. Conservar inicialmente límites del ejemplo hasta medir; no afirmar que bastan. Usar un RAW YA EXISTENTE producido por el receptor o captura anterior, sin abrir otro lector. El siguiente análisis lee solo ese archivo, usando el parser offline existente; no toca SQLite, CAN ni .env. Reemplazar ruta/format(csv o candump clásico absoluto), no usar timestamps relativos.

<!-- RATE_AUDIT_TESTABLE -->
```bash
"$PY" -B - <<'PY'
from collections import Counter
from pathlib import Path
import json, math
from tools.j1939_recorder_offline import parse_replay_line

def analyze(path,format_name,selected):
    pairs=Counter(); bins=Counter(); lo=hi=previous=None; unordered=invalid=0; selected_count=0
    with Path(path).open(encoding='utf-8') as f:
        for line in f:
            try: frame=parse_replay_line(line,format_name)
            except ValueError: invalid+=1; continue
            if frame is None or frame.j1939 is None: continue
            pair=(frame.j1939.pgn,frame.j1939.source_address); pairs[pair]+=1
            t=frame.timestamp_utc.timestamp()
            unordered+=int(previous is not None and t<previous); previous=t
            if pair not in selected: continue
            selected_count+=1; lo=t if lo is None else min(lo,t); hi=t if hi is None else max(hi,t)
            bins[math.floor(t)]+=1
    # Toda ventana deslizante1s cabe en2 intervalos alineados adyacentes: cota conservadora.
    peak_bound=max((n+bins.get(k+1,0) for k,n in bins.items()),default=0)
    span=(hi-lo) if hi is not None else 0
    result=dict(pairs={f'{p:04X}/{s:02X}':n for (p,s),n in sorted(pairs.items())},
                selectedFrames=selected_count,spanSeconds=span,invalid=invalid,outOfOrder=unordered,
                averageHz=selected_count/span if span>0 else None,peakOneSecondUpperBound=peak_bound,
                recommendedBuffer90sWith50PercentMargin=math.ceil(peak_bound*90*1.5))
    return result

if __name__=='__main__':
    print(json.dumps(analyze('/home/pi/capturas_j1939/REEMPLAZAR.log','candump',{(0xF004,0xEA)}),indent=2))
PY
```

Revisar duración suficiente, representatividad en marcha/parado, intervalos/errores y pares reales; bytes crudos no bastan para confirmar semántica de señales. C debe cubrir la confirmación real por tiempo Y número de muestras; si esta supera30s, ajustar max_confirmation_seconds y recalcular antes de B. Margen1.5 es propuesta de ingeniería, no garantía de ráfagas ni tasa futura. Con R=peakOneSecondUpperBound, C=30s, P=60s, B>=ceil(1.5*R*(P+C)); B10000 admite R<=74.07tramas/s con este margen; a R100 se requieren13500; a R200,27000. Configurar cola Q>=ceil(1.5*R*Tstall)+2; ejemplo R200/Tstall5s requiere1502, menor2048. Tstall debe medirse en el disco real; cola no resuelve escritura sostenida más lenta que recepción.

Estimar bytes/trama con tamaño/número de líneas de RAW CSV ya cerrado (no usar tamaño candump como equivalente automático). Días aproximados de cuota=bytesDisponibles/(Rmedio*bytesCSVporTrama*86400), agregar manifiestos/rotaciones y actividad real; a100Hz y100bytes/trama,1GiB dura unas29.8h de grabación continua antes de sobrecarga. Rotación1h y max_files200 también limitan la duración aun si hay espacio. Medir RSS real con B configurado; búfer y dedup guardan referencias/objetos Python, no son B*8bytes. No aumentar sin revisar RAM. Si R o tiempos/volumen exceden límites, modificar JSON operativo revisado y referencia Windows para trazabilidad. Retenciónfalse puede llenar la cuota; preparar respaldo/supervisión, no borrar capturas para seguir.

## F. Respaldo de configuración local [CAMBIO, preserva .env/app.log]

No leer/imprimir .env en consola ni bitácora. Respaldo externo con directorio único y acceso root; si /var/backups/samee100-j1939 ya existe verificar que es directorio real root0700 antes de usarlo.

```bash
sudo install -d -o root -g root -m 0700 /var/backups/samee100-j1939
BACKUP_J1939=$(sudo mktemp -d /var/backups/samee100-j1939/preactivacion.XXXXXXXX)
sudo cp --preserve=mode,timestamps -- /home/pi/SAMEE100/scr/.env "$BACKUP_J1939/project.env"
sudo chown root:root "$BACKUP_J1939/project.env"
sudo chmod 0600 "$BACKUP_J1939/project.env"
sudo test -s "$BACKUP_J1939/project.env"
printf 'Respaldo privado: %s\n' "$BACKUP_J1939"
```

Respaldar también engine.json/recorder.env/drop-in existentes con cp hacia ese directorio, sin mostrar valores; hacerlo antes de C/E/G si ya hay configuración. app.log no se restaura ni publica; el servicio puede seguir escribiéndolo, no se modifica manualmente. La copia de .env no cambia su archivo original. No se necesita modificar .env para este procedimiento.

## G. Preparar activación externa [CAMBIO; inicialmente ambas false]

Se propone archivo externo con SOLO opciones del registrador, más un drop-in que añade EnvironmentFile después del actual. Conserva .env, ExecStart, dependencias y resto de entorno. systemd aplica archivos de entorno en orden; el último valor prevalece; revisar todos los drop-ins efectivos. load_project_env(override=False) del código conserva valores ya heredados. Referencias oficiales: [systemd.exec EnvironmentFile](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html#EnvironmentFile=), [systemd.unit drop-ins](https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html). Consultar también man local; no es una comprobación del systemd instalado.

Solo crear si esos nombres NO existen; si existen, respaldo y revisión previa. No resetear la lista EnvironmentFile ni reemplazar unidad completa.

```bash
sudo test ! -e /etc/samee100-j1939/recorder.env
sudo sh -c 'umask 077; set -C; cat > /etc/samee100-j1939/recorder.env' <<'EOF'
J1939_ENGINE_EVENTS_ENABLED=false
J1939_AUTO_EVIDENCE_ENABLED=false
J1939_ENGINE_CONFIG=/etc/samee100-j1939/engine.json
EOF
sudo install -d -o root -g root -m 0755 /etc/systemd/system/samee100-j1939.service.d
sudo test ! -e /etc/systemd/system/samee100-j1939.service.d/90-j1939-recorder.conf
sudo sh -c 'set -C; cat > /etc/systemd/system/samee100-j1939.service.d/90-j1939-recorder.conf' <<'EOF'
[Service]
EnvironmentFile=/etc/samee100-j1939/recorder.env
EOF
sudo chmod 0644 /etc/systemd/system/samee100-j1939.service.d/90-j1939-recorder.conf
sudo systemctl daemon-reload
systemctl show samee100-j1939.service -p EnvironmentFiles -p DropInPaths
```

Verificar que recorder.env queda último y no está anulado por UnsetEnvironment. daemon-reload relee definiciones, no valida adquisición ni reinicia el proceso. Si aparecen otros overrides, detener y revisar. No mostrar todo Environment= si contiene secretos.

Para cambiar etapa, respaldo F y `sudoedit /etc/samee100-j1939/recorder.env`; escribir exactamente uno de estos pares (mantener J1939_ENGINE_CONFIG):

| Etapa | ENGINE_EVENTS | AUTO_EVIDENCE |
|---|---|---|
| Desactivado / recuperación | false | false |
| A: SQLite | true | false |
| B: SQLite+RAW, después de A validada | true | true |

Contenido exacto para **Etapa A**, despues de respaldo y revision, usando `sudoedit /etc/samee100-j1939/recorder.env`:

```ini
J1939_ENGINE_EVENTS_ENABLED=true
J1939_AUTO_EVIDENCE_ENABLED=false
J1939_ENGINE_CONFIG=/etc/samee100-j1939/engine.json
```

Contenido exacto para **Etapa B**, solo despues de verificar A y con otro reinicio autorizado:

```ini
J1939_ENGINE_EVENTS_ENABLED=true
J1939_AUTO_EVIDENCE_ENABLED=true
J1939_ENGINE_CONFIG=/etc/samee100-j1939/engine.json
```

No hay recarga dinámica. Cambiar el archivo solo afecta al siguiente arranque del servicio. No hace falta daemon-reload al cambiar únicamente su contenido; sí al cambiar el drop-in. No usar export en SSH como activación persistente.

## H. Reinicio exclusivo [CAMBIO PRODUCTIVO, requiere autorización por etapa]

Después de revisar los gates y configurar la etapa correspondiente:

```bash
sudo systemctl restart samee100-j1939.service
systemctl is-active samee100-j1939.service medidor.service can0.service samee100-dashboard.service
systemctl show samee100-j1939.service -p MainPID -p NRestarts -p ActiveEnterTimestamp -p Restart
```

Es el único reinicio propuesto. Hay breve hueco de adquisición J1939 durante el reinicio; no se promete continuidad del proceso detenido. Primero comprobar desactivado si se quiere línea base; autorizar cada siguiente reinicio de A/B. NUNCA incluir restart medidor/can0 ni reboot aquí.

## I. Verificación A/B y sesiones [SOLO LECTURA]

API: repetir status/signals de A, sin iniciar otro J1939Runtime ni otra instancia del servicio. `engineIntegration.enabled=true`, initializationOrOfferError=null, recorder.enabled=true, batchesWritten crece, queued se vacía, writeErrors/droppedSamples/observerErrors no aumentan. A: evidence.enabled=false. B: evidence.enabled=true, buffered crece con RPM y luego se acota, queued estable, errores/drops cero o sin incrementos previamente justificados. activeCapture=null al estar parado es normal: RAW queda armado, no genera archivos de funcionamiento artificiales. Esperar90s de RX estable antes de declarar prebuffer preparado y ver que hay cobertura60s; buffered por sí solo no prueba continuidad UTC ni ventana temporal completa.

**La API actual NO expone directamente detector.state ni workerAlive.** engineIntegration.enabled solo prueba construcción. Consultar checkpoint durable reciente y contadores; no declarar salud solo por enabled. En reposo confirmado se espera STOPPED/reconciliación, no START/STOP nuevos. Primer RUNNING observado tras reinicio no fabrica START y sesión puede ser INDETERMINADA. Durante huecos conserva sesión con calidad incompleta. Fechas de eventos son de confirmación, no instante mecánico exacto.

```bash
sudo -u pi "$PY" -B - <<'PY'
from contextlib import closing
from pathlib import Path
import sqlite3
p=Path('/var/lib/samee100-j1939/engine.sqlite')
with closing(sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=1)) as c:
    c.execute('PRAGMA query_only=ON')
    queries={
      'migraciones':'SELECT version,checksum FROM j1939_schema_migrations ORDER BY version',
      'detector_checkpoint':'SELECT gateway_id,equipment_id,state,last_confirmed_state,last_observed_at_utc,sequence,session_id,needs_reconcile FROM j1939_recorder_checkpoint',
      'eventos':'SELECT timestamp_utc,event_type,rpm,source_address,reason FROM j1939_engine_events ORDER BY rowid DESC LIMIT 10',
      'sesiones':'SELECT session_id,status,active,started_at_utc,ended_at_utc,duration_seconds,verified_seconds,quality FROM j1939_engine_sessions ORDER BY rowid DESC LIMIT 5',
      'evidencia':'SELECT segment_id,session_id,frame_count,size_bytes,integrity,sha256,close_reason FROM j1939_evidence_segments ORDER BY rowid DESC LIMIT 10'}
    for label,q in queries.items(): print(label,c.execute(q).fetchall())
PY
find /var/lib/samee100-j1939/raw -maxdepth 1 -type f -name 'j1939_auto_*' -printf '%f %s bytes\n'
du -sh /var/lib/samee100-j1939/raw
df -h /var/lib/samee100-j1939
```

SQLite se abre por transaccion y se cierra: no exigir un descriptor permanentemente abierto. Campos de checkpoint recientes y secuencia creciente prueban actividad durable; no exponen RPM instantánea (consultar signals/engine_speed). Comparar UTC y SA de signals, no connected=true como prueba de frescura. En reposo, una DB vacía después de varios intervalos flush/confirmación pese a RPM válida es fallo a investigar.

Tras el próximo ciclo REAL que ocurra por operación normal de planta (no lo provocar aquí): comprobar START/STOP únicos, sesión con límites/duración compatibles, evidencia de pre60/durante/post60, SHA y asociación session_id. Para un archivo .txt cerrado con SHA no nulo: `sha256sum -- /var/lib/samee100-j1939/raw/NOMBRE_REAL.txt` y comparar con SQLite/manifiesto. No exigir SHA estable a .partial OPEN ni copiar una DB activa sin backupSQLite. Sesiones/archivos INCOMPLETE no se renombrarán COMPLETE para aprobar prueba. Puede haber prebuffer corto/solapamientos legítimos; verificar razón.

## J. Errores, CPU/RAM y autonomía [SOLO LECTURA]

```bash
journalctl -u samee100-j1939.service --since '-10 minutes' --no-pager -n 100
systemctl show samee100-j1939.service -p MainPID -p NRestarts -p MemoryCurrent -p CPUUsageNSec -p Restart -p UnitFileState
PID_J1939=$(systemctl show samee100-j1939.service -p MainPID --value)
ps -p "$PID_J1939" -o pid,etime,pcpu,rss,args
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8765/api/j1939/status
```

Comparar dos observaciones separadas y antes/después de A/B: framesReceived avanza, RPMUTC reciente, sin crecimientos de decodeErrorCount/errores/drops, backlog acotado y NRestarts estable. Contadores reinician con proceso; registrar PID/UTC junto con ellos. MemoryCurrent/CPUUsageNSec pueden no estar disponibles sin accounting; RSS de ps enKiB y %CPU observado no son máximos. No cambiar accounting/unidad como parte de esta preparación. Considerar tasa y carga eléctrica real, no solo simulado.

Confirmar `is-enabled`: si está disabled y se aprueba persistencia, [CAMBIO autorizado] `sudo systemctl enable samee100-j1939.service` (no --now, no reinicia). Si static/masked, detener y revisar dependencias, no unmask automáticamente. La unidad versionada tiene Restart=on-failure/5s, no garantiza reinicio de un hilo muerto mientras el proceso principal vive: observar contadores y checkpoints. Código no depende de SSH. Verificar desde una segunda conexión tras cerrar la primera: PID/contadores continúan. Sobrevivencia a reboot queda pendiente hasta un reinicio de sistema aprobado en otra ventana; NO ejecutar reboot aquí. Tras ese reinicio futuro comprobar bootID/servicios/checkpoint/sesiones/RAW: habrá hueco de observación y nunca debe inventar STOP. No afirmar autonomía validada solo por configuración enabled.

## K. Desactivación y recuperación [CAMBIO con reinicio autorizado]

Respaldar recorder.env como F, `sudoedit /etc/samee100-j1939/recorder.env` y fijar ambas opciones false; conservar ruta JSON. Con autorización ejecutar SOLO el reinicio de H. Comprobar status engineIntegration.enabled=false, recepción de RPM y medidor/can0/dashboard activos. Mantener drop-in y archivo externo en lugar de borrarlos: así false prevalece aunque .env antiguo contenga true. No deshabilitar el servicio receptor.

Conservar DB/WAL/SHM/RAW/parciales/logs; no restaurar DB vieja sobre activa ni borrar evidencia. Falta de permisos/cuota: diagnosticar y respaldar antes de corregir. Si shutdown dice pending_data o hay reinicios repetidos, marcar ventana incompleta, no inventar duración/STOP. Errores SQLite/RAW pueden no aparecer cada vez en journal: API/status y manifiestos son necesarios.

## Separación futura de secretos del repositorio (propuesta; NO ejecutada)

El drop-in anterior separa controles nuevos pero NO retira secretos de .env/historial. Antes de git rm --cached en Windows: inventariar consumidores de .env y app.log, respaldar configuración real de cada Raspberry fuera del repo, preparar archivo completo privado externo y mecanismo compatible para CADA servicio (J1939/medidor/dashboard/AWS) en cambio separado revisado. Probar que todos pueden funcionar sin .env rastreado; no alterar esos servicios aquí. Para J1939, load_project_env no sobreescribe entorno heredado, pero otros consumidores pueden exigir ruta .env: no asumirlos migrados.

Solo tras esa migración respaldada/revisada, autorizar commit Windows que desindexe .env; coordinar pull supervisado, porque la eliminación versionada puede borrar el archivo limpio o abortar con modificaciones locales. Tener copia externa verificable ANTES de pull; si un consumidor aún depende de la ruta antigua, detener migración y preparar compatibilidad/restitución desde backup antes de reiniciar, sin sobreescribir la copia privada. Git pull no es backup. No confiar en assume-unchanged/skip-worktree/ignore como protección. Rotación/historial de secretos requiere revisión aparte; no mostrar valores. No ejecutar git rm/reset/clean/restore ni modificar app.log en este prompt.

## Registro de ejecución del operador y criterios finales

Anotar por etapa: UTC, host/bootID, commit, PID, autorización, configuración revisada/IDs, versiones/checksums, espacio/permisos, estadoAPI/checkpoint y variación de contadores, archivo/evidenciaSHA cuando exista. Sin credenciales ni copia de .env. Antes de declarar **armado para el próximo arranque**: A validada, B efectiva, RPM/SQL recientes, prebuffer probado y errores/drops bajo control; una sesión real posterior valida START/STOP/evidencia completa. Este documento se entrega **PREPARADO, ACTIVACIÓN PENDIENTE**. Resultados locales en bitácora; ningún comando Raspberry fue ejecutado por Codex.

## Despliegue fase 07 — Historial de funcionamiento y evidencia J1939

### Alcance y puertas de autorización

Origen documentado en PC y reportado instalado en Raspberry: `bb14e3d8fb9c32e59f7cd1bd51fc1ec546bc38b9`. El diagnóstico real aportado por el operador informa servicios activos, CAN0 ERROR-ACTIVE a 250 kbit/s, recepción continua, cero TX durante la muestra y aumento de errores CAN. Este dato exige seguimiento; no demuestra que no haya problemas físicos. La copia de pruebas 07N registró 202 pruebas, 201 aprobadas y una omitida en Windows, con prueba POSIX anterior en Ubuntu. No equivale a aceptación física del nuevo código.

Los cambios revisados agregan control de confianza y frescura, persistencia de RPM máxima por sesión, migración aditiva 003, consultas de historial y de interrupciones vinculadas y contexto previo, verificación RAW bajo demanda, proxy Flask y panel histórico. El integrador emite instantáneas v2 y el historial contempla instantáneas v1/v2; se corrigió el cálculo de cobertura `verified_seconds`. La migración no reconstruye valores históricos ni recalcula tiempos verificados. No se cambian aquí SocketCAN ni CAN0, medición principal, watchdog, GPIO23, umbrales START/STOP, bases históricas, RAW originales, configuración local ni credenciales.

Las cuatro autorizaciones son independientes: (1) inventario y commit/push en PC; (2) ventana y respaldo; (3) actualización, migración y reinicios mínimos, solo tras verificar respaldo y reversión; (4) aceptación después de pruebas. Ningún bloque de escritura siguiente está autorizado por la existencia de esta guía. No detener medidor ni CAN0 sin motivo y autorización separados.

### Inventario para el commit de PC

Incluir: `api/app.py`; `j1939/engine_detector.py`, `engine_recorder.py`, `engine_store.py`, `integration.py`, `service.py`, `state.py`, `history.py` y `migrations/003_session_summary.sql`; `templates/dashboard.html`; `static/js/j1939_history.js`; `tests/test_j1939_dashboard.py`, `test_j1939_integration.py`, `test_j1939_recorder.py`, `test_j1939_abrupt_07i.py`, `test_j1939_context.py`, `test_j1939_history.py`, `test_j1939_history_dom.js`, `test_j1939_history_linux.py`, `test_j1939_migration_003.py`; esta guía y la bitácora central tras revisión de contenido. El cambio previo del usuario en esta guía se conserva. `tests/test_j1939_activation_procedure.py` es preexistente y queda fuera hasta decisión de su propietario. Los auxiliares de auditoría, navegador, compatibilidad y copia real quedan pendientes de revisión para publicación; las pruebas anteriores no dependen de ellos para su ejecución ordinaria.

Conservar fuera del commit las evidencias `docs/j1939/evidencias/prompt07/` hasta su revisión y sanitización, bases SQLite, RAW, logs operativos, credenciales y claves. `.env` y `app.log` ya están versionados: no se incluyen en la propuesta ni se modifica su contenido, pero excluirlos de nuevos cambios no elimina el historial anterior. Revisar la bitácora y los fixtures antes de publicarlos: pueden contener referencias operativas. No usar `git add`, commit ni push hasta la autorización 1 y la revisión final de cada diferencia.

### Diagnóstico y Git en Raspberry

Leer el estado sin mostrar contenidos de `.env` o logs. Confirmar rutas y usuario efectivo; mantener resultados operativos en un lugar privado:

```bash
cd /home/pi/SAMEE100/scr
git branch --show-current
git rev-parse HEAD
git status --short --branch
git diff --name-only
systemctl is-active can0.service medidor.service samee100-dashboard.service samee100-j1939.service
systemctl show samee100-j1939.service -p User -p ExecStart -p WorkingDirectory
ip -details -statistics link show dev can0
curl -fsS --max-time 5 http://127.0.0.1:8765/api/j1939/status
curl -fsS --max-time 5 http://127.0.0.1:8765/api/j1939/capture/status
df -h /var/lib/samee100-j1939
stat -c '%n %s %y' /var/lib/samee100-j1939/engine.sqlite
du -sh /var/lib/samee100-j1939/raw
```

Revisar `lastFrameAt`, el estado manual de captura y `engineIntegration.evidence.activeCapture`; verificar además colas, errores de escritura y fin de postcaptura. Identificar cualquier otro escritor con el operador. No abrir otro receptor CAN. Si hay captura activa, escritor desconocido, espacio insuficiente, cambios imprevistos o error de integridad, detener la intervención.

Tras autorización 3, actualizar primero la referencia remota con `git fetch origin feature/samee100-j1939-can` y comparar el hash recibido con el hash autorizado por PC. `fetch` cambia referencias Git y usa red; no es parte del diagnóstico de solo lectura. Sustituir `HASH_AUTORIZADO` por ese hash validado:

```bash
git rev-parse HEAD
git rev-parse origin/feature/samee100-j1939-can
git diff --name-status HEAD HASH_AUTORIZADO
git diff --name-only HEAD HASH_AUTORIZADO -- .env app.log
git merge-base --is-ancestor HEAD HASH_AUTORIZADO
```

Confirmar rama, que la referencia remota coincide exactamente con `HASH_AUTORIZADO`, que el último comando termina con éxito y que el diff no toca `.env` ni `app.log` ni otro archivo local modificado. Si no se cumplen estas condiciones o Git informa conflicto, detenerse y acordar una estrategia específica; no ocultar cambios ni usar reset, clean, restore o stash automático. Tras aprobación del estado exacto, ejecutar `git pull --ff-only origin feature/samee100-j1939-can`, comprobar `git rev-parse HEAD` y `git status --short --branch`, y detenerse si el HEAD final no es el autorizado. Existe riesgo de que la referencia cambie entre comprobación y pull: volver a comprobarla inmediatamente antes y no continuar si cambia; una discrepancia posterior requiere detener la operación, no corregirla destructivamente.

### Respaldo coherente: solamente con autorización 2

Confirmar ventana, hora UTC, ausencia de capturas manuales y automáticas activas o pendientes, cierre de RAW y escritores. Identificar y detener `samee100-j1939.service` solamente con autorización de la ventana; comprobar que no quedan otros escritores ni trabajos de cierre. No detener medidor ni CAN0. Asegurar permisos del usuario, destino privado y espacio suficiente para SQLite, RAW, configuración y margen; seleccionar un directorio de respaldo fuera del repositorio, distinto del respaldo histórico.

El siguiente ejemplo crea un directorio nuevo con permisos privados; requiere que `/var/backups` permita escribir al operador autorizado. Copia SQLite mediante Backup API, verifica su integridad y genera el hash. Antes de ejecutarlo verificar las rutas efectivas y que no existen capturas en curso:

```bash
umask 077
BACKUP_07=$(mktemp -d /var/backups/samee100-fase07-XXXXXXXX) || exit 1
export BACKUP_07
date -u +%FT%TZ
/home/pi/medidorsamee100/bin/python -B - <<'PY' || exit 1
import os, sqlite3
from pathlib import Path
src = 'file:/var/lib/samee100-j1939/engine.sqlite?mode=ro'
dst = Path(os.environ['BACKUP_07']) / 'engine.sqlite'
with sqlite3.connect(src, uri=True) as source, sqlite3.connect(dst) as target:
    source.backup(target)
    result = target.execute('PRAGMA quick_check').fetchall()
    if result != [('ok',)]:
        raise SystemExit('Fallo quick_check de respaldo: ' + repr(result))
    for table in ('j1939_engine_sessions', 'j1939_engine_events',
                  'j1939_observation_gaps', 'j1939_evidence_segments'):
        print(table, target.execute('SELECT count(*) FROM ' + table).fetchone()[0])
    print('migraciones', target.execute('SELECT version FROM j1939_schema_migrations ORDER BY version').fetchall())
PY
sha256sum "$BACKUP_07/engine.sqlite" || exit 1
cp -a -- /var/lib/samee100-j1939/raw "$BACKUP_07/raw" || exit 1
cp -p -- /home/pi/SAMEE100/scr/.env "$BACKUP_07/project.env" || exit 1
find "$BACKUP_07/raw" -type f -printf '%P %s %TY-%Tm-%TdT%TH:%TM:%TS\n'
du -sh "$BACKUP_07"
```

Comprobar manualmente el código de salida de cada comando y detenerse ante error; no interpretar un respaldo parcial como válido. Copiar también, tras identificarla, cualquier configuración externa necesaria con permisos privados, sin imprimir secretos. Conservar el listado y hashes de RAW cerrados fuera del repositorio y verificar que todos los segmentos y metadatos registrados en la copia tengan su archivo correspondiente o una explicación de ausencia/incompletitud. Registrar hora, ubicación, hash y conteos en registro privado. La copia SQLite incluye WAL mediante Backup API; no copiar solamente el archivo activo ni usar `immutable=1`. Los conteos por sí solos no identifican actualizaciones: conservar identificadores, marcas de tiempo y un nuevo snapshot para comparar cambios posteriores antes de una reversión. Mantener intacto y separado el respaldo histórico.

### Migración 003: solamente con autorización 3

Con backup verificado y escritores excluidos, comprobar que existen 001 y, para evidencia automática, 002, sus checksums y tablas. El estado anterior no tiene `j1939_session_summary`; 003 añade esa tabla y la versión 3. Si ya existe versión 3, comparar checksum con el archivo de migración y confirmar la tabla; una discrepancia es bloqueo, no ejecutar una reparación. El método valida checksum, es idempotente si coincide, no crea la base faltante y llama primero a `migrate()`, que también comprueba 001 y configura WAL. La transacción de 003 revierte ante error, pero la preparación de 001/WAL es una acción previa separada.

```bash
cd /home/pi/SAMEE100/scr
/home/pi/medidorsamee100/bin/python -B -c "from j1939.evidence_store import EvidenceStore; EvidenceStore('/var/lib/samee100-j1939/engine.sqlite').migrate_summary()"
```

Antes y después, consultar con conexión `file:/var/lib/samee100-j1939/engine.sqlite?mode=ro` la tabla `j1939_schema_migrations`, `sqlite_master`, `PRAGMA quick_check` y conteos de `j1939_engine_events`, `j1939_engine_sessions`, `j1939_observation_gaps` y `j1939_evidence_segments`. Comparar con el respaldo y revisar que los registros y RAW coincidan. Ante excepción, checksum incompatible o diferencia inexplicada, detenerse, conservar estado y evidencia; no restaurar ni reintentar automáticamente.

### Aceptación y reversión

Reanudar solo los servicios necesarios tras autorización 3; verificar que `can0`, medidor, dashboard y J1939 siguen activos, que hay recepción continua sin TX ni nuevas pérdidas relevantes y observar la evolución de errores CAN respecto de la muestra reportada. Comprobar errores críticos, integridad SQLite, versión 003, registros y segmentos. En una sesión nueva que ocurra naturalmente, verificar persistencia de RPM máxima; no provocar operación de planta.

Desde SQLite y dashboard comparar dinámicamente la sesión seleccionada con las referencias conservadas en evidencia privada: observación, START/STOP, estado, duración almacenada, RPM, interrupciones, integridad RAW y valores ausentes. Confirmar hora Colombia sin recalcular el histórico. Comprobar últimos valores, historial, detalle y paneles existentes; investigar diferencias antes de la autorización 4.

Si falla una condición crítica, detener el avance y, con autorización, preservar una nueva copia coherente y todos los RAW generados desde el primer respaldo, además de los cambios locales. Priorizar reversión supervisada de código al commit anterior, sin sobrescribir SQLite ni usar Git destructivo; revisar cómo conservar `.env` y `app.log` antes de elegir el mecanismo. La compatibilidad del código anterior con 003 se probó en copia aislada y debe confirmarse para la instalación efectiva: conserva el máximo existente pero no actualiza los nuevos resúmenes. Restaurar una copia anterior sobre la base reciente descartaría datos posteriores; solo contemplarlo tras análisis y reconciliación explícitos y autorización independiente.
