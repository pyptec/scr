# Catálogo técnico de señales CAN J1939 — SAMEE100-ALKOSTO

Fecha: 2026-11-14. Rama: feature/samee100-j1939-can. Referencia de código: 9d98df1 más cambios locales documentados en Prompt 02/03. Fuente: repositorio local; no se consultaron normas externas ni documentación EMCP3 adicional. Este catálogo describe contratos implementados, no certifica su correspondencia física.

## Convenciones y evidencia

Estados documentales: IMPLEMENTADO; PROBADO CON DATOS SINTÉTICOS; CONFIRMADO CON CAPTURA REAL; PENDIENTE DE VALIDACIÓN; NO SOPORTADO. Una señal puede tener varios estados de evidencia. Ninguna señal de este catálogo está CONFIRMADO CON CAPTURA REAL: no se localizaron capturas operativas locales en data/j1939_captures ni en los archivos rastreados examinados. Los CAN ID/SA que aparecen abajo son fixtures sintéticos, NO identificadores físicamente confirmados.

Los seis contratos provienen de config/j1939_signals.yml, source=alkosto_reference. La etiqueta confidence del YAML es una declaración heredada, no prueba de recepción. Bytes numerados desde 1, sin signo, little endian. SignalDecoder.__init__ excluye enabled=false; SignalDecoder.decode/_decode_one (j1939/decoder.py:8,21,27) implementa extracción, escala, offset, rango y calidad. decode_identifier (j1939/parser.py:12) extrae SA; ninguna definición impone un origen. No se mezclan los fixtures EA con una confirmación de ECU real.

## Señales identificadas

| Nombre / key | PGN hex (decimal) | SPN declarado | CAN ID 29 bits / SA (solo fixture) | Bytes / longitud | Escala + offset | Unidad / rango configurado | Valor no disponible configurado |
|---|---|---|---|---|---|---|---|
| RPM del motor / engine_speed | F004 (61444) | 190 | 0CF004EA / EA | 4-5 / 16 bits | raw×0.125 + 0 | rpm / 0..3000 | 65535 (FFFF) |
| Temperatura de refrigerante / coolant_temperature | FEEE (65262) | 110 | 18FEEEEA / EA | 1 / 8 bits | raw×1 − 40 | °C / −40..210 | 255 (FF) |
| Horas totales de motor / engine_total_hours | FEE5 (65253) | 247 | 18FEE5EA / EA | 1-4 / 32 bits | raw×0.05 + 0 | h / 0..214748364.75 | 4294967295 (FFFFFFFF) |
| Campo de voltaje DC 1 / dc_voltage_field_1 | FEF7 (65271) | No asignado (null) | Sin ID/SA de recepción demostrado | 5-6 / 16 bits | raw×0.05 + 0 | V / 0..40 | 65535 (FFFF) |
| Campo de voltaje DC 2 / dc_voltage_field_2 | FEF7 (65271) | No asignado (null) | Sin ID/SA de recepción demostrado | 7-8 / 16 bits | raw×0.05 + 0 | V / 0..40 | 65535 (FFFF) |
| Campo candidato de frecuencia / generator_frequency_candidate | FE06 (65030) | No asignado (null) | Sin ID/SA de recepción demostrado | 1-2 / 16 bits | raw×0.2 + 0 | Hz / sin rango configurado | 65535 (FFFF) |

| Señal | Código / habilitación / confidence heredada | Evidencia de prueba reproducible | Estado documental / observaciones |
|---|---|---|---|
| engine_speed | YAML:5-23; SignalDecoder._decode_one; enabled=true; CONFIRMED | tests/test_j1939_core.py:DecoderTests.test_confirmed_signals_and_unknown_pgn: 0x3840 → 1800 rpm; test_na_and_short_payload: FFFF→NOT_AVAILABLE y payload corto→INVALID. tests/test_j1939_engine_detector.py:test_decoder_adapter_real_contract_synthetic_payload. tests/test_j1939_dashboard.js: valor/calidad/origen/frescura | IMPLEMENTADO; PROBADO CON DATOS SINTÉTICOS; PENDIENTE DE VALIDACIÓN física. EEC1 según descripción del repositorio; RPM no prueban producción eléctrica ni entrega de carga |
| coolant_temperature | YAML:24-42; mismo decoder; enabled=true; CONFIRMED | DecoderTests.test_confirmed_signals_and_unknown_pgn: raw 0x60 → 56 °C | IMPLEMENTADO; PROBADO CON DATOS SINTÉTICOS; PENDIENTE DE VALIDACIÓN. Descripción local Engine Temperature 1 |
| engine_total_hours | YAML:43-61; mismo decoder; enabled=true; CONFIRMED | DecoderTests.test_confirmed_signals_and_unknown_pgn: raw 0x1B30 → 348 h | IMPLEMENTADO; PROBADO CON DATOS SINTÉTICOS; PENDIENTE DE VALIDACIÓN. Horómetro ECU, distinto de horas por sesiones locales; no sumarlos |
| dc_voltage_field_1 | YAML:62-80; mismo decoder; enabled=true; PROBABLE | Extracción soportada por decoder genérico; no se localizó prueba específica de escala/función física en los tests anteriores | IMPLEMENTADO; PENDIENTE DE VALIDACIÓN. No etiquetar como batería. Rango/escalamiento son contrato local, no medición confirmada |
| dc_voltage_field_2 | YAML:81-99; mismo decoder genérico, definición enabled=false; UNKNOWN | No se localizó prueba específica ni captura real | PENDIENTE DE VALIDACIÓN; NO SOPORTADO en runtime por defecto (definición deshabilitada). No confundir existencia de YAML con recepción |
| generator_frequency_candidate | YAML:100-115; mismo decoder genérico, definición enabled=false; PROBABLE | No se localizó prueba específica ni captura real | PENDIENTE DE VALIDACIÓN; NO SOPORTADO en runtime por defecto. Deshabilitado por contratos contradictorios según descripción local |

La lista invalid_raw_values no pretende cubrir exhaustivamente códigos de error/reservados SAE. Minimum/maximum fuera de rango produce INVALID y value=None. Un valor no disponible produce NOT_AVAILABLE y value=None. No se asignan SPN a los campos DC/frecuencia por semejanza con normas. No se añadieron nombres de parámetros EMCP3 sin fuente documental.

## Variables requeridas sin fuente confirmada

| Celda/variable | PGN/SPN | Situación y presentación |
|---|---|---|
| Comunicación CAN | No aplica como SPN de motor | Metadatos status.lastFrameAt/connected; diagnóstico de tiempo, no señal física EMCP3 ni estado motor |
| Estado confirmado del motor | RPM F004/190 sería entrada, no SPN de estado | Detector aislado, sin validación física ni integración. PENDIENTE DE VALIDACIÓN; celda Sin dato validado |
| Batería | No asignar | DC1 no identificado físicamente. PENDIENTE DE VALIDACIÓN; Sin dato validado |
| Tensión AC L1-L2, L2-L3, L1-L3 | No asignar | NO SOPORTADO por las definiciones CAN activas; Sin dato validado |
| Frecuencia del generador | Candidato FE06 sin SPN asignado | Deshabilitado; PENDIENTE DE VALIDACIÓN; Sin dato validado |
| Potencia/carga/corriente del generador | No asignar | NO SOPORTADO en definiciones CAN activas; Sin dato validado. Mediciones Modbus no se reasignan al generador |
| Estados EMCP3, alarmas/advertencias/DM1 | No asignar | NO SOPORTADO en YAML activo; no inventar códigos/controlador |
| Último arranque, última parada, horas por sesiones | Eventos locales futuros, no SPN inferido | Persistencia aún no implementada. Sin dato validado |

## Integración visual y separación de ECU

Flujo conservado: SocketCanFrameSource/SerialCanFrameSource/ReplayCanFrameSource → J1939Runtime.process → SignalDecoder → SignalState → HTTP interno → api/app.py:_j1939_proxy → static/js/dashboard.js. No se modificaron estos componentes Python ni la configuración CAN.

SignalState guarda la última señal por key y puede sobrescribir orígenes. Limitación preexistente: la API no ofrece historial completo por ECU. RpmMonitor de static/js/j1939_diagnostics.js conserva únicamente señales engine_speed/F004/rpm consultadas desde la apertura de la página, en un Map separado por sourceAddress. El selector mantiene el origen elegido aunque otra ECU emita después. No puede reconstruir muestras de ECU omitidas entre consultas. Edad válida se conserva por SA y nunca se hereda de otra. No se presume que SA EA corresponda al motor real.

El diagnóstico de frescura usa 15 s como referencia visual explícitamente pendiente de calibración, configurable en data-stale-seconds de j1939Section; no modifica timeout del detector ni declara parada. Última muestra significa adquisición conocida por la API; última muestra válida observada significa consulta válida observada en esa página, no historial persistido. Las tarjetas originales muestran últimos valores decodificados con calidad, origen y UTC; el bloque diagnóstico oculta RPM no recientes/invalidas.

## Verificación reproducible y límites

- python -B -m unittest tests.test_j1939_core tests.test_j1939_capture tests.test_j1939_socketcan tests.test_j1939_service_api tests.test_j1939_engine_detector -v
- python -B -m unittest tests.test_j1939_dashboard -v
- node --test tests/test_j1939_dashboard.js

Fixtures son sintéticos. Para CONFIRMADO CON CAPTURA REAL exigir captura pasiva anotada, fecha/ID/SA, referencia de registro y contraste físico por señal, sin subir archivos operativos a Git. Documentar evidencia sanitizada y ubicación protegida de RAW. Validación de cadencia, origen motor, puesta a cero y calibración permanece pendiente. No se activó el detector ni se desplegó nada en Raspberry.

## Seguridad de publicación

.env está rastreado. No se imprimió ni leyó su contenido en este trabajo. .gitignore ya impide nuevos archivos de ese nombre, pero no remueve seguimiento/historial. Antes de publicar: conservar copia local protegida, revisar solo nombres rastreados; retirar del índice con git rm --cached -- .env (cuando se autorice), verificar que la copia local permanece y que git check-ignore --no-index .env aplica, preparar ejemplo sin secretos, revisar diff de nombres y aprobar commit desde PC. No ejecutar git rm sin --cached. Si hubo credenciales reales accesibles en remoto, tratar como potencialmente expuestas y coordinar revocación/rotación con su responsable; aquí no se inspeccionaron valores ni accesibilidad del remoto. Eliminar el archivo del último commit no elimina historial; cualquier saneamiento histórico necesita alcance y autorización separados. No se ejecutó este procedimiento ni commit/push.
