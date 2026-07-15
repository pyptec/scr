# Fase 2 — Subfase 2.6A: extractor normalizado de paradas reportadas

## Alcance

Se corrigió exclusivamente la extracción de paradas desde observaciones de
producción. No se implementó conciliación con eventos eléctricos ni se calcularon
indicadores de confiabilidad.

## Contrato

Cada evento reportado contiene `eventId`, `productionDate`, `startTime`, `endTime`,
`durationMinutes`, `crossesMidnight`, `rawText`, `matchedText`, `cause`,
`temporalSource` y `status`. Se conserva temporalmente `date` como alias compatible
de `productionDate`.

`rawText` conserva la observación completa sin reemplazarla por el fragmento que
coincidió. `matchedText` contiene el fragmento asociado con la mención concreta.

Estados:

- `VALID`: intervalo inicio-fin válido o duración explícita inequívoca de hasta 24 h.
- `PARTIAL`: existe una hora útil, pero no un intervalo o duración completo.
- `PENDING_REVIEW`: existe mención sin evidencia temporal suficiente, o la duración
  explícita requiere revisión.

Fuentes temporales:

- `START_END`
- `EXPLICIT_DURATION`
- `PARTIAL_TIME`
- `TEXT_ONLY`

## Reglas aplicadas

- Las menciones comienzan con expresiones de parada reales, no con el `para` que
  introduce una finalidad como `para limpieza` o `para mantenimiento`.
- Se reconocen `a la`, `a las`, `inicia`, `reinicia`, `reibicia`, `arranca` y
  `reanuda`, con o sin la palabra `máquina` o `producción`.
- Un fin anterior al inicio se asigna al día siguiente y marca
  `crossesMidnight=true`.
- Una hora de reinicio aislada no genera una hora de inicio.
- El identificador estable usa SHA-256 sobre fecha productiva, posición de la
  mención, componentes temporales y observación normalizada.
- Los eventos equivalentes dentro de la misma observación se deduplican.
- Se reconocen únicamente causas explícitas y acotadas: limpieza, mantenimiento,
  ajuste, falla, falta de material y cambio de molde. Una causa no reconocible
  permanece `null`.
- Los estados `PARTIAL` y `PENDING_REVIEW` mantienen pendientes los KPI derivados;
  no se convierten en cero minutos.

## Validación sobre la base histórica local

La base se abrió en modo SQLite de solo lectura. Se procesaron 56 filas de
producción y 24 observaciones no vacías; 22 observaciones contenían menciones de
parada reconocibles.

Antes de la corrección, el extractor devolvía 35 registros: 20 `VALID` y 15
`PENDING_REVIEW`. Diez observaciones producían simultáneamente resultados válidos y
pendientes, principalmente por interpretar `para limpieza/mantenimiento/ajuste`
como otra parada.

Después de la corrección se obtuvieron 26 eventos únicos:

| Estado | Cantidad |
|---|---:|
| `VALID` | 22 |
| `PARTIAL` | 1 |
| `PENDING_REVIEW` | 3 |

| Fuente temporal | Cantidad |
|---|---:|
| `EXPLICIT_DURATION` | 19 |
| `START_END` | 3 |
| `PARTIAL_TIME` | 1 |
| `TEXT_ONLY` | 3 |

No se encontraron `eventId` duplicados ni claves semánticas duplicadas.

Casos corregidos:

- 4 de mayo: 14:50–18:00, 190 minutos.
- 13 de mayo: 16:15–20:40, 265 minutos, reconociendo `reibicia`; la segunda parada
  de 105 minutos permanece como evento independiente.
- 24 de junio: 09:40–01:00, 920 minutos y cruce de medianoche.
- 18 de mayo: solo fin 14:00, estado `PARTIAL`; no se inventa inicio.
- 5 de junio: duración explícita de 160 minutos y fin contextual 15:30, sin inventar
  inicio.

## Limitaciones

- El extractor es determinista y basado en patrones; nuevas variantes lingüísticas
  requerirán casos de prueba adicionales.
- Las menciones `en varias ocasiones` o `en dos ocasiones` permanecen como un único
  registro `PENDING_REVIEW`, porque el texto no permite separar eventos ni duraciones.
- La causa es informativa y no constituye clasificación de falla.
- No existe todavía matching con eventos eléctricos ni clasificaciones de la
  subfase 2.6.
