# Fase 2 — Subfase 2.4: horas por estado

## Alcance

Consolidación por jornada productiva 06:00–06:00 y por periodo de las horas
clasificadas eléctricamente para ME337_1 (`gateway_id=10`, `device_id=24`). No se
calcularon eventos, MTBF, MTTR ni disponibilidad técnica.

## Contrato

Cada jornada y el resumen del periodo exponen:

- `productiveHours`;
- `idleHours`;
- `offHours`;
- `noDataHours`;
- `knownDataHours`;
- `scheduledHours`;
- `coveragePct`;
- `balanceDifferenceSeconds`;
- `balanceToleranceSeconds`;
- `balanceStatus`.

La tolerancia corresponde a un intervalo esperado de muestreo, actualmente 600 s.
Los periodos parciales usan su duración real. `knownDataHours` excluye siempre
`NO_DATA`.

## Resultado histórico local

Periodo evaluado: 1 de mayo de 2026 06:00 a 26 de junio de 2026 06:00,
`America/Bogota`.

| Indicador | Resultado |
|---|---:|
| Duración | 1.344,0000 h |
| PRODUCTIVE | 855,0096 h |
| IDLE | 409,4349 h |
| OFF | 8,8628 h |
| NO_DATA | 70,6929 h |
| Horas con datos | 1.273,3071 h |
| Cobertura | 94,7401 % |
| Balance temporal | VALID |

Las horas `PRODUCTIVE` continúan siendo una clasificación eléctrica preliminar y no
se reconstruyen mediante producción.

## Limitaciones

- `NO_DATA` no representa parada ni apagado.
- La cobertura energética no sustituye la cobertura de estados.
- Los eventos consecutivos y su conciliación pertenecen a subfases posteriores.
