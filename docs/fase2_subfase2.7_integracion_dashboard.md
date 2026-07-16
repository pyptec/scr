# SUBFASE 2.7 — Integración final de fase 2

## Alcance

El dashboard consume una instantánea histórica común con semántica `[inicio, fin)`,
jornada 06:00–06:00 y zona `America/Bogota`. El adaptador
`db/fase2_dashboard.py` no persiste resultados ni crea modelos analíticos.

## Endpoint integrado

```text
GET /api/fase2/dashboard?inicio=<unix>&fin=<unix>
```

Secciones conservadas y separadas:

- `production`: operación reportada y contrato original `periodo`;
- `quality`: indicadores derivados de los totales reportados;
- `energy`: energía medida, reconstruida, conocida y NO_DATA;
- `electricalStates`: PRODUCTIVE preliminar, IDLE, OFF y NO_DATA;
- `electricalEvents`: eventos eléctricos sin convertirlos en fallas;
- `reconciliation`: contrato cerrado de conciliación y rango conciliable;
- `legacyDashboard`: indicadores heredados requeridos por resumen e impacto;
- `gateway`: referencia explícita al endpoint instantáneo fuera del filtro;
- `ranges` y `methodology`: fronteras, zona horaria y trazabilidad.

Cada sección histórica añade, sin renombrar sus campos cerrados:

```text
requestedRange
effectiveRange
reconciliableRange
timezone = America/Bogota
startInclusive = true
endExclusive = true
```

Alias preservados:

- `production.periodo.inicio_utc` → `production.requestedRange.startUtc`;
- `production.periodo.fin_utc` → `production.requestedRange.endUtc`;
- `reconciliation.effectiveRange` se conserva y el contrato común añade
  `reconciliation.reconciliableRange`.

## Fronteras

Las mediciones históricas usan:

```sql
timestamp_utc >= inicio AND timestamp_utc < fin
```

La producción usa solapamiento:

```sql
fecha_hora_fin_utc > inicio AND fecha_hora_inicio_utc < fin
```

Para mayo de 2026 el rango de control es `1777633200–1780311600`: contiene
31 jornadas y 744 horas. Una fila con timestamp `1780311600` queda excluida.

## Frontend

Cada actualización crea una instantánea congelada. Todos los cargadores reciben
esa misma referencia. Las respuestas se almacenan en caché por versión, endpoint,
parámetros, inicio y fin; un cambio de rango invalida la caché.

`/api/estado` continúa siendo instantáneo y se rotula fuera del filtro histórico.
`/api/ultimos` recibe inicio y fin y devuelve el último valor de cada variable
dentro del rango seleccionado.

PRODUCTIVE permanece rotulado como clasificación eléctrica preliminar. No se
calculan MTBF, MTTR, disponibilidad técnica, Base 100 ni CUSUM definitivos.
