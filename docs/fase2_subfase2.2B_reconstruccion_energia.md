# Fase 2 — Subfase 2.2B: reconstrucción trazable de energía

## Alcance

Reconstrucción local sobre `DATOS_HISTORICOS_DE_PRUEBA`. No se ejecutó clasificación
de estados 2.3 ni se contactó la Raspberry.

## Jerarquía implementada

1. `ACCUMULATOR_DELTA` de `unit_id 100` válido: `MEASURED`.
2. `POWER_TRAPEZOIDAL` con potencias inicial y final: `RECONSTRUCTED_HIGH`.
3. `POWER_RECTANGULAR` con una sola potencia válida: `RECONSTRUCTED_MEDIUM`.
4. `CURRENT_MODEL`: deshabilitado porque no existe modelo aprobado.
5. Sin fuente técnicamente suficiente: `NO_DATA` y energía `null`.

La integración usa siempre la duración real:

```text
E_kWh = ((P_inicio_kW + P_fin_kW) / 2) × Δt_horas
```

La integración rectangular sólo se permite dentro de veinte minutos.

## Configuración versionada

Versión: `aoki-energy-reconstruction-v1-2026-07`.

- Máximo atribuible para potencia: 20 minutos.
- Máximo recuperable por delta agregado: 720 minutos.
- Potencia derivada máxima empírica: 62,5 kW.
- Tolerancia de validación cruzada: 25 %.
- Umbral informativo de resultado estimado: 20 % reconstruido.

Los límites de potencia y error se basan en el histórico mayo–junio: potencia máxima
observada de 50 kW, error cruzado mediano 4,26 % y percentil 95 de 18,87 %. Son límites
provisionales de calidad, no capacidad nominal de Aoki.

## Reinicios, saltos y huecos

- Delta negativo: `ACCUMULATOR_RESET`; nunca se aplica valor absoluto.
- Potencia derivada superior a 62,5 kW: `PHYSICALLY_IMPOSSIBLE_JUMP`.
- Error acumulador–potencia superior a 25 %: `INCONSISTENT_ENERGY_SOURCE`.
- Los tres casos recurren a potencia sólo si el intervalo y la señal son válidos.
- Un hueco largo puede conservar energía total por delta como
  `AGGREGATED_GAP_ENERGY`, pero continúa sin datos para estados internos.
- No se integra potencia entre extremos de un hueco largo.
- Los bordes del rango sin medición son `NO_DATA`.

## Resultado: mayo 1 a junio 25 de 2026

| Indicador | Resultado |
|---|---:|
| Energía medida por acumulador | 52.585,000 kWh |
| Energía reconstruida por potencia | 814,688 kWh |
| Energía total calculada | 53.399,688 kWh |
| Porcentaje reconstruido | 1,5256 % |
| Cobertura temporal energética | 99,9785 % |
| Tiempo `NO_DATA` no recuperable | 17,317 min |
| Intervalos por acumulador | 5.788 |
| Intervalos por potencia trapezoidal | 177 |
| Intervalos `NO_DATA` | 2 |
| Huecos con energía agregada recuperada | 161 |

### Motivos de sustitución

- `INCONSISTENT_ENERGY_SOURCE`: 175 intervalos.
- `ACCUMULATOR_RESET`: 1 intervalo.
- `PHYSICALLY_IMPOSSIBLE_JUMP`: 1 intervalo.
- Bordes sin fuente: 2 intervalos que permanecen `NO_DATA`.

### Totales mensuales evaluados

| Periodo | Total kWh | Medida kWh | Reconstruida kWh |
|---|---:|---:|---:|
| Mayo | 29.021,321 | 28.477,000 | 544,321 |
| Junio 1–25 | 24.378,367 | 24.108,000 | 270,367 |

## Validación cruzada

- Comparaciones acumulador–potencia: 5.802.
- Error promedio observado, incluyendo intervalos rechazados: 7,9785 %.
- Se rechazaron 175 deltas por superar 25 % y se reconstruyeron con potencia.
- La energía irrecuperable de los dos bordes permanece desconocida (`null`), no cero.

## Trazabilidad

Cada intervalo conserva timestamps, duración, fuente, calidad, motivo, error cruzado,
IDs y valores originales de ambos extremos, y versión de configuración. El campo
`stateDataAvailable` distingue energía agregada recuperable de cobertura apta para
clasificación de estados.

## Limitaciones

- No existe modelo corriente–potencia aprobado; `unit_id 54` no genera energía.
- La energía agregada de huecos no describe la forma interna del consumo.
- Los intervalos agregados se asignan a la jornada donde comienzan; no se reparte su
  energía entre jornadas porque eso inventaría una distribución temporal.
- Los límites empíricos requieren aprobación técnica antes de uso productivo.
