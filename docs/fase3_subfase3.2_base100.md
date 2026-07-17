# Fase 3 — Subfase 3.2: Índice Base 100

## Alcance

Se implementó el Índice Base 100 diario y consolidado como una transformación
pura del contrato aprobado de la subfase 3.1. El servicio Base 100 no consulta
la base de datos ni recalcula producción, energía, horas eléctricas, coberturas
o energía esperada.

No se implementó CUSUM, reentrenamiento, impacto económico o ambiental
definitivo, MTBF, MTTR, disponibilidad técnica ni alarmas.

## Fuente y cálculo

La única fuente es la salida completa de `build_daily_performance()`.

Una jornada entra al índice únicamente cuando:

```text
evaluationStatus = VALID_PRELIMINARY
knownEnergyKWh != null
expectedEnergyKWh != null
expectedEnergyKWh > 0
```

El cálculo diario es:

```text
base100Index = knownEnergyKWh / expectedEnergyKWh × 100
```

Las jornadas no evaluables conservan `base100Index = null`, se marcan con
`includedInPeriodIndex = false` y aparecen como huecos en la gráfica.

El índice del periodo usa razón de sumas:

```text
periodBase100Index =
sum(knownEnergyKWh de jornadas evaluables)
/
sum(expectedEnergyKWh de las mismas jornadas)
× 100
```

No se calcula como promedio simple de índices diarios. El contrato declara
`calculationMethod = RATIO_OF_SUMS`.

## Clasificación

Los límites se derivan de `model.cv_rmse_pct`, actualmente 3,64 %:

```text
Base 100 < 96,36      → FAVORABLE_PRELIMINARY
96,36 a 103,64        → NEUTRAL_WITHIN_MODEL_VARIABILITY
Base 100 > 103,64     → UNFAVORABLE_PRELIMINARY
```

Un valor inferior a 100 indica consumo inferior al esperado, pero no constituye
por sí solo ahorro demostrado ni una mejora energética sostenida verificada.

## Calidad y trazabilidad

Cada fila conserva las banderas originales de 3.1 y agrega, según corresponda:

```text
BASE100_VALID_PRELIMINARY
BASE100_INSUFFICIENT_DATA
BASE100_LOW_ENERGY_COVERAGE
BASE100_LOW_STATE_COVERAGE
BASE100_HIGH_RECONSTRUCTION
BASE100_INCONSISTENT_SIGNALS
```

`performanceQualityVersion` se copia desde `quality.thresholds.version`.
Los motivos de exclusión permanecen en `exclusionReasons`.

## Endpoint

```text
GET /api/linea-base/base-100?inicio=<epoch>&fin=<epoch>
```

Valida límites obligatorios, `fin > inicio` y un rango máximo local de 90 días.
La respuesta contiene:

```text
ranges
model
quality
daily
summary
methodology
```

El adaptador obtiene una vez el contrato 3.1 mediante
`build_daily_performance()` y lo pasa a `build_base100_contract()`.

## Control de mayo de 2026

Rango:

```text
[2026-05-01 06:00, 2026-06-01 06:00) America/Bogota
```

| Indicador | Resultado |
|---|---:|
| Jornadas solicitadas | 31 |
| Jornadas incluidas | 28 |
| Jornadas excluidas | 3 |
| Jornadas insuficientes | 0 |
| Energía conocida evaluable | 25.908,855474 kWh |
| Energía esperada evaluable | 25.238,984219 kWh |
| Índice Base 100 consolidado | 102,654113 |
| Clasificación | `NEUTRAL_WITHIN_MODEL_VARIABILITY` |
| Promedio simple diario, solo como control | 102,555209 |

La diferencia entre razón de sumas y promedio simple es aproximadamente
`0,098905` puntos. El valor publicado es exclusivamente la razón de sumas.

Las jornadas excluidas son:

```text
2026-05-08
2026-05-20
2026-05-21
```

Las tres conservan `LOW_STATE_COVERAGE`, reciben
`BASE100_LOW_STATE_COVERAGE`, tienen `base100Index = null` y quedan fuera tanto
del numerador como del denominador.

## Dashboard

La vista Base 100 muestra tarjetas del periodo, gráfica diaria con referencia
100 y límites 96,36/103,64, y una tabla con energías, índice, clasificación,
coberturas, reconstrucción, banderas y motivos de exclusión. La gráfica usa
`spanGaps: false` y conserva los valores nulos.

## Validación

Las pruebas unitarias verifican límites, nulos, exclusiones, banderas, versión,
pureza y razón de sumas. La integración abre SQLite con
`mode=ro&immutable=1` y valida mayo, `[inicio, fin)`, los totales y los tres días
excluidos.

La base histórica maestra no fue modificada y no se realizaron operaciones
sobre la Raspberry.
