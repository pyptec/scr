# SAMEE200 — Plan de desarrollo modular para Codex

## Objetivo general

Reorganizar y corregir el dashboard industrial SAMEE200 para que presente de forma clara, modular y técnicamente consistente la información del proceso Aoki y de la planta de plásticos.

El desarrollo debe ejecutarse por fases. No avanzar a una fase posterior sin cerrar, probar y documentar la fase actual.

## Contexto funcional

- `ME337_1`: consumo energético del proceso Aoki.
- `ME337_2`: totalizador de la planta de plásticos.
- Jornada productiva: 06:00 del día actual a 06:00 del día siguiente.
- Tres turnos: 3 × 8 horas.
- Dos turnos: 2 × 12 horas.
- Las mediciones eléctricas se registran aproximadamente cada 10 minutos.
- La producción incluye fecha, envases buenos, envases malos, número de turnos, observaciones, anomalías y paradas reportadas.

La línea base energética oficial actual es:

```text
E_esperada_kWh =
514.50
+ 0.005018 × envases_buenos
+ 16.5198 × horas_productivas
```

Indicadores del modelo:

```text
R² = 0.9278
R² ajustado = 0.9248
CV(RMSE) = 3.64 %
```

No reemplazar este modelo durante la fase 1.

## Arquitectura propuesta del dashboard

Dividir el dashboard en módulos de navegación independientes:

1. Resumen
2. Producción
3. Calidad
4. Eficiencia operacional
5. Eficiencia energética
6. Línea base ISO 50001
7. Impacto económico y ambiental
8. Confiabilidad y mantenimiento
9. Variables eléctricas
10. Estado del gateway

Dentro de `Línea base ISO 50001` también deben existir vistas para `Índice Base 100` y `CUSUM`. En la fase 1 se prepara únicamente su estructura visual y navegación; los cálculos definitivos se implementan en la fase 3.

Cada módulo debe tener sus propios componentes, consultas y funciones de cálculo, pero compartir un filtro global de fechas.

## Fases del proyecto

### Fase 1 — Reorganización del dashboard y corrección de producción
Objetivo: crear navegación modular y corregir indicadores básicos de producción, calidad y eficiencia operacional.

### Fase 2 — Estados eléctricos y detección de paradas
Objetivo: clasificar cada intervalo de `ME337_1` como productivo, espera, apagado o sin datos.

### Fase 3 — Eficiencia energética y línea base
Objetivo: calcular energía real, EnPI, energía esperada, desviación, ahorro o sobreconsumo, además de las gráficas de Índice Base 100 y CUSUM.

### Fase 4 — Confiabilidad y mantenimiento
Objetivo: conciliar paradas reportadas y eléctricas, calcular MTBF, MTTR y disponibilidad técnica.

### Fase 5 — Impacto económico, ambiental y visualizaciones
Objetivo: costos, emisiones, pérdidas por espera, gráficas y reportes.

# FASE 1 — Instrucción de trabajo

Trabaja únicamente en la fase 1.

No implementes todavía detección automática avanzada de paradas, MTBF, MTTR, disponibilidad técnica, reentrenamiento de la línea base, modelos predictivos, alarmas automáticas ni cambios en la ecuación oficial.

Antes de modificar código:

1. identifica los archivos de frontend y backend relacionados con el dashboard;
2. identifica la tecnología utilizada;
3. documenta las consultas actuales;
4. identifica componentes duplicados;
5. identifica inconsistencias entre tarjetas, tablas y filtros;
6. propone una estructura de componentes modular;
7. realiza los cambios de forma incremental.

Al finalizar cada subfase, detente y presenta archivos modificados, componentes creados, funciones modificadas, pruebas, resultados y pendientes.

## Subfase 1.1 — Menú y estructura modular

Crear un menú principal con estas opciones:

```text
Resumen
Producción
Calidad
Eficiencia operacional
Eficiencia energética
Línea base ISO 50001
Impacto económico y ambiental
Confiabilidad y mantenimiento
Variables eléctricas
Estado del gateway
```

Requisitos:

- conservar el estilo visual actual;
- no duplicar consultas;
- mantener un filtro global de fechas;
- aplicar el mismo rango efectivo a todos los módulos;
- usar jornada productiva 06:00–06:00;
- mostrar el periodo efectivo evaluado;
- permitir navegación sin perder el filtro;
- no cargar todos los módulos a la vez si no es necesario;
- usar `Resumen` como pantalla inicial;
- dejar preparadas las rutas o componentes de `Índice Base 100` y `CUSUM`, mostrando `Pendiente de fase 3`;
- asegurar que el resumen tenga tarjetas para `Horas productivas` y `Horas de parada`.

No avances a la subfase 1.2 hasta terminar y probar la navegación.

## Subfase 1.2 — Módulo Producción

Crear una pantalla `Producción` con:

```text
Envases buenos
Envases malos
Producción total
Horas programadas
Horas reales de trabajo
Horas de parada
Producción buena por hora real
Producción total por hora real
Días de producción incluidos
```

Fórmulas:

```text
produccion_total = envases_buenos + envases_malos
horas_programadas = 24 horas por jornada completa válida
horas_parada = suma de paradas reportadas
horas_reales_trabajo = horas_programadas - horas_parada
productividad_buena_hora = envases_buenos / horas_reales_trabajo
productividad_total_hora = produccion_total / horas_reales_trabajo
```

Para periodos parciales usar la duración real. No usar el porcentaje de eficiencia suministrado como indicador principal.

Validaciones:

- no dividir por cero;
- no permitir horas negativas;
- no asumir cero minutos cuando la observación sea ambigua;
- mostrar `Dato pendiente` cuando una parada no tenga duración;
- no contar pérdida de datos eléctricos como parada en esta fase.

Agregar una tabla diaria con fecha, buenos, malos, total, turnos, horas programadas, minutos de parada reportados, horas reales, buenos por hora y observaciones.

## Subfase 1.3 — Extracción de horas de parada reportadas

Crear una función para extraer duraciones desde observaciones.

Ejemplos:

```text
"Se para la máquina 40 minutos" → 40 minutos
"Se para la máquina 75 minutos" → 75 minutos
"Se para a las 14:50 y se inicia a las 18:00" → 190 minutos
"Se para a las 16:15 y se reinicia a las 20:40" → 265 minutos
```

Si existen varias paradas, sumarlas.

Crear una estructura similar a:

```typescript
interface ReportedDowntime {
  date: string;
  startTime: string | null;
  endTime: string | null;
  durationMinutes: number | null;
  rawText: string;
  cause: string | null;
  status: "VALID" | "PENDING_REVIEW";
}
```

Reglas:

- conservar el texto original;
- no inventar duraciones;
- usar `null` si no puede determinarse;
- marcar el evento como `PENDING_REVIEW`;
- evitar duplicados;
- no implementar aún detección por corriente.

## Subfase 1.4 — Módulo Calidad

Crear una pantalla `Calidad` con:

```text
Envases buenos
Envases malos
Producción total
Eficiencia de calidad
Tasa de rechazo
Envases malos por 1.000 producidos
```

Fórmulas:

```text
eficiencia_calidad_pct = envases_buenos / produccion_total × 100
tasa_rechazo_pct = envases_malos / produccion_total × 100
rechazos_por_1000 = envases_malos / produccion_total × 1000
```

No promediar porcentajes diarios. Calcular siempre desde totales acumulados. Agregar tabla diaria y gráfica de buenos, malos y tasa de rechazo.

## Subfase 1.5 — Módulo Eficiencia operacional

Crear una pantalla `Eficiencia operacional` con:

```text
Horas programadas
Horas de parada reportadas
Horas reales de trabajo
Disponibilidad operacional reportada
Envases buenos por hora real
Producción total por hora real
Tasa de rechazo
```

Fórmulas:

```text
disponibilidad_operacional_reportada = horas_reales_trabajo / horas_programadas × 100
```

La eficiencia productiva debe calcularse así:

```text
eficiencia_produccion_real =
envases_buenos /
(horas_reales_trabajo × capacidad_nominal_envases_hora)
× 100
```

No calcular eficiencia productiva como `envases_buenos / envases_totales`; esa es eficiencia de calidad.

Buscar si existe `capacidad_nominal_envases_hora`. Si no existe, no inventarla: crear un parámetro configurable y mostrar `Pendiente de parametrización`.

Diferenciar claramente eficiencia de calidad, eficiencia productiva, productividad y disponibilidad.

## Subfase 1.6 — Resumen general

Actualizar `Resumen` para mostrar:

```text
Energía Aoki
Energía total planta
Producción buena
Producción total
Horas productivas o reales de trabajo
Horas de parada reportadas
Disponibilidad operacional reportada
Eficiencia de calidad
Productividad buena por hora
EnPI Aoki
Estado frente a línea base
Cobertura de datos
```

No duplicar cálculos. Cada tarjeta debe consumir servicios o funciones centrales. No mostrar `0` cuando el dato no existe; usar `No disponible`, `Pendiente de parametrización` o `Datos insuficientes`.


## Subfase 1.7 — Estado del gateway y temperatura

Actualizar el módulo `Estado del gateway` para mostrar:

```text
Temperatura actual del gateway
Temperatura mínima del periodo
Temperatura máxima del periodo
Temperatura promedio del periodo
Fecha y hora de la última lectura
Estado térmico
```

La temperatura debe provenir de la variable real del sistema Raspberry Pi o gateway, mantenerse en °C y no confundirse con la temperatura ambiental del proceso Aoki. Agregar una gráfica temporal para el rango seleccionado.

No inventar umbrales térmicos. Buscar primero si ya existen en configuración. Si no existen, crear parámetros configurables y mostrar `Pendiente de parametrización`. Usar estados `NORMAL`, `ADVERTENCIA`, `CRÍTICO` o `SIN_DATOS`.

La temperatura del gateway no entra en la ecuación oficial actual de la línea base; queda disponible para verificar estabilidad del nodo, calidad de datos y futuros análisis.

## Preparación de Índice Base 100 y CUSUM

Durante la fase 1 crear solamente componentes, rutas y contratos de datos para estas dos vistas dentro de `Línea base ISO 50001`. Mostrar `Pendiente de fase 3` mientras no exista cálculo validado.

En la fase 3 se deben usar estas fórmulas:

```text
indice_base_100 = energia_real / energia_esperada × 100
residuo_dia = energia_real_dia - energia_esperada_dia
CUSUM_dia = CUSUM_dia_anterior + residuo_dia
```

Interpretación:

```text
Base 100 = 100: desempeño igual a la línea base
Base 100 < 100: consumo menor al esperado
Base 100 > 100: consumo mayor al esperado
CUSUM creciente: sobreconsumo acumulado
CUSUM decreciente: ahorro acumulado
```

No calcular Base 100 ni CUSUM con días sin energía real, energía esperada o cobertura suficiente.

## Criterios de aceptación de la fase 1

1. Existe navegación modular.
2. El filtro se conserva entre módulos.
3. Todas las pantallas usan el mismo rango efectivo.
4. La jornada productiva es 06:00–06:00.
5. Buenos + malos = total.
6. La eficiencia de calidad se calcula desde totales.
7. Las horas de parada se extraen desde observaciones.
8. Las horas reales se calculan como programadas menos parada reportada.
9. La productividad usa horas reales.
10. La eficiencia productiva no se confunde con calidad.
11. No se inventa capacidad nominal.
12. No se implementan MTBF ni MTTR.
13. No se modifica la línea base oficial.
14. Los datos faltantes no se muestran como cero.
15. Existen pruebas unitarias para fórmulas y extracción de paradas.
16. El resumen muestra horas productivas y horas de parada.
17. El estado del gateway muestra temperatura real, estadísticas del periodo y última lectura.
18. Existe una gráfica temporal de temperatura del gateway.
19. Las vistas Índice Base 100 y CUSUM quedan preparadas sin cálculos improvisados.

# Instrucción inicial para Codex

Empieza únicamente con:

```text
SUBFASE 1.1 — Menú y estructura modular
```

No avances a Producción, Calidad o Eficiencia operacional hasta que la navegación haya sido revisada y aprobada.