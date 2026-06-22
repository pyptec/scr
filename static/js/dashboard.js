let chartPrincipal = null;
let graficaActual = 'potencia';
let rangoActual = 'hoy';

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

async function mostrarGrafica(tipo) {
    graficaActual = tipo;

    if (chartPrincipal) {
        chartPrincipal.destroy();
    }

    const ctx = document.getElementById('chartPrincipal');

    if (tipo === 'potencia') {
        document.getElementById('tituloGrafica').innerText =
            'Potencia Activa Total';

        const rango = obtenerRangoUnix();
        const res = await fetch(`/api/serie/61?inicio=${rango.inicio}&fin=${rango.fin}&limite=200`);
        const data = await res.json();

        chartPrincipal = new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.serie.map(x => x.timestamp_utc),
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

        const rango = obtenerRangoUnix();
        const res = await fetch(`/api/energia/dia?inicio=${rango.inicio}&fin=${rango.fin}&limite=30`);
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

        const rango = obtenerRangoUnix();
        const res = await fetch(`/api/series?ids=7,8,9&inicio=${rango.inicio}&fin=${rango.fin}&limite=200`);
        const data = await res.json();

        const s7 = data.series["7"] || [];
        const s8 = data.series["8"] || [];
        const s9 = data.series["9"] || [];

        chartPrincipal = new Chart(ctx, {
            type: 'line',
            data: {
                labels: s7.map(x => x.timestamp_utc),
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

        const rango = obtenerRangoUnix();
        const res = await fetch(`/api/series?ids=10,11,12&inicio=${rango.inicio}&fin=${rango.fin}&limite=200`);
        const data = await res.json();

        const s10 = data.series["10"] || [];
        const s11 = data.series["11"] || [];
        const s12 = data.series["12"] || [];

        chartPrincipal = new Chart(ctx, {
            type: 'line',
            data: {
                labels: s10.map(x => x.timestamp_utc),
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

async function actualizarTodo() {
    await cargarDashboard();

    if (graficaActual) {
        await mostrarGrafica(graficaActual);
    }
}

async function cargarSelectorVariables() {
    const res = await fetch('/api/variables');
    const data = await res.json();

    const select = document.getElementById('selectVariable');
    select.innerHTML = '';

    data.variables.forEach(v => {
        const opt = document.createElement('option');
        opt.value = v.unit_id;
        opt.textContent = `${v.unit_id} - ${v.variable} (${v.simbolo || 'NA'})`;
        select.appendChild(opt);
    });
}

async function graficarVariableSeleccionada() {
    const select = document.getElementById('selectVariable');
    const unitId = select.value;

    if (!unitId) return;

    if (chartPrincipal) {
        chartPrincipal.destroy();
    }

    const texto = select.options[select.selectedIndex].text;
    document.getElementById('tituloGrafica').innerText = texto;

    const rango = obtenerRangoUnix();
    const res = await fetch(`/api/serie/${unitId}?inicio=${rango.inicio}&fin=${rango.fin}&limite=200`);
    const data = await res.json();

    const ctx = document.getElementById('chartPrincipal');

    chartPrincipal = new Chart(ctx, {
        type: 'line',
        data: {
            labels: data.serie.map(x => x.timestamp_utc),
            datasets: [{
                label: texto,
                data: data.serie.map(x => x.valor),
                tension: 0.25
            }]
        }
    });

    graficaActual = null;
}

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

cargarSelectorVariables();
actualizarTodo();

setInterval(actualizarTodo, 30000);