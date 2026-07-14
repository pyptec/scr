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
16. Mostrar por separado horas productivas y horas de parada.
17. La temperatura del gateway debe provenir de la variable real del sistema y mostrarse en °C.
18. No usar temperatura del gateway en la línea base oficial sin reentrenamiento aprobado.
19. Base 100 y CUSUM deben usar energía real y esperada de los mismos días válidos.
20. No calcular Base 100 ni CUSUM con datos o cobertura insuficientes.

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
11. El módulo `Estado del gateway` debe mostrar temperatura actual, mínima, máxima, promedio y última lectura.
12. Incluir gráfica temporal de temperatura cuando existan datos históricos.
13. Mantener componentes separados para Índice Base 100 y CUSUM.
14. En fase 1 estos componentes deben quedar en estado `Pendiente de fase 3`, sin cálculos provisionales.

## Backend

1. Centralizar reglas de negocio.
2. Evitar fórmulas duplicadas entre frontend y backend.
3. Usar DTOs consistentes.
4. Validar zona horaria y límites inclusivos/exclusivos.
5. Registrar advertencias de calidad de datos.
6. Mantener trazabilidad del origen de cada indicador.
7. No alterar la base de datos sin justificarlo.
8. Si se requiere migración, documentarla.


## Reglas de Índice Base 100 y CUSUM

1. `indice_base_100 = energia_real / energia_esperada × 100`.
2. `residuo_dia = energia_real_dia - energia_esperada_dia`.
3. `CUSUM_dia = CUSUM_anterior + residuo_dia`.
4. Usar exactamente los mismos días válidos para energía real y esperada.
5. Mostrar de forma visible la convención de signos.
6. No reiniciar CUSUM dentro del rango salvo cambio del periodo o de versión de línea base.
7. No mezclar datos de versiones distintas del modelo.

## Pruebas

Cada subfase debe incluir pruebas unitarias, pruebas de integración cuando correspondan, datos nulos, divisiones por cero, periodos parciales, observaciones ambiguas, diferencias de zona horaria y validación de totales, temperatura del gateway, horas productivas, horas de parada y estados pendientes de Base 100/CUSUM.

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

## Reglas específicas de la fase 2 — Estados eléctricos y paradas

1. Usar únicamente `ME337_1` para detectar el estado operativo de Aoki.
2. `ME337_2` es el totalizador de planta y no debe usarse para inferir paradas de Aoki.
3. Clasificar cada intervalo como `PRODUCTIVE`, `IDLE`, `OFF` o `NO_DATA`.
4. Los umbrales preliminares de corriente son:
   - `I < 27.38 A` → `OFF`;
   - `27.38 A ≤ I < 54.58 A` → `IDLE`;
   - `I ≥ 54.58 A` → `PRODUCTIVE`.
5. Los umbrales deben ser configurables, versionados y visibles en la trazabilidad del cálculo.
6. Usar potencia activa como señal secundaria de validación, no como sustituto automático de la corriente.
7. Exigir al menos dos muestras consecutivas o 20 minutos para confirmar un cambio de estado.
8. Una muestra aislada no crea una parada.
9. Un hueco de datos nunca se clasifica como apagado.
10. Los intervalos mayores al límite de cobertura se clasifican `NO_DATA`.
11. No interpolar huecos largos para calcular horas productivas.
12. Ordenar timestamps y eliminar duplicados antes de clasificar estados.
13. Conservar el valor original, timestamp, variable, unidad y criterio de clasificación.
14. Agrupar únicamente intervalos consecutivos válidos para construir eventos.
15. No considerar todo evento no productivo como falla correctiva.
16. Los eventos sin causa deben quedar `PENDING_REVIEW` o `SIN_CLASIFICAR`.
17. Conciliar eventos eléctricos con observaciones usando tolerancia configurable.
18. No duplicar una parada reportada y detectada.
19. Conservar duración reportada y duración eléctrica por separado.
20. Calcular y mostrar por separado:
   - horas productivas;
   - horas de espera;
   - horas apagado;
   - horas sin datos;
   - cobertura;
   - eventos reportados;
   - eventos detectados.
21. Validar que la suma de estados coincida con el periodo dentro de una tolerancia de un intervalo.
22. Las horas productivas detectadas serán la variable operacional utilizada por la línea base, una vez validadas.
23. No sustituir horas productivas faltantes por 24 horas.
24. No calcular MTBF, MTTR ni disponibilidad técnica definitiva en la fase 2.
25. No modificar la ecuación oficial de la línea base durante la fase 2.
26. Añadir pruebas para cambios de estado, rebotes, muestras aisladas, huecos, duplicados, periodos parciales y conciliación de eventos.
27. El dashboard debe mostrar claramente cuándo un indicador es `Detectado`, `Reportado`, `Conciliado`, `Pendiente de revisión` o `Sin datos`.
28. La gráfica de estados debe incluir corriente, umbrales, estado clasificado y eventos reportados.
29. No usar colores sin leyenda ni ocultar los criterios de clasificación.
30. Al terminar cada subfase de la fase 2, detenerse y esperar autorización.

## Base de datos histórica local y protección de la Raspberry

1. La base local contiene datos históricos reales del 1 de mayo al 25 de junio de 2026 y se usa únicamente para pruebas.
2. La Raspberry `192.168.2.124` es una fuente de solo lectura durante estas fases.
3. La única copia autorizada es Raspberry → Windows.
4. Está prohibido copiar, desplegar o sincronizar la base de Windows hacia la Raspberry.
5. No ejecutar comandos remotos que escriban, borren, renombren, migren o reemplacen archivos en `/home/pi/SAMEE200/scr/data`.
6. No usar sincronización bidireccional ni opciones destructivas como `rsync --delete`.
7. No ejecutar migraciones de esquema sobre la Raspberry.
8. Todas las pruebas y modificaciones deben realizarse en el proyecto local de Windows.
9. Antes de modificar una base local, crear una copia desechable o respaldo.
10. Etiquetar el conjunto de datos como `DATOS_HISTORICOS_DE_PRUEBA` y no presentarlo como telemetría actual.
11. Si una operación puede afectar la Raspberry, detenerse y solicitar autorización expresa.
12. Ningún cambio local autoriza automáticamente un despliegue al gateway.