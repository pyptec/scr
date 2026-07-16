# Fase 2 — Subfase 2.6: conciliación trazable de paradas

## Alcance

Se implementó la comparación preliminar entre eventos eléctricos `IDLE/OFF` de
ME337_1 y paradas reportadas normalizadas por la subfase 2.6A. La conciliación no
confirma fallas, no valida causas y no calcula MTBF, MTTR ni disponibilidad técnica.

## Configuración

Archivo: `device/downtime_reconciliation.json`.

```text
matchingToleranceMinutes = 20
minimumOverlapMinutes = 10
minimumOverlapPct = 30
version = aoki-downtime-reconciliation-v1-2026-07
```

Los valores son preliminares y no representan validación industrial.

## Contratos

Los eventos eléctricos incorporan un `eventId` estable derivado de ME337_1,
gateway 10, dispositivo 24, inicio, fin y versión de umbrales.

Cada salida de conciliación conserva:

- IDs eléctricos y reportados, sin reutilización entre salidas;
- inicio, fin y duración de ambas fuentes por separado;
- diferencias firmadas `eléctrico - reportado`;
- solapamiento y coberturas de ambas fuentes;
- `rawText`, `matchedText` y causa reportada;
- confianza categórica y motivo de decisión;
- relaciones individuales para documentar casos múltiples;
- `isFailure=false`.

`confidencePct` permanece `null`: no existe un modelo calibrado que permita mostrar
una probabilidad. La confianza explicable usa `HIGH`, `MEDIUM`, `LOW` o
`NOT_APPLICABLE`.

Todas las salidas automáticas conservan `status=PENDING_REVIEW`. `VALIDATED` queda
reservado para una validación humana posterior.

## Algoritmo

1. Limitar el cálculo a la intersección entre filtro, producción cargada y periodo
   con corriente ME337_1.
2. Construir ventanas completas únicamente cuando el reporte tiene inicio y fin.
3. Generar candidatos por solapamiento, contención o diferencias de inicio/fin
   dentro de ±20 minutos.
4. Calcular métricas por cada pareja candidata.
5. Construir componentes de un grafo bipartito para resolver uno-a-uno,
   uno-a-varios y varios-a-uno sin reutilización silenciosa.
6. Mantener relaciones múltiples, solapamientos parciales, causas no claras y
   reportes temporalmente incompletos como `PENDIENTE_REVISION`.
7. Usar `SIN_DATOS` cuando los huecos impiden una conclusión.
8. Clasificar eventos eléctricos no asociados como `SOLO_DETECTADA`, siempre con
   advertencia de que no son fallas confirmadas.
9. Excluir eventos eléctricos posteriores al fin de producción cargada.

Las duraciones se agregan por IDs únicos y los solapamientos mediante unión de
intervalos, evitando doble conteo.

## Resultado histórico local

Rango conciliable:

```text
2026-05-01 06:00
2026-06-26 06:00
America/Bogota
```

Entradas:

- 26 paradas reportadas únicas;
- 150 eventos eléctricos únicos;
- 9 segmentos `NO_DATA`, equivalentes a 70,6929 horas.

Salida:

| Clasificación | Cantidad de salidas |
|---|---:|
| `REPORTADA_Y_DETECTADA` | 0 |
| `SOLO_REPORTADA` | 0 |
| `SOLO_DETECTADA` | 147 |
| `SIN_DATOS` | 1 |
| `PENDIENTE_REVISION` | 25 |

Se produjeron 173 salidas con 173 `reconciliationId` únicos. Los 150 IDs eléctricos
y 26 IDs reportados aparecen una sola vez en la salida consolidada.

Casos con relación candidata:

- 4 de mayo: 190 minutos de solapamiento; queda pendiente porque la causa reportada
  no es clara.
- 13 de mayo: 189 minutos de solapamiento; queda pendiente por solapamiento parcial
  y límites diferentes.
- 24 de junio: 211 minutos de solapamiento y 611,767 minutos `NO_DATA`; se clasifica
  `SIN_DATOS` porque la pérdida de cobertura impide confirmar la relación.

Los otros 23 reportes carecen de un intervalo completo y permanecen pendientes. No
se emparejan por compartir jornada o por tener una duración similar.

## Dashboard

La vista de eficiencia operacional muestra tarjetas, periodo conciliable, filtros
por clasificación, confianza, estado dominante, jornada y revisión, además de una
tabla con duraciones, diferencias, solapamiento, coberturas, causa, observación y
motivo.

La advertencia metodológica permanece visible:

```text
Los eventos eléctricos no son fallas confirmadas. La conciliación es preliminar y
requiere revisión cuando la evidencia sea incompleta.
```

## Limitaciones

- Solo tres reportes históricos tienen inicio y fin completos.
- No existen relaciones múltiples verificables en el conjunto real; se validan con
  pruebas sintéticas.
- La medición eléctrica puede contener cargas auxiliares o compartidas.
- No existe persistencia de validación humana en esta subfase.
- No se calculan confiabilidad ni disponibilidad técnica.
