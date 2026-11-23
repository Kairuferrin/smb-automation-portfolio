/**
 * Cruce por código entre lo que dice una respuesta y el estado ACTUAL de cada pedido.
 * Está aparte de revisar.ts para poder probarlo solo (sin llamar a Gemini ni al MCP).
 *
 * Es prudente a propósito: si duda (varios estados, pasado o futuro, negación), no dice nada.
 * Un falso veto bloquea al orquestador; un error que se escapa aún puede pillarlo Gemini.
 */
// Palabras que indican cada estado (en singular o plural, con o sin acento)
export const PALABRAS_ESTADO: Record<string, RegExp> = {
  enviado: /\b(enviad[oa]s?|en camino)\b/i,
  entregado: /\b(entregad[oa]s?)\b/i,
  preparando: /\b(preparando|en preparaci[oó]n|prepar[aá]ndose)\b/i,
  devuelto: /\b(devuelt[oa]s?)\b/i,
};

// Si el trozo habla del pasado o del futuro, el estado que nombra no es necesariamente el de ahora
const PASADO_O_FUTURO = /\b(fue|fueron|ser[aá]n?|una vez|cuando|tendr[aá]n?|se haya|hayan?|hasta que|despu[eé]s de|antes de|si se|podr[aá]n?)\b/i;

const MESES = 'enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre';

/** Quita del trozo lo que se parece a un número de pedido sin serlo: fechas e importes. */
function quitarFechasEImportes(texto: string): string {
  return texto
    .replace(/\b\d{4}-\d{2}-\d{2}\b/g, ' ') // 2025-12-30
    .replace(/\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b/g, ' ') // 30/12/2025, 30-12-2025
    .replace(new RegExp(`\\b(?:de|del|en|año|a[ñn]o|${MESES})\\s+(?:de\\s+)?\\d{4}\\b`, 'gi'), ' ') // de/del/en/año 2025, diciembre (de) 2025
    .replace(/\b\d{1,2}\.\d{1,2}\.\d{4}\b/g, ' ') // 30.12.2025
    .replace(/\b\d{1,3}(?:\.\d{3})+(?:,\d+)?\b/g, ' ') // 1.350,20
    .replace(/\b\d+[.,]\d{1,2}\b/g, ' ') // 1350,20 · 1350.20
    .replace(/\b\d+\s*(?:€|eur|euros)\b/gi, ' '); // 1350 €
}

/**
 * Cruza cada pedido de la respuesta con su estado real (Gemini falla cruzando listas largas).
 * Trocea la respuesta en frases, filas de tabla y partes unidas por "pero / mientras / aunque";
 * si un trozo nombra pedidos y UN solo estado en presente, ese estado es el de esos pedidos.
 * Devuelve las contradicciones encontradas (vacía = todo cuadra o no se puede saber).
 */
export function contradiccionesDeEstado(respuesta: string, estadosReales: Map<string, string>): string[] {
  const fallos: string[] = [];
  const trozos = respuesta
    .split('\n')
    .flatMap((linea) => (linea.includes('|') ? [linea] : linea.split(/[.;:]+|,?\s+(?:pero|mientras(?: que)?|aunque|en cambio|sin embargo)\s+/i)));
  for (const trozo of trozos) {
    if (PASADO_O_FUTURO.test(trozo)) continue;
    // Un estado negado no cuenta: "aún no entregado", "no se haya entregado", "sin enviar", "ni devuelto"
    let limpio = trozo.replace(/\b(?:no|sin|ni)\b(?:\s+\S+){0,3}?\s+(?:entregad|enviad|devuelt|prepar)\S*/gi, ' ');
    // "líneas devueltas", "unidades devueltas"… son cifras de ventas, no el estado de un pedido
    limpio = limpio.replace(/\b(l[ií]neas|unidades|prendas|ventas|importes?|dinero|reembolsos?)\s+devuelt\S*/gi, ' ');
    const estados = Object.entries(PALABRAS_ESTADO).filter(([, re]) => re.test(limpio)).map(([e]) => e);
    if (estados.length !== 1) continue; // ninguno o varios: no se puede asignar sin riesgo
    for (const m of quitarFechasEImportes(limpio).matchAll(/(?:#|\b)(\d{4})\b/g)) {
      const real = estadosReales.get(m[1]);
      if (real && real !== estados[0]) fallos.push(`el pedido ${m[1]} aparece como "${estados[0]}" pero está "${real}"`);
    }
  }
  return [...new Set(fallos)];
}
