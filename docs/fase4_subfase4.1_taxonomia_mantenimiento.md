# Fase 4 — Subfase 4.1: taxonomía de mantenimiento

## Alcance

La subfase transforma el contrato integrado de fase 2 en eventos de revisión de
mantenimiento. No consulta fuentes adicionales, no persiste validaciones humanas y
no modifica la base histórica. Las clasificaciones automáticas son sugerencias.

## Taxonomía

La versión `aoki-maintenance-taxonomy-v1-2026-07` está declarada en
`device/aoki_maintenance_taxonomy.json`. Cada evento comienza con:

```text
validatedClassification = null
validationStatus = PENDING_HUMAN_REVIEW
confirmedFailure = false
```

Una falla solo podrá confirmarse posteriormente cuando se cumplan simultáneamente:

```text
validatedClassification = CORRECTIVE_FAILURE
validationStatus = HUMAN_VALIDATED
```

## Reglas conservadoras

- `IDLE`, `OFF` y `SOLO_DETECTADA` sin texto quedan `UNDETERMINED`.
- `SIN_DATOS` se sugiere como `DATA_QUALITY_EVENT`.
- La palabra mantenimiento sin daño, avería o reparación queda `UNDETERMINED`.
- Daño, falla, avería, escape o reparación explícita permiten sugerir
  `CORRECTIVE_FAILURE`, pero no confirman una falla.
- Limpieza, lubricación, cambio, material y ajustes se mantienen separados.

El `maintenanceEventId` usa un hash de IDs reportados y eléctricos canónicos,
ordenados. La versión de taxonomía no participa en la identidad.

## API de solo lectura

```text
GET /api/mantenimiento/taxonomia
GET /api/mantenimiento/eventos?inicio=<unix>&fin=<unix>
GET /api/mantenimiento/eventos/{maintenanceEventId}?inicio=<unix>&fin=<unix>
```

Los rangos usan `America/Bogota`, jornada 06:00–06:00 y semántica
`[inicio, fin)`. No existe endpoint POST en esta subfase.

## Control de mayo

Para `[2026-05-01 06:00, 2026-06-01 06:00)`:

- 31 jornadas;
- 13 paradas reportadas;
- 103 eventos eléctricos completos;
- 101 `SOLO_DETECTADA`;
- 13 `PENDIENTE_REVISION`;
- 0 fallas confirmadas.

Sugerencias resultantes:

- 4 `CORRECTIVE_FAILURE`;
- 4 `PREVENTIVE_MAINTENANCE`;
- 1 `CLEANING`;
- 105 `UNDETERMINED`.

Los cuatro candidatos correctivos corresponden a falla del Booster, compresor sin
alcanzar presión y cambio de pieza, daño de empaques y escape de agua. Permanecen
pendientes de validación humana y no incrementan fallas confirmadas.

No se calcularon MTBF, MTTR, disponibilidad técnica ni tasa de fallas.
