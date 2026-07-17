# Fase 4 — Subfase 4.2: MTBF, MTTR y disponibilidad técnica

## Condición previa

El servicio consume exclusivamente el contrato de eventos humanos de 4.1B y
`validatedAssetUptimeHours`. Solo calcula cuando el readiness es
`READY_FOR_RELIABILITY_KPI` y las verificaciones internas producen `VALID`.

Con cualquier otro estado, todos los KPI permanecen `null`.

## Metodología

Versión:

```text
aoki-reliability-method-v1-2026-07
```

Fórmulas:

```text
MTBF = validatedAssetUptimeHours / confirmedFailureCount
MTTR = validatedCorrectiveDowntimeHours / failuresWithValidatedDowntime
Disponibilidad por tiempo =
  uptime / (uptime + downtime correctivo) × 100
Disponibilidad MTBF/MTTR =
  MTBF / (MTBF + MTTR) × 100
Tasa auxiliar por 1.000 h = 1000 / MTBF
```

Una falla requiere `CORRECTIVE_FAILURE`, `HUMAN_VALIDATED`, evidencia `CURRENT`
e inicio validado. MTTR exige además reparación completa y downtime humano
positivo.

## Censura

- `LEFT_CENSORED`: no cuenta como falla iniciada en el periodo.
- `RIGHT_CENSORED`: cuenta para MTBF, pero no MTTR.
- `FULLY_OBSERVED`: puede entrar en ambos.
- `OUTSIDE_RANGE`: excluida.

El rango usa `[inicio, fin)`, `America/Bogota` y jornada 06:00–06:00.

## Endpoint

```text
GET /api/mantenimiento/confiabilidad?inicio=<unix>&fin=<unix>
```

El endpoint es estrictamente de lectura y no modifica validaciones.

## Control real de mayo

La base auxiliar comienza sin actores, validaciones ni ventanas:

```text
readinessStatus = NO_HUMAN_VALIDATIONS
status = NO_HUMAN_VALIDATIONS
confirmedFailureCount = 0
validatedAssetUptimeHours = null
validatedCorrectiveDowntimeHours = null
mtbfHours = null
mttrHours = null
technicalAvailabilityPct = null
technicalAvailabilityByTimePct = null
failureRatePer1000Hours = null
```

No se utilizan PRODUCTIVE eléctrico, 24 horas por día, duración eléctrica,
duración reportada ni sugerencias automáticas.
