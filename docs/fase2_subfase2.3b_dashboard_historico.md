# Fase 2 — Subfase 2.3B: dashboard histórico

## Alcance

Ajuste local del dashboard para presentar la base histórica de prueba del 1 de mayo
al 25 de junio de 2026. No se reconstruyeron estados mediante producción, no se
rellenó `NO_DATA`, no se calculó productividad de referencia y no se reentrenó la
línea base.

## Separación metodológica

- Operación reportada: producción, paradas extraídas de observaciones y horas reales
  reportadas.
- Clasificación eléctrica preliminar: estados `PRODUCTIVE`, `IDLE`, `OFF` y `NO_DATA`
  obtenidos de ME337_1.
- Energía medida: deltas válidos del acumulador.
- Energía reconstruida: integración de potencia validada en 2.2B.
- `NO_DATA`: se conserva por separado para estados y energía.

Los estados eléctricos no se presentan como prueba del estado productivo real. La
relación observada entre producción diaria y horas `PRODUCTIVE` continúa siendo baja
(`R²` entre 0,0245 y 0,0719 en los filtros auditados).

## Línea base

Se conserva sin cambios:

```text
E_esperada_kWh =
514.50
+ 0.005018 × envases_buenos
+ 16.5198 × horas_productivas
```

La evaluación usa horas de la clasificación eléctrica y devuelve
`RESULTADO_PRELIMINAR`, junto con fuente, versión de umbrales, cobertura de estados y
horas `NO_DATA`. El control de reentrenamiento fue retirado del dashboard.

## Resultados históricos de referencia

- Horas `PRODUCTIVE`: 855,01 h.
- Horas `IDLE`: 409,43 h.
- Horas `OFF`: 8,86 h.
- Horas `NO_DATA` de estados: 70,69 h.
- Cobertura de estados: 94,74 %.
- Energía medida: 52.585 kWh.
- Energía reconstruida: 814,688 kWh.
- Cobertura energética: 99,98 %.

La cobertura energética no sustituye la cobertura de estados: un delta acumulado
puede recuperar el consumo total de un hueco sin revelar sus estados internos.

## Limitaciones

- La medición puede incluir cargas auxiliares o compartidas.
- Los resultados de línea base siguen siendo exploratorios.
- No se calcularon MTBF, MTTR ni disponibilidad técnica.
- No se modificó ni desplegó ninguna base hacia la Raspberry.
