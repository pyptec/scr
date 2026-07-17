# Fase 4 — Subfase 4.1B: validaciones humanas y uptime validado

## Alcance

La subfase incorpora una base SQLite auxiliar independiente, autenticación por
token individual, historial append-only, ventanas operativas humanas y preparación
de uptime. No modifica `samee200.db`, no usa `eventos_mantenimiento` y no calcula
MTBF, MTTR ni disponibilidad técnica.

## Seguridad

Los tokens se provisionan offline y solo se conserva su SHA-256. No se precargan
actores. Los roles son `MAINTENANCE_VALIDATOR` y `MAINTENANCE_ADMIN`.

Las escrituras requieren simultáneamente:

```text
MAINTENANCE_WRITES_ENABLED=true
debug=false
origen loopback o proxy TLS expresamente confiable
Authorization: Bearer <token individual>
Idempotency-Key: <identificador único>
```

El token se usa en memoria por el dashboard y no se almacena en Web Storage.

## Base auxiliar

Ruta:

```text
data/aoki_maintenance_validations.db
```

Tablas:

- `schema_metadata`;
- `validation_actors`;
- `maintenance_validation_current`;
- `maintenance_validation_history`;
- `validated_operating_windows`;
- `validated_operating_window_history`.

Los historiales tienen triggers que rechazan `UPDATE` y `DELETE`. Las tablas
current usan `version` incremental y `expectedVersion`. Una versión obsoleta
produce `409 VERSION_CONFLICT`.

## Evidencia

`aoki-maintenance-evidence-hash-v1` usa JSON canónico UTF-8, Unicode NFC, claves
ordenadas, IDs fuente ordenados y SHA-256. Una diferencia se expone como
`STALE_SOURCE_EVIDENCE` y requiere nueva revisión humana.

## Política de uptime

Versión:

```text
aoki-uptime-policy-v1-2026-07
```

El calendario proviene exclusivamente de ventanas `SCHEDULED_OPERATION`
validadas. Se restan mediante unión de intervalos:

- paradas planificadas, externas y periodos no operativos;
- downtime correctivo humano validado;
- `NO_DATA` y `UNKNOWN`, que permanecen no resueltos.

`PRODUCTIVE` eléctrico es solo evidencia. No se asumen 24 horas diarias.

La salida preparatoria contiene:

```text
validatedAssetUptimeHours
validatedCorrectiveDowntimeHours
excludedNoDataHours
unresolvedHours
```

Estados:

```text
NO_HUMAN_VALIDATIONS
INSUFFICIENT_OPERATING_WINDOWS
INSUFFICIENT_CORRECTIVE_TIMES
READY_FOR_RELIABILITY_KPI
```

## Endpoints

Lectura:

```text
GET /api/mantenimiento/eventos
GET /api/mantenimiento/eventos/{id}
GET /api/mantenimiento/eventos/{id}/historial
GET /api/mantenimiento/ventanas-operacion
GET /api/mantenimiento/ventanas-operacion/{id}/historial
GET /api/mantenimiento/uptime-validado
GET /api/mantenimiento/preparacion-kpi
```

Escritura:

```text
POST /api/mantenimiento/eventos/{id}/validacion
POST /api/mantenimiento/ventanas-operacion
POST /api/mantenimiento/ventanas-operacion/{id}
```

## Operación offline

Provisionar un actor:

```text
python -m db.provision_maintenance_actor <actor_id> "<nombre>" <rol>
```

El token se muestra una sola vez.

Crear respaldo consistente:

```text
python -m db.backup_maintenance_validations
```

Se usa SQLite Backup API y se crea manifiesto con tamaño, SHA-256 e
`integrity_check`.

## Limitación

`READY_FOR_RELIABILITY_KPI` solo declara suficiencia de datos. La subfase no
calcula ni muestra MTBF, MTTR o disponibilidad técnica.
