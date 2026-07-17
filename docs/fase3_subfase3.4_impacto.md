# Fase 3 — Subfase 3.4: evaluación económica y ambiental

## Alcance

Se implementó una evaluación económica y ambiental preliminar como
transformación pura de los contratos 3.1, 3.2 y 3.3.

El servicio no consulta SQLite, producción, energía, estados, línea base,
eventos, conciliaciones ni fuentes externas. No recalcula residuo, Base 100,
CUSUM, energía o coberturas.

## Configuración

`device/aoki_impact_factors.json` se creó con versión
`impact-factors-v1`, moneda COP y ambos factores en `null`.

```text
energyTariffCopPerKWh = null
emissionFactorKgCo2ePerKWh = null
```

Los defaults heredados `950` y `0.164` no se usan. No tienen fuente, fecha
efectiva, versión ni unidad ambiental suficientemente definida.

Las unidades del contrato nuevo son:

```text
tarifa: COP/kWh
impacto económico: COP
factor de emisión: kgCO2e/kWh
impacto ambiental: kgCO2e
```

## Función pura

```text
build_impact_contract(
    performance_contract,
    base100_contract,
    cusum_contract,
    factors,
    request_overrides=None
)
```

La función usa `includedInCusum` como única máscara, copia `residualKWh`,
`base100Index` y `cusumKWh`, y verifica que `totalResidualKWh` coincida con
`finalCusumKWh`.

Sin tarifa, los impactos económicos son `null` y el estado es
`TARIFF_NOT_CONFIGURED`. Sin factor, los impactos ambientales son `null` y el
estado es `EMISSION_FACTOR_NOT_CONFIGURED`.

Un factor explícito igual a cero es válido y produce un impacto calculado igual
a cero. Esto se distingue de un factor no configurado.

## Endpoint

```text
GET /api/linea-base/impacto
```

Parámetros obligatorios:

```text
inicio
fin
```

Overrides opcionales:

```text
tarifa_cop_kwh
factor_emision_kgco2e_kwh
```

Los overrides deben ser finitos y mayores o iguales a cero. Se identifican como
`REQUEST_OVERRIDE` y versión `REQUEST_OVERRIDE_EPHEMERAL`. No se escriben en
JSON, `.env` o SQLite.

La respuesta contiene:

```text
ranges
inputs
daily
summary
methodology
quality
```

## Control de mayo sin factores

Rango:

```text
[2026-05-01 06:00, 2026-06-01 06:00) America/Bogota
```

| Indicador | Resultado |
|---|---:|
| Jornadas solicitadas | 31 |
| Jornadas evaluables | 28 |
| Jornadas excluidas | 3 |
| Residuo del periodo | +669,871255 kWh |
| CUSUM final | +669,871255 kWh |
| Impacto económico | `null` |
| Impacto ambiental | `null` |
| Estado económico | `TARIFF_NOT_CONFIGURED` |
| Estado ambiental | `EMISSION_FACTOR_NOT_CONFIGURED` |

Las jornadas excluidas son 8, 20 y 21 de mayo. Sus impactos diarios permanecen
`null`.

## Control matemático con factores ficticios

Solo en pruebas se usaron:

```text
tarifa ficticia = 1000 COP/kWh
factor ficticio = 0.2 kgCO2e/kWh
```

Resultados:

| Indicador | Resultado |
|---|---:|
| Impacto económico neto estimado | +669.871,255 COP |
| Costo evitado preliminar estimado | 198.324,447 COP |
| Sobrecosto preliminar estimado | 868.195,702 COP |
| Impacto ambiental neto estimado | +133,974251 kgCO2e |
| Emisiones evitadas preliminares estimadas | 39,664889 kgCO2e |
| Emisiones adicionales preliminares estimadas | 173,639140 kgCO2e |

Estos valores solo verifican las operaciones matemáticas y no forman parte de
la configuración local.

## Dashboard

La vista de impacto dejó de consumir los costos y emisiones legados. Ahora
muestra:

- diferencia energética;
- costos evitados y sobrecostos preliminares estimados;
- emisiones evitadas y adicionales preliminares estimadas;
- factores aplicados o mensajes de no configuración;
- días evaluables y excluidos;
- gráficas económicas y ambientales con huecos;
- tabla diaria con trazabilidad.

## Limitaciones

Mientras los factores continúen en `null`, no existe evaluación monetaria o
ambiental base. Los overrides son escenarios efímeros, no parámetros
productivos.

La evaluación sigue dependiendo de la línea base histórica, horas eléctricas
preliminares y umbrales provisionales de calidad. No constituye ahorro
verificado, reducción certificada ni demostración definitiva de mejora.

No se modificó la base histórica y no se realizaron operaciones sobre la
Raspberry.
