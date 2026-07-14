# Fase 2 — Subfase 2.1: auditoría eléctrica de ME337_1

## Alcance y fuentes

Auditoría documental, sin clasificación de estados ni cambios en datos.

Fuentes revisadas:

- `device/meatrolME337.yml`.
- `db/catalogos_unidades.csv`.
- esquema `mediciones_detalle` en `db/samee200_db.py`.
- importador histórico `db/importar_mediciones_historicas_samee200.py`.
- `data/import_mediciones/mediciones_samee200_lps_mayo_junio_2026.csv`.

La base `data/samee200.db` no está incluida en el workspace. Las métricas de calidad
corresponden al CSV histórico disponible y deben contrastarse con la base desplegada.

## Identificación del equipo

| Campo | Valor auditado |
|---|---|
| Equipo lógico | `ME337_1` |
| `device_id` histórico/configurado | `24` |
| Nombre | Proceso Aoki / compresor |
| Rol | Proceso |
| Gateway | `10` — SAMEE200-LPS-AOKI |
| Origen | medidor ME337 trifásico, `source_type=device` |

El importador confirma explícitamente que `device_id 24` corresponde a ME337_1,
proceso Aoki. `device_id 25` es ME337_2 y no debe utilizarse para detectar estados
de Aoki.

## Variables candidatas validadas

| `unit_id` | Registro ME337 | Alias | Catálogo | Unidad | Uso candidato |
|---:|---|---|---|---|---|
| 54 | Average value of L1L2L3 three-phase current | `AVGcurrent` | Corriente trifásica promedio | A | Variable primaria |
| 61 | Total Active power | `PTotal` | Potencia activa total | kW | Validación secundaria |
| 100 | Total Positive active energy | `kWh_total` | Energía activa importada acumulada UInt32 | kWh | Balance energético, no clasificación directa |

El timestamp está en `mediciones_detalle.timestamp_utc`. En el CSV corresponde a
la primera columna `utc_date`. El valor se almacena como texto en SQLite y debe
validarse/convertirse explícitamente a número durante el preprocesamiento.

## Resultado sobre el histórico disponible

Periodo observado en UTC: `2026-05-01 00:07:19` a `2026-06-30 23:52:49`.

| Indicador | Corriente 54 | Potencia 61 | Energía 100 |
|---|---:|---:|---:|
| Muestras válidas | 6.499 | 6.499 | 6.499 |
| Nulas o no numéricas | 0 | 0 | 0 |
| Mínimo | 0,0 A | 0,4 kW | 0,0 kWh |
| Máximo | 70,5 A | 50,0 kW | 55.002,0 kWh |
| Promedio | 53,290 A | 37,255 kW | 28.529,814 kWh |
| Valores negativos | 0 | 0 | 0 |
| Valores cero | 1 | 0 | 1 |
| Duplicados exactos | 1 | 1 | 1 |
| Grupos con timestamp duplicado | 1 | 1 | 1 |
| Fuera de orden según archivo | 0 | 0 | 0 |

### Frecuencia y huecos

- Mediana del intervalo: 625 s (10 min 25 s).
- Percentil 75: 1.013 s (16 min 53 s).
- Percentil 95: 1.048 s (17 min 28 s).
- Huecos mayores de 20 minutos: 161 para cada variable.
- Huecos mayores de 30 minutos: 2 para cada variable.
- Mayor hueco: 37.867 s (10 h 31 min 7 s), entre
  `2026-06-24 14:20:39 UTC` y `2026-06-25 00:51:46 UTC`.
- Segundo hueco mayor: 11.211 s (3 h 6 min 51 s), entre
  `2026-05-20 20:15:57 UTC` y `2026-05-20 23:22:48 UTC`.

La cadencia no es uniformemente de diez minutos: existe una concentración adicional
alrededor de 17 minutos. La subfase 2.2 debe usar `Δt` real y no asignar duración
fija a cada muestra.

### Signo de potencia

La potencia activa total no presenta valores negativos en el histórico auditado.
Su rango y el catálogo son coherentes con **kW**, no con W. El código actual de KPI
documenta `unit_id 61` como W y divide entre 1000; esta inconsistencia debe corregirse
en una tarea autorizada antes de usar potencia como validación cuantitativa.

### Confiabilidad de energía acumulada

La energía `unit_id 100` es acumulada y no debe promediarse. Se observaron:

- 6.311 incrementos positivos.
- 185 deltas iguales a cero.
- 1 delta negativo: 2.081 → 0 kWh el `2026-05-02 22:05:55 UTC`.
- salto posterior de 0 → 2.093 kWh en aproximadamente diez minutos.

Esto indica reinicio, dato anómalo o secuencia histórica concatenada. La variable es
útil sólo después de aplicar reglas trazables para reinicios y saltos; no se considera
todavía validada para clasificar estados.

## Cobertura por jornada 06:00–06:00

La agrupación se realizó en `America/Bogota`, asignando cada muestra a la jornada que
comienza a las 06:00. Las tres variables tienen timestamps coincidentes.

- 62 jornadas tocadas, incluyendo las dos jornadas parciales de los extremos.
- En las 60 jornadas entre `2026-05-01` y `2026-06-29`: mediana de 112 muestras.
- Rango diario completo observado: 58–113 muestras.
- Frente a 144 muestras teóricas/día a exactamente 10 minutos, cobertura por conteo:
  mínimo 40,28 %, mediana 77,78 %, máximo 78,47 %.
- Todas las jornadas quedan debajo de 80 % si se exige exactamente una muestra cada
  diez minutos. Este porcentaje es descriptivo: debe recalcularse por duración cubierta
  en 2.2 debido a la cadencia real cercana también a 17 minutos.
- Jornadas especialmente reducidas: 8, 20, 21, 28 y 30 de mayo; 19, 21, 22, 23, 24 y
  26 de junio.

## Calidad del dato y trazabilidad

- Los valores históricos auditados son numéricos y no nulos.
- Existe un duplicado exacto por variable; debe eliminarse conservando referencia al
  registro original.
- No se detectó desorden en el orden físico del CSV, pero el servicio debe ordenar por
  timestamp porque SQLite no garantiza orden sin `ORDER BY`.
- Los huecos no pueden interpretarse como apagado ni parada.
- El campo `valor` de SQLite es `TEXT`; las conversiones fallidas deben producir dato
  inválido o `NO_DATA`, nunca cero.
- La consulta debe filtrar simultáneamente `device_id=24`, `gateway_id=10` y el
  `unit_id` requerido para evitar mezclar ME337_1 con ME337_2.

## Conclusión de la auditoría

1. Variable primaria validada para continuar: corriente trifásica promedio, `unit_id 54`, A.
2. Variable secundaria candidata: potencia activa total, `unit_id 61`, catalogada en kW.
3. Energía acumulada `unit_id 100`: disponible, pero requiere tratamiento de reinicios.
4. Timestamp válido: `timestamp_utc`; la jornada debe convertirse a `America/Bogota` 06:00–06:00.
5. Hay huecos y un duplicado que obligan a ejecutar el preprocesamiento antes de clasificar.
6. No se implementó ninguna etiqueta `OFF`, `IDLE`, `PRODUCTIVE` o `NO_DATA`.

## Pendientes para revisión

- Confirmar estas métricas contra la base SQLite del gateway desplegado.
- Confirmar que la unidad real entregada por el ME337 para `unit_id 61` es kW y corregir
  el KPI que actualmente la interpreta como W.
- Aprobar `unit_id 54` como señal primaria y `unit_id 61` como validación secundaria.
- Sólo después de esa aprobación, iniciar la subfase 2.2 de preprocesamiento.
