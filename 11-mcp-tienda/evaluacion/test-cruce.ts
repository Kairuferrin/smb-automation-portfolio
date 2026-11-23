// Pruebas del cruce por código de estados (sin Gemini ni MCP). Uso: node evaluacion/test-cruce.ts
import { contradiccionesDeEstado as f } from '../orquestador/revisor/cruce.ts';
const reales = new Map([['2362', 'enviado'], ['2025', 'entregado'], ['2391', 'preparando'], ['2383', 'entregado'], ['1350', 'entregado']]);
const casos: [string, boolean][] = [
  ['Tu pedido 2362 salió el 30/12/2025 y está en camino', false],
  ['El 2362 está enviado desde el 2025-12-30', false],
  ['2362 enviado el 3 de enero de 2025', false],
  ['2391 ya está enviado', true],
  ['2383 entregado y 2391 en preparación', false],
  ['| 2391 | enviado |', true],
  ['Los demás: 2362 y 2391 están en preparación', true],
  ['no hay fecha límite para el 2362 mientras el pedido no se haya entregado', false],
  ['#2362 · aún no entregado', false],
  ['El 2391 aún no se ha enviado: está en preparación', false],
  // Frases correctas que el revisor interno encontró (no deben vetar)
  ['Tu pedido 2383 fue enviado el 2025-03-02', false],
  ['Una vez entregado, el 2362 tendrá 30 días', false],
  ['Cuando se haya enviado el 2391, te avisaremos', false],
  ['El importe del 2383 será devuelto cuando se apruebe', false],
  ['Del 2391 aún no hay fecha, pero el 2362 está enviado', false],
  ['1350,20 € netos y 3 líneas devueltas', false],
  ['El 2362 está en camino desde diciembre 2025', false],
  ['El 2362 está en camino desde el 30-12-2025', false],
  ['El 2362 está en camino desde finales del 2025', false],
  ['El 2362 está enviado desde el 30.12.2025', false],
  ['Te devolveremos el dinero devuelto del 2383', false],
  // Y errores que sí deben vetar
  ['El 2362 está enviado, pero el 2391 ya está entregado', true],
  ['Los pedidos 2380 a 2392 están en camino salvo ninguno; el 2383 está en preparación', true],
];
let ok = 0;
for (const [texto, esperaFallo] of casos) {
  const r = f(texto, reales);
  const bien = (r.length > 0) === esperaFallo;
  ok += Number(bien);
  console.log(bien ? 'OK ' : 'MAL', JSON.stringify(texto), '→', r);
}
console.log(`${ok}/${casos.length}`);
