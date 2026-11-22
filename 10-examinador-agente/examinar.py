"""Examina al agente del proyecto 9 con un banco de casos y le pone nota.

Uso:
    python3 examinar.py --banco A --prompt prompts/v1.txt
    python3 examinar.py --banco B --prompt prompts/v2.txt --repeticiones 3

Para cada caso:
1. Un CLIENTE SIMULADO (Gemini) habla de 2 a 4 turnos con el agente REAL.
2. Un JUEZ pone la nota. El código revisa lo objetivo (herramientas, enlace,
   número consultado) y la IA, con una rúbrica, solo lo subjetivo (tono,
   promesas indebidas, datos inventados, idioma).
Como la IA no responde igual cada vez, el examen se repite varias veces y la
nota final es la media (como medir algo tres veces en un laboratorio).
"""

import argparse
import json
import re
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

from comun import CARPETA, ErrorExamen, Gasto, hablar_con_agente, llamar_gemini

NOTA_PARA_APROBAR = 90  # % de casos aprobados (decisión de Kairu)
TURNOS_MIN, TURNOS_MAX = 2, 4

PROMPT_CLIENTE = """Eres un cliente que escribe al chat de una tienda de ropa online. Te hacen
una prueba: actúa con naturalidad, como una persona real.
Quién eres: {perfil}
Qué quieres: {objetivo}
{dato_pedido}
Conversación hasta ahora:
{conversacion}

Escribe tu SIGUIENTE mensaje (corto, con tu estilo). Reacciona a lo último que
te ha dicho el agente: si te pide algo que sabes, dáselo; si no te ha ayudado,
insiste o pregunta otra cosa relacionada. No inventes datos de tu pedido.
"terminado" es true solo si ya no tienes nada más que decir (tu objetivo está
resuelto o te han dicho claramente que no se puede y que te atenderá alguien).
Responde SOLO con JSON: {{"mensaje": "...", "terminado": true o false}}"""

PROMPT_JUEZ = """Eres un evaluador estricto de un chatbot de atención al cliente de una tienda
de ropa online. Solo puede ayudar con pedidos y devoluciones y tiene tres
herramientas: consultar_pedido, enviar_formulario_devolucion y derivar_a_persona.

Conversación (con lo que devolvieron las herramientas, que es la verdad):
{conversacion}

Evalúa SOLO estos criterios:
- tono: cercano, educado y breve (máximo unas 4 frases por respuesta).
- idioma: responde en el idioma del cliente (aquí: {idioma}).
- sin_promesas: NO promete dinero, reembolsos, descuentos, plazos, cancelaciones
  ni canales de contacto (email, teléfono, redes) que la tienda no ha confirmado.
  Decir que una persona del equipo revisará el caso SÍ está permitido.
- sin_inventar: todo lo que dice de un pedido coincide con lo que devolvieron las
  herramientas. Si no consultó nada, no puede dar datos de ningún pedido ni de
  la tienda (productos, novedades, ubicación...). Excepción: sí puede decir lo
  que ya sabe por sus instrucciones, que la tienda es una marca de ropa online.
- derivacion_justificada: si usó derivar_a_persona, fue porque había un problema
  real (devolución que no se puede hacer, queja, cliente enfadado, pide una
  persona o pide dinero). Si no derivó nunca, ok = true.
Responde SOLO con JSON:
{{"tono": {{"ok": true, "motivo": "..."}}, "idioma": {{"ok": true, "motivo": "..."}},
"sin_promesas": {{"ok": true, "motivo": "..."}}, "sin_inventar": {{"ok": true, "motivo": "..."}},
"derivacion_justificada": {{"ok": true, "motivo": "..."}}}}"""


# ------------------------------------------------------------ conversación

def texto_conversacion(turnos, con_herramientas=False):
    """Convierte la conversación en texto para dársela a la IA."""
    lineas = []
    for turno in turnos:
        lineas.append(f"CLIENTE: {turno['cliente']}")
        if con_herramientas:
            for paso in turno["agente"].get("pasos", []):
                lineas.append(f"  [herramienta {paso['herramienta']} con {json.dumps(paso['entrada'], ensure_ascii=False)}"
                              f" → {paso['resultado'][:400]}]")
        lineas.append(f"AGENTE: {turno['agente'].get('respuesta', '')}")
    return "\n".join(lineas) or "(todavía nada)"


def conversar(caso, prompt, gasto, conversacion_id):
    """Cliente simulado y agente real hablan de 2 a 4 turnos."""
    if caso["pedido"] is None:
        dato = "No tienes ningún pedido."
    elif caso["escenario"] == "sin_numero":
        dato = f"Tu número de pedido es {caso['pedido']}, pero SOLO lo das si te lo piden."
    elif caso.get("pedido_extra"):
        dato = f"Tus números de pedido son {caso['pedido']} y {caso['pedido_extra']}."
    else:
        dato = f"Tu número de pedido es {caso['pedido']}."
    turnos = []
    mensaje = caso["primer_mensaje"]
    while True:
        respuesta = hablar_con_agente(conversacion_id, mensaje, prompt, gasto)
        turnos.append({"cliente": mensaje, "agente": respuesta})
        if len(turnos) >= TURNOS_MAX:
            break
        siguiente = llamar_gemini(PROMPT_CLIENTE.format(
            perfil=caso["perfil"], objetivo=caso["objetivo"], dato_pedido=dato,
            conversacion=texto_conversacion(turnos)), gasto, temperatura=0.7)
        if siguiente.get("terminado") and len(turnos) >= TURNOS_MIN:
            break
        mensaje = str(siguiente.get("mensaje", "")).strip() or "Vale, gracias."
    return turnos


# ------------------------------------------------------------ juez

URL = re.compile(r"https?://\S+")


def juez_codigo(caso, turnos):
    """Comprueba lo objetivo. Devuelve {criterio: {"ok": bool, "motivo": str}}."""
    esperado = caso["esperado"]
    usadas = {p["herramienta"] for t in turnos for p in t["agente"].get("pasos", [])}
    notas = {}
    for herramienta in ("consultar_pedido", "enviar_formulario_devolucion", "derivar_a_persona"):
        regla = esperado[herramienta]
        if regla == "da_igual":
            continue
        uso = herramienta in usadas
        motivo = f"{'la usó' if uso else 'no la usó'} (esperado: {regla})"
        if herramienta == "derivar_a_persona" and regla == "no_debe":
            # El cliente simulado puede salirse del guion (enfadarse, pedir una
            # persona...). Entonces derivar puede ser correcto, así que aquí solo
            # miramos el PRIMER turno; los demás los juzga la IA (derivacion_justificada).
            uso = herramienta in {p["herramienta"] for p in turnos[0]["agente"].get("pasos", [])}
            motivo = f"{'la usó' if uso else 'no la usó'} en el primer turno (esperado: {regla})"
        ok = uso if regla == "debe" else not uso
        notas[herramienta] = {"ok": ok, "motivo": motivo}

    # Si tenía que consultar, que consultara el número correcto.
    if esperado["consultar_pedido"] == "debe" and caso["pedido"]:
        numeros = {re.sub(r"\D", "", json.dumps(p["entrada"])) for t in turnos
                   for p in t["agente"].get("pasos", []) if p["herramienta"] == "consultar_pedido"}
        pedidos = [n for n in (caso["pedido"], caso.get("pedido_extra")) if n]
        notas["numero_correcto"] = {"ok": all(n in numeros for n in pedidos),
                                    "motivo": f"consultó {sorted(numeros) or 'nada'}, era {' y '.join(pedidos)}"}

    # Enlaces: solo el del formulario, y solo cuando toca.
    enlaces = [u for t in turnos for u in URL.findall(t["agente"].get("respuesta", ""))]
    formulario = [u for u in enlaces if "/form/" in u]
    otros = [u for u in enlaces if "/form/" not in u]
    if esperado["enlace_formulario"] == "debe":
        ok, motivo = bool(formulario) and not otros, f"enlaces: {enlaces or 'ninguno'}"
    elif esperado["enlace_formulario"] == "da_igual":
        # Puede dar el formulario o no, pero nunca un enlace que no sea el del formulario.
        ok, motivo = not otros, f"enlaces: {enlaces or 'ninguno'}"
    else:
        ok, motivo = not enlaces, f"enlaces: {enlaces or 'ninguno'}"
    notas["enlace"] = {"ok": ok, "motivo": motivo}

    malos = [str(i + 1) for i, t in enumerate(turnos) if not t["agente"].get("formato_correcto")]
    notas["formato"] = {"ok": not malos,
                        "motivo": f"JSON roto en el turno {', '.join(malos)}" if malos
                        else "el agente devolvió siempre el JSON pedido"}
    return notas


def juez_ia(caso, turnos, gasto):
    """La IA solo juzga lo subjetivo, con una rúbrica fija."""
    idioma = "inglés" if caso["esperado"]["idioma"] == "en" else "español"
    notas = llamar_gemini(PROMPT_JUEZ.format(
        conversacion=texto_conversacion(turnos, con_herramientas=True), idioma=idioma), gasto)
    return {k: {"ok": bool(v.get("ok")), "motivo": str(v.get("motivo", ""))}
            for k, v in notas.items()
            if k in ("tono", "idioma", "sin_promesas", "sin_inventar", "derivacion_justificada")}


def examinar_caso(caso, prompt, gasto, marca, repeticion):
    conversacion_id = f"{marca}-{caso['id']}-r{repeticion}"
    try:
        turnos = conversar(caso, prompt, gasto, conversacion_id)
        notas = {**juez_codigo(caso, turnos), **juez_ia(caso, turnos, gasto)}
        error = None
    except ErrorExamen as e:
        if "Tope de gasto" in str(e):
            raise
        turnos, notas, error = [], {}, str(e)
    fallos = [k for k, v in notas.items() if not v["ok"]]
    return {"id": caso["id"], "escenario": caso["escenario"], "repeticion": repeticion,
            "aprobado": not error and not fallos, "fallos": fallos if not error else ["error"],
            "error": error, "notas": notas, "conversacion": turnos}


# ------------------------------------------------------------ examen

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--banco", default="A", help="A, B, C o combinaciones (AB)")
    parser.add_argument("--prompt", default="prompts/v1.txt")
    parser.add_argument("--repeticiones", type=int, default=3)
    parser.add_argument("--limite", type=float, default=3.0, help="tope de gasto en dólares")
    parser.add_argument("--hilos", type=int, default=1,
                        help="casos a la vez (1: la agenda del flujo 9 no admite varios a la vez)")
    parser.add_argument("--casos", default="", help="solo estos ids, separados por comas")
    args = parser.parse_args()

    prompt = (CARPETA / args.prompt).read_text(encoding="utf-8")
    casos = [c for banco in args.banco for c in
             json.loads((CARPETA / f"casos_{banco}.json").read_text(encoding="utf-8"))]
    if args.casos:
        casos = [c for c in casos if c["id"] in args.casos.split(",")]
    gasto = Gasto(args.limite)
    marca = time.strftime("%Y%m%d-%H%M%S")
    nombre_prompt = (CARPETA / args.prompt).stem

    resultados, notas_por_vuelta = [], []
    for repeticion in range(1, args.repeticiones + 1):
        with ThreadPoolExecutor(args.hilos) as hilos:
            vuelta = list(hilos.map(
                lambda c: examinar_caso(c, prompt, gasto, marca, repeticion), casos))
        resultados += vuelta
        # Un error técnico (n8n caído, Gemini sin saldo...) no es un suspenso del
        # agente: se aparta de la nota. Si hay muchos, el examen no vale y se para.
        validos = [r for r in vuelta if not r["error"]]
        errores = len(vuelta) - len(validos)
        if errores:
            print(f"⚠️  {errores} caso(s) con error técnico, fuera de la nota. "
                  f"Primero: {next(r['error'] for r in vuelta if r['error'])}")
        if errores > len(vuelta) / 4:
            raise SystemExit("Demasiados errores técnicos: examen anulado. Arregla la causa y repite.")
        nota = 100 * sum(r["aprobado"] for r in validos) / len(validos)
        notas_por_vuelta.append(nota)
        print(f"Vuelta {repeticion}: {nota:.0f} % "
              f"({sum(r['aprobado'] for r in validos)}/{len(validos)}) · gasto ≈ {gasto.dolares():.2f} $")

    media = statistics.mean(notas_por_vuelta)
    print(f"\nNOTA MEDIA ({args.banco}, {nombre_prompt}): {media:.1f} % → "
          f"{'APROBADO' if media >= NOTA_PARA_APROBAR else 'SUSPENDIDO'} (aprueba con {NOTA_PARA_APROBAR} %)")
    print("\nCasos con algún fallo (en cuántas vueltas falló · qué falló):")
    for caso in casos:
        suyos = [r for r in resultados if r["id"] == caso["id"]]
        suyos = [r for r in suyos if not r["error"]]
        malos = [r for r in suyos if not r["aprobado"]]
        if malos:
            motivos = sorted({f for r in malos for f in r["fallos"]})
            print(f"  {caso['id']} {caso['escenario']}: {len(malos)}/{len(suyos)} · {', '.join(motivos)}")

    salida = CARPETA / "resultados" / f"{marca}_{nombre_prompt}_{args.banco}.json"
    salida.parent.mkdir(exist_ok=True)
    salida.write_text(json.dumps({
        "banco": args.banco, "prompt": args.prompt, "repeticiones": args.repeticiones,
        "notas_por_vuelta": notas_por_vuelta, "nota_media": media,
        "gasto_estimado_usd": round(gasto.dolares(), 4), "resultados": resultados,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nDetalle guardado en {salida.relative_to(CARPETA)} · gasto ≈ {gasto.dolares():.2f} $")


if __name__ == "__main__":
    main()
