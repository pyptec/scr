let chartPrincipal = null;
let graficaActual = "potencia";
let rangoActual = "hoy";
let ultimosValores = [];
let variablesDisponibles = [];

function obtenerRangoUnix() {
    const ahora = Math.floor(Date.now() / 1000);
    const fecha = new Date();

    let inicio = 0;
    let fin = ahora;

    if (rangoActual === "hora") {
        inicio = ahora - 3600;
    } else if (rangoActual === "hoy") {
        fecha.setHours(0, 0, 0, 0);
        inicio = Math.floor(fecha.getTime() / 1000);
    } else if (rangoActual === "semana") {
        inicio = ahora - 7 * 24 * 3600;
    } else if (rangoActual === "mes") {
        inicio = ahora - 30 * 24 * 3600;
    } else if (rangoActual === "todo") {
        inicio = 0;
        fin = 9999999999;
    }

    return { inicio, fin };
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

    document.getElementById("estadoIpEth").innerText =
        reconstruirIpv4DesdeDigitos(data.ip_ethernet);

    document.getElementById("estadoConnect").innerText =
        data.connected_meter ?? "--";
}

async function cargarSelectorVariables() {
    const res = await fetch("/api/variables");
    const data = await res.json();

    variablesDisponibles = data.variables || [];

    const selector = document.getElementById("selectorVariable");
    selector.innerHTML = "";

    const optDefault = document.createElement("option");
    optDefault.value = "";
    optDefault.textContent = "Seleccione una variable...";
    selector.appendChild(optDefault);

    const grupos = {};

    variablesDisponibles.forEach((v, index) => {
        const equipo = v.source_type === "gateway"
            ? "Gateway"
            : `${v.dispositivo || "Dispositivo"} (${v.rol || "sin rol"})`;

        const grupo = `${v.gateway || "Gateway"} / ${equipo}`;

        if (!grupos[grupo]) grupos[grupo] = [];

        grupos[grupo].push({ ...v, index });
    });

    Object.keys(grupos).sort().forEach(nombreGrupo => {
        const optgroup = document.createElement("optgroup");
        optgroup.label = nombreGrupo;

        grupos[nombreGrupo]
            .sort((a, b) => Number(a.unit_id) - Number(b.unit_id))
            .forEach(v => {
                const option = document.createElement("option");
                option.value = String(v.index);
                option.textContent = `Unit ${v.unit_id} | ${v.variable || "Variable"} ${v.simbolo || ""}`;
                optgroup.appendChild(option);
            });

        selector.appendChild(optgroup);
    });
}

function destruirGrafica() {
    if (chartPrincipal) {
        chartPrincipal.destroy();
        chartPrincipal = null;
    }
}

async function obtenerSerie(unitId, deviceId, gatewayId = 10, limite = 1000) {
    const rango = obtenerRangoUnix();

    const params = new URLSearchParams({
        inicio: rango.inicio,
        fin: rango.fin,
        limite: limite,
        gateway_id: gatewayId,
        device_id: deviceId,
        source_type: "device"
    });

    const res = await fetch(`/api/serie/${unitId}?${params.toString()}`);
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

    destruirGrafica();

    document.getElementById("tituloGrafica").innerText =
        `${v.dispositivo || "Gateway"} | Unit ${v.unit_id} | ${v.variable}`;

    const rango = obtenerRangoUnix();

    const params = new URLSearchParams({
        inicio: rango.inicio,
        fin: rango.fin,
        limite: 1000,
        gateway_id: v.gateway_id,
        source_type: v.source_type
    });

    if (v.device_id) {
        params.append("device_id", v.device_id);
    }

    const res = await fetch(`/api/serie/${v.unit_id}?${params.toString()}`);
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
    await cargarDashboard();
    await cargarEstado();
    await cargarUltimosValores();

    if (graficaActual) {
        await mostrarGrafica(graficaActual);
    }
}

document.getElementById("rangoTiempo").addEventListener("change", async (e) => {
    rangoActual = e.target.value;
    await actualizarTodo();
});

cargarSelectorVariables();
actualizarTodo();

setInterval(actualizarTodo, 30000);