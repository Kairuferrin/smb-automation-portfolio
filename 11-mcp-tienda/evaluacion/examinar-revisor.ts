/**
 * Examen del revisor externo: le pasa el banco de casos (casos.ts) varias veces y mide cuánto acierta.
 *
 * Trabaja en una COPIA del orquestador (.sandbox-revisor/), así no toca las lecciones ni el registro reales.
 * La copia está al mismo nivel que orquestador/, para que sus rutas relativas (MCP y clave) sigan funcionando.
 *
 * Uso (desde mcp-tienda/):  node evaluacion/examinar-revisor.ts [repeticiones]   (por defecto 3)
 */
import { spawnSync } from 'node:child_process';
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { CASOS } from './casos.ts';

const MCP_TIENDA = fileURLToPath(new URL('..', import.meta.url));
const ORIGEN = join(MCP_TIENDA, 'orquestador');
const COPIA = join(MCP_TIENDA, '.sandbox-revisor');
const CARPETA_RESULTADOS = join(MCP_TIENDA, 'evaluacion', 'resultados');
const REPETICIONES = Number(process.argv[2] ?? 3);
const FILTRO = process.argv[3] ?? ''; // opcional: solo los casos cuyo id empieza así (p. ej. "x-")
if (!Number.isInteger(REPETICIONES) || REPETICIONES < 1) throw new Error('Repeticiones: un número entero mayor que 0.');
// Los casos dependen de que ningún pedido tenga una devolución solicitada (si no, sus datos cambian)
if (existsSync(join(MCP_TIENDA, 'datos', 'devoluciones.db'))) {
  throw new Error('Existe datos/devoluciones.db: los datos de los casos podrían no coincidir. Apártalo antes del examen.');
}
const LECCIONES_VACIAS = '# Lecciones\n<!-- Solo el revisor añade lecciones aquí, cuando las aprueba. -->\n';
const PAUSA_MS = 4000; // no saturar a Gemini

type Intento = { veredicto: string; motivo: string; por?: 'codigo' | 'gemini' };

function prepararCopia(archivos: Record<string, string>) {
  rmSync(COPIA, { recursive: true, force: true });
  cpSync(ORIGEN, COPIA, { recursive: true });
  // Lecciones fijas y vacías: el examen no depende de lo que haya aprendido el orquestador real
  writeFileSync(join(COPIA, 'trabajadores', 'atencion-pedidos', 'lecciones.md'), LECCIONES_VACIAS);
  for (const [ruta, contenido] of Object.entries(archivos)) {
    mkdirSync(dirname(join(COPIA, ruta)), { recursive: true });
    writeFileSync(join(COPIA, ruta), contenido);
  }
}

const resultados: { id: string; tipo: string; esperado: string; que_se_prueba: string; intentos: Intento[] }[] = [];
for (const caso of CASOS.filter((c) => c.id.startsWith(FILTRO))) {
  const intentos: Intento[] = [];
  for (let i = 0; i < REPETICIONES; i++) {
    prepararCopia(caso.archivos);
    const r = spawnSync(process.execPath, ['revisor/revisar.ts', ...caso.args], { cwd: COPIA, encoding: 'utf8' });
    try {
      const v = JSON.parse(r.stdout.trim()) as Intento;
      // El código forma parte del revisor (comprueba lo medible). Un veto por la HUELLA del puesto
      // significa que el examen está mal montado: eso es ERROR, no un acierto.
      v.por = v.motivo.startsWith('Comprobación automática') ? 'codigo' : 'gemini';
      if (v.por === 'codigo' && caso.tipo === 'resultado' && v.motivo.includes('no está aprobado')) v.veredicto = 'ERROR';
      // Retirar aprobado: además del veredicto, comprobamos que los archivos quedaron como deben
      if (caso.tipo === 'retirar' && v.veredicto === 'APROBADO') {
        const titulo = Object.values(caso.archivos).join('\n').match(/^Lección a retirar:\s*(.+)$/m)![1].trim();
        const carpeta = join(COPIA, 'trabajadores', 'atencion-pedidos');
        const quedan = readFileSync(join(carpeta, 'lecciones.md'), 'utf8');
        const retiradas = existsSync(join(carpeta, 'lecciones-retiradas.md')) ? readFileSync(join(carpeta, 'lecciones-retiradas.md'), 'utf8') : '';
        const otras = (Object.values(caso.archivos)[0].match(/^## .+$/gm) ?? []).filter((t) => t !== `## ${titulo}`);
        if (quedan.includes(`## ${titulo}`) || !retiradas.includes(`## ${titulo}`) || otras.some((t) => !quedan.includes(t))) {
          v.veredicto = 'ERROR';
          v.motivo = 'Aprobó, pero los archivos de lecciones no quedaron bien. ' + v.motivo;
        }
      }
      intentos.push(v);
    } catch {
      intentos.push({ veredicto: 'ERROR', motivo: (r.stderr || r.stdout).trim().slice(0, 200) });
    }
    await new Promise((ok) => setTimeout(ok, PAUSA_MS));
  }
  const aciertos = intentos.filter((x) => x.veredicto === caso.esperado).length;
  console.error(`${caso.id.padEnd(26)} esperado ${caso.esperado.padEnd(8)} → ${intentos.map((x) => x.veredicto).join(', ')}  (${aciertos}/${REPETICIONES})`);
  resultados.push({ id: caso.id, tipo: caso.tipo, esperado: caso.esperado, que_se_prueba: caso.que_se_prueba, intentos });
}
rmSync(COPIA, { recursive: true, force: true });

// ---- Las tres cifras del informe ----
// Los ERROR no cuentan en los porcentajes (no son veredictos de Gemini)
const todos = resultados.flatMap((r) => r.intentos.map((x) => ({ ...x, esperado: r.esperado }))).filter((x) => x.veredicto !== 'ERROR');
const conError = todos.filter((x) => x.esperado === 'VETADO');
const buenos = todos.filter((x) => x.esperado === 'APROBADO');
const pct = (a: number, b: number) => (b ? Math.round((a / b) * 1000) / 10 : 0);
const resumen = {
  fecha: new Date().toISOString(),
  repeticiones: REPETICIONES,
  casos: resultados.length,
  // De los trabajos con error, ¿cuántas veces lo vetó? (cuanto más alto, mejor)
  errores_detectados_pct: pct(conError.filter((x) => x.veredicto === 'VETADO').length, conError.length),
  // De los trabajos buenos, ¿cuántas veces los vetó sin motivo? (cuanto más bajo, mejor)
  vetos_injustos_pct: pct(buenos.filter((x) => x.veredicto === 'VETADO').length, buenos.length),
  // ¿En cuántos casos cambió de opinión entre repeticiones? (cuanto más bajo, mejor)
  casos_inconsistentes: resultados.filter((r) => new Set(r.intentos.map((x) => x.veredicto)).size > 1).map((r) => r.id),
  // Quién acertó: el código (lo medible) o Gemini (lo que hay que juzgar)
  aciertos_por: {
    codigo: resultados.flatMap((r) => r.intentos.filter((x) => x.por === 'codigo' && x.veredicto === r.esperado)).length,
    gemini: resultados.flatMap((r) => r.intentos.filter((x) => x.por === 'gemini' && x.veredicto === r.esperado)).length,
  },
  errores_de_ejecucion: resultados.flatMap((r) => r.intentos).filter((x) => x.veredicto === 'ERROR').length,
  por_tipo: Object.fromEntries(['resultado', 'leccion', 'retirar', 'carpeta'].map((t) => {
    const deTipo = resultados.filter((r) => r.tipo === t).flatMap((r) => r.intentos.map((x) => x.veredicto === r.esperado));
    return [t, `${deTipo.filter(Boolean).length}/${deTipo.length} aciertos`];
  })),
  fallos: resultados.flatMap((r) => r.intentos.filter((x) => x.veredicto !== r.esperado)
    .map((x) => ({ id: r.id, que_se_prueba: r.que_se_prueba, esperado: r.esperado, dijo: x.veredicto, motivo: x.motivo }))),
};

mkdirSync(CARPETA_RESULTADOS, { recursive: true });
const ahora = new Date(); // hora local, para que el nombre coincida con tu reloj
const marca = `${ahora.getFullYear()}${String(ahora.getMonth() + 1).padStart(2, '0')}${String(ahora.getDate()).padStart(2, '0')}-${String(ahora.getHours()).padStart(2, '0')}${String(ahora.getMinutes()).padStart(2, '0')}`;
const archivo = join(CARPETA_RESULTADOS, `examen-revisor-${marca}.json`);
writeFileSync(archivo, JSON.stringify({ resumen, resultados }, null, 2) + '\n');
console.log(JSON.stringify(resumen, null, 2));
console.error(`Guardado en ${archivo}`);
