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

    const fecha = new Date(valor);

    if (Number.isNaN(fecha.getTime())) {
        return null;
    }

    return Math.floor(fecha.getTime() / 1000);
}

function unixADatetimeLocal(timestamp) {
    const fecha = new Date(timestamp * 1000);
    const year = fecha.getFullYear();
    const month = String(fecha.getMonth() + 1).padStart(2, "0");
    const day = String(fecha.getDate()).padStart(2, "0");
    const hour = String(fecha.getHours()).padStart(2, "0");
    const minute = String(fecha.getMinutes()).padStart(2, "0");

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

async function cargarProduccion() {
    const rango = obtenerRangoUnix();

    const resResumen = await fetch(`/api/produccion/modulo?inicio=${rango.inicio}&fin=${rango.fin}`);
    const resumen = await resResumen.json();

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

async function cargarEstadosAoki() {
    const rango = obtenerRangoUnix();
    const respuesta = await fetch(`/api/aoki/estados?inicio=${rango.inicio}&fin=${rango.fin}`);
    const data = await respuesta.json();
    if (!respuesta.ok) throw new Error(data.error || "No fue posible clasificar los estados de Aoki");
    const diarios = data.daily || [];
    const sumar = campo => diarios.reduce((total, dia) => total + Number(dia[campo] || 0), 0);
    const programadas = sumar("scheduledHours");
    const productivas = sumar("productiveHours");
    const espera = sumar("idleHours");
    const apagado = sumar("offHours");
    const sinDatos = sumar("noDataHours");
    const cobertura = programadas > 0 ? (programadas - sinDatos) / programadas * 100 : null;
    document.getElementById("estadoHorasProductivas").innerText = formatearNumero(productivas, 2);
    document.getElementById("estadoHorasEspera").innerText = formatearNumero(espera, 2);
    document.getElementById("estadoHorasApagado").innerText = formatearNumero(apagado, 2);
    document.getElementById("estadoHorasSinDatos").innerText = formatearNumero(sinDatos, 2);
    document.getElementById("estadoCobertura").innerText = cobertura === null ? "Datos insuficientes" : `${formatearNumero(cobertura, 2)} %`;
    document.getElementById("estadoInconsistencias").innerText = formatearEntero(sumar("inconsistentSegments"));
    const umbrales = data.thresholds || {};
    document.getElementById("estadoCriterio").innerText = `Criterio ${umbrales.version || "--"}: OFF < ${umbrales.offIdleCurrentA} A; IDLE < ${umbrales.idleProductiveCurrentA} A; persistencia ${umbrales.minimumConsecutiveSamples} muestras o ${umbrales.minimumPersistenceMinutes} min; hueco máximo ${umbrales.maximumGapMinutes} min.`;

    const tbody = document.getElementById("tablaEstadosAoki");
    tbody.innerHTML = diarios.length ? "" : '<tr><td colspan="8">Sin datos para el periodo</td></tr>';
    diarios.forEach(dia => {
        const fila = document.createElement("tr");
        fila.innerHTML = `<td>${escaparHtml(dia.productionDate)}</td><td>${formatearNumero(dia.productiveHours, 2)}</td><td>${formatearNumero(dia.idleHours, 2)}</td><td>${formatearNumero(dia.offHours, 2)}</td><td>${formatearNumero(dia.noDataHours, 2)}</td><td>${formatearNumero(dia.coveragePct, 2)} %</td><td>${formatearEntero(dia.stateTransitions)}</td><td>${formatearEntero(dia.inconsistentSegments)}</td>`;
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

async function cargarEnergiaReconstruidaAoki() {
    const rango = obtenerRangoUnix();
    const respuesta = await fetch(`/api/aoki/energia-reconstruida?inicio=${rango.inicio}&fin=${rango.fin}`);
    const data = await respuesta.json();
    if (!respuesta.ok) throw new Error(data.error || "No fue posible reconstruir la energía de Aoki");
    const diarios = data.daily || [];
    const sumar = campo => diarios.reduce((total, dia) => total + Number(dia[campo] || 0), 0);
    const total = sumar("calculatedEnergyKWh");
    const medida = sumar("measuredEnergyKWh");
    const reconstruida = sumar("reconstructedEnergyKWh");
    const intervalosNoData = sumar("noDataIntervals");
    const duracionTotal = (data.intervals || []).reduce((suma, intervalo) => suma + Number(intervalo.durationSeconds || 0), 0);
    const duracionNoData = (data.intervals || []).filter(i => i.source === "NO_DATA").reduce((suma, intervalo) => suma + Number(intervalo.durationSeconds || 0), 0);
    const cobertura = duracionTotal > 0 ? (duracionTotal - duracionNoData) / duracionTotal * 100 : null;
    const porcentajeReconstruido = total > 0 ? reconstruida / total * 100 : null;
    document.getElementById("energiaReconTotal").innerText = formatearNumero(total, 3);
    document.getElementById("energiaReconMedida").innerText = formatearNumero(medida, 3);
    document.getElementById("energiaReconEstimada").innerText = formatearNumero(reconstruida, 3);
    document.getElementById("energiaReconCobertura").innerText = cobertura === null ? "Datos insuficientes" : `${formatearNumero(cobertura, 2)} %`;
    document.getElementById("energiaReconPct").innerText = porcentajeReconstruido === null ? "Datos insuficientes" : `${formatearNumero(porcentajeReconstruido, 2)} %`;
    document.getElementById("energiaReconNoData").innerText = formatearEntero(intervalosNoData);
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

async function cargarLineaBase() {
    const rango = obtenerRangoUnix();

    const res = await fetch(`/api/linea-base?inicio=${rango.inicio}&fin=${rango.fin}`);
    const data = await res.json();

    if (data.ok === false || data.error) {
        document.getElementById("lbClasificacion").innerText = "Sin modelo";
        document.getElementById("lbMensaje").innerText = data.error || "No hay datos suficientes";
        return;
    }

    document.getElementById("lbEnergiaReal").innerText =
        formatearNumero(data.energia?.real_kwh, 3);

    document.getElementById("lbEnergiaEsperada").innerText =
        formatearNumero(data.energia?.esperada_kwh, 3);

    document.getElementById("lbDesviacionPct").innerText =
        formatearNumero(data.energia?.desviacion_pct, 2);

    document.getElementById("lbAhorroKwh").innerText =
        formatearNumero(data.energia?.ahorro_kwh, 3);

    document.getElementById("lbAhorroCop").innerText =
        formatearEntero(data.impacto?.ahorro_cop);

    document.getElementById("lbClasificacion").innerText =
        data.clasificacion || "--";

    document.getElementById("lbMensaje").innerText =
        data.mensaje || "ISO 50001";

    const beta0 = data.modelo?.intercepto;
    const betaEnvases = data.modelo?.coef_envases_buenos;
    const betaHoras = data.modelo?.coef_horas_productivas;

    if (beta0 !== undefined && betaEnvases !== undefined && betaHoras !== undefined) {
        document.getElementById("lbModelo").innerText =
            `${formatearNumero(beta0, 2)} + ${formatearNumero(betaEnvases, 6)} × envases + ` +
            `${formatearNumero(betaHoras, 4)} × horas`;
    } else {
        document.getElementById("lbModelo").innerText = "--";
    }

    document.getElementById("lbR2").innerText =
        formatearNumero(data.modelo?.r2, 3);
}


async function entrenarLineaBase() {
    const ok = confirm("¿Desea reentrenar la línea base energética con muestras simuladas?");

    if (!ok) {
        return;
    }

    const res = await fetch("/api/linea-base/entrenar?dias=30");
    const data = await res.json();

    if (data.ok) {
        alert("Línea base reentrenada correctamente.");
    } else {
        alert("No fue posible entrenar la línea base.");
    }

    await cargarLineaBase();
}

async function cargarDashboard() {
    const rango = obtenerRangoUnix();

    const res = await fetch(`/api/dashboard?inicio=${rango.inicio}&fin=${rango.fin}`);
    const data = await res.json();

    document.getElementById("energiaTotalizador").innerText =
        formatearNumero(data.totalizador?.energia_kwh, 3);

    document.getElementById("energiaProceso").innerText =
        formatearNumero(data.proceso?.energia_kwh, 3);

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

    document.getElementById("costoTotalizador").innerText =
        formatearEntero(data.impacto?.costo_totalizador_cop);

    document.getElementById("costoProceso").innerText =
        formatearEntero(data.impacto?.costo_proceso_cop);

    document.getElementById("co2Totalizador").innerText =
        formatearNumero(data.impacto?.co2_totalizador_kg, 2);

    document.getElementById("co2Proceso").innerText =
        formatearNumero(data.impacto?.co2_proceso_kg, 2);
}

async function cargarEstado() {
    const res = await fetch("/api/estado");
    const data = await res.json();

    const estadoDatos = document.getElementById("estadoDatos");
    estadoDatos.innerText = data.estado_datos || "--";
    estadoDatos.classList.remove("estado-ok", "estado-alerta", "estado-error");

    if (data.estado_datos === "OK") {
        estadoDatos.classList.add("estado-ok");
    } else {
        estadoDatos.classList.add("estado-alerta");
    }

    document.getElementById("ultimaMedicion").innerText =
        `Última medición: ${data.ultima_medicion_colombia || "--"}`;

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

async function obtenerSerie(unitId, deviceId, gatewayId = 10, limite = 5000) {
    const rango = obtenerRangoUnix();
    const granularidad = obtenerGranularidad();

    const params = new URLSearchParams({
        inicio: rango.inicio,
        fin: rango.fin,
        limite: limite,
        gateway_id: gatewayId,
        device_id: deviceId,
        source_type: "device",
        granularidad: granularidad
    });

    const res = await fetch(`/api/serie-agregada/${unitId}?${params.toString()}`);
    const data = await res.json();

    return data.serie || [];
}

async function mostrarGrafica(tipo) {
    graficaActual = tipo;
    destruirGrafica();

    const ctx = document.getElementById("chartPrincipal").getContext("2d");

    if (tipo === "potencia") {
        document.getElementById("tituloGrafica").innerText =
            "Potencia activa total: Totalizador vs Proceso";

        const serieTotal = await obtenerSerie(61, 25);
        const serieProceso = await obtenerSerie(61, 24);

        chartPrincipal = new Chart(ctx, {
            type: "line",
            data: {
                labels: serieTotal.map(x => formatearHoraColombia(x.timestamp_utc)),
                datasets: [
                    {
                        label: "Totalizador kW",
                        data: serieTotal.map(x => Number(x.valor) / 1000),
                        tension: 0.25,
                        pointRadius: 2
                    },
                    {
                        label: "Proceso kW",
                        data: serieProceso.map(x => Number(x.valor) / 1000),
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

        const serieTotal = await obtenerSerie(100, 25);
        const serieProceso = await obtenerSerie(100, 24);

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

        const rango = obtenerRangoUnix();
        const res = await fetch(`/api/dashboard?inicio=${rango.inicio}&fin=${rango.fin}`);
        const data = await res.json();

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
            "Línea base ISO 50001: Energía real vs esperada";

        const rango = obtenerRangoUnix();

        const res = await fetch(`/api/linea-base?inicio=${rango.inicio}&fin=${rango.fin}`);
        const data = await res.json();

        const energiaReal = data.energia?.real_kwh || 0;
        const energiaEsperada = data.energia?.esperada_kwh || 0;
        const ahorro = data.energia?.ahorro_kwh || 0;
        const sobreconsumo = data.energia?.sobreconsumo_kwh || 0;

        chartPrincipal = new Chart(ctx, {
            type: "bar",
            data: {
                labels: ["Real", "Esperada", "Ahorro", "Sobreconsumo"],
                datasets: [{
                    label: "kWh",
                    data: [
                        energiaReal,
                        energiaEsperada,
                        ahorro,
                        sobreconsumo
                    ]
                }]
            }
        });
    }
    if (tipo === "produccion") {
        document.getElementById("tituloGrafica").innerText =
            "Producción de envases por periodo";

        const rango = obtenerRangoUnix();

        const res = await fetch(`/api/produccion?inicio=${rango.inicio}&fin=${rango.fin}`);
        const data = await res.json();

        const periodos = data.periodos || [];

        chartPrincipal = new Chart(ctx, {
            type: "bar",
            data: {
                labels: periodos.map(x => x.fecha_hora_inicio_local),
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
        await graficarVariableSeleccionada();
    }
}


async function graficarVariableSeleccionada() {
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

    const rango = obtenerRangoUnix();

    const params = new URLSearchParams({
        inicio: rango.inicio,
        fin: rango.fin,
        limite: 5000,
        gateway_id: v.gateway_id,
        source_type: v.source_type,
        granularidad: obtenerGranularidad()
    });

    if (v.device_id) {
        params.append("device_id", v.device_id);
    }

    const res = await fetch(`/api/serie-agregada/${v.unit_id}?${params.toString()}`);
    const data = await res.json();
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

async function cargarUltimosValores() {
    const res = await fetch("/api/ultimos");
    const data = await res.json();

    ultimosValores = data.datos || [];

    pintarTablaUltimos(ultimosValores);
}

function formatearValorVariable(item) {
    const unitId = Number(item.unit_id);
    const valor = item.valor;

    if (unitId === 137 || unitId === 144) {
        return reconstruirIpv4DesdeDigitos(valor);
    }

    if ([58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69].includes(unitId)) {
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
    if (actualizacionEnCurso) return;
    actualizacionEnCurso = true;

    try {
        obtenerRangoUnix();
        await cargarEstado();

        if (moduloActual === "resumen" || moduloActual === "impacto") {
            await cargarDashboard();
        } else if (moduloActual === "produccion") {
            await cargarProduccion();
        } else if (moduloActual === "eficiencia-operacional") {
            await cargarEstadosAoki();
        } else if (moduloActual === "eficiencia-energetica") {
            await cargarEnergiaReconstruidaAoki();
        } else if (moduloActual === "linea-base") {
            await cargarLineaBase();
        } else if (moduloActual === "variables") {
            if (!variablesDisponibles.length) await cargarSelectorVariables();
            await cargarUltimosValores();
            if (graficaActual) await mostrarGrafica(graficaActual);
        }
    } finally {
        actualizacionEnCurso = false;
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
        boton.addEventListener("click", () => {
            const vistaSeleccionada = boton.dataset.lineaBaseTarget;

            document.querySelectorAll("[data-linea-base-view]").forEach(vista => {
                vista.hidden = vista.dataset.lineaBaseView !== vistaSeleccionada;
            });
            document.querySelectorAll("[data-linea-base-target]").forEach(item => {
                const activo = item.dataset.lineaBaseTarget === vistaSeleccionada;
                item.classList.toggle("activo", activo);
                item.setAttribute("aria-current", activo ? "page" : "false");
            });
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
            obtenerRangoUnix();
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

    obtenerRangoUnix();
}

async function iniciarDashboard() {
    await cargarRangosProduccion();
    inicializarFiltros();
    inicializarVistasLineaBase();
    obtenerRangoUnix();

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
iniciarDashboard();
