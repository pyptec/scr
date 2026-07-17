let chartPrincipal = null;
let graficaActual = "potencia";
let rangoActual = "ultimos_datos";
let ultimosValores = [];
let variablesDisponibles = [];
let variableSeleccionadaKey = null;
let mesesProduccion = [];
let moduloActual = "resumen";
let actualizacionEnCurso = false;
let chartEstadosAoki = null;
let chartBase100Diario = null;
let chartCusumDiario = null;
let chartImpactoEconomico = null;
let chartImpactoAmbiental = null;
let conciliacionActual = [];
let mantenimientoActual = [];
let ventanasOperacionActuales = [];
let rangoSnapshotActual = null;
let actualizacionPendiente = false;
const cacheHistorico = new Map();
const CACHE_VERSION = "fase2-dashboard-v1";

function obtenerKeyVariable(v) {
    if (!v) return null;

    return [
        v.gateway_id ?? "",
        v.source_type ?? "",
        v.device_id ?? "",
        v.unit_id ?? ""
    ].join("|");
}

function datetimeLocalAUnix(valor) {
    if (!valor) return null;
    const match = String(valor).match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/);
    if (!match) return null;
    const [, year, month, day, hour, minute, second = "0"] = match;
    return unixDesdeColombia(
        Number(year), Number(month), Number(day), Number(hour), Number(minute), Number(second)
    );
}

function unixADatetimeLocal(timestamp) {
    const fecha = new Date((timestamp - 5 * 3600) * 1000);
    const year = fecha.getUTCFullYear();
    const month = String(fecha.getUTCMonth() + 1).padStart(2, "0");
    const day = String(fecha.getUTCDate()).padStart(2, "0");
    const hour = String(fecha.getUTCHours()).padStart(2, "0");
    const minute = String(fecha.getUTCMinutes()).padStart(2, "0");

    return `${year}-${month}-${day}T${hour}:${minute}`;
}

function unixDesdeColombia(year, month, day, hour = 0, minute = 0, second = 0) {
    // Colombia UTC-5. Date.UTC recibe mes base cero.
    return Math.floor(Date.UTC(year, month - 1, day, hour + 5, minute, second) / 1000);
}

function ultimoDiaMes(year, month) {
    return new Date(year, month, 0).getDate();
}

function rangoMesProduccion(mesTexto) {
    // mesTexto viene como "2026-05"
    const partes = String(mesTexto).split("-");

    if (partes.length !== 2) {
        const ahora = Math.floor(Date.now() / 1000);
        return {
            inicio: ahora - 7 * 24 * 3600,
            fin: ahora
        };
    }

    const year = Number(partes[0]);
    const month = Number(partes[1]);
    const siguienteYear = month === 12 ? year + 1 : year;
    const siguienteMonth = month === 12 ? 1 : month + 1;

    return {
        inicio: unixDesdeColombia(year, month, 1, 6, 0, 0),
        fin: unixDesdeColombia(siguienteYear, siguienteMonth, 1, 6, 0, 0)
    };
}

function rangoTodoProduccion() {
    if (!mesesProduccion || !mesesProduccion.length) {
        const ahora = Math.floor(Date.now() / 1000);
        return {
            inicio: ahora - 7 * 24 * 3600,
            fin: ahora
        };
    }

    const mesesOrdenados = [...mesesProduccion].sort((a, b) =>
        String(a.mes).localeCompare(String(b.mes))
    );

    const primerMes = mesesOrdenados[0].mes;
    const ultimoMes = mesesOrdenados[mesesOrdenados.length - 1].mes;

    const rInicio = rangoMesProduccion(primerMes);
    const rFin = rangoMesProduccion(ultimoMes);

    return {
        inicio: rInicio.inicio,
        fin: rFin.fin
    };
}

function obtenerRangoUnix() {
    const ahora = Math.floor(Date.now() / 1000);
    const selectorRango = document.getElementById("rangoTiempo");
    const rango = selectorRango ? selectorRango.value : rangoActual;

    let inicio = ahora - 86400;
    let fin = ahora;

    if (rango === "manual") {
        const inicioManual = datetimeLocalAUnix(
            document.getElementById("fechaInicioManual").value
        );

        const finManual = datetimeLocalAUnix(
            document.getElementById("fechaFinManual").value
        );

        if (inicioManual && finManual && finManual > inicioManual) {
            const rangoManual = {
                inicio: inicioManual,
                fin: finManual
            };
            formatearPeriodoEfectivo(rangoManual);
            return rangoManual;
        }
    }

    if (rango === "ultimos_datos") {
        if (mesesProduccion.length) {
            const r = rangoTodoProduccion();
            inicio = r.inicio;
            fin = r.fin;
        } else {
            inicio = ahora - 7 * 24 * 3600;
            fin = ahora;
        }

    } else if (rango === "hora") {
        inicio = ahora - 3600;

    } else if (rango === "hoy") {
        ({ inicio, fin } = rangoJornadaActual(1));

    } else if (rango === "semana") {
        ({ inicio, fin } = rangoJornadaActual(7));

    } else if (rango === "mes") {
        ({ inicio, fin } = rangoJornadaActual(30));

    } else if (rango === "prod_todo") {
        const r = rangoTodoProduccion();
        inicio = r.inicio;
        fin = r.fin;

    } else if (rango && rango.startsWith("prod_mes:")) {
        const mes = rango.replace("prod_mes:", "");
        const r = rangoMesProduccion(mes);
        inicio = r.inicio;
        fin = r.fin;
    }

    const inputInicio = document.getElementById("fechaInicioManual");
    const inputFin = document.getElementById("fechaFinManual");

    if (inputInicio) {
        inputInicio.value = unixADatetimeLocal(inicio);
    }

    if (inputFin) {
        inputFin.value = unixADatetimeLocal(fin);
    }

    const rangoEfectivo = { inicio, fin };
    formatearPeriodoEfectivo(rangoEfectivo);
    return rangoEfectivo;
}

function formatearPeriodoEfectivo(rango) {
    const opciones = {
        timeZone: "America/Bogota",
        year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit", hour12: false
    };
    const inicio = new Date(rango.inicio * 1000).toLocaleString("es-CO", opciones);
    const fin = new Date(rango.fin * 1000).toLocaleString("es-CO", opciones);
    const texto = document.getElementById("periodoEfectivo");
    if (texto) texto.textContent = `Periodo efectivo evaluado: ${inicio} – ${fin} (jornada 06:00–06:00)`;
}

function crearInstantaneaRango() {
    const rango = obtenerRangoUnix();
    const requestedRange = Object.freeze({ startUtc: rango.inicio, endUtc: rango.fin });
    const snapshot = Object.freeze({
        requestedRange,
        effectiveRange: requestedRange,
        reconciliableRange: null,
        timezone: "America/Bogota",
        startInclusive: true,
        endExclusive: true,
        inicio: rango.inicio,
        fin: rango.fin
    });
    const anterior = rangoSnapshotActual
        ? `${rangoSnapshotActual.inicio}:${rangoSnapshotActual.fin}`
        : null;
    const actual = `${snapshot.inicio}:${snapshot.fin}`;
    if (anterior !== actual) cacheHistorico.clear();
    rangoSnapshotActual = snapshot;
    return snapshot;
}

function requerirSnapshot(snapshot) {
    if (!snapshot) throw new Error("No existe una instantánea activa del rango");
    return snapshot;
}

async function fetchJsonCacheado(endpoint, snapshot) {
    snapshot = requerirSnapshot(snapshot);
    const key = `${CACHE_VERSION}|${endpoint}|${snapshot.inicio}|${snapshot.fin}`;
    if (!cacheHistorico.has(key)) {
        const promise = fetch(endpoint).then(async respuesta => {
            const data = await respuesta.json();
            if (!respuesta.ok) throw new Error(data.error || `Error consultando ${endpoint}`);
            return data;
        }).catch(error => {
            cacheHistorico.delete(key);
            throw error;
        });
        cacheHistorico.set(key, promise);
    }
    return cacheHistorico.get(key);
}

function obtenerFase2(snapshot) {
    snapshot = requerirSnapshot(snapshot);
    return fetchJsonCacheado(
        `/api/fase2/dashboard?inicio=${snapshot.inicio}&fin=${snapshot.fin}`,
        snapshot
    );
}

function rangoJornadaActual(dias = 1) {
    const ahora = new Date();
    const partes = new Intl.DateTimeFormat("en-CA", {
        timeZone: "America/Bogota", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", hour12: false
    }).formatToParts(ahora).reduce((acc, parte) => ({ ...acc, [parte.type]: parte.value }), {});
    let fin = unixDesdeColombia(Number(partes.year), Number(partes.month), Number(partes.day), 6);
    if (Number(partes.hour) >= 6) fin += 86400;
    return { inicio: fin - dias * 86400, fin };
}

function obtenerGranularidad() {
    return document.getElementById("granularidad")?.value || "hora";
}

async function aplicarFiltroManual() {
    rangoActual = document.getElementById("rangoTiempo").value;

    await actualizarTodo();
}

function formatearNumero(valor, decimales = 2) {
    if (valor === null || valor === undefined || Number.isNaN(Number(valor))) {
        return "--";
    }

    return Number(valor).toLocaleString("es-CO", {
        minimumFractionDigits: decimales,
        maximumFractionDigits: decimales
    });
}
function formatearEntero(valor) {
    if (valor === null || valor === undefined || Number.isNaN(Number(valor))) {
        return "--";
    }

    return Number(valor).toLocaleString("es-CO", {
        maximumFractionDigits: 0
    });
}

function escaparHtml(valor) {
    return String(valor ?? "").replace(/[&<>'"]/g, caracter => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
    })[caracter]);
}

function formatearHoraColombia(timestampUtc) {
    if (!timestampUtc) return "--";

    const fecha = new Date(Number(timestampUtc) * 1000);

    return fecha.toLocaleString("es-CO", {
        timeZone: "America/Bogota",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false
    });
}

function formatearIsoColombia(valor) {
    if (!valor) return "--";
    const fecha = new Date(valor);
    if (Number.isNaN(fecha.getTime())) return String(valor);
    return fecha.toLocaleString("es-CO", {
        timeZone: "America/Bogota", year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false
    });
}

function formatearEdadSegundos(segundos) {
    if (segundos === null || segundos === undefined) return "--";

    const s = Number(segundos);

    if (s < 60) return `${s} s`;
    if (s < 3600) return `${Math.floor(s / 60)} min`;

    return `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`;
}

function reconstruirIpv4DesdeDigitos(valor) {
    if (valor === null || valor === undefined) return "--";

    const textoOriginal = String(valor).trim();

    if (textoOriginal.includes(".")) return textoOriginal;

    const digitos = textoOriginal.replace(/\D/g, "");

    if (!digitos) return "--";

    const resultados = [];

    function backtrack(pos, partes) {
        if (partes.length === 4) {
            if (pos === digitos.length) {
                resultados.push(partes.join("."));
            }
            return;
        }

        const restantes = digitos.length - pos;
        const partesRestantes = 4 - partes.length;

        if (restantes < partesRestantes || restantes > partesRestantes * 3) {
            return;
        }

        for (let len = 1; len <= 3; len++) {
            const segmento = digitos.slice(pos, pos + len);

            if (!segmento) continue;
            if (segmento.length > 1 && segmento.startsWith("0")) continue;

            const n = Number(segmento);

            if (n >= 0 && n <= 255) {
                backtrack(pos + len, [...partes, segmento]);
            }
        }
    }

    backtrack(0, []);

    if (!resultados.length) return textoOriginal;

    const privadas = resultados.filter(ip =>
        ip.startsWith("192.168.") ||
        ip.startsWith("10.") ||
        /^172\.(1[6-9]|2\d|3[0-1])\./.test(ip)
    );

    return privadas[0] || resultados[0];
}

async function cargarProduccion(snapshot = rangoSnapshotActual) {
    const resumen = (await obtenerFase2(snapshot)).production || {};

    document.getElementById("prodBuenos").innerText =
        formatearEntero(resumen.envases_buenos);

    document.getElementById("prodMalos").innerText =
        formatearEntero(resumen.envases_malos);

    document.getElementById("prodTotal").innerText =
        formatearEntero(resumen.produccion_total);

    const pendiente = "Dato pendiente";
    document.getElementById("prodHorasProgramadas").innerText = formatearNumero(resumen.horas_programadas, 2);
    document.getElementById("prodHorasReales").innerText = resumen.horas_reales_trabajo === null ? pendiente : formatearNumero(resumen.horas_reales_trabajo, 2);
    document.getElementById("prodHorasParada").innerText = resumen.horas_parada_reportadas === null ? pendiente : formatearNumero(resumen.horas_parada_reportadas, 2);
    document.getElementById("prodBuenosHora").innerText = resumen.produccion_buena_hora_real === null ? pendiente : formatearNumero(resumen.produccion_buena_hora_real, 2);
    document.getElementById("prodTotalHora").innerText = resumen.produccion_total_hora_real === null ? pendiente : formatearNumero(resumen.produccion_total_hora_real, 2);
    document.getElementById("prodDias").innerText = formatearEntero(resumen.dias_produccion_incluidos);

    const tbody = document.getElementById("tablaProduccionDiaria");
    tbody.innerHTML = "";

    const detalle = resumen.detalle_diario || [];
    if (!detalle.length) {
        tbody.innerHTML = `<tr><td colspan="10">No hay producción cargada para el periodo</td></tr>`;
        return;
    }

    detalle.forEach(fila => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td>${escaparHtml(fila.fecha || "--")}</td>
            <td>${formatearEntero(fila.envases_buenos)}</td>
            <td>${formatearEntero(fila.envases_malos)}</td>
            <td>${formatearEntero(fila.produccion_total)}</td>
            <td>${formatearNumero(fila.turnos, 0)}</td>
            <td>${formatearNumero(fila.horas_programadas, 2)}</td>
            <td>${fila.minutos_parada_reportados === null ? pendiente : formatearNumero(fila.minutos_parada_reportados, 0)}</td>
            <td>${fila.horas_reales_trabajo === null ? pendiente : formatearNumero(fila.horas_reales_trabajo, 2)}</td>
            <td>${fila.produccion_buena_hora_real === null ? pendiente : formatearNumero(fila.produccion_buena_hora_real, 2)}</td>
            <td>${escaparHtml(fila.observaciones || "--")}</td>
        `;
        tbody.appendChild(tr);
    });
}

async function cargarEstadosAoki(snapshot = rangoSnapshotActual) {
    const integrado = await obtenerFase2(snapshot);
    const data = integrado.electricalStates || {};
    const operacion = integrado.production || {};
    const conciliacion = integrado.reconciliation || {};
    const eventosData = integrado.electricalEvents || {};
    const diarios = data.daily || [];
    const resumenPeriodo = data.periodSummary || {};
    document.getElementById("estadoHorasProductivas").innerText = formatearNumero(resumenPeriodo.productiveHours, 2);
    document.getElementById("estadoHorasEspera").innerText = formatearNumero(resumenPeriodo.idleHours, 2);
    document.getElementById("estadoHorasApagado").innerText = formatearNumero(resumenPeriodo.offHours, 2);
    document.getElementById("estadoHorasSinDatos").innerText = formatearNumero(resumenPeriodo.noDataHours, 2);
    document.getElementById("estadoHorasConDatos").innerText = formatearNumero(resumenPeriodo.knownDataHours, 2);
    document.getElementById("estadoCobertura").innerText = resumenPeriodo.coveragePct === null ? "Datos insuficientes" : `${formatearNumero(resumenPeriodo.coveragePct, 2)} %`;
    document.getElementById("estadoInconsistencias").innerText = formatearNumero(resumenPeriodo.inconsistentHours, 2);
    document.getElementById("estadoBalance").innerText = resumenPeriodo.balanceStatus === "VALID"
        ? `Válido (${formatearNumero(resumenPeriodo.balanceDifferenceSeconds, 2)} s)`
        : "Fuera de tolerancia";
    const resumenEventos = eventosData.summary || {};
    document.getElementById("eventosDetectados").innerText = formatearEntero(resumenEventos.eventCount);
    document.getElementById("eventosHorasIdle").innerText = formatearNumero(resumenEventos.idleHours, 2);
    document.getElementById("eventosHorasOff").innerText = formatearNumero(resumenEventos.offHours, 2);
    document.getElementById("eventosHorasTotal").innerText = formatearNumero(resumenEventos.nonProductiveHours, 2);
    const tbodyEventos = document.getElementById("tablaEventosAoki");
    const eventos = eventosData.events || [];
    tbodyEventos.innerHTML = eventos.length ? "" : '<tr><td colspan="10">No hay eventos eléctricos detectados en el periodo</td></tr>';
    eventos.forEach(evento => {
        const fila = document.createElement("tr");
        fila.innerHTML = `<td>${escaparHtml(evento.startLocal)}</td><td>${escaparHtml(evento.endLocal)}</td><td>${formatearNumero(evento.durationMinutes, 2)}</td><td>${escaparHtml(evento.dominantState)}</td><td>${formatearNumero(evento.minimumCurrentA, 2)}</td><td>${formatearNumero(evento.averageCurrentA, 2)}</td><td>${formatearNumero(evento.averagePowerKW, 2)}</td><td>${formatearEntero(evento.sampleCount)}</td><td>${escaparHtml(evento.status)}</td><td>${escaparHtml(evento.classification)}</td>`;
        tbodyEventos.appendChild(fila);
    });
    cargarConciliacionAoki(conciliacion);
    document.getElementById("opHorasProgramadas").innerText = formatearNumero(operacion.horas_programadas, 2);
    document.getElementById("opHorasReales").innerText = operacion.horas_reales_trabajo === null ? "Dato pendiente" : formatearNumero(operacion.horas_reales_trabajo, 2);
    document.getElementById("opHorasParada").innerText = operacion.horas_parada_reportadas === null ? "Dato pendiente" : formatearNumero(operacion.horas_parada_reportadas, 2);
    document.getElementById("opDisponibilidadReportada").innerText = operacion.disponibilidad_operacional_reportada_pct === null
        ? "Dato pendiente"
        : `${formatearNumero(operacion.disponibilidad_operacional_reportada_pct, 2)} %`;
    const umbrales = data.thresholds || {};
    document.getElementById("estadoCriterio").innerText = `Criterio ${umbrales.version || "--"}: OFF < ${umbrales.offIdleCurrentA} A; IDLE < ${umbrales.idleProductiveCurrentA} A; persistencia ${umbrales.minimumConsecutiveSamples} muestras o ${umbrales.minimumPersistenceMinutes} min; hueco máximo ${umbrales.maximumGapMinutes} min.`;

    const tbody = document.getElementById("tablaEstadosAoki");
    tbody.innerHTML = diarios.length ? "" : '<tr><td colspan="10">Sin datos para el periodo</td></tr>';
    diarios.forEach(dia => {
        const fila = document.createElement("tr");
        fila.innerHTML = `<td>${escaparHtml(dia.productionDate)}</td><td>${formatearNumero(dia.productiveHours, 2)}</td><td>${formatearNumero(dia.idleHours, 2)}</td><td>${formatearNumero(dia.offHours, 2)}</td><td>${formatearNumero(dia.noDataHours, 2)}</td><td>${formatearNumero(dia.knownDataHours, 2)}</td><td>${formatearNumero(dia.coveragePct, 2)} %</td><td>${escaparHtml(dia.balanceStatus)}</td><td>${formatearEntero(dia.stateTransitions)}</td><td>${formatearNumero(dia.inconsistentHours, 2)}</td>`;
        tbody.appendChild(fila);
    });
    if (chartEstadosAoki) chartEstadosAoki.destroy();
    chartEstadosAoki = new Chart(document.getElementById("chartEstadosAoki"), {
        type: "bar",
        data: { labels: diarios.map(d => d.productionDate), datasets: [
            { label: "PRODUCTIVE", data: diarios.map(d => d.productiveHours), backgroundColor: "#16a34a" },
            { label: "IDLE", data: diarios.map(d => d.idleHours), backgroundColor: "#f59e0b" },
            { label: "OFF", data: diarios.map(d => d.offHours), backgroundColor: "#64748b" },
            { label: "NO_DATA", data: diarios.map(d => d.noDataHours), backgroundColor: "#dc2626" }
        ]},
        options: { responsive: true, scales: { x: { stacked: true }, y: { stacked: true, title: { display: true, text: "Horas" } } } }
    });
}

function jornadaConciliacion(evento) {
    return evento.reportedEvents?.[0]?.productionDate
        || evento.electricalEvents?.[0]?.productionDates?.[0]
        || "";
}

function poblarFiltroConciliacion(id, valores) {
    const selector = document.getElementById(id);
    if (!selector) return;
    const seleccionado = selector.value;
    selector.innerHTML = '<option value="">Todas</option>';
    [...new Set(valores.filter(Boolean))].sort().forEach(valor => {
        const option = document.createElement("option");
        option.value = valor;
        option.textContent = valor;
        selector.appendChild(option);
    });
    if ([...selector.options].some(option => option.value === seleccionado)) selector.value = seleccionado;
}

function cargarConciliacionAoki(data) {
    const resumen = data.summary || {};
    document.getElementById("conciliacionReportadas").innerText = formatearEntero(resumen.totalReportadas);
    document.getElementById("conciliacionDetectadas").innerText = formatearEntero(resumen.totalDetectadas);
    document.getElementById("conciliacionAmbas").innerText = formatearEntero(resumen.totalReportadasYDetectadas);
    document.getElementById("conciliacionSoloReportadas").innerText = formatearEntero(resumen.totalSoloReportadas);
    document.getElementById("conciliacionSoloDetectadas").innerText = formatearEntero(resumen.totalSoloDetectadas);
    document.getElementById("conciliacionPendientes").innerText = formatearEntero(resumen.totalPendientesRevision);
    const rango = data.effectiveRange;
    document.getElementById("conciliacionPeriodo").innerText = rango
        ? `Periodo conciliable: ${formatearIsoColombia(rango.startLocal)} – ${formatearIsoColombia(rango.endLocal)} · tolerancia ±${data.config?.matchingToleranceMinutes ?? "--"} min`
        : "Periodo conciliable: sin intersección entre producción y mediciones eléctricas";
    conciliacionActual = data.events || [];
    poblarFiltroConciliacion("filtroConciliacionClasificacion", conciliacionActual.map(item => item.classification));
    poblarFiltroConciliacion("filtroConciliacionConfianza", conciliacionActual.map(item => item.confidence));
    renderizarConciliacionAoki();
}

function renderizarConciliacionAoki() {
    const clasificacion = document.getElementById("filtroConciliacionClasificacion")?.value || "";
    const confianza = document.getElementById("filtroConciliacionConfianza")?.value || "";
    const estado = document.getElementById("filtroConciliacionEstado")?.value || "";
    const jornada = document.getElementById("filtroConciliacionJornada")?.value || "";
    const revision = document.getElementById("filtroConciliacionRevision")?.value || "";
    const filtrados = conciliacionActual.filter(item => {
        const estados = (item.electricalEvents || []).map(evento => evento.dominantState);
        return (!clasificacion || item.classification === clasificacion)
            && (!confianza || item.confidence === confianza)
            && (!estado || estados.includes(estado))
            && (!jornada || jornadaConciliacion(item) === jornada)
            && (!revision || item.status === revision);
    });
    const tbody = document.getElementById("tablaConciliacionAoki");
    tbody.innerHTML = filtrados.length ? "" : '<tr><td colspan="16">No hay eventos para los filtros seleccionados</td></tr>';
    filtrados.forEach(item => {
        const fila = document.createElement("tr");
        const coberturas = `${formatearNumero(item.reportedCoveragePct, 1)} % / ${formatearNumero(item.electricalCoveragePct, 1)} %`;
        fila.innerHTML = `
            <td>${escaparHtml(jornadaConciliacion(item) || "--")}</td>
            <td>${escaparHtml(formatearIsoColombia(item.startReported))}</td>
            <td>${escaparHtml(formatearIsoColombia(item.endReported))}</td>
            <td>${formatearNumero(item.reportedDurationMinutes, 2)}</td>
            <td>${escaparHtml(formatearIsoColombia(item.startElectrical))}</td>
            <td>${escaparHtml(formatearIsoColombia(item.endElectrical))}</td>
            <td>${formatearNumero(item.electricalDurationMinutes, 2)}</td>
            <td>${formatearNumero(item.durationDifferenceMinutes, 2)}</td>
            <td>${formatearNumero(item.overlapMinutes, 2)}</td>
            <td>${escaparHtml(coberturas)}</td>
            <td>${escaparHtml(item.classification)}</td>
            <td>${escaparHtml(item.confidence || "NOT_APPLICABLE")}</td>
            <td>${escaparHtml(item.cause || "--")}</td>
            <td>${escaparHtml(item.rawText || "--")}</td>
            <td>${escaparHtml(item.reason || "--")}</td>
            <td>${escaparHtml(item.status || "--")}</td>`;
        tbody.appendChild(fila);
    });
}

function renderizarMantenimiento() {
    const sugerencia = document.getElementById("filtroMantSugerencia")?.value || "";
    const validacion = document.getElementById("filtroMantValidacion")?.value || "";
    const filtrados = mantenimientoActual.filter(evento =>
        (!sugerencia || evento.suggestedClassification === sugerencia)
        && (!validacion || evento.validationStatus === validacion)
    );
    const tbody = document.getElementById("tablaMantenimiento");
    tbody.innerHTML = filtrados.length
        ? ""
        : '<tr><td colspan="12">No hay eventos para los filtros seleccionados</td></tr>';
    filtrados.forEach(evento => {
        const fila = document.createElement("tr");
        fila.innerHTML = `
            <td>${escaparHtml(evento.maintenanceEventId)}</td>
            <td>${escaparHtml(evento.productionDate || "--")}</td>
            <td>${escaparHtml(evento.suggestedClassification)}</td>
            <td>${evento.validatedClassification === null ? "Sin validar" : escaparHtml(evento.validatedClassification)}</td>
            <td>${escaparHtml(evento.validationStatus)}</td>
            <td>${escaparHtml(evento.cause || "--")}</td>
            <td>${escaparHtml(formatearIsoColombia(evento.reportedStart))}</td>
            <td>${escaparHtml(formatearIsoColombia(evento.electricalStart))}</td>
            <td>${formatearNumero(evento.reportedDurationMinutes, 2)}</td>
            <td>${formatearNumero(evento.electricalDurationMinutes, 2)}</td>
            <td>${escaparHtml(evento.rawText || "Solo evidencia eléctrica")}</td>
            <td>${escaparHtml((evento.suggestionReasons || []).join(" "))}</td>`;
        tbody.appendChild(fila);
    });
}

function idempotencyKey() {
    return globalThis.crypto?.randomUUID?.()
        || `maintenance-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function poblarEventosValidacion() {
    const selector = document.getElementById("mantEventoValidar");
    const seleccionado = selector.value;
    selector.innerHTML = '<option value="">Seleccione</option>';
    mantenimientoActual.forEach(evento => {
        const option = document.createElement("option");
        option.value = evento.maintenanceEventId;
        option.textContent = `${evento.productionDate || "--"} · ${evento.maintenanceEventId} · ${evento.suggestedClassification}`;
        selector.appendChild(option);
    });
    if (mantenimientoActual.some(e => e.maintenanceEventId === seleccionado)) {
        selector.value = seleccionado;
    }
}

function renderizarVentanasOperacion() {
    const tbody = document.getElementById("tablaVentanasOperacion");
    tbody.innerHTML = ventanasOperacionActuales.length
        ? ""
        : '<tr><td colspan="8">No existen ventanas operativas validadas</td></tr>';
    ventanasOperacionActuales.forEach(ventana => {
        const fila = document.createElement("tr");
        fila.innerHTML = `<td>${escaparHtml(ventana.windowId)}</td><td>${escaparHtml(formatearIsoColombia(new Date(ventana.startUtc * 1000).toISOString()))}</td><td>${escaparHtml(formatearIsoColombia(new Date(ventana.endUtc * 1000).toISOString()))}</td><td>${escaparHtml(ventana.windowType)}</td><td>${escaparHtml(ventana.source)}</td><td>${escaparHtml(ventana.actorId)}</td><td>${formatearEntero(ventana.version)}</td><td>${escaparHtml(ventana.status)}</td>`;
        tbody.appendChild(fila);
    });
}

function valorKpiConUnidad(value, unit, decimals = 3) {
    return value === null || value === undefined
        ? "KPI no disponibles"
        : `${formatearNumero(value, decimals)} ${unit}`;
}

function renderizarConfiabilidad(data) {
    const summary = data.summary || {};
    const valid = data.status === "VALID";
    document.getElementById("relReparacionesCompletas").innerText =
        formatearEntero(summary.failuresWithValidatedDowntime);
    document.getElementById("relDowntimeValidado").innerText =
        summary.validatedCorrectiveDowntimeHours === null
            ? "No disponible"
            : `${formatearNumero(summary.validatedCorrectiveDowntimeHours, 3)} h`;
    document.getElementById("relMtbf").innerText =
        valorKpiConUnidad(summary.mtbfHours, "h");
    document.getElementById("relMttr").innerText =
        valorKpiConUnidad(summary.mttrHours, "h");
    document.getElementById("relDisponibilidadTiempo").innerText =
        valorKpiConUnidad(summary.technicalAvailabilityByTimePct, "%");
    document.getElementById("relDisponibilidadMtbf").innerText =
        valorKpiConUnidad(summary.technicalAvailabilityPct, "%");
    document.getElementById("relTasaFallas").innerText =
        valorKpiConUnidad(summary.failureRatePer1000Hours, "fallas/1.000 h");
    document.getElementById("relEstado").innerText = data.status || "--";
    document.getElementById("relEstadoDetalle").innerText = valid
        ? `Método ${data.methodology?.reliabilityMethodVersion || "--"}`
        : `KPI no disponibles · readiness ${data.readinessStatus || "--"}`;
    const tbody = document.getElementById("tablaConfiabilidad");
    const events = data.events || [];
    tbody.innerHTML = events.length
        ? ""
        : '<tr><td colspan="12">No existen eventos de mantenimiento en el rango</td></tr>';
    events.forEach(event => {
        const row = document.createElement("tr");
        const start = event.validatedStartUtc === null
            ? "--"
            : formatearIsoColombia(new Date(event.validatedStartUtc * 1000).toISOString());
        const end = event.validatedEndUtc === null
            ? "--"
            : formatearIsoColombia(new Date(event.validatedEndUtc * 1000).toISOString());
        row.innerHTML = `<td>${escaparHtml(event.maintenanceEventId)}</td><td>${escaparHtml(start)}</td><td>${escaparHtml(end)}</td><td>${event.validatedDowntimeMinutes === null ? "No disponible" : formatearNumero(event.validatedDowntimeMinutes, 3)}</td><td>${escaparHtml(event.censoringStatus)}</td><td>${event.includedInMtbf ? "Sí" : "No"}</td><td>${event.includedInMttr ? "Sí" : "No"}</td><td>${event.includedInAvailability ? "Sí" : "No"}</td><td>${escaparHtml(event.evidenceStatus || "--")}</td><td>${escaparHtml((event.exclusionReasons || []).join(", ") || "--")}</td><td>${escaparHtml(event.actorId || "--")}</td><td>${formatearEntero(event.validationVersion)}</td>`;
        tbody.appendChild(row);
    });
}

async function cargarMantenimiento(snapshot = rangoSnapshotActual) {
    snapshot = requerirSnapshot(snapshot);
    const [data, uptime, ventanas, confiabilidad] = await Promise.all([
        fetchJsonCacheado(
            `/api/mantenimiento/eventos?inicio=${snapshot.inicio}&fin=${snapshot.fin}`,
            snapshot
        ),
        fetchJsonCacheado(
            `/api/mantenimiento/preparacion-kpi?inicio=${snapshot.inicio}&fin=${snapshot.fin}`,
            snapshot
        ),
        fetchJsonCacheado(
            `/api/mantenimiento/ventanas-operacion?inicio=${snapshot.inicio}&fin=${snapshot.fin}`,
            snapshot
        ),
        fetchJsonCacheado(
            `/api/mantenimiento/confiabilidad?inicio=${snapshot.inicio}&fin=${snapshot.fin}`,
            snapshot
        )
    ]);
    const resumen = data.summary || {};
    const sugerencias = resumen.suggestionsByClassification || {};
    document.getElementById("mantPendientes").innerText = formatearEntero(resumen.pendingHumanReview);
    document.getElementById("mantCorrectivas").innerText = formatearEntero(sugerencias.CORRECTIVE_FAILURE || 0);
    document.getElementById("mantPreventivos").innerText = formatearEntero(sugerencias.PREVENTIVE_MAINTENANCE || 0);
    document.getElementById("mantOperacionales").innerText = formatearEntero(sugerencias.OPERATIONAL_STOP || 0);
    document.getElementById("mantSinDatos").innerText = formatearEntero(sugerencias.DATA_QUALITY_EVENT || 0);
    document.getElementById("mantValidados").innerText = formatearEntero(resumen.humanValidated);
    document.getElementById("mantFallasConfirmadas").innerText = formatearEntero(resumen.confirmedFailures);
    document.getElementById("mantEstadoPreparacion").innerText = uptime.status || "--";
    document.getElementById("mantUptimeValidado").innerText =
        uptime.summary?.validatedAssetUptimeHours === null
            ? "No disponible"
            : formatearNumero(uptime.summary?.validatedAssetUptimeHours, 3);
    document.getElementById("mantTiempoNoResuelto").innerText =
        uptime.summary?.unresolvedHours === null
            ? "No disponible"
            : formatearNumero(uptime.summary?.unresolvedHours, 3);
    document.getElementById("mantTaxonomia").innerText =
        `Taxonomía: ${data.taxonomyVersion || "--"} · validaciones humanas separadas y trazables`;
    mantenimientoActual = data.events || [];
    ventanasOperacionActuales = ventanas.windows || [];
    poblarFiltroConciliacion(
        "filtroMantSugerencia",
        mantenimientoActual.map(evento => evento.suggestedClassification)
    );
    poblarEventosValidacion();
    renderizarVentanasOperacion();
    renderizarConfiabilidad(confiabilidad);
    renderizarMantenimiento();
}

async function guardarValidacionMantenimiento() {
    const snapshot = requerirSnapshot(rangoSnapshotActual);
    const id = document.getElementById("mantEventoValidar").value;
    const event = mantenimientoActual.find(item => item.maintenanceEventId === id);
    const token = document.getElementById("mantBearerToken").value;
    const output = document.getElementById("mantResultadoEscritura");
    if (!event || !token) {
        output.textContent = "Seleccione un evento e ingrese el token individual.";
        return;
    }
    const startValue = document.getElementById("mantInicioValidado").value;
    const endValue = document.getElementById("mantFinValidado").value;
    const payload = {
        validatedClassification: document.getElementById("mantClasificacionValidada").value || null,
        validationStatus: document.getElementById("mantEstadoValidacion").value,
        validatedStartUtc: startValue ? datetimeLocalAUnix(startValue) : null,
        validatedEndUtc: endValue ? datetimeLocalAUnix(endValue) : null,
        reviewComment: document.getElementById("mantComentarioValidacion").value || null,
        expectedVersion: event.version || 0,
        sourceEvidenceHash: event.sourceEvidenceHash
    };
    const response = await fetch(
        `/api/mantenimiento/eventos/${encodeURIComponent(id)}/validacion?inicio=${snapshot.inicio}&fin=${snapshot.fin}`,
        {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${token}`,
                "Idempotency-Key": idempotencyKey()
            },
            body: JSON.stringify(payload)
        }
    );
    const result = await response.json();
    output.textContent = response.ok
        ? `Validación guardada. Versión ${result.version}.`
        : `${result.code || "ERROR"}: ${result.error || "No fue posible guardar"}`;
    if (response.ok) {
        cacheHistorico.clear();
        await cargarMantenimiento(snapshot);
    }
}

async function guardarVentanaOperacion() {
    const snapshot = requerirSnapshot(rangoSnapshotActual);
    const id = document.getElementById("mantWindowId").value.trim();
    const token = document.getElementById("mantBearerToken").value;
    const current = ventanasOperacionActuales.find(item => item.windowId === id);
    const output = document.getElementById("mantResultadoEscritura");
    if (!id || !token) {
        output.textContent = "Ingrese ID de ventana y token de administrador.";
        return;
    }
    const payload = {
        windowId: id,
        startUtc: datetimeLocalAUnix(document.getElementById("mantWindowStart").value),
        endUtc: datetimeLocalAUnix(document.getElementById("mantWindowEnd").value),
        windowType: document.getElementById("mantWindowType").value,
        source: document.getElementById("mantWindowSource").value,
        comment: document.getElementById("mantWindowComment").value || null,
        expectedVersion: current?.version || 0
    };
    const response = await fetch("/api/mantenimiento/ventanas-operacion", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${token}`,
            "Idempotency-Key": idempotencyKey()
        },
        body: JSON.stringify(payload)
    });
    const result = await response.json();
    output.textContent = response.ok
        ? `Ventana guardada. Versión ${result.version}.`
        : `${result.code || "ERROR"}: ${result.error || "No fue posible guardar"}`;
    if (response.ok) {
        cacheHistorico.clear();
        await cargarMantenimiento(snapshot);
    }
}

async function cargarEnergiaReconstruidaAoki(snapshot = rangoSnapshotActual) {
    const data = (await obtenerFase2(snapshot)).energy || {};
    const diarios = data.daily || [];
    const resumen = data.periodSummary || {};
    const total = resumen.knownEnergyKWh;
    const medida = resumen.measuredEnergyKWh;
    const reconstruida = resumen.reconstructedEnergyKWh;
    const intervalosNoData = resumen.noDataIntervals;
    const cobertura = resumen.energyCoveragePct;
    const porcentajeReconstruido = resumen.reconstructedPct;
    document.getElementById("energiaReconTotal").innerText = formatearNumero(total, 3);
    document.getElementById("energiaReconMedida").innerText = formatearNumero(medida, 3);
    document.getElementById("energiaReconEstimada").innerText = formatearNumero(reconstruida, 3);
    document.getElementById("energiaReconCobertura").innerText = cobertura === null ? "Datos insuficientes" : `${formatearNumero(cobertura, 2)} %`;
    document.getElementById("energiaReconPct").innerText = porcentajeReconstruido === null ? "Datos insuficientes" : `${formatearNumero(porcentajeReconstruido, 2)} %`;
    document.getElementById("energiaReconNoData").innerText = formatearEntero(intervalosNoData);
    document.getElementById("energiaReconNoDataHoras").innerText = formatearNumero(resumen.noDataDurationHours, 2);
    const config = data.config || {};
    document.getElementById("energiaReconCriterio").innerText = `Criterio ${config.version || "--"}: acumulador → potencia trapezoidal → potencia rectangular → NO_DATA. Corriente no usada como energía.`;
    const tbody = document.getElementById("tablaEnergiaReconstruida");
    tbody.innerHTML = diarios.length ? "" : '<tr><td colspan="8">Sin datos para el periodo</td></tr>';
    diarios.forEach(dia => {
        const fila = document.createElement("tr");
        fila.innerHTML = `<td>${escaparHtml(dia.productionDate)}</td><td>${formatearNumero(dia.calculatedEnergyKWh, 3)}</td><td>${formatearNumero(dia.measuredEnergyKWh, 3)}</td><td>${formatearNumero(dia.reconstructedEnergyKWh, 3)}</td><td>${dia.reconstructedPct === null ? "No disponible" : formatearNumero(dia.reconstructedPct, 2) + " %"}</td><td>${dia.energyCoveragePct === null ? "No disponible" : formatearNumero(dia.energyCoveragePct, 2) + " %"}</td><td>${formatearEntero(dia.noDataIntervals)}</td><td>${escaparHtml(dia.resultType)}</td>`;
        tbody.appendChild(fila);
    });
}

async function cargarLineaBase(snapshot = rangoSnapshotActual) {
    snapshot = requerirSnapshot(snapshot);
    const res = await fetch(`/api/linea-base/desempeno-diario?inicio=${snapshot.inicio}&fin=${snapshot.fin}`);
    const data = await res.json();

    if (!res.ok || data.error) {
        document.getElementById("lbClasificacion").innerText = "Sin datos";
        document.getElementById("lbMensaje").innerText = data.error || "No hay datos suficientes";
        return;
    }

    const resumen = data.summary || {};
    document.getElementById("lbEnergiaReal").innerText =
        formatearNumero(resumen.totalKnownEnergyKWh, 3);
    document.getElementById("lbEnergiaMedida").innerText =
        formatearNumero(resumen.totalMeasuredEnergyKWh, 3);
    document.getElementById("lbEnergiaReconstruida").innerText =
        formatearNumero(resumen.totalReconstructedEnergyKWh, 3);
    document.getElementById("lbEnergiaEsperada").innerText =
        formatearNumero(resumen.totalExpectedEnergyKWh, 3);
    document.getElementById("lbDesviacionPct").innerText =
        resumen.totalDeviationPct === null ? "Datos insuficientes" : `${formatearNumero(resumen.totalDeviationPct, 2)} %`;
    document.getElementById("lbDiferenciaKwh").innerText =
        resumen.favorableDifferenceKWh > 0
            ? `${formatearNumero(resumen.favorableDifferenceKWh, 3)} favorable`
            : (resumen.unfavorableDifferenceKWh > 0
                ? `${formatearNumero(resumen.unfavorableDifferenceKWh, 3)} desfavorable`
                : (resumen.totalResidualKWh === null ? "Datos insuficientes" : "Neutral"));
    document.getElementById("lbCoberturaEnergia").innerText =
        resumen.energyCoveragePct === null ? "Datos insuficientes" : `${formatearNumero(resumen.energyCoveragePct, 2)} %`;
    document.getElementById("lbCoberturaEstados").innerText =
        resumen.stateCoveragePct === null ? "Datos insuficientes" : `${formatearNumero(resumen.stateCoveragePct, 2)} %`;
    document.getElementById("lbDiasValidos").innerText = formatearEntero(resumen.validDays);
    document.getElementById("lbDiasExcluidos").innerText =
        `${formatearEntero(resumen.excludedDays)} (+${formatearEntero(resumen.insufficientDays)} insuf.)`;
    const clasificacionesValidas = (data.daily || [])
        .filter(dia => dia.evaluationStatus === "VALID_PRELIMINARY")
        .map(dia => dia.performanceClassification);
    document.getElementById("lbClasificacion").innerText =
        clasificacionesValidas.length === 0 ? "INSUFFICIENT_DATA"
            : (new Set(clasificacionesValidas).size === 1 ? clasificacionesValidas[0] : "RESULTADO_MIXTO_PRELIMINAR");
    document.getElementById("lbMensaje").innerText =
        `${data.quality?.status || "--"}; resultado no definitivo.`;

    const beta0 = data.model?.intercepto;
    const betaEnvases = data.model?.coef_envases_buenos;
    const betaHoras = data.model?.coef_horas_productivas;

    if (beta0 !== undefined && betaEnvases !== undefined && betaHoras !== undefined) {
        document.getElementById("lbModelo").innerText =
            `${formatearNumero(beta0, 2)} + ${formatearNumero(betaEnvases, 6)} × envases + ` +
            `${formatearNumero(betaHoras, 4)} × horas`;
    } else {
        document.getElementById("lbModelo").innerText = "--";
    }

    document.getElementById("lbR2").innerText =
        formatearNumero(data.model?.r2, 3);

    const tbody = document.getElementById("tablaLineaBaseDiaria");
    const diarios = data.daily || [];
    tbody.innerHTML = diarios.length ? "" : '<tr><td colspan="12">Sin datos para el periodo</td></tr>';
    diarios.forEach(dia => {
        const fila = document.createElement("tr");
        const coberturaEnergia = dia.energyCoveragePct === null ? "No disponible" : `${formatearNumero(dia.energyCoveragePct, 2)} %`;
        const coberturaEstados = dia.stateCoveragePct === null ? "No disponible" : `${formatearNumero(dia.stateCoveragePct, 2)} %`;
        fila.innerHTML = `<td>${escaparHtml(dia.productionDate)}</td><td>${formatearEntero(dia.goodUnits)}</td><td>${formatearNumero(dia.productiveElectricalHours, 3)}</td><td>${formatearNumero(dia.measuredEnergyKWh, 3)}</td><td>${formatearNumero(dia.reconstructedEnergyKWh, 3)}</td><td>${formatearNumero(dia.knownEnergyKWh, 3)}</td><td>${formatearNumero(dia.expectedEnergyKWh, 3)}</td><td>${formatearNumero(dia.residualKWh, 3)}</td><td>${dia.deviationPct === null ? "No disponible" : formatearNumero(dia.deviationPct, 2) + " %"}</td><td>${escaparHtml(dia.performanceClassification)}</td><td>${coberturaEnergia} / ${coberturaEstados}</td><td>${escaparHtml((dia.qualityFlags || []).join(", "))}</td>`;
        tbody.appendChild(fila);
    });
}

async function cargarBase100(snapshot = rangoSnapshotActual) {
    snapshot = requerirSnapshot(snapshot);
    const res = await fetch(`/api/linea-base/base-100?inicio=${snapshot.inicio}&fin=${snapshot.fin}`);
    const data = await res.json();
    if (!res.ok || data.error) return;

    const resumen = data.summary || {};
    document.getElementById("base100Periodo").innerText =
        resumen.periodBase100Index === null ? "Datos insuficientes" : formatearNumero(resumen.periodBase100Index, 3);
    document.getElementById("base100EnergiaConocida").innerText =
        formatearNumero(resumen.periodKnownEnergyKWh, 3);
    document.getElementById("base100EnergiaEsperada").innerText =
        formatearNumero(resumen.periodExpectedEnergyKWh, 3);
    document.getElementById("base100DiasIncluidos").innerText =
        formatearEntero(resumen.includedDays);
    document.getElementById("base100DiasExcluidos").innerText =
        `${formatearEntero(resumen.excludedDays)} (+${formatearEntero(resumen.insufficientDays)} insuf.)`;
    document.getElementById("base100Clasificacion").innerText =
        resumen.classification || "INSUFFICIENT_DATA";
    document.getElementById("base100Variabilidad").innerText =
        resumen.modelVariabilityPct === null ? "Datos insuficientes" : `±${formatearNumero(resumen.modelVariabilityPct, 2)} %`;

    const diarios = data.daily || [];
    const tbody = document.getElementById("tablaBase100Diaria");
    tbody.innerHTML = diarios.length ? "" : '<tr><td colspan="11">Sin datos para el periodo</td></tr>';
    diarios.forEach(dia => {
        const fila = document.createElement("tr");
        fila.innerHTML = `<td>${escaparHtml(dia.productionDate)}</td><td>${formatearNumero(dia.knownEnergyKWh, 3)}</td><td>${formatearNumero(dia.expectedEnergyKWh, 3)}</td><td>${dia.base100Index === null ? "No disponible" : formatearNumero(dia.base100Index, 3)}</td><td>${escaparHtml(dia.base100Classification)}</td><td>${dia.includedInPeriodIndex ? "Incluido" : "Excluido"}</td><td>${dia.energyCoveragePct === null ? "No disponible" : formatearNumero(dia.energyCoveragePct, 2) + " %"}</td><td>${dia.stateCoveragePct === null ? "No disponible" : formatearNumero(dia.stateCoveragePct, 2) + " %"}</td><td>${dia.reconstructedEnergyPct === null ? "No disponible" : formatearNumero(dia.reconstructedEnergyPct, 2) + " %"}</td><td>${escaparHtml((dia.qualityFlags || []).join(", "))}</td><td>${escaparHtml((dia.exclusionReasons || []).join(", "))}</td>`;
        tbody.appendChild(fila);
    });

    if (chartBase100Diario) chartBase100Diario.destroy();
    const reference = diarios.map(() => 100);
    const lower = diarios.map(() => resumen.favorableLimit);
    const upper = diarios.map(() => resumen.unfavorableLimit);
    chartBase100Diario = new Chart(document.getElementById("chartBase100Diario"), {
        type: "line",
        data: {
            labels: diarios.map(dia => dia.productionDate),
            datasets: [
                { label: "Base 100 diario", data: diarios.map(dia => dia.base100Index), borderColor: "#2563eb", spanGaps: false },
                { label: "Referencia 100", data: reference, borderColor: "#475569", pointRadius: 0, borderDash: [5, 5] },
                { label: `Límite favorable ${formatearNumero(resumen.favorableLimit, 2)}`, data: lower, borderColor: "#16a34a", pointRadius: 0, borderDash: [3, 3] },
                { label: `Límite desfavorable ${formatearNumero(resumen.unfavorableLimit, 2)}`, data: upper, borderColor: "#dc2626", pointRadius: 0, borderDash: [3, 3] }
            ]
        },
        options: { scales: { y: { title: { display: true, text: "Índice Base 100" } } } }
    });
}

async function cargarCusum(snapshot = rangoSnapshotActual) {
    snapshot = requerirSnapshot(snapshot);
    const res = await fetch(`/api/linea-base/cusum?inicio=${snapshot.inicio}&fin=${snapshot.fin}`);
    const data = await res.json();
    if (!res.ok || data.error) return;

    const resumen = data.summary || {};
    document.getElementById("cusumFinal").innerText =
        formatearNumero(resumen.finalCusumKWh, 3);
    document.getElementById("cusumFavorables").innerText =
        formatearNumero(resumen.favorableAccumulatedKWh, 3);
    document.getElementById("cusumDesfavorables").innerText =
        formatearNumero(resumen.unfavorableAccumulatedKWh, 3);
    document.getElementById("cusumDiasEvaluables").innerText =
        formatearEntero(resumen.evaluableDays);
    document.getElementById("cusumDiasExcluidos").innerText =
        `${formatearEntero(resumen.excludedDays)} (+${formatearEntero(resumen.missingDays)} falt.)`;
    document.getElementById("cusumDesviacion").innerText =
        resumen.periodDeviationPct === null ? "Datos insuficientes" : `${formatearNumero(resumen.periodDeviationPct, 3)} %`;
    document.getElementById("cusumBase100").innerText =
        formatearNumero(resumen.periodBase100Index, 3);

    const diarios = data.daily || [];
    const tbody = document.getElementById("tablaCusumDiaria");
    tbody.innerHTML = diarios.length ? "" : '<tr><td colspan="14">Sin datos para el periodo</td></tr>';
    diarios.forEach(dia => {
        const fila = document.createElement("tr");
        const coberturaEnergia = dia.energyCoveragePct === null ? "No disponible" : `${formatearNumero(dia.energyCoveragePct, 2)} %`;
        const coberturaEstados = dia.stateCoveragePct === null ? "No disponible" : `${formatearNumero(dia.stateCoveragePct, 2)} %`;
        fila.innerHTML = `<td>${escaparHtml(dia.productionDate)}</td><td>${formatearNumero(dia.knownEnergyKWh, 3)}</td><td>${formatearNumero(dia.expectedEnergyKWh, 3)}</td><td>${dia.residualKWh === null ? "No disponible" : formatearNumero(dia.residualKWh, 3)}</td><td>${dia.cusumContributionKWh === null ? "No disponible" : formatearNumero(dia.cusumContributionKWh, 3)}</td><td>${formatearNumero(dia.cusumKWh, 3)}</td><td>${formatearNumero(dia.positiveCusumKWh, 3)}</td><td>${formatearNumero(dia.negativeCusumKWh, 3)}</td><td>${dia.base100Index === null ? "No disponible" : formatearNumero(dia.base100Index, 3)}</td><td>${escaparHtml(dia.performanceClassification)}</td><td>${dia.includedInCusum ? "Incluido" : "Excluido"}</td><td>${coberturaEnergia} / ${coberturaEstados}</td><td>${escaparHtml((dia.qualityFlags || []).join(", "))}</td><td>${escaparHtml((dia.exclusionReasons || []).join(", "))}</td>`;
        tbody.appendChild(fila);
    });

    if (chartCusumDiario) chartCusumDiario.destroy();
    chartCusumDiario = new Chart(document.getElementById("chartCusumDiario"), {
        type: "line",
        data: {
            labels: diarios.map(dia => dia.productionDate),
            datasets: [
                { label: "Residuo diario kWh", data: diarios.map(dia => dia.cusumContributionKWh), borderColor: "#f59e0b", spanGaps: false },
                { label: "CUSUM firmado kWh", data: diarios.map(dia => dia.cusumKWh), borderColor: "#2563eb" },
                { label: "CUSUM positivo", data: diarios.map(dia => dia.positiveCusumKWh), borderColor: "#dc2626", borderDash: [4, 3], pointRadius: 0 },
                { label: "CUSUM negativo", data: diarios.map(dia => dia.negativeCusumKWh), borderColor: "#16a34a", borderDash: [4, 3], pointRadius: 0 },
                { label: "Referencia 0", data: diarios.map(() => 0), borderColor: "#475569", borderDash: [5, 5], pointRadius: 0 },
                { label: "Jornada excluida", data: diarios.map(dia => dia.includedInCusum ? null : dia.cusumKWh), borderColor: "#7c3aed", backgroundColor: "#7c3aed", showLine: false, pointRadius: 5 }
            ]
        },
        options: { scales: { y: { title: { display: true, text: "kWh" } } } }
    });
}

async function cargarImpacto(snapshot = rangoSnapshotActual) {
    snapshot = requerirSnapshot(snapshot);
    const res = await fetch(`/api/linea-base/impacto?inicio=${snapshot.inicio}&fin=${snapshot.fin}`);
    const data = await res.json();
    if (!res.ok || data.error) return;

    const resumen = data.summary || {};
    const inputs = data.inputs || {};
    document.getElementById("impactoResidual").innerText =
        resumen.periodResidualKWh === null ? "Datos insuficientes" : `${formatearNumero(resumen.periodResidualKWh, 3)} kWh`;
    document.getElementById("impactoCostoEvitado").innerText =
        resumen.periodEstimatedAvoidedCostCop === null ? "Tarifa no configurada" : `${formatearNumero(resumen.periodEstimatedAvoidedCostCop, 2)} COP`;
    document.getElementById("impactoSobrecosto").innerText =
        resumen.periodEstimatedAdditionalCostCop === null ? "Tarifa no configurada" : `${formatearNumero(resumen.periodEstimatedAdditionalCostCop, 2)} COP`;
    document.getElementById("impactoEmisionesEvitadas").innerText =
        resumen.periodEstimatedAvoidedEmissionsKgCo2e === null ? "Factor de emisión no configurado" : `${formatearNumero(resumen.periodEstimatedAvoidedEmissionsKgCo2e, 3)} kgCO2e`;
    document.getElementById("impactoEmisionesAdicionales").innerText =
        resumen.periodEstimatedAdditionalEmissionsKgCo2e === null ? "Factor de emisión no configurado" : `${formatearNumero(resumen.periodEstimatedAdditionalEmissionsKgCo2e, 3)} kgCO2e`;
    document.getElementById("impactoTarifa").innerText =
        inputs.energyTariffCopPerKWh === null ? "Tarifa no configurada" : `${formatearNumero(inputs.energyTariffCopPerKWh, 3)} COP/kWh`;
    document.getElementById("impactoFactorEmision").innerText =
        inputs.emissionFactorKgCo2ePerKWh === null ? "Factor de emisión no configurado" : `${formatearNumero(inputs.emissionFactorKgCo2ePerKWh, 6)} kgCO2e/kWh`;
    document.getElementById("impactoDiasEvaluables").innerText =
        formatearEntero(resumen.evaluableDays);
    document.getElementById("impactoDiasExcluidos").innerText =
        formatearEntero(resumen.excludedDays);

    const diarios = data.daily || [];
    const tbody = document.getElementById("tablaImpactoDiaria");
    tbody.innerHTML = diarios.length ? "" : '<tr><td colspan="15">Sin datos para el periodo</td></tr>';
    diarios.forEach(dia => {
        const fila = document.createElement("tr");
        fila.innerHTML = `<td>${escaparHtml(dia.productionDate)}</td><td>${dia.residualKWh === null ? "No disponible" : formatearNumero(dia.residualKWh, 3)}</td><td>${dia.base100Index === null ? "No disponible" : formatearNumero(dia.base100Index, 3)}</td><td>${dia.cusumKWh === null ? "No disponible" : formatearNumero(dia.cusumKWh, 3)}</td><td>${dia.energyTariffCopPerKWh === null ? "No configurada" : formatearNumero(dia.energyTariffCopPerKWh, 3)}</td><td>${dia.economicImpactCop === null ? "No disponible" : formatearNumero(dia.economicImpactCop, 2)}</td><td>${dia.estimatedAvoidedCostCop === null ? "No disponible" : formatearNumero(dia.estimatedAvoidedCostCop, 2)}</td><td>${dia.estimatedAdditionalCostCop === null ? "No disponible" : formatearNumero(dia.estimatedAdditionalCostCop, 2)}</td><td>${dia.emissionFactorKgCo2ePerKWh === null ? "No configurado" : formatearNumero(dia.emissionFactorKgCo2ePerKWh, 6)}</td><td>${dia.co2eImpactKg === null ? "No disponible" : formatearNumero(dia.co2eImpactKg, 3)}</td><td>${dia.estimatedAvoidedEmissionsKgCo2e === null ? "No disponible" : formatearNumero(dia.estimatedAvoidedEmissionsKgCo2e, 3)}</td><td>${dia.estimatedAdditionalEmissionsKgCo2e === null ? "No disponible" : formatearNumero(dia.estimatedAdditionalEmissionsKgCo2e, 3)}</td><td>${dia.includedInImpact ? "Incluido" : "Excluido"}</td><td>${escaparHtml((dia.qualityFlags || []).join(", "))}</td><td>${escaparHtml((dia.exclusionReasons || []).join(", "))}</td>`;
        tbody.appendChild(fila);
    });

    if (chartImpactoEconomico) chartImpactoEconomico.destroy();
    chartImpactoEconomico = new Chart(document.getElementById("chartImpactoEconomico"), {
        type: "line",
        data: {
            labels: diarios.map(dia => dia.productionDate),
            datasets: [
                { label: "Impacto económico diario COP", data: diarios.map(dia => dia.economicImpactCop), borderColor: "#2563eb", spanGaps: false },
                { label: "Costo evitado estimado", data: diarios.map(dia => dia.estimatedAvoidedCostCop), borderColor: "#16a34a", spanGaps: false },
                { label: "Sobrecosto estimado", data: diarios.map(dia => dia.estimatedAdditionalCostCop), borderColor: "#dc2626", spanGaps: false },
                { label: "Referencia 0", data: diarios.map(() => 0), borderColor: "#475569", borderDash: [5, 5], pointRadius: 0 }
            ]
        }
    });
    if (chartImpactoAmbiental) chartImpactoAmbiental.destroy();
    chartImpactoAmbiental = new Chart(document.getElementById("chartImpactoAmbiental"), {
        type: "line",
        data: {
            labels: diarios.map(dia => dia.productionDate),
            datasets: [
                { label: "Impacto diario kgCO2e", data: diarios.map(dia => dia.co2eImpactKg), borderColor: "#2563eb", spanGaps: false },
                { label: "Emisiones evitadas estimadas", data: diarios.map(dia => dia.estimatedAvoidedEmissionsKgCo2e), borderColor: "#16a34a", spanGaps: false },
                { label: "Emisiones adicionales estimadas", data: diarios.map(dia => dia.estimatedAdditionalEmissionsKgCo2e), borderColor: "#dc2626", spanGaps: false },
                { label: "Referencia 0", data: diarios.map(() => 0), borderColor: "#475569", borderDash: [5, 5], pointRadius: 0 }
            ]
        }
    });
}

async function cargarCalidad(snapshot = rangoSnapshotActual) {
    const data = (await obtenerFase2(snapshot)).production || {};
    document.getElementById("calidadBuenos").innerText = formatearEntero(data.envases_buenos);
    document.getElementById("calidadMalos").innerText = formatearEntero(data.envases_malos);
    document.getElementById("calidadTotal").innerText = formatearEntero(data.produccion_total);
    document.getElementById("calidadEficiencia").innerText = data.eficiencia_calidad_pct === null ? "Datos insuficientes" : `${formatearNumero(data.eficiencia_calidad_pct, 2)} %`;
    document.getElementById("calidadRechazo").innerText = data.tasa_rechazo_pct === null ? "Datos insuficientes" : `${formatearNumero(data.tasa_rechazo_pct, 2)} %`;
    document.getElementById("calidadPorMil").innerText = data.rechazos_por_1000 === null ? "Datos insuficientes" : formatearNumero(data.rechazos_por_1000, 2);
}

async function cargarDashboard(snapshot = rangoSnapshotActual) {
    const integrado = await obtenerFase2(snapshot);
    const data = integrado.legacyDashboard || {};
    const operacion = integrado.production || {};
    const resumenEstados = integrado.electricalStates?.periodSummary || {};
    const resumenEnergia = integrado.energy?.periodSummary || {};

    document.getElementById("energiaTotalizador").innerText =
        formatearNumero(data.totalizador?.energia_kwh, 3);

    document.getElementById("energiaProceso").innerText =
        formatearNumero(resumenEnergia.knownEnergyKWh, 3);

    document.getElementById("potenciaTotalizador").innerText =
        formatearNumero(data.totalizador?.potencia_actual_kw, 2);

    document.getElementById("potenciaProceso").innerText =
        formatearNumero(data.proceso?.potencia_actual_kw, 2);

    document.getElementById("produccion").innerText =
        formatearEntero(data.produccion?.envases_periodo);

    document.getElementById("enpiTotalizador").innerText =
        formatearNumero(data.enpi?.kwh_por_1000_envases_totalizador, 3);

    document.getElementById("enpiProceso").innerText =
        formatearNumero(data.enpi?.kwh_por_1000_envases_proceso, 3);

    document.getElementById("participacionProceso").innerText =
        formatearNumero(data.proceso?.participacion_totalizador_pct, 2);

    document.getElementById("horasProductivasResumen").innerText = resumenEstados.productiveHours == null ? "Datos insuficientes" : formatearNumero(resumenEstados.productiveHours, 2);
    document.getElementById("horasParadaResumen").innerText = operacion.horas_parada_reportadas === null ? "Dato pendiente" : formatearNumero(operacion.horas_parada_reportadas, 2);
    document.getElementById("coberturaEstadosResumen").innerText = resumenEstados.coveragePct == null ? "Datos insuficientes" : `${formatearNumero(resumenEstados.coveragePct, 2)} %`;
    document.getElementById("coberturaEnergiaResumen").innerText = resumenEnergia.energyCoveragePct == null ? "Datos insuficientes" : `${formatearNumero(resumenEnergia.energyCoveragePct, 2)} %`;
}

async function cargarEstado() {
    const res = await fetch("/api/estado");
    const data = await res.json();

    const estadoDatos = document.getElementById("estadoDatos");
    estadoDatos.innerText = `Estado actual: ${data.estado_datos || "--"}`;
    estadoDatos.classList.remove("estado-ok", "estado-alerta", "estado-error");

    if (data.estado_datos === "OK") {
        estadoDatos.classList.add("estado-ok");
    } else {
        estadoDatos.classList.add("estado-alerta");
    }

    document.getElementById("ultimaMedicion").innerText =
        `Última medición disponible (fuera del filtro): ${data.ultima_medicion_colombia || "--"}`;

    document.getElementById("estadoGateway").innerText =
        `${data.gateway || "--"} ID ${data.gateway_id || ""}`;

    document.getElementById("estadoCliente").innerText =
        data.cliente || "--";

    document.getElementById("estadoUltima").innerText =
        data.ultima_medicion_colombia || "--";

    document.getElementById("estadoEdad").innerText =
        formatearEdadSegundos(data.edad_segundos);

    document.getElementById("estadoRam").innerText =
        data.ram !== null && data.ram !== undefined ? `${data.ram} %` : "--";

    document.getElementById("estadoCpu").innerText =
        data.cpu !== null && data.cpu !== undefined ? `${data.cpu} %` : "--";

    document.getElementById("estadoTemperaturaSistema").innerText =
        data.temperatura_sistema_c !== null && data.temperatura_sistema_c !== undefined
            ? `${formatearNumero(data.temperatura_sistema_c, 1)} °C`
            : "No disponible";

    document.getElementById("estadoTemperaturaFecha").innerText =
        data.temperatura_sistema_fecha_colombia || "No disponible";

    document.getElementById("estadoIpEth").innerText =
        reconstruirIpv4DesdeDigitos(data.ip_ethernet);

    document.getElementById("estadoConnect").innerText =
        data.connected_meter ?? "--";
}

async function cargarSelectorVariables() {
    const selector = document.getElementById("selectorVariable");

    if (!selector) {
        console.error("No existe selectorVariable en el HTML");
        return;
    }

    const variableAnterior = selector.value !== ""
        ? variablesDisponibles[Number(selector.value)]
        : null;
    const keyAnterior = variableSeleccionadaKey || obtenerKeyVariable(variableAnterior);

    selector.innerHTML = "";

    const optCargando = document.createElement("option");
    optCargando.value = "";
    optCargando.textContent = "Cargando variables...";
    selector.appendChild(optCargando);

    try {
        const res = await fetch("/api/variables");

        if (!res.ok) {
            throw new Error(`HTTP ${res.status} al consultar /api/variables`);
        }

        const data = await res.json();

        variablesDisponibles = Array.isArray(data.variables) ? data.variables : [];

        selector.innerHTML = "";

        const optDefault = document.createElement("option");
        optDefault.value = "";
        optDefault.textContent = `Seleccione una variable (${variablesDisponibles.length})...`;
        selector.appendChild(optDefault);

        if (!variablesDisponibles.length) {
            const opt = document.createElement("option");
            opt.value = "";
            opt.textContent = "No hay variables disponibles";
            selector.appendChild(opt);
            return;
        }

        const grupos = {};

        variablesDisponibles.forEach((v, index) => {
            const gateway = v.gateway || `Gateway ${v.gateway_id || ""}`;
            const dispositivo = v.dispositivo || (
                v.device_id ? `Device ${v.device_id}` : "Variables del gateway"
            );
            const rol = v.rol || v.source_type || "sin rol";

            const grupo = `${gateway} / ${dispositivo} (${rol})`;

            if (!grupos[grupo]) {
                grupos[grupo] = [];
            }

            grupos[grupo].push({
                ...v,
                index
            });
        });

        Object.keys(grupos).sort().forEach(nombreGrupo => {
            const optgroup = document.createElement("optgroup");
            optgroup.label = nombreGrupo;

            grupos[nombreGrupo]
                .sort((a, b) => Number(a.unit_id) - Number(b.unit_id))
                .forEach(v => {
                    const option = document.createElement("option");
                    option.value = String(v.index);

                    const variable = v.variable || `Variable ${v.unit_id}`;
                    const simbolo = v.simbolo || "";
                    const descripcion = v.descripcion || "";

                    option.textContent =
                        `Unit ${v.unit_id} | ${variable}` +
                        `${simbolo ? " [" + simbolo + "]" : ""}` +
                        `${descripcion ? " | " + descripcion : ""}` +
                        ` | ${formatearEntero(v.registros || 0)} reg.`;

                    optgroup.appendChild(option);
                });

            selector.appendChild(optgroup);
        });

        if (keyAnterior) {
            const indiceSeleccionado = variablesDisponibles.findIndex(v =>
                obtenerKeyVariable(v) === keyAnterior
            );

            if (indiceSeleccionado >= 0) {
                selector.value = String(indiceSeleccionado);
            }
        }

        console.log("Variables cargadas:", variablesDisponibles.length);

    } catch (error) {
        console.error("Error cargando variables:", error);

        selector.innerHTML = "";

        const optError = document.createElement("option");
        optError.value = "";
        optError.textContent = "Error cargando variables";
        selector.appendChild(optError);
    }
}

function destruirGrafica() {
    if (chartPrincipal) {
        chartPrincipal.destroy();
        chartPrincipal = null;
    }
}

async function obtenerSerie(unitId, deviceId, gatewayId = 10, limite = 5000, snapshot = rangoSnapshotActual) {
    snapshot = requerirSnapshot(snapshot);
    const granularidad = obtenerGranularidad();

    const params = new URLSearchParams({
        inicio: snapshot.inicio,
        fin: snapshot.fin,
        limite: limite,
        gateway_id: gatewayId,
        device_id: deviceId,
        source_type: "device",
        granularidad: granularidad
    });

    const data = await fetchJsonCacheado(`/api/serie-agregada/${unitId}?${params.toString()}`, snapshot);

    return data.serie || [];
}

async function mostrarGrafica(tipo, snapshot = rangoSnapshotActual) {
    snapshot = requerirSnapshot(snapshot);
    graficaActual = tipo;
    destruirGrafica();

    const ctx = document.getElementById("chartPrincipal").getContext("2d");

    if (tipo === "potencia") {
        document.getElementById("tituloGrafica").innerText =
            "Potencia activa total: Totalizador vs Proceso";

        const [serieTotal, serieProceso] = await Promise.all([
            obtenerSerie(61, 25, 10, 5000, snapshot),
            obtenerSerie(61, 24, 10, 5000, snapshot)
        ]);

        chartPrincipal = new Chart(ctx, {
            type: "line",
            data: {
                labels: serieTotal.map(x => formatearHoraColombia(x.timestamp_utc)),
                datasets: [
                    {
                        label: "Totalizador kW",
                        data: serieTotal.map(x => Number(x.valor)),
                        tension: 0.25,
                        pointRadius: 2
                    },
                    {
                        label: "Proceso kW",
                        data: serieProceso.map(x => Number(x.valor)),
                        tension: 0.25,
                        pointRadius: 2
                    }
                ]
            }
        });
    }

    if (tipo === "energia") {
        document.getElementById("tituloGrafica").innerText =
            "Energía activa acumulada: Totalizador vs Proceso";

        const [serieTotal, serieProceso] = await Promise.all([
            obtenerSerie(100, 25, 10, 5000, snapshot),
            obtenerSerie(100, 24, 10, 5000, snapshot)
        ]);

        chartPrincipal = new Chart(ctx, {
            type: "line",
            data: {
                labels: serieTotal.map(x => formatearHoraColombia(x.timestamp_utc)),
                datasets: [
                    {
                        label: "Totalizador kWh",
                        data: serieTotal.map(x => Number(x.valor)),
                        tension: 0.25,
                        pointRadius: 2
                    },
                    {
                        label: "Proceso kWh",
                        data: serieProceso.map(x => Number(x.valor)),
                        tension: 0.25,
                        pointRadius: 2
                    }
                ]
            }
        });
    }

    if (tipo === "enpi") {
        document.getElementById("tituloGrafica").innerText =
            "EnPI del periodo";

        const data = (await obtenerFase2(snapshot)).legacyDashboard || {};

        chartPrincipal = new Chart(ctx, {
            type: "bar",
            data: {
                labels: ["Totalizador", "Proceso"],
                datasets: [{
                    label: "kWh / 1000 envases",
                    data: [
                        data.enpi?.kwh_por_1000_envases_totalizador || 0,
                        data.enpi?.kwh_por_1000_envases_proceso || 0
                    ]
                }]
            }
        });
    }
    if (tipo === "linea_base") {
        document.getElementById("tituloGrafica").innerText =
            "Línea base ISO 50001: energía conocida vs esperada por jornada";

        const res = await fetch(`/api/linea-base/desempeno-diario?inicio=${snapshot.inicio}&fin=${snapshot.fin}`);
        const data = await res.json();
        const diarios = data.daily || [];

        chartPrincipal = new Chart(ctx, {
            type: "bar",
            data: {
                labels: diarios.map(dia => dia.productionDate),
                datasets: [
                    {
                        label: "Energía conocida kWh",
                        data: diarios.map(dia => dia.knownEnergyKWh)
                    },
                    {
                        label: "Energía esperada kWh",
                        data: diarios.map(dia => dia.expectedEnergyKWh)
                    }
                ]
            }
        });
    }
    if (tipo === "produccion") {
        document.getElementById("tituloGrafica").innerText =
            "Producción de envases por periodo";

        const periodos = (await obtenerFase2(snapshot)).production?.detalle_diario || [];

        chartPrincipal = new Chart(ctx, {
            type: "bar",
            data: {
                labels: periodos.map(x => x.fecha),
                datasets: [
                    {
                        label: "Envases buenos",
                        data: periodos.map(x => Number(x.envases_buenos || 0))
                    },
                    {
                        label: "Envases malos",
                        data: periodos.map(x => Number(x.envases_malos || 0))
                    }
                ]
            }
        });
    }
    if (tipo === "variable") {
        await graficarVariableSeleccionada(snapshot);
    }
}


async function graficarVariableSeleccionada(snapshot = rangoSnapshotActual) {
    const selector = document.getElementById("selectorVariable");

    if (!selector.value) {
        return;
    }

    const v = variablesDisponibles[Number(selector.value)];

    if (!v) return;

    graficaActual = "variable";
    variableSeleccionadaKey = obtenerKeyVariable(v);

    destruirGrafica();

    document.getElementById("tituloGrafica").innerText =
        `${v.dispositivo || "Gateway"} | Unit ${v.unit_id} | ${v.variable}`;

    snapshot = requerirSnapshot(snapshot);

    const params = new URLSearchParams({
        inicio: snapshot.inicio,
        fin: snapshot.fin,
        limite: 5000,
        gateway_id: v.gateway_id,
        source_type: v.source_type,
        granularidad: obtenerGranularidad()
    });

    if (v.device_id) {
        params.append("device_id", v.device_id);
    }

    const data = await fetchJsonCacheado(`/api/serie-agregada/${v.unit_id}?${params.toString()}`, snapshot);
    const serie = data.serie || [];

    const ctx = document.getElementById("chartPrincipal").getContext("2d");

    chartPrincipal = new Chart(ctx, {
        type: "line",
        data: {
            labels: serie.map(x => formatearHoraColombia(x.timestamp_utc)),
            datasets: [{
                label: `${v.variable || "Variable"} ${v.simbolo || ""}`,
                data: serie.map(x => Number(x.valor)),
                tension: 0.25,
                pointRadius: 2
            }]
        }
    });
}

async function cargarUltimosValores(snapshot = rangoSnapshotActual) {
    snapshot = requerirSnapshot(snapshot);
    const data = await fetchJsonCacheado(
        `/api/ultimos?inicio=${snapshot.inicio}&fin=${snapshot.fin}`,
        snapshot
    );

    ultimosValores = data.datos || [];

    pintarTablaUltimos(ultimosValores);
}

function formatearValorVariable(item) {
    const unitId = Number(item.unit_id);
    const valor = item.valor;

    if (unitId === 137 || unitId === 144) {
        return reconstruirIpv4DesdeDigitos(valor);
    }

    if ([58, 59, 60, 62, 63, 64, 65, 66, 67, 68, 69].includes(unitId)) {
        return formatearNumero(Number(valor) / 1000, 3);
    }

    return formatearNumero(valor, 3);
}

function unidadVisual(item) {
    const unitId = Number(item.unit_id);

    if ([58, 59, 60, 61].includes(unitId)) return "kW";
    if ([62, 63, 64, 65].includes(unitId)) return "kVAr";
    if ([66, 67, 68, 69].includes(unitId)) return "kVA";

    return item.simbol || "";
}

function pintarTablaUltimos(datos) {
    const tbody = document.getElementById("tablaUltimos");
    tbody.innerHTML = "";

    if (!datos.length) {
        tbody.innerHTML = `<tr><td colspan="8">No hay datos</td></tr>`;
        return;
    }

    datos.forEach(item => {
        const tr = document.createElement("tr");

        tr.innerHTML = `
            <td>${item.gateway || ""}</td>
            <td>${item.dispositivo || "Gateway"}</td>
            <td>${item.rol || ""}</td>
            <td>${item.unit_id}</td>
            <td>${item.variable || ""}</td>
            <td>${formatearValorVariable(item)}</td>
            <td>${unidadVisual(item)}</td>
            <td>${formatearHoraColombia(item.timestamp_utc)}</td>
        `;

        tbody.appendChild(tr);
    });
}

function filtrarTablaUltimos() {
    const texto = document.getElementById("buscarTabla").value.toLowerCase().trim();

    if (!texto) {
        pintarTablaUltimos(ultimosValores);
        return;
    }

    const filtrados = ultimosValores.filter(item => {
        return JSON.stringify(item).toLowerCase().includes(texto);
    });

    pintarTablaUltimos(filtrados);
}

async function actualizarTodo() {
    if (actualizacionEnCurso) {
        actualizacionPendiente = true;
        return;
    }
    actualizacionEnCurso = true;

    try {
        const snapshot = crearInstantaneaRango();
        await cargarEstado();

        if (moduloActual === "resumen") {
            await cargarDashboard(snapshot);
        } else if (moduloActual === "impacto") {
            await cargarImpacto(snapshot);
        } else if (moduloActual === "produccion") {
            await cargarProduccion(snapshot);
        } else if (moduloActual === "calidad") {
            await cargarCalidad(snapshot);
        } else if (moduloActual === "eficiencia-operacional") {
            await cargarEstadosAoki(snapshot);
        } else if (moduloActual === "eficiencia-energetica") {
            await cargarEnergiaReconstruidaAoki(snapshot);
        } else if (moduloActual === "linea-base") {
            await cargarLineaBase(snapshot);
            const vistaBase100 = document.querySelector('[data-linea-base-view="indice-base-100"]');
            if (vistaBase100 && !vistaBase100.hidden) await cargarBase100(snapshot);
            const vistaCusum = document.querySelector('[data-linea-base-view="cusum"]');
            if (vistaCusum && !vistaCusum.hidden) await cargarCusum(snapshot);
        } else if (moduloActual === "confiabilidad") {
            await cargarMantenimiento(snapshot);
        } else if (moduloActual === "variables") {
            if (!variablesDisponibles.length) await cargarSelectorVariables();
            await cargarUltimosValores(snapshot);
            if (graficaActual) await mostrarGrafica(graficaActual, snapshot);
        }
    } finally {
        actualizacionEnCurso = false;
        if (actualizacionPendiente) {
            actualizacionPendiente = false;
            await actualizarTodo();
        }
    }
}

async function navegarAModulo(nombre, actualizarHash = true) {
    const existe = document.querySelector(`[data-module="${nombre}"]`);
    moduloActual = existe ? nombre : "resumen";

    document.querySelectorAll("[data-module]").forEach(elemento => {
        elemento.hidden = elemento.dataset.module !== moduloActual;
    });
    document.querySelectorAll("[data-module-target]").forEach(boton => {
        const activo = boton.dataset.moduleTarget === moduloActual;
        boton.classList.toggle("activo", activo);
        boton.setAttribute("aria-current", activo ? "page" : "false");
    });

    if (actualizarHash) history.replaceState(null, "", `#${moduloActual}`);
    await actualizarTodo();
}

function inicializarNavegacion() {
    document.querySelectorAll("[data-module-target]").forEach(boton => {
        boton.addEventListener("click", () => navegarAModulo(boton.dataset.moduleTarget));
    });
    const moduloInicial = window.location.hash.slice(1) || "resumen";
    return navegarAModulo(moduloInicial, false);
}

function inicializarVistasLineaBase() {
    document.querySelectorAll("[data-linea-base-target]").forEach(boton => {
        boton.addEventListener("click", async () => {
            const vistaSeleccionada = boton.dataset.lineaBaseTarget;

            document.querySelectorAll("[data-linea-base-view]").forEach(vista => {
                vista.hidden = vista.dataset.lineaBaseView !== vistaSeleccionada;
            });
            document.querySelectorAll("[data-linea-base-target]").forEach(item => {
                const activo = item.dataset.lineaBaseTarget === vistaSeleccionada;
                item.classList.toggle("activo", activo);
                item.setAttribute("aria-current", activo ? "page" : "false");
            });
            if (vistaSeleccionada === "indice-base-100") {
                await cargarBase100(rangoSnapshotActual);
            } else if (vistaSeleccionada === "cusum") {
                await cargarCusum(rangoSnapshotActual);
            }
        });
    });
}

function inicializarFiltros() {
    const selectorRango = document.getElementById("rangoTiempo");
    const selectorGranularidad = document.getElementById("granularidad");
    const inputInicio = document.getElementById("fechaInicioManual");
    const inputFin = document.getElementById("fechaFinManual");

    if (selectorRango) {
        selectorRango.value = rangoActual;

        selectorRango.addEventListener("change", async (e) => {
            rangoActual = e.target.value;
            await actualizarTodo();
        });
    }

    if (selectorGranularidad) {
        selectorGranularidad.addEventListener("change", async () => {
            await actualizarTodo();
        });
    }

    if (inputInicio) {
        inputInicio.addEventListener("change", () => {
            if (selectorRango) selectorRango.value = "manual";
            rangoActual = "manual";
        });
    }

    if (inputFin) {
        inputFin.addEventListener("change", () => {
            if (selectorRango) selectorRango.value = "manual";
            rangoActual = "manual";
        });
    }

}

function inicializarFiltrosConciliacion() {
    [
        "filtroConciliacionClasificacion", "filtroConciliacionConfianza",
        "filtroConciliacionEstado", "filtroConciliacionJornada",
        "filtroConciliacionRevision"
    ].forEach(id => document.getElementById(id)?.addEventListener("change", renderizarConciliacionAoki));
}

function inicializarFiltrosMantenimiento() {
    ["filtroMantSugerencia", "filtroMantValidacion"].forEach(
        id => document.getElementById(id)?.addEventListener("change", renderizarMantenimiento)
    );
    document.getElementById("mantGuardarValidacion")?.addEventListener(
        "click", guardarValidacionMantenimiento
    );
    document.getElementById("mantGuardarVentana")?.addEventListener(
        "click", guardarVentanaOperacion
    );
}

async function iniciarDashboard() {
    await cargarRangosProduccion();
    inicializarFiltros();
    inicializarFiltrosConciliacion();
    inicializarFiltrosMantenimiento();
    inicializarVistasLineaBase();
    await inicializarNavegacion();

    setInterval(actualizarTodo, 30000);
}

async function cargarRangosProduccion() {
    const selector = document.getElementById("rangoTiempo");

    if (!selector) return;

    let meses = [];

    try {
        const res = await fetch("/api/produccion/meses");
        const data = await res.json();
        meses = data.meses || [];
    } catch (error) {
        console.error("No se pudieron cargar meses de producción:", error);
        meses = [];
    }

    mesesProduccion = meses;

    selector.innerHTML = "";

    const opcionesBase = [
        ["ultimos_datos", "Últimos datos disponibles"],
        ["manual", "Manual"],
        ["hora", "Última hora"],
        ["hoy", "Hoy"],
        ["semana", "Últimos 7 días"],
        ["mes", "Últimos 30 días"],
        ["prod_todo", "Todo producción"]
    ];

    opcionesBase.forEach(([value, label]) => {
        const opt = document.createElement("option");
        opt.value = value;
        opt.textContent = label;
        selector.appendChild(opt);
    });

    mesesProduccion.forEach(m => {
        const opt = document.createElement("option");
        opt.value = `prod_mes:${m.mes}`;
        opt.textContent = `${m.mes} | ${formatearEntero(m.envases_total)} envases`;
        selector.appendChild(opt);
    });

    selector.value = rangoActual;
}
if (typeof document !== "undefined") iniciarDashboard();

if (typeof module !== "undefined" && module.exports) {
    module.exports = { datetimeLocalAUnix, unixADatetimeLocal, unixDesdeColombia, rangoMesProduccion };
}
