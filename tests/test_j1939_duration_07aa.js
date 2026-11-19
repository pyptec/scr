const assert = require('assert');
const {duration} = require('../static/js/j1939_history.js');
for (const [value, expected] of [[0,'0 segundos'],[45,'45 segundos'],[125,'2 minutos 5 segundos'],[1875,'31 minutos 15 segundos'],[3600,'1 hora'],[3725,'1 hora 2 minutos 5 segundos'],[86400,'1 día'],[90061,'1 día 1 hora 1 minuto 1 segundo'],[59.6,'1 minuto'],[3599.6,'1 hora'],[86399.6,'1 día'],[null,'Sin dato'],[-1,'Sin dato'],[NaN,'Sin dato'],['12','Sin dato']]) assert.strictEqual(duration(value),expected);
console.log('PASS: duración legible, redondeo y valores inválidos');
