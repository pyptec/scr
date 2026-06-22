let chartPrincipal = null;
let graficaActual = 'potencia';

async function cargarDashboard() {

    const res = await fetch('/api/dashboard');
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

        const res = await fetch('/api/serie/61?limite=200');
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

        const res = await fetch('/api/energia/dia?limite=30');
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

        const res = await fetch('/api/series?ids=7,8,9&limite=200');
        const data = await res.json();

        chartPrincipal = new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.series["7"].map(x => x.timestamp_utc),
                datasets: [
                    {
                        label: 'VL1',
                        data: data.series["7"].map(x => x.valor),
                        tension: 0.25
                    },
                    {
                        label: 'VL2',
                        data: data.series["8"].map(x => x.valor),
                        tension: 0.25
                    },
                    {
                        label: 'VL3',
                        data: data.series["9"].map(x => x.valor),
                        tension: 0.25
                    }
                ]
            }
        });
    }

    if (tipo === 'corrientes') {

        document.getElementById('tituloGrafica').innerText =
            'Corrientes por Fase';

        const res = await fetch('/api/series?ids=10,11,12&limite=200');
        const data = await res.json();

        chartPrincipal = new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.series["10"].map(x => x.timestamp_utc),
                datasets: [
                    {
                        label: 'I1',
                        data: data.series["10"].map(x => x.valor),
                        tension: 0.25
                    },
                    {
                        label: 'I2',
                        data: data.series["11"].map(x => x.valor),
                        tension: 0.25
                    },
                    {
                        label: 'I3',
                        data: data.series["12"].map(x => x.valor),
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

actualizarTodo();

setInterval(actualizarTodo, 30000);