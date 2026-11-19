/* Read-only history; timestamps are shown in Colombia and retained in UTC. */
(() => {
    const latest = typeof document === 'undefined' ? null : document.getElementById('engineLatest');
    const esc = value => String(value ?? 'Sin dato').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const date = value => value ? `${new Date(value).toLocaleString('es-CO', {timeZone: 'America/Bogota', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3, hour12: false})} (${esc(value)} UTC)` : 'No confirmado';
    const fmt = value => value == null ? 'Sin dato' : esc(value);
    const duration = n => {
        if (typeof n !== 'number' || !Number.isFinite(n) || n < 0) return 'Sin dato';
        let v = Math.round(n);
        const days = Math.floor(v / 86400); v %= 86400;
        const hours = Math.floor(v / 3600); v %= 3600;
        const minutes = Math.floor(v / 60), seconds = v % 60;
        const parts = [[days, 'día', 'días'], [hours, 'hora', 'horas'], [minutes, 'minuto', 'minutos'], [seconds, 'segundo', 'segundos']];
        return parts.filter(x => x[0] !== 0).map(([value, singular, plural]) => `${value} ${value === 1 ? singular : plural}`).join(' ') || '0 segundos';
    };
    if (typeof module !== 'undefined' && module.exports) module.exports = {duration};
    if (!latest) return;
    const elapsed = s => {
        if (!s.ended_at_utc || !s.stop_event_id) return null;
        const start = Date.parse(s.started_at_utc || s.observed_from_utc);
        const end = Date.parse(s.ended_at_utc);
        return Number.isFinite(start) && Number.isFinite(end) && end >= start ? (end - start) / 1000 : null;
    };
    const hours = s => s?.value ?? null;
    const hourObservation = s => s ? `${s.value} h (${date(s.timestamp_utc)}; ${s.source}, evento ${s.event_id})` : 'Sin dato';
    const priorContext = d => (d.prior_observation_context || []).map(g =>
        `ID ${g.gap_id}: ${date(g.started_at_utc)} → ${date(g.recovered_at_utc)} (${g.reason})`).join('; ') || 'Sin dato';
    let offset = 0;
    async function get(path) { const r = await fetch(path); if (!r.ok) throw Error('No disponible'); return r.json(); }
    async function load() {
        try {
            const data = await get('/api/j1939/engine/latest');
            const expected = ['engine_speed','coolant_temperature','engine_total_hours','dc_voltage_field_1'];
            latest.innerHTML = expected.map(key => {
                const s = data.signals.find(x => x.key === key && x.sourceAddress === 'EA');
                if (!s) return `<article class="j1939-signal">${esc(key)}: Sin dato de SA EA</article>`;
                const age = (Date.now() - Date.parse(s.timestampUtc)) / 1000;
                const stale = !Number.isFinite(age) || age < 0 || age > 15;
                return `<article class="j1939-signal"><span>${esc(s.name)}</span><strong>${fmt(s.value)} ${esc(s.unit)}</strong><small>${stale ? 'DESACTUALIZADO · ' : ''}${esc(s.quality)} · ${esc(s.confidence)} · PGN ${esc(s.pgn)} · SA ${esc(s.sourceAddress)}<br>Muestra: ${date(s.timestampUtc)}<br>Último cambio: ${date(s.lastChangedAt)}<br>Última publicación (${esc(s.publishReason)}): ${date(s.lastPublishedAt)}</small></article>`;
            }).join('') + `<article class="j1939-signal"><span>Estado del motor</span><strong>${esc(data.engine.state ?? 'UNKNOWN')}</strong><small>${esc(data.engine.quality ?? 'NO_DATA')} · Última observación: ${date(data.engine.lastObservationUtc)}</small></article>`;
            const page = await get(`/api/j1939/engine/sessions?limit=20&offset=${offset}`);
            const el = document.getElementById('engineHistory');
            el.innerHTML = page.sessions.length ? '<table><thead><tr><th>Primera observación</th><th>Inicio</th><th>Parada</th><th>Tiempo verificado (legible)</th><th>RPM inicial observada</th><th>RPM máxima registrada</th><th>RPM final</th><th>Refrigerante °C</th><th>Horómetro previo h</th><th>Horómetro posterior h</th><th>Diferencia h</th><th>Estado</th><th>Evidencia RAW</th><th>Detalle</th></tr></thead><tbody>' + page.sessions.map(s => `<tr><td>${date(s.observed_from_utc)}</td><td>${s.started_at_utc ? date(s.started_at_utc) : 'Arranque no confirmado'}</td><td>${date(s.ended_at_utc)}</td><td>${esc(duration(s.verified_seconds))}</td><td>${fmt(s.initial_rpm)}</td><td>${fmt(s.rpm_max)}</td><td>${fmt(s.final_rpm)}</td><td>${fmt(s.coolant_first)} / ${fmt(s.coolant_last)}</td><td>${fmt(hours(s.hourmeter_observations?.prior))}</td><td>${fmt(hours(s.hourmeter_observations?.posterior))}</td><td>${fmt(s.hourmeter_delta)}</td><td>${esc(s.status)}</td><td>${esc((s.evidence || []).map(e => e.integrity).join(', ') || 'Sin dato')}</td><td><button type="button" data-session="${esc(s.session_id)}">Detalle</button></td></tr>`).join('') + '</tbody></table>' : 'Sin sesiones';
            el.querySelectorAll('[data-session]').forEach(button => button.addEventListener('click', async () => {
                try { const d = await get('/api/j1939/engine/sessions/' + encodeURIComponent(button.dataset.session)); document.getElementById('engineDetail').textContent = `Sesión ${d.session_id}\nInicio: ${d.started_at_utc || 'Arranque no confirmado'}\nPrimera observación: ${d.observed_from_utc}\nParada: ${d.ended_at_utc || 'No confirmado'}\nRPM primera observación RUNNING: ${d.initial_rpm ?? 'Sin dato'} · máxima persistida: ${d.rpm_max ?? 'Sin dato'} · final: ${d.final_rpm ?? 'Sin dato'}\nRefrigerante inicial/final: ${d.coolant_first ?? 'Sin dato'} / ${d.coolant_last ?? 'Sin dato'} °C\nHorómetro asociado START/STOP: ${hours(d.hourmeter_observations?.start) ?? 'Sin dato'} / ${hours(d.hourmeter_observations?.stop) ?? 'Sin dato'} h · observado previo/posterior: ${hourObservation(d.hourmeter_observations?.prior)} / ${hourObservation(d.hourmeter_observations?.posterior)} · diferencia: ${d.hourmeter_delta ?? 'Sin dato'}\nTiempo transcurrido (${d.started_at_utc ? 'START confirmado' : 'primera observación RUNNING'}): ${duration(elapsed(d))}\nTiempo verificado: ${duration(d.verified_seconds)} (${d.verified_seconds ?? 'Sin dato'} s) · Estado: ${d.status}\nInterrupciones vinculadas: ${d.observation_gaps.length} · Contexto previo no vinculado: ${(d.prior_observation_context || []).length} (${priorContext(d)}) · Evidencia: ${d.evidence.map(e => e.integrity).join(', ') || 'Sin dato'}\nAdvertencias: ${d.warnings.join(', ') || 'ninguna'}`; }
                catch (_) { document.getElementById('engineDetail').textContent = 'Detalle no disponible'; }
            }));
            if (offset === 0 && page.sessions.length) {
                const d = await get('/api/j1939/engine/sessions/' + encodeURIComponent(page.sessions[0].session_id));
                document.getElementById('engineLastSession').textContent = `Inicio: ${d.started_at_utc ? date(d.started_at_utc) : 'Arranque no confirmado'} · Primera observación: ${date(d.observed_from_utc)} · Parada: ${date(d.ended_at_utc)} · RPM primera observación RUNNING / máxima registrada / final: ${d.initial_rpm ?? 'Sin dato'} / ${d.rpm_max ?? 'Sin dato'} / ${d.final_rpm ?? 'Sin dato'} · Refrigerante inicial / final: ${d.coolant_first ?? 'Sin dato'} / ${d.coolant_last ?? 'Sin dato'} °C · Horómetro observado previo / posterior: ${hourObservation(d.hourmeter_observations?.prior)} / ${hourObservation(d.hourmeter_observations?.posterior)} · diferencia: ${d.hourmeter_delta ?? 'Sin dato'} · Tiempo transcurrido (${d.started_at_utc ? 'START confirmado' : 'primera observación RUNNING'}): ${duration(elapsed(d))} · Tiempo verificado: ${duration(d.verified_seconds)} (${d.verified_seconds ?? 'Sin dato'} s) · Estado: ${d.status} · Interrupciones vinculadas: ${d.observation_gaps.length} · Contexto previo no vinculado: ${(d.prior_observation_context || []).length} (${priorContext(d)}) · Evidencia: ${(d.evidence || []).map(e => e.integrity).join(', ') || 'Sin dato'} · Advertencias: ${d.warnings.join(', ') || 'ninguna'}`;
            }
        } catch (_) { latest.textContent = 'Historial o telemetría no disponible'; }
    }
    document.getElementById('engineMore').addEventListener('click', () => { offset += 20; load(); });
    load(); setInterval(load, 30000);
})();
