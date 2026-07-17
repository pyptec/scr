# Fase 3 — Subfase 3.1: consolidación diaria de desempeño energético

## Alcance

Se implementó la consolidación por jornada productiva 06:00–06:00 en
`America/Bogota`, con semántica temporal `[inicio, fin)`. El resultado es
preliminar: no demuestra ahorro ni constituye una verificación ISO 50001
definitiva.

No se reentrenó ni modificó la línea base oficial. Tampoco se implementaron
Índice Base 100, CUSUM, impacto económico, CO₂, MTBF, MTTR, disponibilidad
técnica o alarmas.

## Modelo oficial y granularidad

La energía esperada se calcula por cada jornada que tenga entradas suficientes:

```text
expectedEnergyKWh_day =
514.50
+ 0.005018 × goodUnits
+ 16.5198 × productiveElectricalHours
```

El intercepto se aplica una vez por jornada evaluable. El total del periodo es:

```text
totalExpectedEnergyKWh = sum(expectedEnergyKWh_day evaluable)
```

No se calcula el periodo mediante una única aplicación del intercepto. Para 31
jornadas completas, el término fijo máximo sería `31 × 514,50 = 15.949,50 kWh`.
En el control de mayo entraron 28 jornadas al total evaluable, por lo que su
contribución fija fue `28 × 514,50 = 14.406,00 kWh`.

## Fuentes

- Producción: `produccion_periodo.envases_buenos`; `envases_malos` y producción
  total se conservan solo como trazabilidad.
- Horas: `daily[].productiveHours` de la clasificación eléctrica de `ME337_1`,
  publicadas como `productiveElectricalHours` con origen
  `ELECTRICAL_CLASSIFICATION_PRELIMINARY`.
- Energía medida: intervalos `ACCUMULATOR_DELTA`.
- Energía reconstruida permitida: `POWER_TRAPEZOIDAL` y
  `POWER_RECTANGULAR`.
- `CURRENT_MODEL` se rechaza en esta consolidación.

`knownEnergyKWh` es la suma de energía medida y reconstruida permitida. Cuando
existen intervalos sin fuente recuperable, `unrecoverableEnergyKWh` permanece
`null`.

## Calidad

La configuración `aoki-performance-quality-v1-2026-07` usa umbrales
`PROVISIONAL_QUALITY_THRESHOLDS`:

```text
minimumEnergyCoveragePct = 98
minimumStateCoveragePct = 98
maximumReconstructedEnergyPct = 20
```

Los días no se ocultan. Una entrada faltante produce `INSUFFICIENT_INPUTS`; una
cobertura inferior, señales inconsistentes o reconstrucción superior al umbral
produce `EXCLUDED_FROM_EVALUATION`. Los valores y banderas permanecen en
`daily`.

La clasificación de desempeño usa el CV(RMSE) oficial de 3,64 %:

- menor que −3,64 %: `FAVORABLE_PRELIMINARY`;
- entre −3,64 % y 3,64 %: `NEUTRAL_WITHIN_MODEL_VARIABILITY`;
- mayor que 3,64 %: `UNFAVORABLE_PRELIMINARY`;
- entradas insuficientes: `INSUFFICIENT_DATA`.

## Contrato

`GET /api/linea-base/desempeno-diario?inicio=<epoch>&fin=<epoch>` devuelve:

- `ranges`: rango solicitado, zona horaria y límites inclusivo/exclusivo;
- `model`: coeficientes oficiales y aplicación diaria del intercepto;
- `daily`: producción, estados, energía, esperado, residuo, clasificación,
  calidad y versiones por jornada;
- `summary`: totales calculados desde días evaluables y coberturas del periodo;
- `quality`: configuración provisional versionada;
- `methodology`: fuentes permitidas, granularidad y carácter preliminar.

El endpoint exige ambos límites, `fin > inicio` y un máximo local de 90 días.

## Control mayo de 2026

Rango:

```text
[2026-05-01 06:00, 2026-06-01 06:00) America/Bogota
```

Resultados:

| Indicador | Resultado |
|---|---:|
| Jornadas | 31 |
| Horas programadas | 744,0000 h |
| Energía medida | 28.467,000000 kWh |
| Energía reconstruida | 544,321168 kWh |
| Energía conocida | 29.011,321168 kWh |
| Cobertura energética | 99,9628 % |
| Cobertura de estados | 95,555 % |
| Días válidos | 28 |
| Días excluidos | 3 |
| Días con entradas insuficientes | 0 |
| Energía esperada de días evaluables | 25.238,984219 kWh |
| Residuo de días evaluables | +669,871255 kWh |
| Desviación de días evaluables | +2,6541 % |

El residuo agregado usa únicamente los mismos 28 días evaluables para energía
conocida y esperada. Es una diferencia desfavorable preliminar, no una
declaración definitiva de desempeño sostenido. De los días válidos, 2 fueron
favorables preliminares, 17 neutrales dentro de la variabilidad y 9
desfavorables preliminares.

Las tres exclusiones presentan `LOW_STATE_COVERAGE`. Veintisiete jornadas
informan `ENERGY_PARTIALLY_RECONSTRUCTED`; esta bandera por sí sola no excluye
cuando el porcentaje reconstruido permanece dentro del máximo provisional.

## Validación

Las pruebas unitarias cubren fórmula e intercepto diario, suma del periodo,
fuentes energéticas permitidas, nulos, coberturas, reconstrucción alta,
clasificaciones, versiones y no uso de producción total. La integración usa
SQLite con `mode=ro&immutable=1` y comprueba las 31 jornadas, 744 horas, controles
energéticos y fin exclusivo.

La base histórica maestra no fue modificada y no se realizaron operaciones
sobre la Raspberry.
