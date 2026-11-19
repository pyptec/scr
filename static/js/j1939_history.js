/* Read-only history; timestamps are shown in Colombia and retained in UTC. */
(() => {
    const latest = document.getElementById('engineLatest');
    if (!latest) return;
    const esc = value => String(value ?? 'Sin dato').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const date = value => value ? `${new Date(value).toLocaleString('es-CO', {timeZone: 'America/Bogota', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3, hour12: false})} (${esc(value)} UTC)` : 'No confirmado';
    const fmt = value => value == null ? 'Sin dato' : esc(value);
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
            el.innerHTML = page.sessions.length ? '<table><thead><tr><th>Primera observación</th><th>Inicio</th><th>Parada</th><th>Tiempo verificado</th><th>RPM máxima</th><th>Refrigerante °C</th><th>Horómetro h</th><th>Estado</th><th>Evidencia RAW</th><th>Detalle</th></tr></thead><tbody>' + page.sessions.map(s => `<tr><td>${date(s.observed_from_utc)}</td><td>${s.started_at_utc ? date(s.started_at_utc) : 'Arranque no confirmado'}</td><td>${date(s.ended_at_utc)}</td><td>${fmt(s.verified_seconds)} s</td><td>${fmt(s.rpm_max)}</td><td>${fmt(s.coolant_first)} / ${fmt(s.coolant_last)}</td><td>${fmt(s.initial_hourmeter)} / ${fmt(s.final_hourmeter)}</td><td>${esc(s.status)}</td><td>${esc((s.evidence || []).map(e => e.integrity).join(', ') || 'Sin dato')}</td><td><button type="button" data-session="${esc(s.session_id)}">Detalle</button></td></tr>`).join('') + '</tbody></table>' : 'Sin sesiones';
            el.querySelectorAll('[data-session]').forEach(button => button.addEventListener('click', async () => {
                try { const d = await get('/api/j1939/engine/sessions/' + encodeURIComponent(button.dataset.session)); document.getElementById('engineDetail').textContent = `Sesión ${d.session_id}\nInicio: ${d.started_at_utc || 'Arranque no confirmado'}\nPrimera observación: ${d.observed_from_utc}\nParada: ${d.ended_at_utc || 'No confirmado'}\nRPM inicial: ${d.initial_rpm ?? 'Sin dato'} · máxima persistida: ${d.rpm_max ?? 'Sin dato'} · final: ${d.final_rpm ?? 'Sin dato'}\nRefrigerante inicial/final: ${d.coolant_first ?? 'Sin dato'} / ${d.coolant_last ?? 'Sin dato'} °C\nHorómetro inicial/final: ${d.initial_hourmeter ?? 'Sin dato'} / ${d.final_hourmeter ?? 'Sin dato'} h · incremento: ${d.hourmeter_delta ?? 'Sin dato'}\nTiempo verificado: ${d.verified_seconds} s · Estado: ${d.status}\nInterrupciones vinculadas: ${d.observation_gaps.length} · Contexto previo no vinculado: ${(d.prior_observation_context || []).length} (${priorContext(d)}) · Evidencia: ${d.evidence.map(e => e.integrity).join(', ') || 'Sin dato'}\nAdvertencias: ${d.warnings.join(', ') || 'ninguna'}`; }
                catch (_) { document.getElementById('engineDetail').textContent = 'Detalle no disponible'; }
            }));
            if (offset === 0 && page.sessions.length) {
                const d = await get('/api/j1939/engine/sessions/' + encodeURIComponent(page.sessions[0].session_id));
                document.getElementById('engineLastSession').textContent = `Inicio: ${d.started_at_utc ? date(d.started_at_utc) : 'Arranque no confirmado'} · Primera observación: ${date(d.observed_from_utc)} · Parada: ${date(d.ended_at_utc)} · RPM inicial / máxima / final: ${d.initial_rpm ?? 'Sin dato'} / ${d.rpm_max ?? 'Sin dato'} / ${d.final_rpm ?? 'Sin dato'} · Refrigerante inicial / final: ${d.coolant_first ?? 'Sin dato'} / ${d.coolant_last ?? 'Sin dato'} °C · Horómetro inicial / final: ${d.initial_hourmeter ?? 'Sin dato'} / ${d.final_hourmeter ?? 'Sin dato'} h · Tiempo verificado: ${d.verified_seconds} s · Estado: ${d.status} · Interrupciones vinculadas: ${d.observation_gaps.length} · Contexto previo no vinculado: ${(d.prior_observation_context || []).length} (${priorContext(d)}) · Evidencia: ${(d.evidence || []).map(e => e.integrity).join(', ') || 'Sin dato'} · Advertencias: ${d.warnings.join(', ') || 'ninguna'}`;
            }
        } catch (_) { latest.textContent = 'Historial o telemetría no disponible'; }
    }
    document.getElementById('engineMore').addEventListener('click', () => { offset += 20; load(); });
    load(); setInterval(load, 30000);
})();
