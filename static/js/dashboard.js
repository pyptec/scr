let chartPrincipal = null;
let graficaActual = 'potencia';
let rangoActual = 'hoy';
let ultimosValores = [];
let variablesDisponibles = [];
let variablesDisponiblesReporte = [];

/* =========================
   FORMATO DE FECHAS
========================= */

function formatearHoraColombia(timestampUtc) {
    if (!timestampUtc) return '';

    let fecha;

    if (!isNaN(timestampUtc)) {
        fecha = new Date(Number(timestampUtc) * 1000);
    } else {
        fecha = new Date(timestampUtc);
    }

    return fecha.toLocaleString('es-CO', {
        timeZone: 'America/Bogota',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false
    });
}

function formatoDatetimeLocal(fecha) {
    const year = fecha.getFullYear();
    const month = String(fecha.getMonth() + 1).padStart(2, '0');
    const day = String(fecha.getDate()).padStart(2, '0');
    const hour = String(fecha.getHours()).padStart(2, '0');
    const minute = String(fecha.getMinutes()).padStart(2, '0');

    return `${year}-${month}-${day}T${hour}:${minute}`;
}

function fechaLocalColombiaAUnixUtc(valorDatetimeLocal) {
    if (!valorDatetimeLocal) {
        return null;
    }

    const fecha = new Date(`${valorDatetimeLocal}:00-05:00`);
    return Math.floor(fecha.getTime() / 1000);
}

/* =========================
   RANGOS
========================= */

function obtenerRangoUnix() {
    const ahora = Math.floor(Date.now() / 1000);
    const fecha = new Date();

    let inicio = 0;
    let fin = ahora;

    if (rangoActual === 'hora') {
        inicio = ahora - 3600;
    } else if (rangoActual === 'hoy') {
        fecha.setHours(0, 0, 0, 0);
        inicio = Math.floor(fecha.getTime() / 1000);
    } else if (rangoActual === 'semana') {
        inicio = ahora - (7 * 24 * 3600);
    } else if (rangoActual === 'mes') {
        inicio = ahora - (30 * 24 * 3600);
    } else if (rangoActual === 'anio') {
        inicio = ahora - (365 * 24 * 3600);
    } else if (rangoActual === 'todo') {
        inicio = 0;
        fin = 9999999999;
    }

    return { inicio, fin };
}

async function cambiarRangoTiempo() {
    rangoActual = document.getElementById('rangoTiempo').value;
    await actualizarTodo();
}

function obtenerRangoReporte() {
    const inicioInput = document.getElementById('fechaInicioReporte').value;
    const finInput = document.getElementById('fechaFinReporte').value;

    const inicio = fechaLocalColombiaAUnixUtc(inicioInput);
    const fin = fechaLocalColombiaAUnixUtc(finInput);

    if (!inicio || !fin) {
        alert('Seleccione fecha y hora de inicio y fin del reporte');
        return null;
    }

    if (inicio >= fin) {
        alert('La fecha inicial debe ser menor que la fecha final');
        return null;
    }

    return { inicio, fin };
}

function inicializarFechasReporte() {
    const ahora = new Date();

    const inicio = new Date();
    inicio.setHours(0, 0, 0, 0);

    document.getElementById('fechaInicioReporte').value =
        formatoDatetimeLocal(inicio);

    document.getElementById('fechaFinReporte').value =
        formatoDatetimeLocal(ahora);
}

/* =========================
   KPIs DASHBOARD
========================= */

async function cargarDashboard() {
    const rango = obtenerRangoUnix();

    const res = await fetch(
        `/api/dashboard?inicio=${rango.inicio}&fin=${rango.fin}`
    );

    const data = await res.json();

    document.getElementById('potencia').innerText =
        data.potencia_actual_kw ?? '--';

    document.getElementById('generacion').innerText =
        data.generacion_kwh ?? '--';

    document.getElementById('consumo').innerText =
        data.consumo_kwh ?? '--';

    document.getElementById('ahorro').innerText =
        Number(data.ahorro_cop ?? 0).toLocaleString('es-CO');

    document.getElementById('co2').innerText =
        data.co2_evitado_kg ?? '--';
}

/* =========================
   GRÁFICAS
========================= */

function destruirGraficaActual() {
    if (chartPrincipal) {
        chartPrincipal.destroy();
        chartPrincipal = null;
    }
}

async function mostrarGrafica(tipo) {
    graficaActual = tipo;
    destruirGraficaActual();

    const ctx = document.getElementById('chartPrincipal').getContext('2d');
    const rango = obtenerRangoUnix();

    if (tipo === 'potencia') {
        document.getElementById('tituloGrafica').innerText =
            'Potencia Activa Total';

        const res = await fetch(
            `/api/serie/61?inicio=${rango.inicio}&fin=${rango.fin}&limite=200&gateway_id=8&source_type=device&device_id=31`
        );

        const data = await res.json();

        chartPrincipal = new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.serie.map(x => formatearHoraColombia(x.timestamp_utc)),
                datasets: [{
                    label: 'Potencia kW',
                    data: data.serie.map(x => x.valor),
                    tension: 0.25
                }]
            }
        });
    }

    if (tipo === 'energia') {
        document.getElementById('tituloGrafica').innerText =
            'Generación Diaria';

        const res = await fetch(
            `/api/energia/dia?inicio=${rango.inicio}&fin=${rango.fin}&limite=30`
        );

        const data = await res.json();

        chartPrincipal = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: data.datos.map(x => x.dia),
                datasets: [{
                    label: 'Generación kWh/día',
                    data: data.datos.map(x => x.kwh)
                }]
            }
        });
    }

    if (tipo === 'voltajes') {
        document.getElementById('tituloGrafica').innerText =
            'Voltajes Línea-Neutro';

        const res = await fetch(
            `/api/series?ids=7,8,9&inicio=${rango.inicio}&fin=${rango.fin}&limite=200&gateway_id=8&source_type=device&device_id=31`
        );

        const data = await res.json();

        const s7 = data.series["7"] || [];
        const s8 = data.series["8"] || [];
        const s9 = data.series["9"] || [];

        chartPrincipal = new Chart(ctx, {
            type: 'line',
            data: {
                labels: s7.map(x => formatearHoraColombia(x.timestamp_utc)),
                datasets: [
                    {
                        label: 'VL1',
                        data: s7.map(x => x.valor),
                        tension: 0.25
                    },
                    {
                        label: 'VL2',
                        data: s8.map(x => x.valor),
                        tension: 0.25
                    },
                    {
                        label: 'VL3',
                        data: s9.map(x => x.valor),
                        tension: 0.25
                    }
                ]
            }
        });
    }

    if (tipo === 'corrientes') {
        document.getElementById('tituloGrafica').innerText =
            'Corrientes por Fase';

        const res = await fetch(
            `/api/series?ids=10,11,12&inicio=${rango.inicio}&fin=${rango.fin}&limite=200&gateway_id=8&source_type=device&device_id=31`
        );

        const data = await res.json();

        const s10 = data.series["10"] || [];
        const s11 = data.series["11"] || [];
        const s12 = data.series["12"] || [];

        chartPrincipal = new Chart(ctx, {
            type: 'line',
            data: {
                labels: s10.map(x => formatearHoraColombia(x.timestamp_utc)),
                datasets: [
                    {
                        label: 'I1',
                        data: s10.map(x => x.valor),
                        tension: 0.25
                    },
                    {
                        label: 'I2',
                        data: s11.map(x => x.valor),
                        tension: 0.25
                    },
                    {
                        label: 'I3',
                        data: s12.map(x => x.valor),
                        tension: 0.25
                    }
                ]
            }
        });
    }
}

async function graficarVariableSeleccionada(mostrarAlertas = true) {
    graficaActual = 'variable';

    const select = obtenerElementoPorIds([
        'selectVariable',
        'selectorVariable'
    ]);

    if (!select || !select.value) {
        if (mostrarAlertas) {
            alert('Seleccione una variable');
        }
        return;
    }

    const opt = select.options[select.selectedIndex];

    const unitId = opt.dataset.unitId;
    const gatewayId = opt.dataset.gatewayId;
    const sourceType = opt.dataset.sourceType;
    const deviceId = opt.dataset.deviceId;

    const variableInfo = variablesDisponibles[Number(select.value)];

    if (!variableInfo) {
        if (mostrarAlertas) {
            alert('No se encontró la información de la variable seleccionada');
        }
        return;
    }

    const rango = obtenerRangoUnix();

    const params = new URLSearchParams({
        inicio: rango.inicio,
        fin: rango.fin,
        limite: 1000
    });

    if (gatewayId) {
        params.append('gateway_id', gatewayId);
    }

    if (sourceType) {
        params.append('source_type', sourceType);
    }

    if (deviceId) {
        params.append('device_id', deviceId);
    }

    const url = `/api/serie/${unitId}?${params.toString()}`;

    try {
        const res = await fetch(url);

        if (!res.ok) {
            throw new Error(`HTTP ${res.status} consultando ${url}`);
        }

        const data = await res.json();
        const serie = data.serie || [];

        if (!serie.length) {
            if (mostrarAlertas) {
                alert('No hay datos para la variable seleccionada en el periodo elegido');
            }
            return;
        }

        destruirGraficaActual();

        const labels = serie.map(x => formatearHoraColombia(x.timestamp_utc));
        const valores = serie.map(x => Number(x.valor));

        const canvas = document.getElementById('chartPrincipal');
        const ctx = canvas.getContext('2d');

        const nombreGateway =
            variableInfo.gateway || `Gateway ${variableInfo.gateway_id || ''}`;

        const nombreDispositivo =
            variableInfo.source_type === 'gateway'
                ? 'Gateway'
                : (variableInfo.dispositivo || `Device ${deviceId || ''}`);

        const nombreVariable =
            variableInfo.variable || `Unit ID ${unitId}`;

        const unidad = variableInfo.simbolo || '';

        chartPrincipal = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: `${nombreDispositivo} - Unit ID ${unitId} - ${nombreVariable}`,
                    data: valores,
                    borderWidth: 2,
                    tension: 0.25,
                    pointRadius: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                animation: false,
                plugins: {
                    legend: {
                        display: true
                    }
                },
                scales: {
                    y: {
                        title: {
                            display: unidad !== '',
                            text: unidad
                        }
                    }
                }
            }
        });

        document.getElementById('tituloGrafica').innerText =
            `${nombreGateway} | ${nombreDispositivo} | Unit ID ${unitId} | ${nombreVariable} ${unidad ? '(' + unidad + ')' : ''}`;

    } catch (error) {
        console.error('Error graficando variable:', error);

        if (mostrarAlertas) {
            alert('Error al graficar la variable seleccionada');
        }
    }
}
/* =========================
   SELECTOR VARIABLE PARA GRÁFICA
========================= */
function normalizarRespuestaVariables(data) {
    if (Array.isArray(data)) {
        return data;
    }

    if (data && Array.isArray(data.variables)) {
        return data.variables;
    }

    if (data && Array.isArray(data.datos)) {
        return data.datos;
    }

    if (data && Array.isArray(data.data)) {
        return data.data;
    }

    console.error('Formato inesperado en /api/variables:', data);
    return [];
}

function obtenerElementoPorIds(ids) {
    for (const id of ids) {
        const elemento = document.getElementById(id);
        if (elemento) {
            return elemento;
        }
    }

    return null;
}

async function cargarSelectorVariables() {
    try {
        const resp = await fetch('/api/variables');

        if (!resp.ok) {
            throw new Error(`HTTP ${resp.status} al consultar /api/variables`);
        }

        const data = await resp.json();
        variablesDisponibles = normalizarRespuestaVariables(data);

        const selector = obtenerElementoPorIds([
            'selectVariable',
            'selectorVariable'
        ]);

        if (!selector) {
            console.error('No existe el selector de variables. Revise el id en dashboard.html');
            return;
        }

        selector.innerHTML = '';

        const optDefault = document.createElement('option');
        optDefault.value = '';
        optDefault.textContent = 'Seleccione una variable...';
        selector.appendChild(optDefault);

        if (!variablesDisponibles.length) {
            const optVacio = document.createElement('option');
            optVacio.value = '';
            optVacio.textContent = 'No hay variables disponibles';
            selector.appendChild(optVacio);
            return;
        }

        const grupos = {};

        variablesDisponibles.forEach((v, index) => {
            const gateway = v.gateway || `Gateway ${v.gateway_id || ''}`;

            let origen = '';
            if (v.source_type === 'gateway') {
                origen = 'Gateway';
            } else {
                origen = v.dispositivo || `Dispositivo ${v.device_id || ''}`;
            }

            const grupoNombre = `${gateway} / ${origen}`;

            if (!grupos[grupoNombre]) {
                grupos[grupoNombre] = [];
            }

            grupos[grupoNombre].push({
                ...v,
                index: index
            });
        });

        Object.keys(grupos).sort().forEach(nombreGrupo => {
            const optgroup = document.createElement('optgroup');
            optgroup.label = nombreGrupo;

            grupos[nombreGrupo]
                .sort((a, b) => Number(a.unit_id || 0) - Number(b.unit_id || 0))
                .forEach(v => {
                    const option = document.createElement('option');

                    const gatewayId = v.gateway_id || '';
                    const sourceType = v.source_type || '';
                    const deviceId = v.device_id || '';
                    const unitId = v.unit_id || '';

                    option.value = String(v.index);

                    option.dataset.gatewayId = gatewayId;
                    option.dataset.sourceType = sourceType;
                    option.dataset.deviceId = deviceId;
                    option.dataset.unitId = unitId;

                    const unidad = v.simbolo ? ` ${v.simbolo}` : '';
                    const deviceTxt = sourceType === 'gateway'
                        ? 'Gateway'
                        : `Device ${deviceId}`;

                    option.textContent =
                        `Unit ${unitId} | ${v.variable || 'Variable'}${unidad} | ${deviceTxt}`;

                    optgroup.appendChild(option);
                });

            selector.appendChild(optgroup);
        });

        console.log(`Selector de variables cargado: ${variablesDisponibles.length} variables`);

    } catch (error) {
        console.error('Error cargando selector de variables:', error);
    }
}
/* =========================
   VARIABLES PARA REPORTE
========================= */
async function cargarVariablesReporte() {
    const contenedor = obtenerElementoPorIds([
        'variablesReporte',
        'contenedorVariablesReporte',
        'listaVariablesReporte',
        'variablesReporteLista'
    ]);

    try {
        if (!contenedor) {
            console.error('No existe el contenedor de variables para reporte. Revise el id en dashboard.html');
            return;
        }

        contenedor.innerHTML = 'Cargando variables...';

        const resp = await fetch('/api/variables');

        if (!resp.ok) {
            throw new Error(`HTTP ${resp.status} al consultar /api/variables`);
        }

        const data = await resp.json();
        const variables = normalizarRespuestaVariables(data);

        variablesDisponiblesReporte = variables;

        contenedor.innerHTML = '';

        if (!variables.length) {
            contenedor.innerHTML = `
                <div class="mensaje-reporte">
                    No hay variables disponibles para reporte.
                </div>
            `;
            return;
        }

        const grupos = {};

        variables.forEach(v => {
            const gateway = v.gateway || `Gateway ${v.gateway_id || ''}`;

            let origen = '';
            if (v.source_type === 'gateway') {
                origen = 'Gateway';
            } else {
                origen = v.dispositivo || `Dispositivo ${v.device_id || ''}`;
            }

            const grupoNombre = `${gateway} / ${origen}`;

            if (!grupos[grupoNombre]) {
                grupos[grupoNombre] = [];
            }

            grupos[grupoNombre].push(v);
        });

        Object.keys(grupos).sort().forEach(nombreGrupo => {
            const bloque = document.createElement('div');
            bloque.className = 'grupo-variables-reporte';

            const titulo = document.createElement('h4');
            titulo.textContent = nombreGrupo;
            bloque.appendChild(titulo);

            grupos[nombreGrupo]
                .sort((a, b) => Number(a.unit_id || 0) - Number(b.unit_id || 0))
                .forEach(v => {
                    const gatewayId = v.gateway_id || '';
                    const sourceType = v.source_type || '';
                    const deviceId = v.device_id || '';
                    const unitId = v.unit_id || '';

                    const label = document.createElement('label');
                    label.className = 'label-variable-reporte';

                    const chk = document.createElement('input');
                    chk.type = 'checkbox';
                    chk.name = 'variables_reporte';
                    chk.className = 'chk-variable-reporte';

                    chk.value = `${gatewayId}|${sourceType}|${deviceId}|${unitId}`;

                    chk.dataset.gatewayId = gatewayId;
                    chk.dataset.sourceType = sourceType;
                    chk.dataset.deviceId = deviceId;
                    chk.dataset.unitId = unitId;

                    const unidad = v.simbolo ? ` ${v.simbolo}` : '';
                    const deviceTxt = sourceType === 'gateway'
                        ? 'Gateway'
                        : `Device ${deviceId}`;

                    label.appendChild(chk);
                    label.appendChild(
                        document.createTextNode(
                            ` Unit ${unitId} | ${v.variable || 'Variable'}${unidad} | ${deviceTxt}`
                        )
                    );

                    bloque.appendChild(label);
                });

            contenedor.appendChild(bloque);
        });

        console.log(`Variables de reporte cargadas: ${variables.length} variables`);

    } catch (error) {
        console.error('Error cargando variables para reporte:', error);

        if (contenedor) {
            contenedor.innerHTML = `
                <div class="mensaje-error-reporte">
                    Error cargando variables. Revise la consola del navegador o el endpoint /api/variables.
                </div>
            `;
        }
    }
}

function seleccionarVariablesReporteBase() {
    const base = [
        61,
        100,
        104,
        58, 59, 60,
        97, 98, 99,
        101, 102, 103,
        7, 8, 9,
        10, 11, 12,
        27,
        135, 136, 137, 144,
        53
    ];

    document
        .querySelectorAll('input.chk-variable-reporte')
        .forEach(chk => {
            const unitId = Number(chk.dataset.unitId);
            chk.checked = base.includes(unitId);
        });
}

function seleccionarTodasVariablesReporte() {
    document
        .querySelectorAll('input.chk-variable-reporte')
        .forEach(chk => {
            chk.checked = true;
        });
}

function limpiarVariablesReporte() {
    document
        .querySelectorAll('input.chk-variable-reporte')
        .forEach(chk => {
            chk.checked = false;
        });
}

function obtenerVariablesSeleccionadasReporte() {
    const seleccionadas = [];

    document
        .querySelectorAll('input.chk-variable-reporte:checked')
        .forEach(chk => {
            seleccionadas.push(chk.value);
        });

    return seleccionadas;
}
function generarReporteExcelSeleccionadas() {
    const rango = obtenerRangoReporte();

    if (!rango) {
        return;
    }

    const variables = obtenerVariablesSeleccionadasReporte();

    if (variables.length === 0) {
        alert('Seleccione al menos una variable para el reporte');
        return;
    }

    const variablesParam = variables.join(',');

    const url =
        `/api/reporte/excel?inicio=${rango.inicio}&fin=${rango.fin}&variables=${variablesParam}`;

    window.location.href = url;
}

/* =========================
   ÚLTIMOS VALORES
========================= */

async function cargarUltimosValores() {
    const res = await fetch('/api/ultimos');
    const data = await res.json();

    ultimosValores = data.datos || [];

    pintarTablaUltimos(ultimosValores);
}

function pintarTablaUltimos(datos) {
    const tbody = document.getElementById('tablaUltimos');
    tbody.innerHTML = '';

    if (!datos || datos.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="9">No hay datos para mostrar</td>
            </tr>
        `;
        return;
    }

    datos.forEach(item => {
        const tr = document.createElement('tr');

        const origen =
            item.source_type === 'gateway'
                ? 'Gateway'
                : item.source_type === 'device'
                    ? 'Dispositivo'
                    : 'Desconocido';

        const dispositivo =
            item.source_type === 'gateway'
                ? 'Gateway'
                : (item.dispositivo || 'Sin dispositivo');

        tr.innerHTML = `
            <td>${item.gateway || `Gateway ${item.gateway_id || ''}`}</td>
            <td>${origen}</td>
            <td>${item.device_id || ''}</td>
            <td>${dispositivo}</td>
            <td>${item.unit_id}</td>
            <td>${item.variable || 'Sin nombre'}</td>
            <td>${formatearValorVariable(item)}</td>
            <td>${item.simbol || ''}</td>
            <td>${formatearHoraColombia(item.timestamp_utc)}</td>
        `;

        tbody.appendChild(tr);
    });
}

function filtrarTablaUltimos() {
    const texto = document
        .getElementById('buscarTabla')
        .value
        .toLowerCase()
        .trim();

    if (!texto) {
        pintarTablaUltimos(ultimosValores);
        return;
    }

    const filtrados = ultimosValores.filter(item => {
        const gateway = String(item.gateway || '').toLowerCase();
        const gatewayId = String(item.gateway_id || '').toLowerCase();
        const sourceType = String(item.source_type || '').toLowerCase();
        const deviceId = String(item.device_id || '').toLowerCase();
        const dispositivo = String(item.dispositivo || '').toLowerCase();
        const tipoDispositivo = String(item.tipo_dispositivo || '').toLowerCase();
        const unitId = String(item.unit_id || '').toLowerCase();
        const variable = String(item.variable || '').toLowerCase();
        const simbolo = String(item.simbol || '').toLowerCase();
        const valor = String(item.valor || '').toLowerCase();

        return (
            gateway.includes(texto) ||
            gatewayId.includes(texto) ||
            sourceType.includes(texto) ||
            deviceId.includes(texto) ||
            dispositivo.includes(texto) ||
            tipoDispositivo.includes(texto) ||
            unitId.includes(texto) ||
            variable.includes(texto) ||
            simbolo.includes(texto) ||
            valor.includes(texto)
        );
    });

    pintarTablaUltimos(filtrados);
}

function exportarUltimosCSV() {
    if (!ultimosValores || ultimosValores.length === 0) {
        alert('No hay datos para exportar');
        return;
    }

    const textoBusqueda = document
        .getElementById('buscarTabla')
        .value
        .toLowerCase()
        .trim();

    let datosExportar = ultimosValores;

    if (textoBusqueda) {
        datosExportar = ultimosValores.filter(item => {
            const gateway = String(item.gateway || '').toLowerCase();
            const gatewayId = String(item.gateway_id || '').toLowerCase();
            const sourceType = String(item.source_type || '').toLowerCase();
            const deviceId = String(item.device_id || '').toLowerCase();
            const dispositivo = String(item.dispositivo || '').toLowerCase();
            const tipoDispositivo = String(item.tipo_dispositivo || '').toLowerCase();
            const unitId = String(item.unit_id || '').toLowerCase();
            const variable = String(item.variable || '').toLowerCase();
            const simbolo = String(item.simbol || '').toLowerCase();
            const valor = String(item.valor || '').toLowerCase();

            return (
                gateway.includes(textoBusqueda) ||
                gatewayId.includes(textoBusqueda) ||
                sourceType.includes(textoBusqueda) ||
                deviceId.includes(textoBusqueda) ||
                dispositivo.includes(textoBusqueda) ||
                tipoDispositivo.includes(textoBusqueda) ||
                unitId.includes(textoBusqueda) ||
                variable.includes(textoBusqueda) ||
                simbolo.includes(textoBusqueda) ||
                valor.includes(textoBusqueda)
            );
        });
    }

    const encabezados = [
        'Gateway ID',
        'Gateway',
        'Cliente',
        'Source Type',
        'Device ID',
        'Dispositivo',
        'Tipo Dispositivo',
        'Unit ID',
        'Variable',
        'Valor',
        'Unidad',
        'Timestamp UTC',
        'Hora Colombia'
    ];

    const filas = datosExportar.map(item => [
        item.gateway_id || '',
        item.gateway || '',
        item.cliente || '',
        item.source_type || '',
        item.device_id || '',
        item.dispositivo || '',
        item.tipo_dispositivo || '',
        item.unit_id,
        item.variable || '',
        formatearValorVariable(item),
        item.simbol || '',
        item.timestamp_utc || '',
        formatearHoraColombia(item.timestamp_utc)
    ]);

    const csv = [
        encabezados,
        ...filas
    ]
    .map(fila =>
        fila.map(campo =>
            `"${String(campo).replace(/"/g, '""')}"`
        ).join(';')
    )
    .join('\n');

    const blob = new Blob([csv], {
        type: 'text/csv;charset=utf-8;'
    });

    const url = URL.createObjectURL(blob);

    const enlace = document.createElement('a');
    enlace.href = url;

    const fecha = new Date()
        .toISOString()
        .slice(0, 19)
        .replace(/:/g, '-');

    enlace.download = `samee100_ultimos_valores_${fecha}.csv`;

    document.body.appendChild(enlace);
    enlace.click();
    document.body.removeChild(enlace);

    URL.revokeObjectURL(url);
}
/* =========================
   ACTUALIZACIÓN GENERAL
========================= */

async function actualizarTodo() {
    await cargarDashboard();
    await cargarEstadoGateway();
    await cargarUltimosValores();

    if (graficaActual === 'variable') {
        await graficarVariableSeleccionada(false);
        return;
    }

    if (graficaActual) {
        await mostrarGrafica(graficaActual);
    }
}

function formatearValorVariable(item) {
    const variable = String(item.variable || '').toLowerCase();
    const unitId = Number(item.unit_id);
    const valor = item.valor;

    // Variables tipo IP
    if (
        unitId === 137 ||
        unitId === 144 ||
        variable.includes('ip_') ||
        variable.includes('ip ')
    ) {
        const texto = String(valor).replace(/\D/g, '');

        if (texto.length === 12) {
            return `${texto.slice(0, 3)}.${texto.slice(3, 6)}.${texto.slice(6, 7)}.${texto.slice(7)}`;
        }

        if (texto.length === 10) {
            return `${texto.slice(0, 3)}.${texto.slice(3, 6)}.${texto.slice(6, 7)}.${texto.slice(7)}`;
        }

        if (texto.length === 9) {
            return `${texto.slice(0, 3)}.${texto.slice(3, 6)}.${texto.slice(6, 7)}.${texto.slice(7)}`;
        }

        return String(valor);
    }

    // Valores numéricos normales
    const numero = Number(valor);

    if (!Number.isNaN(numero)) {
        return numero.toLocaleString('es-CO');
    }

    return String(valor ?? '');
}

/* =========================
   ESTADO DEL GATEWAY
========================= */

function formatearEdadSegundos(segundos) {
    if (segundos === null || segundos === undefined) {
        return '--';
    }

    const s = Number(segundos);

    if (s < 60) {
        return `${s} s`;
    }

    if (s < 3600) {
        return `${Math.floor(s / 60)} min`;
    }

    return `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`;
}

function formatearIpDesdeValor(valor) {
    if (valor === null || valor === undefined) {
        return '--';
    }

    const texto = String(valor).replace(/\D/g, '');

    if (texto.length === 10) {
        return `${texto.slice(0, 3)}.${texto.slice(3, 6)}.${texto.slice(6, 7)}.${texto.slice(7)}`;
    }

    if (texto.length === 9) {
        return `${texto.slice(0, 3)}.${texto.slice(3, 6)}.${texto.slice(6, 7)}.${texto.slice(7)}`;
    }

    if (texto.length === 12) {
        return `${texto.slice(0, 3)}.${texto.slice(3, 6)}.${texto.slice(6, 7)}.${texto.slice(7)}`;
    }

    return String(valor);
}

function pintarEstadoTexto(id, valor, claseEstado = '') {
    const el = document.getElementById(id);
    if (!el) return;

    el.innerText = valor ?? '--';

    el.classList.remove('estado-ok', 'estado-alerta', 'estado-error');

    if (claseEstado) {
        el.classList.add(claseEstado);
    }
}

async function cargarEstadoGateway() {
    try {
        const res = await fetch('/api/estado');

        if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
        }

        const data = await res.json();

        const estadoDatosClase =
            data.estado_datos === 'OK'
                ? 'estado-ok'
                : 'estado-alerta';

        const estadoMedidorClase =
            data.estado_medidor_31 === 'OK'
                ? 'estado-ok'
                : 'estado-alerta';

        pintarEstadoTexto(
            'estadoGateway',
            `${data.gateway || 'Gateway'} ID ${data.gateway_id || ''}`
        );

        pintarEstadoTexto(
            'estadoDatos',
            data.estado_datos || '--',
            estadoDatosClase
        );

        pintarEstadoTexto(
            'estadoUltimaMedicion',
            data.ultima_medicion_utc
                ? formatearHoraColombia(data.ultima_medicion_utc)
                : '--'
        );

        pintarEstadoTexto(
            'estadoEdadDato',
            formatearEdadSegundos(data.edad_segundos),
            estadoDatosClase
        );

        pintarEstadoTexto(
            'estadoMedidor31',
            data.estado_medidor_31 || '--',
            estadoMedidorClase
        );

        pintarEstadoTexto(
            'estadoConnectedMeter',
            data.connected_meter ?? '--'
        );

        pintarEstadoTexto(
            'estadoRam',
            data.ram !== null && data.ram !== undefined ? `${data.ram} %` : '--'
        );

        pintarEstadoTexto(
            'estadoCpu',
            data.cpu !== null && data.cpu !== undefined ? `${data.cpu} %` : '--'
        );

        pintarEstadoTexto(
            'estadoIpUsb0',
            formatearIpDesdeValor(data.ip_usb0)
        );

        pintarEstadoTexto(
            'estadoIpEth',
            formatearIpDesdeValor(data.ip_ethernet)
        );

    } catch (error) {
        console.error('Error cargando estado del gateway:', error);

        pintarEstadoTexto('estadoDatos', 'ERROR', 'estado-error');
        pintarEstadoTexto('estadoMedidor31', 'ERROR', 'estado-error');
    }
}
/* =========================
   INICIO
========================= */

inicializarFechasReporte();
cargarSelectorVariables();
cargarVariablesReporte();
actualizarTodo();

setInterval(actualizarTodo, 30000);