# Fase 2 — Resultados de subfases 2.2 y 2.3

## Entorno protegido

- Ejecución exclusivamente local en Windows.
- Base: `data/samee200.db`, abierta en modo de solo lectura para la validación.
- Tipo: `DATOS_HISTORICOS_DE_PRUEBA`.
- Raspberry `192.168.2.124`: no contactada ni modificada.
- Integridad SQLite: `ok`.
- SHA-256 auditado: `9c421aaf7d75b5e96dbaad258318d82d29ff10d202a1105e05a9edc5abc4b14c`.

## Subfase 2.2 — Preprocesamiento

El servicio central:

- filtra exclusivamente `gateway_id=10`, `device_id=24`, unidades 54 y 61;
- conserva ID, orden, timestamp y valor original;
- valida números finitos sin convertir inválidos en cero;
- detecta desorden antes de ordenar;
- elimina duplicados exactos;
- registra conflictos para un mismo timestamp;
- calcula `deltaSeconds` real;
- añade hora local de Colombia y jornada 06:00–06:00;
- usa un hueco máximo configurable de 20 minutos;
- convierte el intervalo completo de un hueco largo en `NO_DATA`.

## Subfase 2.3 — Clasificación preliminar

Configuración `aoki-current-v1-2026-07`:

- `I < 27.38 A`: `OFF`.
- `27.38 A <= I < 54.58 A`: `IDLE`.
- `I >= 54.58 A`: `PRODUCTIVE`.
- Persistencia: dos muestras consecutivas o veinte minutos reales.
- Potencia `unit_id=61` en kW: validación secundaria, nunca sustituye la corriente.
- Potencia ausente: `PARTIAL_SIGNAL`.
- Corriente productiva y potencia no positiva: `INCONSISTENT_SIGNAL`.

Los segmentos se dividen al cruzar las 06:00 y no se unen a través de `NO_DATA`.

## Resultado local: 1 de mayo a 25 de junio de 2026

Rango evaluado: `2026-05-01 06:00` a `2026-06-26 06:00`, America/Bogota.

| Indicador | Total |
|---|---:|
| Jornadas | 56 |
| Horas programadas del rango | 1.344,000 |
| Horas `PRODUCTIVE` | 855,010 |
| Horas `IDLE` | 409,435 |
| Horas `OFF` | 8,863 |
| Horas `NO_DATA` | 70,693 |
| Cobertura | 94,740 % |
| Segmentos | 376 |
| Transiciones diarias | 320 |
| Segmentos inconsistentes | 0 |

La diferencia de cierre por redondeo de los campos publicados es aproximadamente
0,001 horas. Internamente los segundos cubren exactamente el rango solicitado.

### Mayo de 2026

- 31 jornadas; 744 horas.
- `PRODUCTIVE`: 452,929 h.
- `IDLE`: 251,099 h.
- `OFF`: 6,900 h.
- `NO_DATA`: 33,071 h.

### Junio, jornadas 1 a 25

- 25 jornadas; 600 horas.
- `PRODUCTIVE`: 402,081 h.
- `IDLE`: 158,335 h.
- `OFF`: 1,962 h.
- `NO_DATA`: 37,622 h.

## Calidad observada en la consulta

- 11.932 filas de entrada (corriente y potencia).
- 5.966 muestras sincronizadas de corriente.
- Valores inválidos: 0.
- Duplicados exactos en el rango: 0.
- Conflictos de timestamp: 0.
- Un retroceso temporal detectado en el orden físico por ID; el servicio lo registra y ordena.
- Potencia ausente: 0 segmentos.
- Señal inconsistente con la regla conservadora de potencia cero: 0 segmentos.

## Límites

- La validación de potencia sólo marca como incoherente `PRODUCTIVE` con potencia no
  positiva. No se inventó un umbral de “potencia elevada” para estado `OFF`.
- Los resultados son preliminares y pertenecen a una base histórica de pruebas.
- No se detectaron eventos de parada, no se conciliaron observaciones y no se calcularon
  MTBF, MTTR ni disponibilidad técnica.
- No se modificó la ecuación oficial de línea base.
