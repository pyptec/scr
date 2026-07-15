# Fase 2 — Cierre técnico de la subfase 2.5

## Alcance validado

Los eventos eléctricos se construyen exclusivamente con segmentos consecutivos
`IDLE` y `OFF` de ME337_1. `PRODUCTIVE` y `NO_DATA` cortan la agrupación. Todos los
eventos permanecen `DETECTED` y `SIN_CLASIFICAR`; no representan fallas confirmadas.

## Tratamiento de límites

Un evento que toca el inicio o el fin del filtro queda censurado porque no se conoce
su límite real fuera del rango. Se conserva en `boundaryCensoredEvents`, pero no se
incluye en los eventos completos ni en sus KPI.

En mayo se identificó un tramo `IDLE` censurado a la derecha:

```text
2026-06-01 05:24:16–06:00:00 America/Bogota
35,733 minutos
motivo: RANGE_END
```

## Resultado de mayo de 2026

Rango: 1 de mayo 06:00 a 1 de junio 06:00, `America/Bogota`.

| Indicador backend | Resultado |
|---|---:|
| Eventos completos | 103 |
| Duración IDLE | 250,2245 h |
| Duración OFF | 6,9003 h |
| Duración no productiva | 257,1248 h |
| Eventos censurados por límite | 1 |
| Duplicados exactos | 0 |
| Solapamientos entre eventos | 0 |

La suma de las duraciones de los 103 eventos es 257,1248 h y coincide con el KPI
`nonProductiveHours` del backend. El frontend consume directamente `data.summary`;
no vuelve a sumar los eventos para construir las tarjetas.

## Diferencia frente a horas por estado

Los KPI de eventos completos no tienen que cubrir todo el tiempo `IDLE/OFF` de la
clasificación. En mayo quedan fuera:

- 0,2794 h correspondientes a un segmento aislado que no cumple persistencia;
- 0,5956 h correspondientes al evento censurado en el límite final.

Estos tiempos permanecen en los KPI de estado eléctrico, pero no se presentan como
eventos completos.

## Trazabilidad

Cada evento conserva inicio y fin UTC/local, duración, estado dominante, minutos por
estado, corriente mínima/promedio, potencia promedio, muestras, calidad, versión de
umbrales y fuente `ME337_1`.

No se calcularon MTBF, MTTR ni disponibilidad técnica. La conciliación con paradas
reportadas pertenece exclusivamente a la subfase 2.6.
