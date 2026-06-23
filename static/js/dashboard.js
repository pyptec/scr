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

    const select = document.getElementById('selectVariable');

    if (!select.value) {
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

        const nombreGateway = variableInfo.gateway || `Gateway ${variableInfo.gateway_id || ''}`;
        const nombreDispositivo = variableInfo.dispositivo || 'Gateway';
        const nombreVariable = variableInfo.variable || `Unit ID ${unitId}`;
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

async function cargarSelectorVariables() {
    try {
        const res = await fetch('/api/variables');
        const data = await res.json();

        variablesDisponibles = data.variables || [];

        const select = document.getElementById('selectVariable');
        select.innerHTML = '';

        if (!variablesDisponibles.length) {
            select.innerHTML = '<option value="">No hay variables disponibles</option>';
            return;
        }

        variablesDisponibles.forEach((v, index) => {
            const opt = document.createElement('option');

            opt.value = index;

            opt.dataset.gatewayId = v.gateway_id || '';
            opt.dataset.sourceType = v.source_type || '';
            opt.dataset.deviceId = v.device_id || '';
            opt.dataset.unitId = v.unit_id || '';

            const gateway = v.gateway || `Gateway ${v.gateway_id || ''}`;
            const origen = v.source_type === 'gateway' ? 'Gateway' : 'Dispositivo';
            const dispositivo = v.dispositivo || origen;

            opt.textContent =
                `${gateway} | ${dispositivo} | Unit ID ${v.unit_id} | ${v.variable} ${v.simbolo ? '(' + v.simbolo + ')' : ''}`;

            select.appendChild(opt);
        });

    } catch (error) {
        console.error('Error cargando variables:', error);
    }
}

/* =========================
   VARIABLES PARA REPORTE
========================= */

async function cargarVariablesReporte() {
    const res = await fetch('/api/variables');
    const data = await res.json();

    variablesDisponiblesReporte = data.variables || [];

    const contenedor = document.getElementById('listaVariablesReporte');
    contenedor.innerHTML = '';

    variablesDisponiblesReporte.forEach(v => {
        const label = document.createElement('label');
        label.className = 'variable-reporte-item';

        label.innerHTML = `
            <input
                type="checkbox"
                class="chk-variable-reporte"
                value="${v.gateway_id || ''}|${v.source_type || ''}|${v.device_id || ''}|${v.unit_id}"
                data-unit-id="${v.unit_id}"
                data-device-id="${v.device_id || ''}"
                data-gateway-id="${v.gateway_id || ''}"
                data-source-type="${v.source_type || ''}"
            >
            <span>
                <strong>${v.gateway || 'Gateway'} / ${v.dispositivo || 'Sin dispositivo'}</strong><br>
                ${v.unit_id} - ${v.variable}
                ${v.simbolo ? `(${v.simbolo})` : ''}
            </span>
        `;

        contenedor.appendChild(label);
    });

    seleccionarVariablesReporteBase();
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

    document.querySelectorAll('.chk-variable-reporte').forEach(chk => {
        const unitId = Number(chk.dataset.unitId);
        chk.checked = base.includes(unitId);
    });
}

function seleccionarTodasVariablesReporte() {
    document.querySelectorAll('.chk-variable-reporte').forEach(chk => {
        chk.checked = true;
    });
}

function limpiarVariablesReporte() {
    document.querySelectorAll('.chk-variable-reporte').forEach(chk => {
        chk.checked = false;
    });
}

function obtenerVariablesSeleccionadasReporte() {
    const seleccionadas = [];

    document.querySelectorAll('.chk-variable-reporte:checked').forEach(chk => {
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
            <td>${Number(item.valor).toLocaleString('es-CO')}</td>
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
        item.valor,
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
    await cargarUltimosValores();

    if (graficaActual === 'variable') {
        await graficarVariableSeleccionada(false);
        return;
    }

    if (graficaActual) {
        await mostrarGrafica(graficaActual);
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