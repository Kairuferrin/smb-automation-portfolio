"""El mejorador: lee los fallos del banco A y propone cambios al prompt del agente.

Uso:
    python3 mejorar.py resultados/<archivo del examen del banco A>.json

Solo acepta resultados del banco A. El banco B es el examen final: si el
mejorador lo viera, aprendería las respuestas de memoria (sobreajuste) y la
nota final ya no diría nada de cómo se porta con clientes nuevos.
Cada propuesta la aprueba o rechaza una persona (Kairu) con aplicar_cambios.py.
"""

import json
import sys

from comun import CARPETA, Gasto, llamar_gemini
from examinar import texto_conversacion

PROMPT_MEJORADOR = """Eres un experto en escribir instrucciones (prompts) para agentes de IA.
Este es el prompt actual de un agente de atención al cliente de una tienda de ropa:
<<<PROMPT
{prompt}
PROMPT>>>

En un examen ha fallado estos casos. Para cada uno tienes lo que se esperaba,
la conversación (con lo que devolvieron las herramientas) y qué criterios fallaron:
{fallos}

Propón como MÁXIMO 4 cambios al prompt que arreglen las CAUSAS de esos fallos.
Reglas:
- Cambios generales, que sirvan para cualquier cliente. Nada de mencionar
  números de pedido ni frases concretas de estos casos (eso sería memorizar el examen).
- No toques la parte del "Formato de salida" (el JSON final).
- Cada cambio es: "buscar" = un trozo EXACTO del prompt actual que se sustituye
  (o "" para añadirlo al final de las reglas) y "reemplazar_por" = el texto nuevo.
- Si un fallo parece culpa del examen y no del agente, dilo en "dudas" en vez de
  proponer un cambio.
Responde SOLO con JSON:
{{"propuestas": [{{"buscar": "...", "reemplazar_por": "...", "por_que": "una frase",
"casos": ["A01"], "riesgo": "qué podría empeorar, una frase"}}], "dudas": ["..."]}}"""


def describir_fallos(resultados, casos):
    bloques = []
    for r in resultados:
        if r["aprobado"] or r["error"]:
            continue
        caso = casos[r["id"]]
        fallados = {k: v["motivo"] for k, v in r["notas"].items() if not v["ok"]}
        bloques.append(
            f"### Caso {r['id']} ({caso['escenario']})\n"
            f"Esperado: {caso['por_que']}\n"
            f"Conversación:\n{texto_conversacion(r['conversacion'], con_herramientas=True)}\n"
            f"Criterios fallados: {json.dumps(fallados, ensure_ascii=False)}")
    return "\n\n".join(bloques)


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    examen = json.loads((CARPETA / sys.argv[1]).read_text(encoding="utf-8"))
    if examen["banco"] != "A":
        raise SystemExit("El mejorador solo puede ver el banco A (el B es el examen final).")
    casos = {c["id"]: c for c in json.loads((CARPETA / "casos_A.json").read_text(encoding="utf-8"))}
    fallos = describir_fallos(examen["resultados"], casos)
    if not fallos:
        raise SystemExit("No hay fallos en el banco A: nada que mejorar.")

    prompt = (CARPETA / examen["prompt"]).read_text(encoding="utf-8")
    gasto = Gasto(limite_usd=0.2)
    respuesta = llamar_gemini(PROMPT_MEJORADOR.format(prompt=prompt, fallos=fallos), gasto)

    propuestas = respuesta.get("propuestas", [])
    for numero, p in enumerate(propuestas, 1):
        p["numero"] = numero
        p["encaja"] = p.get("buscar", "") == "" or p["buscar"] in prompt
    salida = CARPETA / "propuestas" / f"{(CARPETA / examen['prompt']).stem}.json"
    salida.parent.mkdir(exist_ok=True)
    salida.write_text(json.dumps({"prompt": examen["prompt"], "examen": sys.argv[1], **respuesta},
                                 ensure_ascii=False, indent=2), encoding="utf-8")

    for p in propuestas:
        print(f"\n[{p['numero']}] {p.get('por_que', '')}  (casos: {', '.join(p.get('casos', []))})")
        print(f"    Cambia: {p.get('buscar') or '(se añade al final de las reglas)'}")
        print(f"    Por:    {p.get('reemplazar_por', '')}")
        print(f"    Riesgo: {p.get('riesgo', '')}")
        if not p["encaja"]:
            print("    ⚠️  El texto a cambiar no está en el prompt: no se podrá aplicar.")
    for duda in respuesta.get("dudas", []):
        print(f"\n¿Culpa del examen? {duda}")
    print(f"\nGuardado en {salida.relative_to(CARPETA)} · gasto ≈ {gasto.dolares():.4f} $")


if __name__ == "__main__":
    main()
