# Fase 4 — Subfase 4.3: alarmas en memoria

## Alcance

La subfase genera alarmas deterministas y de solo lectura desde los contratos
aprobados de las fases 2, 3 y 4. No existe base de alarmas, persistencia,
reconocimiento, resolución, supresión ni notificación externa.

Una alarma nunca confirma una falla. En particular, `IDLE`, `OFF`,
`SOLO_DETECTADA` y una sugerencia `CORRECTIVE_FAILURE` conservan su carácter
operacional o pendiente de revisión.

## Configuración

La versión `aoki-alert-rules-v1-2026-07` reside en
`device/aoki_alert_rules.json`. Reutiliza exclusivamente:

- CV(RMSE) y clasificaciones de desempeño de 3.1;
- Base 100 de 3.2 como evidencia correlacionada;
- coberturas versionadas de 3.1;
- `maximumGapMinutes` y persistencia de fase 2;
- eventos eléctricos y conciliación de fase 2;
- taxonomía, validaciones y evidencia de 4.1/4.1B;
- estado metodológico de 4.2.

No recalcula energía, línea base, Base 100, eventos, conciliación ni KPI.

## Reglas activas

```text
ENERGY_OVERCONSUMPTION
ENERGY_FAVORABLE_DEVIATION
LOW_ENERGY_COVERAGE
LOW_STATE_COVERAGE
NO_DATA_PROLONGED
ELECTRICAL_IDLE_EVENT
ELECTRICAL_OFF_EVENT
UNREPORTED_ELECTRICAL_EVENT
REPORTED_STOP_NOT_DETECTED
MAINTENANCE_REVIEW_REQUIRED
STALE_MAINTENANCE_EVIDENCE
RELIABILITY_KPI_UNAVAILABLE
```

Las reglas CUSUM, metas de confiabilidad y gateway permanecen explícitamente
deshabilitadas porque no existen límites calibrados o metas versionadas.

## Deduplicación y correlación

- Desviación y Base 100 forman un episodio energético por jornada.
- `SOLO_DETECTADA` se correlaciona dentro de la alarma del evento eléctrico.
- Conciliación y mantenimiento usan el `maintenanceEventId` estable.
- `NO_DATA` y baja cobertura comparten correlación diaria, pero conservan
  alarmas distintas porque aportan evidencia de granularidad diferente.

`alarmId` y `deduplicationKey` se derivan mediante SHA-256 del tipo, IDs fuente
canónicos, versión de regla y rango natural del evento. `detectedAtUtc` usa el
fin del rango natural y no el reloj del servidor, garantizando determinismo.

## Endpoints

```text
GET /api/alarmas?inicio=<unix>&fin=<unix>
GET /api/alarmas/{alarmId}?inicio=<unix>&fin=<unix>
GET /api/alarmas/reglas
```

El listado admite filtros `tipo`, `severidad`, `estado` y `modulo`. Los rangos
son `[inicio, fin)`, `America/Bogota`, con máximo local de 90 días.

No existen endpoints POST.

## Control de mayo

Para `[2026-05-01 06:00, 2026-06-01 06:00)`:

| Regla | Coincidencias |
|---|---:|
| `ENERGY_OVERCONSUMPTION` | 9 |
| `ENERGY_FAVORABLE_DEVIATION` | 2 |
| `LOW_ENERGY_COVERAGE` | 0 |
| `LOW_STATE_COVERAGE` | 3 |
| `NO_DATA_PROLONGED` | 4 |
| `ELECTRICAL_IDLE_EVENT` | 103 |
| `ELECTRICAL_OFF_EVENT` | 0 |
| `UNREPORTED_ELECTRICAL_EVENT` | 101 correlacionadas |
| `REPORTED_STOP_NOT_DETECTED` | 0 |
| `MAINTENANCE_REVIEW_REQUIRED` | 114 |
| `STALE_MAINTENANCE_EVIDENCE` | 0 |
| `RELIABILITY_KPI_UNAVAILABLE` | 1 |

El resultado es 236 alarmas emitidas después de deduplicación. Las 101
coincidencias `SOLO_DETECTADA` están trazadas dentro de los 103 eventos
eléctricos y no crean filas adicionales.

Las correlaciones reales son:

- 11 episodios energéticos con evidencia Base 100 del mismo día;
- 101 eventos eléctricos correlacionados con `SOLO_DETECTADA`;
- 114 revisiones de mantenimiento enlazadas a su conciliación;
- 3 segmentos `NO_DATA` correlacionados con los 3 días de baja cobertura.

No se crea `data/aoki_alerts.db`; las bases histórica y auxiliar solo se leen.
