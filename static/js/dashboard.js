let chartPotencia = null;
let chartEnergiaDia = null;
let chartVoltajes = null;
let chartCorrientes = null;

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

async function cargarGraficaPotencia() {

    const res = await fetch('/api/serie/61?limite=200');
    const data = await res.json();

    const labels = data.serie.map(x => x.timestamp_utc);
    const valores = data.serie.map(x => x.valor);

    const ctx = document.getElementById('chartPotencia');

    if (chartPotencia) chartPotencia.destroy();

    chartPotencia = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [{
                label: 'Potencia kW',
                data: valores,
                tension: 0.25
            }]
        }
    });
}

async function cargarGraficaEnergiaDia() {

    const res = await fetch('/api/energia/dia?limite=30');
    const data = await res.json();

    const labels = data.datos.map(x => x.dia);
    const valores = data.datos.map(x => x.kwh);

    const ctx = document.getElementById('chartEnergiaDia');

    if (chartEnergiaDia) chartEnergiaDia.destroy();

    chartEnergiaDia = new Chart(ctx, {
        type: 'bar',
        data: {
            labels,
            datasets: [{
                label: 'Generación kWh/día',
                data: valores
            }]
        }
    });
}

async function cargarGraficaVoltajes() {

    const res = await fetch('/api/series?ids=7,8,9&limite=200');
    const data = await res.json();

    const s7 = data.series["7"] || [];
    const s8 = data.series["8"] || [];
    const s9 = data.series["9"] || [];

    const labels = s7.map(x => x.timestamp_utc);

    const ctx = document.getElementById('chartVoltajes');

    if (chartVoltajes) chartVoltajes.destroy();

    chartVoltajes = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [
                {
                    label: 'VL1',
                    data: s7.map(x => x.valor)
                },
                {
                    label: 'VL2',
                    data: s8.map(x => x.valor)
                },
                {
                    label: 'VL3',
                    data: s9.map(x => x.valor)
                }
            ]
        }
    });
}

async function cargarGraficaCorrientes() {

    const res = await fetch('/api/series?ids=10,11,12&limite=200');
    const data = await res.json();

    const s10 = data.series["10"] || [];
    const s11 = data.series["11"] || [];
    const s12 = data.series["12"] || [];

    const labels = s10.map(x => x.timestamp_utc);

    const ctx = document.getElementById('chartCorrientes');

    if (chartCorrientes) chartCorrientes.destroy();

    chartCorrientes = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [
                {
                    label: 'I1',
                    data: s10.map(x => x.valor)
                },
                {
                    label: 'I2',
                    data: s11.map(x => x.valor)
                },
                {
                    label: 'I3',
                    data: s12.map(x => x.valor)
                }
            ]
        }
    });
}

async function actualizarTodo() {

    await cargarDashboard();
    await cargarGraficaPotencia();
    await cargarGraficaEnergiaDia();
    await cargarGraficaVoltajes();
    await cargarGraficaCorrientes();
}

actualizarTodo();

setInterval(actualizarTodo, 30000);