# Fase 4 — Subfase 4.4: integración final

## Alcance

`GET /api/fase4/dashboard?inicio=<unix>&fin=<unix>` compone en una sola
solicitud los contratos aprobados de fase 2, mantenimiento 4.1, validaciones y
uptime 4.1B, confiabilidad 4.2 y alarmas 4.3. La capa no introduce modelos,
fórmulas ni identidades nuevas.

La canalización es:

```text
fase 2 → mantenimiento → validaciones → uptime → confiabilidad → alarmas
       → DTO integrado 4.4
```

## Contrato

La respuesta contiene:

```text
ranges
maintenance
validations
uptime
reliability
alerts
methodology
quality
```

`ranges` normaliza `requestedRange`, `effectiveRange`, `reconciliableRange`,
`America/Bogota`, inicio inclusivo y fin exclusivo. Las validaciones expuestas
se limitan a los `maintenanceEventId` presentes en el rango; las ventanas se
consultan por solapamiento `[inicio, fin)`.

## Protección de KPI e identidad

Cuando `reliability.status != VALID`, la composición fuerza a `null`:

```text
mtbfHours
mttrHours
technicalAvailabilityPct
technicalAvailabilityByTimePct
failureRatePer1000Hours
```

Además expone `quality.kpiVisible = false` y una explicación visible. Cada
`maintenanceEventId` se copia sin modificación desde el contrato 4.1.

## Control de mayo de 2026

Para `[2026-05-01 06:00, 2026-06-01 06:00) America/Bogota`:

```text
eventos de mantenimiento = 114
readiness = NO_HUMAN_VALIDATIONS
fallas confirmadas = 0
kpiVisible = false
alarmas deduplicadas = 236
alarmas abiertas = 236
fallas derivadas de alarmas = 0
```

Correlaciones:

```text
energía + Base 100 = 11
evento eléctrico + SOLO_DETECTADA = 101
mantenimiento + conciliación = 114
NO_DATA + baja cobertura = 3
```

## Restricciones preservadas

- Sin persistencia de alarmas ni notificaciones externas.
- Sin uso de sugerencias como fallas confirmadas.
- Sin modificación de las bases histórica o auxiliar.
- Sin operaciones sobre la Raspberry.
