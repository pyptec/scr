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

# FASE 2 — Estados eléctricos y detección de paradas

## Objetivo

Usar las variables eléctricas de `ME337_1` para determinar las horas productivas reales de Aoki, las horas de espera, las horas apagadas, las horas sin datos y las paradas no reportadas. Esta fase debe complementar, no reemplazar, las paradas extraídas de las observaciones de producción.

Trabaja una sola subfase a la vez. No avances sin autorización. No calcules todavía MTBF, MTTR ni disponibilidad técnica definitiva; esos indicadores corresponden a la fase 4.

## Subfase 2.1 — Auditoría de variables eléctricas

Identificar en backend, base de datos y catálogos las variables reales de `ME337_1` necesarias para clasificar estados:

```text
Corriente trifásica promedio L1-L2-L3
Potencia activa total
Energía activa, si existe y es confiable
Timestamp
Unidad
Calidad del dato
```

Documentar:

- identificador de cada variable;
- nombre y alias;
- unidad;
- frecuencia de muestreo;
- signo de potencia;
- huecos, duplicados y valores fuera de orden;
- cobertura diaria.

No implementar clasificación hasta validar qué variables corresponden realmente a Aoki.

## Subfase 2.2 — Preprocesamiento y calidad de datos

Crear un servicio central que:

- ordene por timestamp;
- elimine duplicados exactos;
- identifique valores nulos;
- marque intervalos fuera de orden;
- calcule `Δt` real entre muestras;
- marque como `SIN_DATOS` los intervalos mayores al máximo permitido;
- no rellene huecos como si fueran operación;
- conserve trazabilidad del dato original.

Usar inicialmente:

```text
intervalo esperado ≈ 10 minutos
persistencia mínima de estado = 2 muestras consecutivas o 20 minutos
```

El límite máximo de hueco debe ser configurable. Como valor inicial puede usarse 20 minutos, pero debe quedar documentado.

## Subfase 2.2B — Reconstrucción trazable de la línea de consumo energético

Esta subfase se ejecuta después del preprocesamiento de datos y antes de clasificar estados. Su objetivo es reconstruir, cuando sea técnicamente posible, la serie de energía consumida por intervalo aunque una de las variables eléctricas falle.

La reconstrucción nunca debe inventar consumo. Un intervalo solo puede recuperarse si existe otra señal válida y físicamente coherente. Si no existe información suficiente, debe conservarse como `NO_DATA`.

### Variables disponibles

Usar para `ME337_1`, proceso Aoki:

```text
unit_id 54 = corriente trifásica promedio, A
unit_id 61 = potencia activa total, kW
unit_id 100 = energía activa positiva acumulada, kWh
```

La prioridad para reconstruir energía por intervalo es:

1. delta válido del acumulador `unit_id 100`;
2. integración de potencia `unit_id 61`;
3. estimación excepcional mediante corriente `unit_id 54`, únicamente si existe un modelo eléctrico validado;
4. `NO_DATA` cuando ninguna fuente sea suficiente.

### Método principal: delta del acumulador

Para cada par consecutivo de lecturas válidas:

```text
energia_intervalo_kWh = energia_final_kWh - energia_inicial_kWh
```

Calcular también:

```text
potencia_media_intervalo_kW = energia_intervalo_kWh / delta_horas
```

Aceptar el delta solo cuando:

- ambos valores sean numéricos;
- `delta_horas > 0`;
- el intervalo no supere el máximo configurable;
- el delta no sea negativo;
- el consumo sea físicamente posible;
- no se detecte reinicio, salto o cambio de escala del acumulador.

Si el acumulador disminuye, marcar:

```text
ACCUMULATOR_RESET
```

No aplicar valor absoluto a un delta negativo.

### Método alternativo: integración de potencia

Cuando el acumulador sea inválido, esté ausente o presente reinicio, usar potencia activa válida:

```text
energia_intervalo_kWh =
((potencia_inicio_kW + potencia_fin_kW) / 2) × delta_horas
```

Usar integración trapezoidal cuando existan ambas lecturas. Si solo existe una potencia válida y el intervalo está dentro del máximo atribuible, se puede usar integración rectangular, pero debe quedar marcada como estimación de menor calidad.

No asumir intervalos fijos de diez minutos. Usar siempre `delta_horas` calculado desde timestamps reales.

### Uso de corriente como último recurso

No convertir corriente directamente a energía con una constante arbitraria.

Solo permitir estimación por corriente si se construye y valida previamente una relación con potencia usando intervalos donde ambas señales sean válidas, por ejemplo:

```text
potencia_estimada_kW = f(corriente_promedio_A)
```

El modelo debe documentar:

- periodo de calibración;
- cantidad de muestras;
- ecuación;
- R², RMSE y error relativo;
- rango válido de corriente;
- versión del modelo.

Si el modelo no alcanza la calidad mínima aprobada, la corriente se usa únicamente para clasificar estados y el intervalo energético permanece `NO_DATA`.

### Jerarquía y calidad del dato

Cada intervalo debe guardar el origen de la energía:

```typescript
interface AokiEnergyInterval {
  startUtc: string;
  endUtc: string;
  durationSeconds: number;
  energyKWh: number | null;
  averagePowerKW: number | null;
  source:
    | "ACCUMULATOR_DELTA"
    | "POWER_TRAPEZOIDAL"
    | "POWER_RECTANGULAR"
    | "CURRENT_MODEL"
    | "NO_DATA";
  quality:
    | "MEASURED"
    | "RECONSTRUCTED_HIGH"
    | "RECONSTRUCTED_MEDIUM"
    | "RECONSTRUCTED_LOW"
    | "INVALID"
    | "NO_DATA";
  reason: string | null;
}
```

Reglas de calidad:

```text
ACCUMULATOR_DELTA válido
→ MEASURED

POWER_TRAPEZOIDAL
→ RECONSTRUCTED_HIGH

POWER_RECTANGULAR
→ RECONSTRUCTED_MEDIUM

CURRENT_MODEL validado
→ RECONSTRUCTED_LOW

sin fuente suficiente
→ NO_DATA
```

### Validación cruzada

Cuando acumulador y potencia estén disponibles, comparar:

```text
potencia_media_desde_energia = delta_kWh / delta_horas
```

contra la potencia media medida.

Calcular:

```text
error_pct =
abs(potencia_media_desde_energia - potencia_media_medida)
/ potencia_media_medida × 100
```

Si el error supera una tolerancia configurable, marcar `INCONSISTENT_ENERGY_SOURCE` y no aceptar silenciosamente el dato.

### Tratamiento de huecos

Un hueco de comunicación no debe reconstruirse por interpolación lineal entre dos acumulados si no puede demostrarse cómo se distribuyó el consumo dentro del hueco.

Se permite recuperar el consumo total del hueco mediante delta acumulado válido, pero:

- el total se asigna al periodo completo del hueco;
- no se inventa la forma minuto a minuto;
- no se usa ese hueco para detectar con precisión paradas o estados internos;
- debe marcarse como `AGGREGATED_GAP_ENERGY`.

Si el hueco supera el máximo permitido para análisis de estados, sigue siendo `NO_DATA` para estados aunque tenga energía total recuperable.

### Serie energética reconstruida

Generar una serie continua por intervalo con:

```text
energía medida
energía reconstruida
energía no recuperable
potencia media del intervalo
fuente utilizada
calidad
motivo de sustitución
```

Calcular por jornada:

```text
energia_medida_kWh
energia_reconstruida_kWh
energia_no_recuperable_kWh
porcentaje_reconstruido
porcentaje_NO_DATA
intervalos_por_fuente
```

No mezclar energía reconstruida con medida sin mostrar su proporción.

### Uso en dashboard y línea base

La energía real del periodo puede usar intervalos medidos y reconstruidos de calidad alta o media.

Los intervalos reconstruidos mediante corriente solo podrán entrar en la línea base con autorización expresa y después de validar el modelo.

Mostrar en el dashboard:

```text
Energía total calculada
Energía medida directamente
Energía reconstruida
Cobertura energética
Porcentaje reconstruido
Intervalos NO_DATA
```

Si el porcentaje reconstruido supera un umbral configurable, clasificar el resultado como `ESTIMACIÓN` y no como medición completa.

### Pruebas mínimas

Agregar pruebas para:

1. delta normal del acumulador;
2. reinicio del acumulador;
3. salto físicamente imposible;
4. reconstrucción trapezoidal con potencia;
5. reconstrucción rectangular con una sola potencia;
6. ausencia de acumulador con potencia válida;
7. ausencia de potencia con acumulador válido;
8. ambas señales inválidas;
9. hueco con delta acumulado recuperable;
10. hueco sin información suficiente;
11. comparación entre potencia medida y derivada del acumulador;
12. trazabilidad de fuente y calidad;
13. no conversión automática de corriente a energía;
14. conservación de `NO_DATA` cuando no es posible reconstruir.

### Entrega de la subfase 2.2B

Presentar:

1. archivos modificados;
2. algoritmo de jerarquía de fuentes;
3. reglas para reinicios y saltos;
4. fórmula de integración de potencia;
5. porcentaje de energía medida y reconstruida;
6. intervalos que permanecen `NO_DATA`;
7. resultados para mayo y junio de 2026;
8. validación cruzada acumulador-potencia;
9. pruebas ejecutadas;
10. limitaciones pendientes.

Detenerse al finalizar. No avanzar a la subfase 2.3 sin autorización.

## Subfase 2.3 — Clasificación de estados eléctricos de Aoki

La subfase 2.2 debe estar aprobada antes de iniciar esta subfase.

Trabaja únicamente en la subfase 2.3. No avances todavía a conciliación de paradas, MTBF, MTTR, disponibilidad técnica, reentrenamiento de línea base ni cambios en el modelo energético oficial.

### Contexto validado

Usar únicamente:

```text
gateway_id = 10
device_id = 24
```

Variables:

```text
unit_id = 54
corriente trifásica promedio
unidad = A
señal primaria
```

```text
unit_id = 61
potencia activa total
unidad = kW
señal secundaria
```

La serie de entrada debe provenir de la subfase 2.2 y contener timestamps ordenados, valores numéricos validados, duplicados controlados, intervalos reales, segmentos `NO_DATA`, hora local `America/Bogota`, jornada 06:00–06:00 y potencia en kW sin dividir entre 1.000.

### Objetivo

Clasificar cada intervalo válido de `ME337_1` como:

```text
PRODUCTIVE
IDLE
OFF
NO_DATA
```

La clasificación debe ser trazable, configurable y resistente a ruido o muestras aisladas.

### Umbrales preliminares

```text
I < 27.38 A
→ OFF

27.38 A <= I < 54.58 A
→ IDLE

I >= 54.58 A
→ PRODUCTIVE
```

Centros estadísticos:

```text
OFF: 9.02 A
IDLE: 45.73 A
PRODUCTIVE: 63.42 A
```

Centralizar los valores en una configuración versionada:

```typescript
interface AokiStateThresholds {
  offIdleCurrentA: number;
  idleProductiveCurrentA: number;
  minimumPersistenceMinutes: number;
  minimumConsecutiveSamples: number;
  version: string;
}
```

Valores iniciales:

```text
offIdleCurrentA = 27.38
idleProductiveCurrentA = 54.58
minimumPersistenceMinutes = 20
minimumConsecutiveSamples = 2
```

### Reglas de clasificación

```text
currentAvgA < 27.38
→ candidato OFF

27.38 <= currentAvgA < 54.58
→ candidato IDLE

currentAvgA >= 54.58
→ candidato PRODUCTIVE

corriente inválida o hueco
→ NO_DATA
```

No clasificar huecos como `OFF`.

### Persistencia

No aceptar cambios de estado por una sola muestra aislada.

Confirmar un cambio cuando se cumpla al menos una condición:

```text
2 muestras consecutivas
```

o:

```text
20 minutos acumulados en el nuevo estado
```

Usar `Δt` real. Si el candidato no cumple persistencia, conservar el estado anterior. No extender muestras más allá del máximo atribuible definido en la subfase 2.2.

### Validación secundaria con potencia

La corriente es la señal primaria. La potencia solo genera advertencias de coherencia.

Ejemplos:

```text
corriente indica PRODUCTIVE y potencia cercana a cero
→ INCONSISTENT_SIGNAL

corriente indica OFF y potencia elevada
→ INCONSISTENT_SIGNAL
```

No cambiar automáticamente el estado solo por potencia.

Usar estas banderas:

```text
VALID_STATE
PARTIAL_SIGNAL
INCONSISTENT_SIGNAL
NO_DATA
```

### Segmentos continuos

Crear:

```typescript
interface AokiStateSegment {
  state: "PRODUCTIVE" | "IDLE" | "OFF" | "NO_DATA";
  startUtc: string;
  endUtc: string;
  startLocal: string;
  endLocal: string;
  productionDate: string;
  durationSeconds: number;
  sampleCount: number;
  averageCurrentA: number | null;
  averagePowerKW: number | null;
  quality:
    | "VALID_STATE"
    | "PARTIAL_SIGNAL"
    | "INCONSISTENT_SIGNAL"
    | "NO_DATA";
  thresholdVersion: string;
}
```

Reglas:

- unir intervalos consecutivos del mismo estado;
- no unir segmentos separados por `NO_DATA`;
- dividir segmentos que crucen las 06:00;
- conservar la jornada productiva;
- mantener trazabilidad del umbral usado.

### Resumen diario

Calcular por jornada:

```text
productiveHours
idleHours
offHours
noDataHours
productivePct
idlePct
offPct
noDataPct
stateTransitions
inconsistentSegments
```

Validar:

```text
productiveHours
+ idleHours
+ offHours
+ noDataHours
≈ scheduledHours
```

Para una jornada completa:

```text
scheduledHours = 24
```

Para periodos parciales, usar la duración real.

No calcular todavía disponibilidad técnica.

### Salida para línea base

Exponer `productiveHours` por jornada para uso posterior en:

```text
E_esperada =
514.50
+ 0.005018 × envases_buenos
+ 16.5198 × productiveHours
```

No modificar todavía la ecuación oficial ni sustituir horas faltantes por 24.

### Actualización mínima del dashboard

Mostrar provisionalmente:

- horas productivas;
- horas de espera;
- horas apagado;
- horas sin datos;
- cobertura;
- segmentos con señal inconsistente.

Agregar una gráfica diaria apilada con:

```text
PRODUCTIVE
IDLE
OFF
NO_DATA
```

Mantener el estilo visual actual. No implementar tabla de fallas, MTBF ni MTTR.

### Pruebas mínimas

Agregar pruebas para:

1. corriente menor a 27.38 A;
2. corriente entre 27.38 y 54.58 A;
3. corriente mayor o igual a 54.58 A;
4. una sola muestra aislada;
5. dos muestras consecutivas;
6. cambio sostenido durante 20 minutos;
7. hueco de datos;
8. segmento que cruza las 06:00;
9. jornada parcial;
10. corriente válida sin potencia;
11. potencia incoherente con corriente;
12. suma de horas por estado;
13. no unión de estados separados por `NO_DATA`.

### Entrega

Presentar:

1. archivos modificados;
2. función de clasificación;
3. lógica de persistencia;
4. configuración y versión de umbrales;
5. uso de potencia como validación;
6. estructura de segmentos;
7. resumen diario;
8. resultados sobre mayo y junio de 2026;
9. horas por estado;
10. segmentos inconsistentes;
11. pruebas ejecutadas;
12. limitaciones pendientes.

Detenerse al finalizar. No avanzar a la subfase 2.4 sin autorización.


## Subfase 2.3B — Ajuste del dashboard con los datos históricos disponibles

Esta subfase se ejecuta después de la clasificación preliminar de estados de la subfase 2.3 y antes de cualquier reentrenamiento con datos nuevos.

Trabaja únicamente en esta subfase. No avances todavía a MTBF, MTTR, disponibilidad técnica definitiva, reconstrucción productiva de huecos ni reentrenamiento de la línea base.

### Decisión metodológica vigente

Los datos históricos actuales permiten organizar, visualizar, auditar y documentar el comportamiento eléctrico y productivo del proceso, pero no permiten demostrar todavía una relación suficientemente fuerte entre producción diaria y horas clasificadas como `PRODUCTIVE`.

Resultados observados:

```text
R² producción total diaria vs horas PRODUCTIVE:
- todas las jornadas: 0.0285
- jornadas con cobertura >= 98 %: 0.0245
- jornadas con cobertura 100 % y producción positiva: 0.0719
```

Por tanto:

- no construir todavía una productividad de referencia a partir de las horas `PRODUCTIVE`;
- no usar producción para rellenar automáticamente segmentos `NO_DATA`;
- no ajustar horas productivas para forzar concordancia con producción;
- no modificar la ecuación oficial de línea base;
- no declarar que los estados eléctricos equivalen directamente al estado productivo real de Aoki;
- conservar los resultados actuales como clasificación eléctrica preliminar.

La medición puede incluir cargas auxiliares o compartidas del proceso. Esta limitación debe documentarse en el dashboard y en los resultados técnicos.

### Objetivo

Continuar ajustando el dashboard con la base histórica local para:

- corregir menús y navegación;
- consolidar producción, calidad, energía y estados eléctricos;
- mostrar cobertura y calidad de datos;
- diferenciar datos medidos, reconstruidos y faltantes;
- dejar preparada la arquitectura para reentrenamiento posterior con datos nuevos;
- evitar conclusiones no demostradas.

### Tratamiento de estados eléctricos

Mantener la clasificación actual:

```text
PRODUCTIVE
IDLE
OFF
NO_DATA
```

pero presentarla como:

```text
clasificación eléctrica preliminar
```

Agregar una nota metodológica visible:

```text
Los estados eléctricos se derivan de corriente y potencia del sistema medido.
No equivalen necesariamente al estado productivo real de Aoki.
La relación con producción debe revalidarse con datos nuevos y medición mejor aislada.
```

No renombrar todavía los estados internos del backend si eso rompe compatibilidad, pero sí aclarar su significado en la interfaz.

### Tratamiento de NO_DATA

Para esta subfase:

- conservar `NO_DATA` cuando falte evidencia;
- no completar huecos con producción;
- no asignar valores fijos;
- permitir únicamente la reconstrucción energética ya validada en la subfase 2.2B;
- distinguir claramente cobertura energética y cobertura de estados;
- mostrar cuánto tiempo permanece sin clasificación.

### Uso de producción

La producción debe mantenerse como módulo independiente con:

```text
envases buenos
envases malos
producción total
horas programadas
paradas reportadas
horas reales reportadas
productividad buena por hora reportada
productividad total por hora reportada
calidad
```

Puede compararse visualmente con energía y estados eléctricos, pero no debe usarse todavía como variable de imputación o reconstrucción automática.

### Ajustes requeridos en Eficiencia operacional

Mostrar:

```text
Horas clasificadas como PRODUCTIVE
Horas clasificadas como IDLE
Horas clasificadas como OFF
Horas NO_DATA
Cobertura de estados
Segmentos inconsistentes
Horas de parada reportadas
Horas reales reportadas
```

Separar claramente:

```text
operación reportada
clasificación eléctrica preliminar
```

No mezclar ambas como si fueran la misma fuente.

### Ajustes requeridos en Eficiencia energética

Mantener:

```text
Energía total calculada
Energía medida directamente
Energía reconstruida
Cobertura energética
Porcentaje reconstruido
Intervalos NO_DATA
```

Usar la jerarquía ya validada:

```text
ACCUMULATOR_DELTA
POWER_TRAPEZOIDAL
POWER_RECTANGULAR
NO_DATA
```

No usar corriente para estimar energía mientras no exista un modelo aprobado.

### Ajustes requeridos en Línea base

Mantener la ecuación oficial sin cambios:

```text
E_esperada_kWh =
514.50
+ 0.005018 × envases_buenos
+ 16.5198 × horas_productivas
```

Pero agregar una advertencia metodológica:

```text
La evaluación actual usa horas productivas clasificadas eléctricamente de forma preliminar.
Los resultados deben considerarse exploratorios hasta revalidar la relación entre estados eléctricos y producción con datos nuevos.
```

La clasificación de mejora o sobreconsumo debe mostrarse como:

```text
RESULTADO_PRELIMINAR
```

cuando dependa de horas productivas todavía no revalidadas.

### Preparación para datos nuevos

Dejar configurada la arquitectura para que, cuando existan nuevos datos, sea posible:

1. recalibrar umbrales de corriente y potencia;
2. separar mejor cargas compartidas;
3. incorporar señal de ciclo, PLC o entrada digital si se dispone;
4. evaluar nuevamente producción vs horas productivas;
5. reentrenar la línea base;
6. recalcular Índice Base 100 y CUSUM;
7. comparar el modelo histórico con el modelo actualizado.

No ejecutar estas tareas todavía.

### Validaciones mínimas

Verificar:

1. que todos los módulos usen el mismo rango 06:00–06:00;
2. que producción y energía usen las mismas fechas efectivas;
3. que los estados eléctricos muestren cobertura;
4. que `NO_DATA` no se convierta en cero;
5. que energía medida y reconstruida estén separadas;
6. que el dashboard no presente estados eléctricos como verdad productiva;
7. que la línea base indique carácter preliminar;
8. que no se use producción para imputar horas;
9. que no se modifique la base local maestra sin respaldo;
10. que no exista ninguna escritura hacia la Raspberry.

### Entrega

Presentar:

1. archivos modificados;
2. menús y vistas corregidos;
3. textos metodológicos agregados;
4. separación entre operación reportada y clasificación eléctrica;
5. cobertura energética y cobertura de estados;
6. resultados preliminares del periodo mayo-junio de 2026;
7. pruebas ejecutadas;
8. limitaciones pendientes;
9. estructura preparada para reentrenamiento futuro.

Detenerse al finalizar. No avanzar a la subfase 2.4 ni reentrenar modelos sin autorización.


## Subfase 2.4 — Cálculo de horas por estado

Por jornada productiva 06:00–06:00 y por periodo seleccionado calcular:

```text
horas_productivas
horas_espera
horas_apagado
horas_sin_datos
horas_con_datos
cobertura_pct
```

Validar:

```text
horas_productivas
+ horas_espera
+ horas_apagado
+ horas_sin_datos
≈ horas_totales_periodo
```

Permitir una tolerancia máxima equivalente a un intervalo de muestreo.

Las horas productivas calculadas en esta fase serán las usadas posteriormente por la línea base oficial. No sustituirlas por 24 horas ni por horas programadas.

## Subfase 2.5 — Detección de eventos no productivos

Agrupar intervalos consecutivos `IDLE` u `OFF` en eventos.

Cada evento debe incluir:

```typescript
interface ElectricalDowntimeEvent {
  start: string;
  end: string;
  durationMinutes: number;
  dominantState: "IDLE" | "OFF";
  minimumCurrentA: number | null;
  averageCurrentA: number | null;
  averagePowerKW: number | null;
  detectedBy: "ME337_1";
  status: "DETECTED" | "PENDING_REVIEW" | "VALIDATED" | "DISCARDED";
}
```

No contar como evento:

- una muestra aislada;
- huecos de comunicación;
- intervalos `NO_DATA`;
- cambios de estado menores que la persistencia mínima.

Mostrar por separado:

```text
Número de eventos detectados
Duración total de espera
Duración total apagado
Duración total no productiva
```

## Subfase 2.6 — Conciliación con paradas reportadas

Comparar los eventos eléctricos con las paradas extraídas en la fase 1. Usar una tolerancia temporal configurable, inicialmente ±20 minutos.

Clasificar cada evento como:

```text
REPORTADA_Y_DETECTADA
SOLO_REPORTADA
SOLO_DETECTADA
SIN_DATOS
```

Evitar duplicar una misma parada. Conservar siempre:

- texto original de la observación;
- duración reportada;
- duración eléctrica;
- diferencia entre ambas;
- causa reportada;
- estado de validación.

No convertir automáticamente un evento eléctrico en falla correctiva. Los eventos sin causa deben quedar `SIN_CLASIFICAR` o `PENDING_REVIEW`.

## Subfase 2.7 — Actualización de módulos del dashboard

Actualizar `Producción`, `Eficiencia operacional`, `Resumen` y `Variables eléctricas` para mostrar:

```text
Horas productivas reales
Horas de espera
Horas apagado
Horas sin datos
Horas de parada reportadas
Horas de parada detectadas
Eventos solo reportados
Eventos solo detectados
Cobertura de datos
```

La tarjeta `Horas reales de trabajo` de la fase 1 debe evolucionar a `Horas productivas detectadas eléctricamente` cuando la fase 2 esté validada.

Agregar:

- gráfica temporal de corriente de `ME337_1`;
- líneas de umbral;
- bandas o colores por estado;
- marcadores de paradas reportadas;
- tabla diaria de horas por estado;
- tabla de eventos conciliados.

No cambiar todavía la ecuación oficial de línea base.

## Criterios de aceptación de la fase 2

1. Las variables eléctricas de Aoki están identificadas y documentadas.
2. Solo se usa `ME337_1` para detectar estados de Aoki.
3. Los huecos se clasifican como `NO_DATA`, no como apagado.
4. Una muestra aislada no crea una parada.
5. Los umbrales son configurables y versionados.
6. Se calculan horas productivas, espera, apagado y sin datos.
7. La suma de horas coincide con el periodo dentro de tolerancia.
8. Se generan eventos no productivos sin duplicados.
9. Se concilian eventos eléctricos y reportados.
10. Las horas productivas quedan disponibles para la línea base.
11. No se calculan todavía MTBF ni MTTR definitivos.
12. Existen pruebas unitarias e integración para cambios de estado, huecos, duplicados y conciliación.

# Instrucción vigente para continuar la fase 2

Las subfases 2.1 y 2.2 deben estar aprobadas. El siguiente trabajo autorizado es únicamente:

```text
SUBFASE 2.3 — Clasificación de estados eléctricos de Aoki
```

No avanzar a la subfase 2.4, conciliación de paradas, MTBF, MTTR ni disponibilidad técnica hasta recibir autorización.


---

# Sincronización de la base de datos real desde la Raspberry Pi

Antes de validar resultados de las subfases 2.2 y 2.3, copiar la base SQLite desplegada en la Raspberry Pi al workspace local de Windows.

## Origen

```text
Host Raspberry Pi: 192.168.2.124
Usuario SSH: pi
Directorio remoto: /home/pi/SAMEE200/scr/data
```

## Destino local

```text
D:\promate\raspberry\modbus\medidorplataformaDanilo\lps_samee200\scr\data
```

Verificar primero el nombre exacto del archivo de base de datos en la Raspberry Pi:

```bash
ssh pi@192.168.2.124 "ls -lh /home/pi/SAMEE200/scr/data"
```

Desde PowerShell en Windows, crear el directorio de destino si no existe:

```powershell
New-Item -ItemType Directory -Force -Path "D:\promate\raspberry\modbus\medidorplataformaDanilo\lps_samee200\scr\data"
```

Copiar una base concreta, por ejemplo `samee200.db`:

```powershell
scp pi@192.168.2.124:/home/pi/SAMEE200/scr/data/samee200.db "D:\promate\raspberry\modbus\medidorplataformaDanilo\lps_samee200\scr\data\samee200.db"
```

Si el nombre del archivo es diferente, reemplazar `samee200.db` por el nombre encontrado con `ls`.

Para copiar todos los archivos del directorio remoto:

```powershell
scp -r pi@192.168.2.124:/home/pi/SAMEE200/scr/data/* "D:\promate\raspberry\modbus\medidorplataformaDanilo\lps_samee200\scr\data\"
```

## Copia consistente de SQLite

No copiar una base SQLite mientras el servicio está escribiendo activamente sin verificar consistencia. Preferir uno de estos métodos:

### Método recomendado: respaldo SQLite en la Raspberry Pi

```bash
ssh pi@192.168.2.124 "sqlite3 /home/pi/SAMEE200/scr/data/samee200.db '.backup /home/pi/SAMEE200/scr/data/samee200_backup.db'"
```

Después copiar el respaldo:

```powershell
scp pi@192.168.2.124:/home/pi/SAMEE200/scr/data/samee200_backup.db "D:\promate\raspberry\modbus\medidorplataformaDanilo\lps_samee200\scr\data\samee200.db"
```

### Si la base usa WAL

Comprobar si existen:

```text
samee200.db
samee200.db-wal
samee200.db-shm
```

No copiar únicamente el archivo `.db` si existe un WAL activo. Crear primero el respaldo con `.backup` o detener temporalmente el servicio que escribe la base.

## Verificación local

Después de copiar:

```powershell
Get-Item "D:\promate\raspberry\modbus\medidorplataformaDanilo\lps_samee200\scr\data\samee200.db"
```

Verificar integridad con SQLite:

```powershell
sqlite3 "D:\promate\raspberry\modbus\medidorplataformaDanilo\lps_samee200\scr\data\samee200.db" "PRAGMA integrity_check;"
```

El resultado esperado es:

```text
ok
```

## Reglas para Codex

1. No sobrescribir la única copia local sin crear respaldo.
2. Antes de importar, renombrar la base anterior con fecha y hora.
3. No confirmar métricas contra el CSV si la base real ya está disponible.
4. Validar las tablas, columnas y rango temporal de la base copiada.
5. Verificar que existan `gateway_id=10`, `device_id=24` y `unit_id` 54, 61 y 100.
6. Ejecutar `PRAGMA integrity_check` antes de usar la base.
7. No modificar la base copiada durante auditoría; abrirla en modo lectura.
8. Documentar fecha de copia, tamaño, hash y periodo de datos.
9. Si el proyecto utiliza `src` y no `scr`, no cambiar rutas silenciosamente: confirmar la ruta real antes de editar configuración.
10. Detenerse y reportar si la base no existe, está bloqueada, falla la integridad o no contiene los IDs esperados.

## Entrega esperada de Codex

Antes de continuar con clasificación de estados, informar:

- nombre exacto de la base copiada;
- ruta remota y ruta local;
- fecha y tamaño del archivo;
- resultado de `PRAGMA integrity_check`;
- tablas relevantes encontradas;
- rango mínimo y máximo de `timestamp_utc`;
- conteos para `unit_id` 54, 61 y 100;
- diferencias frente al CSV histórico;
- advertencias de WAL, bloqueos o rutas inconsistentes.

# Restricción crítica — Base de datos local de pruebas

La base de datos utilizada en este proyecto es una copia local de pruebas que contiene datos reales históricos del proceso entre el 1 de mayo y el 25 de junio de 2026.

Su finalidad exclusiva es:

- validar consultas;
- corregir cálculos;
- organizar y probar los menús del dashboard;
- comprobar producción, calidad, horas productivas, paradas y línea base;
- desarrollar y probar la interfaz en Visual Studio Code sobre Windows.

## Dirección permitida de copia

La única dirección permitida es:

```text
Raspberry Pi → Windows
```

Origen de solo lectura:

```text
pi@192.168.2.124:/home/pi/SAMEE200/scr/data
```

Destino local de desarrollo:

```text
D:\promate\raspberry\modbus\medidorplataformaDanilo\lps_samee200\scr\data
```

## Prohibiciones

Codex no debe:

- copiar la base local hacia la Raspberry;
- ejecutar `scp` desde Windows hacia `192.168.2.124`;
- reemplazar la base existente en la Raspberry;
- escribir sobre `/home/pi/SAMEE200/scr/data`;
- modificar datos del gateway;
- ejecutar migraciones sobre la Raspberry;
- borrar, renombrar o mover archivos remotos;
- usar sincronización bidireccional;
- usar `rsync --delete`;
- desplegar automáticamente la base de pruebas;
- asumir que la base local es la base productiva actual.

La Raspberry debe tratarse como fuente remota de solo lectura.

## Trabajo local

Todos los cambios de esta fase deben ejecutarse únicamente sobre:

```text
D:\promate\raspberry\modbus\medidorplataformaDanilo\lps_samee200
```

La base local puede:

- copiarse con otro nombre;
- abrirse en modo lectura;
- utilizarse para pruebas automatizadas;
- restaurarse desde una copia limpia;
- modificarse únicamente si se crea previamente una copia desechable específica para pruebas.

No modificar directamente el archivo maestro de prueba sin crear respaldo.

## Identificación del conjunto de datos

Registrar en el dashboard o en la configuración de desarrollo:

```text
Tipo de base: PRUEBAS
Origen: copia histórica del SAMEE200
Periodo de datos: 2026-05-01 a 2026-06-25
Uso: desarrollo y validación de menús y cálculos
```

No presentar estos datos como mediciones actuales. El indicador de datos recientes debe distinguir entre:

```text
DATOS_HISTORICOS_DE_PRUEBA
DATOS_RECIENTES
SIN_DATOS_RECIENTES
```

## Confirmación obligatoria antes de cualquier operación remota

Si una instrucción puede escribir en la Raspberry, Codex debe detenerse y advertir:

```text
Operación bloqueada: la Raspberry es de solo lectura durante el desarrollo con la base de pruebas.
```

No continuar sin autorización expresa del usuario.