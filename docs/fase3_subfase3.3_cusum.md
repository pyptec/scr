# Fase 3 — Subfase 3.3: CUSUM diario y acumulado

## Alcance

Se implementó un CUSUM firmado, descriptivo y preliminar como transformación
pura de los contratos aprobados de las subfases 3.1 y 3.2.

El servicio no consulta SQLite, producción, energía, estados, coberturas o línea
base. Tampoco recalcula energía conocida, esperada, residuo o Base 100.

No se implementaron parámetros `k`, `h`, V-mask, límites estadísticos de
decisión, alarmas, reentrenamiento, impacto económico o ambiental definitivo,
MTBF, MTTR o disponibilidad técnica.

## Entradas y máscara

`build_cusum_contract(performance_contract, base100_contract)` usa:

- `residualKWh` directamente desde la subfase 3.1;
- `includedInPeriodIndex` directamente desde la subfase 3.2;
- `base100Index`, razones de exclusión y versiones desde la subfase 3.2.

La convención de signo se conserva:

```text
residualKWh < 0 → diferencia favorable preliminar
residualKWh > 0 → diferencia desfavorable preliminar
```

## Acumulados

Cada consulta comienza en cero:

```text
cusumKWh = 0
positiveCusumKWh = 0
negativeCusumKWh = 0
resetPolicy = RANGE_START_ZERO
```

Para jornadas evaluables:

```text
cusumKWh += residualKWh
positiveCusumKWh = max(0, positiveCusumKWh + residualKWh)
negativeCusumKWh = min(0, negativeCusumKWh + residualKWh)
```

Para jornadas excluidas:

```text
residualKWh = null
cusumContributionKWh = null
includedInCusum = false
```

El CUSUM y las dos series auxiliares conservan su valor anterior. Esta
continuidad no representa una contribución real igual a cero.

Las fechas se ordenan, los duplicados se rechazan y cualquier jornada ausente
del rango contractual aparece explícitamente como `MISSING_DAY`.

## Endpoint

```text
GET /api/linea-base/cusum?inicio=<epoch>&fin=<epoch>
```

El adaptador valida los límites y el máximo de 90 días. Obtiene una sola vez el
contrato 3.1, deriva Base 100 mediante la transformación 3.2 y entrega ambos a
CUSUM.

La respuesta contiene:

```text
ranges
model
quality
daily
summary
methodology
```

## Control de mayo de 2026

Rango:

```text
[2026-05-01 06:00, 2026-06-01 06:00) America/Bogota
```

| Indicador | Resultado |
|---|---:|
| Jornadas solicitadas | 31 |
| Jornadas evaluables | 28 |
| Jornadas excluidas | 3 |
| Jornadas faltantes | 0 |
| Residuo total evaluable | +669,871255 kWh |
| CUSUM final | +669,871255 kWh |
| Diferencias favorables acumuladas | 198,324447 kWh |
| Diferencias desfavorables acumuladas | 868,195702 kWh |
| CUSUM positivo final | 669,871255 kWh |
| CUSUM negativo final | 0,000000 kWh |
| Energía conocida evaluable | 25.908,855474 kWh |
| Energía esperada evaluable | 25.238,984219 kWh |
| Desviación consolidada publicada por 3.1 | +2,6541 % |
| Base 100 consolidado publicado por 3.2 | 102,654113 |

La desviación conserva la precisión del contrato 3.1 y no se recalcula dentro
de CUSUM.

Se verifica:

```text
868,195702 - 198,324447 = 669,871255 kWh
```

Las jornadas excluidas y su continuidad son:

| Jornada | Contribución | CUSUM |
|---|---:|---:|
| 2026-05-08 | `null` | 70,725818 kWh |
| 2026-05-20 | `null` | 302,083737 kWh |
| 2026-05-21 | `null` | 302,083737 kWh |

Las tres conservan `LOW_STATE_COVERAGE`.

## Dashboard

La vista CUSUM incluye tarjetas, tabla diaria y una gráfica con:

- residuo diario, manteniendo huecos;
- CUSUM firmado continuo;
- CUSUM positivo y negativo auxiliares;
- referencia cero;
- marcadores visibles para jornadas excluidas.

El CUSUM negativo no se presenta como ahorro confirmado y las series auxiliares
no se presentan como detector estadístico.

## Validación y limitaciones

Las pruebas cubren residuos positivos, negativos y cero; exclusiones; días
faltantes; continuidad; duplicados; orden; reinicio entre consultas; totales;
coherencia con Base 100 y ausencia de dependencias de base de datos.

La integración abre la base histórica mediante `mode=ro&immutable=1`. La base
maestra no fue modificada y no se realizaron operaciones sobre la Raspberry.

El resultado sigue dependiendo de la línea base histórica, de umbrales
provisionales de calidad y de horas derivadas de clasificación eléctrica. Es
descriptivo y no constituye una prueba estadística calibrada.
