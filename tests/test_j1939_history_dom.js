const assert = require('assert');
const elements = Object.fromEntries(['engineLatest', 'engineHistory', 'engineLastSession', 'engineDetail', 'engineMore'].map(id => [id, {innerHTML:'', textContent:'', addEventListener() {}, querySelectorAll() { return []; }}]));
global.document = {getElementById(id) { return elements[id] || null; }};
global.setInterval = () => 0;
const session = {session_id:'synthetic-session', observed_from_utc:'2031-04-12T13:52:47Z', started_at_utc:null, ended_at_utc:'2031-04-12T14:25:30Z', verified_seconds:1234.567, status:'INDETERMINADA', quality:'INCOMPLETE', initial_rpm:1555.125, final_rpm:0, coolant_first:null, coolant_last:null, initial_hourmeter:null, final_hourmeter:null, observation_gaps:[{},{}], evidence:[{integrity:'INCOMPLETE'},{integrity:'INCOMPLETE'}], warnings:['unconfirmed_start','observation_gaps']};
global.fetch = async url => ({ok:true, json:async () => url.endsWith('/latest') ? {signals:[], engine:{state:'UNKNOWN',quality:'STALE',lastObservationUtc:null}} : url.includes('?') ? {sessions:[session]} : session});
require('../static/js/j1939_history.js');
setTimeout(() => {
  assert(elements.engineLatest.innerHTML.includes('STALE'));
  assert(elements.engineHistory.innerHTML.includes('Arranque no confirmado'));
  assert(elements.engineHistory.innerHTML.includes('INDETERMINADA'));
  assert(elements.engineLastSession.textContent.includes('Arranque no confirmado'));
  assert(elements.engineLastSession.textContent.includes('INCOMPLETE'));
  assert(elements.engineLastSession.textContent.includes('Interrupciones vinculadas: 2'));
  assert(elements.engineLastSession.textContent.includes('Sin dato'));
  assert(elements.engineLastSession.textContent.includes('1234.567'));
  assert(elements.engineLastSession.textContent.includes('9:25:30'));
  console.log('PASS: DOM simulado, sesión indeterminada y datos ausentes');
}, 50);
