# Codex Rules — SAMEE200

## Alcance

Estas reglas aplican a todos los cambios del proyecto SAMEE200.

## Forma de trabajo

1. Trabajar una sola subfase a la vez.
2. No avanzar sin autorización.
3. No realizar refactorizaciones generales no solicitadas.
4. No modificar módulos fuera del alcance.
5. Antes de editar, identificar archivos, funciones y dependencias.
6. Después de editar, ejecutar pruebas.
7. Documentar causa raíz, cambios y resultados.
8. Indicar archivos y funciones concretas.
9. No asumir estructuras o nombres sin revisar el código.
10. Mantener compatibilidad con datos históricos.

## Reglas de cálculo

1. `ME337_1` corresponde al proceso Aoki.
2. `ME337_2` corresponde al totalizador de planta.
3. La jornada productiva es de 06:00 a 06:00.
4. Tres turnos equivalen a 24 horas.
5. Dos turnos equivalen a 24 horas.
6. No usar el porcentaje suministrado como eficiencia productiva calculada.
7. Diferenciar eficiencia de calidad, eficiencia productiva, productividad y disponibilidad.
8. No promediar porcentajes diarios cuando puedan calcularse desde totales.
9. No dividir por cero.
10. No convertir datos inválidos en cero.
11. Usar `null`, `No disponible`, `Datos insuficientes` o `Pendiente de parametrización`.
12. No inventar capacidad nominal.
13. No inventar duración de paradas.
14. Conservar el texto original de observaciones.
15. No contar ausencia de datos como parada.

## Línea base

La ecuación oficial es:

```text
E_esperada_kWh =
514.50
+ 0.005018 × envases_buenos
+ 16.5198 × horas_productivas
```

Métricas:

```text
R² = 0.9278
R² ajustado = 0.9248
CV(RMSE) = 3.64 %
```

No modificar, reemplazar ni reentrenar este modelo sin autorización expresa.

## Frontend

1. Mantener el estilo visual existente.
2. Crear componentes pequeños y reutilizables.
3. Evitar lógica de negocio duplicada en componentes.
4. Centralizar filtros.
5. Mantener selección de fechas entre módulos.
6. No mostrar cero como sustituto de dato faltante.
7. Etiquetar claramente unidades.
8. Mostrar el periodo efectivo evaluado.
9. No recargar todo el dashboard si solo cambia un módulo.
10. Evitar efectos que sobrescriban selecciones del usuario.

## Backend

1. Centralizar reglas de negocio.
2. Evitar fórmulas duplicadas entre frontend y backend.
3. Usar DTOs consistentes.
4. Validar zona horaria y límites inclusivos/exclusivos.
5. Registrar advertencias de calidad de datos.
6. Mantener trazabilidad del origen de cada indicador.
7. No alterar la base de datos sin justificarlo.
8. Si se requiere migración, documentarla.

## Pruebas

Cada subfase debe incluir pruebas unitarias, pruebas de integración cuando correspondan, datos nulos, divisiones por cero, periodos parciales, observaciones ambiguas, diferencias de zona horaria y validación de totales.

## Entrega de cada subfase

La respuesta final de cada subfase debe incluir:

1. causa raíz;
2. archivos modificados;
3. funciones creadas o modificadas;
4. pruebas ejecutadas;
5. resultados;
6. limitaciones;
7. siguiente subfase recomendada.

Luego debe detenerse.
