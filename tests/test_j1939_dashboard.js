'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const D = require('../static/js/j1939_diagnostics.js');
const now = Date.parse('2026-11-14T12:00:00Z');
const signal = (changes = {}) => ({key: 'engine_speed', name: 'RPM del motor', value: 1800,
    quality: 'GOOD', unit: 'rpm', pgn: 'F004', sourceAddress: 'EA',
    timestampUtc: new Date(now).toISOString(), ...changes});
const view = (m, sa = 'EA', time = now, unavailable = false) => m.view(sa, time, 15, unavailable);

test('RPM conserva valor, origen y contrato F004/SPN190', () => {
    const m = new D.RpmMonitor(); m.observe([signal()], now);
    assert.equal(view(m).rpm, 1800); assert.equal(view(m).source, 'EA');
    assert.equal(view(m).pgn, 'F004'); assert.equal(view(m).spn, 190);
});
test('valores inválidos nunca se muestran como RPM', () => {
    for (const changes of [{value: null}, {value: '1800'}, {value: NaN}, {value: Infinity},
        {value: -1}, {value: 3001}, {quality: 'INVALID'}, {quality: 'NOT_AVAILABLE'}]) {
        const m = new D.RpmMonitor(); m.observe([signal(changes)], now);
        assert.equal(view(m).rpm, null);
    }
});
test('sin señales ni origen no provoca errores ni inventa valores', () => {
    const m = new D.RpmMonitor(); m.observe(null, now);
    assert.equal(view(m).rpm, null); assert.equal(view(m).lastValidAge, null);
    assert.equal(view(m).quality, 'Sin dato validado');
});
test('no acepta key, PGN, unidad u origen ajenos al contrato RPM', () => {
    const m = new D.RpmMonitor();
    for (const changes of [{key: 'x'}, {pgn: 'FEEE'}, {unit: 'V'}, {sourceAddress: '<x>'}])
        m.observe([signal(changes)], now);
    assert.equal(m.sources.size, 0);
});
test('separa valores y última muestra válida entre ECU', () => {
    const m = new D.RpmMonitor(); m.observe([signal(), signal({sourceAddress: '01', value: 900})], now);
    assert.equal(view(m).rpm, 1800); assert.equal(view(m, '01').rpm, 900);
    m.observe([signal({sourceAddress: '01', value: 0, quality: 'INVALID'})], now + 1000);
    assert.equal(view(m).rpm, 1800); assert.equal(view(m, '01').rpm, null);
});
test('caducidad no implica motor detenido ni RPM cero', () => {
    const m = new D.RpmMonitor(); m.observe([signal()], now);
    const v = view(m, 'EA', now + 16000);
    assert.equal(v.rpm, null); assert.equal(v.lastValidAge, 16);
    assert.equal(v.communication, 'Sin RPM válida reciente');
    assert.ok(!JSON.stringify(v).includes('STOPPED'));
});
test('dato inválido conserva únicamente fecha válida previa del mismo origen', () => {
    const m = new D.RpmMonitor(); m.observe([signal()], now);
    m.observe([signal({quality: 'NOT_AVAILABLE', value: null,
        timestampUtc: new Date(now + 2000).toISOString()})], now + 2000);
    assert.equal(view(m, 'EA', now + 3000).lastValidAge, 3);
    assert.equal(view(m, 'EA', now + 3000).rpm, null);
    assert.equal(view(m, '01', now + 3000).lastValidAge, null);
});
test('timestamps futuros, sin zona o malformados no son muestras válidas', () => {
    for (const stamp of ['2026-11-14T12:01:00Z', '2026-11-14T12:00:00', 'bad', null]) {
        const m = new D.RpmMonitor(); m.observe([signal({timestampUtc: stamp})], now);
        assert.equal(view(m).rpm, null);
    }
});
test('respuesta fuera de orden no retrocede la evidencia', () => {
    const m = new D.RpmMonitor(); m.observe([signal()], now);
    m.observe([signal({value: 0, timestampUtc: new Date(now - 1000).toISOString()})], now);
    assert.equal(view(m).rpm, 1800);
});
test('fallo API oculta RPM aunque la muestra anterior fuera reciente', () => {
    const m = new D.RpmMonitor(); m.observe([signal()], now);
    assert.equal(view(m, 'EA', now, true).rpm, null);
    assert.equal(view(m, 'EA', now, true).communication, 'API no disponible');
});
test('bus abierto sin tráfico reciente no muestra ONLINE', () => {
    assert.equal(D.busState({connected: true, lastFrameAt: new Date(now - 16000).toISOString()}, now, 15), 'Sin RX reciente');
    assert.equal(D.busState({connected: true}, now, 15), 'Sin recepción verificable');
    assert.equal(D.busState({connected: false}, now, 15), 'Transporte desconectado');
    assert.equal(D.busState({connected: true, lastFrameAt: new Date(now).toISOString()}, now, 15), 'RX reciente');
});

function browserHarness({fail = false, hidden = false, delayed = false} = {}) {
    const nodes = new Map(); const intervals = new Map(); const timeouts = new Map();
    const calls = []; const listeners = new Map(); let seq = 0; let failing = fail;
    const element = id => {
        if (!nodes.has(id)) nodes.set(id, {hidden: true, dataset: {staleSeconds: '15'},
            textContent: '', innerHTML: '', value: id === 'j1939CaptureDuration' ? '300' : 'nota',
            addEventListener: (event, fn) => listeners.set(`${id}:${event}`, fn)});
        return nodes.get(id);
    };
    let release;
    const gate = delayed ? new Promise(resolve => { release = resolve; }) : Promise.resolve();
    const context = {
        J1939Diagnostics: D, AbortController,
        Date: class extends Date { static now() { return now; } },
        document: {hidden, getElementById: element, addEventListener: (name, fn) => listeners.set(name, fn)},
        setInterval: (fn, ms) => { const id = ++seq; intervals.set(id, {fn, ms}); return id; },
        clearInterval: id => intervals.delete(id),
        setTimeout: (fn, ms) => { const id = ++seq; timeouts.set(id, {fn, ms}); return id; },
        clearTimeout: id => timeouts.delete(id),
        alert: () => {}, prompt: () => 'marca',
        fetch: async (url, options) => {
            calls.push({url, options}); await gate;
            if (failing) throw new Error('offline');
            const payload = url.endsWith('/status') && !url.includes('capture')
                ? {connected: true, framesReceived: 1, lastFrameAt: new Date(now).toISOString()}
                : url.endsWith('/signals') ? {signals: [signal()]}
                : url.endsWith('/recent') ? {frames: []}
                : url.endsWith('/captures') ? {captures: [{captureId: 'j1939_capture_20261114_120000Z', fileName: 'synthetic.txt', sizeBytes: 1}]} : {captureActive: false};
            return {ok: true, json: async () => payload};
        },
    };
    vm.createContext(context);
    const source = fs.readFileSync(path.join(__dirname, '../static/js/dashboard.js'), 'utf8');
    vm.runInContext(source.slice(source.indexOf('let j1939Timer = null;')), context);
    return {context, nodes, calls, intervals, timeouts, listeners, element, release,
        fail: value => { failing = value; }};
}
const flush = () => new Promise(resolve => setImmediate(resolve));

test('DOM conserva tarjetas, diagnóstico RPM y descarga/captura', async () => {
    const h = browserHarness(); await flush();
    assert.equal(h.element('j1939RpmValue').textContent, '1800 rpm');
    assert.equal(h.element('j1939RpmPgnSpn').textContent, 'PGN F004 / SPN 190');
    assert.ok(h.element('j1939Signals').innerHTML.includes('1800 rpm'));
    assert.ok(h.element('j1939Signals').innerHTML.includes('SA EA'));
    assert.equal(h.element('j1939BusState').textContent, 'RX reciente');
    assert.ok(h.element('j1939CaptureFiles').innerHTML.includes('/api/j1939/captures/j1939_capture_20261114_120000Z/download'));
    await h.context.j1939CaptureAction('marker', {note: 'marca'});
    const post = h.calls.find(c => c.options.method === 'POST');
    assert.equal(post.url, '/api/j1939/capture/marker');
    assert.equal(JSON.parse(post.options.body).note, 'marca');
});
test('primer fallo HTTP mantiene reintento y no muestra RPM antigua', async () => {
    const h = browserHarness({fail: true}); await flush();
    assert.equal(h.intervals.size, 1);
    assert.equal(h.element('j1939BusState').textContent, 'API no disponible');
    assert.equal(h.element('j1939RpmValue').textContent, 'Sin dato válido reciente');
    h.fail(false); await h.context.actualizarJ1939();
    assert.equal(h.element('j1939RpmValue').textContent, '1800 rpm');
});
test('consulta pendiente no se solapa con siguiente actualización', async () => {
    const h = browserHarness({delayed: true});
    assert.equal(h.calls.length, 5);
    await h.context.actualizarJ1939(); assert.equal(h.calls.length, 5);
    h.release(); await flush();
    assert.equal(h.timeouts.size, 0);
});
test('pestaña oculta pausa polling y al volver recupera consultas', async () => {
    const h = browserHarness({hidden: true}); await flush();
    assert.equal(h.calls.length, 0); assert.equal(h.intervals.size, 0);
    h.context.document.hidden = false; h.listeners.get('visibilitychange')(); await flush();
    assert.equal(h.calls.length, 5); assert.equal(h.intervals.size, 1);
    h.context.document.hidden = true; h.listeners.get('visibilitychange')();
    assert.equal(h.intervals.size, 0);
});
test('petición colgada tiene aborto temporal y no bloquea JavaScript', async () => {
    const h = browserHarness({hidden: true});
    h.context.fetch = (_url, options) => new Promise((_resolve, reject) => {
        options.signal.addEventListener('abort', () => reject(new Error('aborted')));
    });
    const pending = h.context.j1939Request('/api/j1939/status');
    const timeout = [...h.timeouts.values()][0]; assert.equal(timeout.ms, 3500);
    timeout.fn(); await assert.rejects(pending, /aborted/); assert.equal(h.timeouts.size, 0);
});
test('contenido dinámico se escapa y no crea HTML ejecutable', async () => {
    const h = browserHarness({hidden: true});
    assert.equal(h.context.j1939Esc('<img src=x>'), '&lt;img src=x&gt;');
});

test('DOM mantiene origen elegido cuando la API publica otra ECU', async () => {
    const h = browserHarness(); await flush();
    const originalFetch = h.context.fetch;
    h.context.fetch = (url, options) => url.endsWith('/signals')
        ? Promise.resolve({ok: true, json: async () => ({signals: [signal({sourceAddress: '01', value: 900})]})})
        : originalFetch(url, options);
    await h.context.actualizarJ1939();
    assert.equal(h.element('j1939RpmValue').textContent, '1800 rpm');
    h.listeners.get('j1939RpmSource:change')({target: {value: '01'}});
    assert.equal(h.element('j1939RpmValue').textContent, '900 rpm');
});
test('DOM rechaza número con calidad INVALID en tarjetas y diagnóstico', async () => {
    const h = browserHarness(); await flush();
    const originalFetch = h.context.fetch;
    h.context.fetch = (url, options) => url.endsWith('/signals')
        ? Promise.resolve({ok: true, json: async () => ({signals: [signal({quality: 'INVALID'})]})})
        : originalFetch(url, options);
    await h.context.actualizarJ1939();
    assert.ok(!h.element('j1939Signals').innerHTML.includes('1800'));
    assert.equal(h.element('j1939RpmValue').textContent, 'Sin dato válido reciente');
});
