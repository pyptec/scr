# Extensión controlada — Confiabilidad reportada preliminar

## Fuente y separación metodológica

El servicio `db/aoki_reported_reliability.py` consume exclusivamente eventos
normalizados por 2.6A, recibidos desde el contrato de conciliación de fase 2. No
consulta Excel ni tablas por una ruta paralela.

La salida se publica en:

```text
GET /api/mantenimiento/confiabilidad-reportada
GET /api/fase4/dashboard → reportedReliability
```

`reportedReliability` es independiente de `reliability`. Siempre declara:

```text
PRELIMINAR_REPORTADO
isTechnicalKpi = false
isPreliminary = true
requiresHumanValidation = true
```

## Metodología

Versión `aoki-reported-reliability-v1-2026-07`. Las clasificaciones son
sugerencias conservadoras basadas en `matchedText`. Los conflictos, causas
múltiples, temperatura de aceite y mantenimiento sin evidencia adicional quedan
`UNDETERMINED`.

MTTR usa solo duraciones reportadas positivas con estado `VALID` o `PARTIAL` de
posibles fallas correctivas. MTBF no usa PRODUCTIVE, tiempo eléctrico, 24 horas
por día ni tiempo calendario implícito. La alternativa de mayo usa las horas
programadas del contrato de producción y queda marcada
`ESTIMATED_REPORTED_OPERATING_TIME`.

## Resultado de mayo

Para `[2026-05-01 06:00, 2026-06-01 06:00) America/Bogota`:

```text
paradas reportadas = 13
duración reportada válida = 14.5 h
posibles fallas correctivas = 5
fallas correctivas con duración = 4
downtime correctivo sugerido = 6.416667 h
MTTR preliminar = 1.604167 h
horas programadas reportadas = 735.5 h
tiempo operativo reportado estimado = 729.083333 h
MTBF preliminar = 145.816667 h
disponibilidad preliminar = 99.127578 %
cobertura de clasificación = 53.846154 %
estado = LOW_CLASSIFICATION_COVERAGE
```

Ninguna sugerencia se convierte en falla confirmada o alimenta los KPI técnicos
de 4.2.
