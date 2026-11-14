/* Diagnóstico visual: no calcula estado del motor ni controla CAN. */
(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    else root.J1939Diagnostics = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';
    function ageSeconds(stamp, nowMs) {
        if (typeof stamp !== 'string' || !/(Z|[+-]\d{2}:\d{2})$/.test(stamp)) return null;
        const stampMs = Date.parse(stamp);
        return Number.isFinite(stampMs) && Number.isFinite(nowMs) && stampMs <= nowMs
            ? (nowMs - stampMs) / 1000 : null;
    }
    function validNumber(signal) {
        return signal?.quality === 'GOOD' && typeof signal.value === 'number' && Number.isFinite(signal.value);
    }
    function sourceAddress(value) {
        return typeof value === 'string' && /^[0-9a-f]{2}$/i.test(value) ? value.toUpperCase() : null;
    }
    class RpmMonitor {
        constructor() { this.sources = new Map(); }
        observe(signals, nowMs) {
            for (const s of Array.isArray(signals) ? signals : []) {
                const source = sourceAddress(s?.sourceAddress);
                if (s?.key !== 'engine_speed' || String(s.pgn).toUpperCase() !== 'F004'
                    || s.unit !== 'rpm' || !source) continue;
                const entry = this.sources.get(source);
                const stamp = ageSeconds(s.timestampUtc, nowMs) === null ? null : s.timestampUtc;
                // No retroceder la evidencia del origen por una respuesta atrasada.
                if (entry && stamp && Date.parse(stamp) < Date.parse(entry.signal.timestampUtc)) continue;
                const good = validNumber(s) && s.value >= 0 && s.value <= 3000 && stamp !== null;
                this.sources.set(source, {
                    signal: {...s, sourceAddress: source},
                    lastValidAt: good ? stamp : entry?.lastValidAt ?? null,
                });
            }
        }
        view(source, nowMs, staleSeconds, unavailable = false) {
            const entry = this.sources.get(source);
            const s = entry?.signal;
            const sampleAge = ageSeconds(s?.timestampUtc, nowMs);
            const lastValidAge = ageSeconds(entry?.lastValidAt, nowMs);
            const good = validNumber(s) && s.value >= 0 && s.value <= 3000 && sampleAge !== null;
            const recent = good && sampleAge <= staleSeconds;
            return {
                source: source ?? '--', pgn: 'F004', spn: 190,
                rpm: !unavailable && recent ? s.value : null,
                timestampUtc: s?.timestampUtc ?? null,
                lastValidAge,
                quality: unavailable ? 'API no disponible' : !s ? 'Sin dato validado'
                    : !good ? 'Dato inválido / no disponible' : !recent ? 'Muestra caducada' : 'GOOD (según decoder)',
                communication: unavailable ? 'API no disponible' : !s ? 'Sin muestra RPM'
                    : recent ? 'RPM reciente' : 'Sin RPM válida reciente',
            };
        }
    }
    function busState(status, nowMs, staleSeconds) {
        const age = ageSeconds(status?.lastFrameAt, nowMs);
        if (status?.connected !== true) return 'Transporte desconectado';
        if (age === null) return 'Sin recepción verificable';
        return age <= staleSeconds ? 'RX reciente' : 'Sin RX reciente';
    }
    return {ageSeconds, validNumber, RpmMonitor, busState};
}));
