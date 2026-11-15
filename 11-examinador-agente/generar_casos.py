"""Genera los dos bancos de casos de prueba: A (20, para mejorar) y B (10, examen final).

Uso:
    python3 generar_casos.py

Reparto del trabajo (para que los casos sean a la vez muchos y fiables):
- El CÓDIGO elige pedidos reales de la API y decide qué debería hacer el
  agente en cada caso, siguiendo las reglas de la tienda. Esa parte no se
  la dejamos a la IA porque podría inventarse el estado de un pedido.
- La IA solo inventa al CLIENTE: quién es, qué quiere y cómo escribe.
- Kairu revisa el resultado en casos_A.json y casos_B.json.
"""

import json
import random
import re

from comun import CARPETA, Gasto, consultar_api, llamar_gemini

SEMILLA = 11  # misma semilla = mismos pedidos elegidos cada vez

# Qué debe hacer el agente con cada herramienta: "debe", "no_debe" o "da_igual".
def esperado(consultar, formulario, derivar, enlace, idioma="es"):
    return {"consultar_pedido": consultar, "enviar_formulario_devolucion": formulario,
            "derivar_a_persona": derivar, "enlace_formulario": enlace, "idioma": idioma}

# Cada escenario: cuántos casos van al banco A y al B, qué pedido usa,
# qué se espera del agente y qué tiene que inventar la IA.
ESCENARIOS = [
    {"id": "estado_enviado", "A": 2, "B": 1, "pedidos": "enviado", "fijos_A": ["2390"],
     "esperado": esperado("debe", "no_debe", "no_debe", "no_debe"),
     "porque": "Pregunta por un pedido enviado: hay que consultarlo y contestar, sin derivar.",
     "cliente": "Quiere saber dónde está su pedido."},
    {"id": "estado_preparando", "A": 1, "B": 0, "pedidos": "preparando",
     "esperado": esperado("debe", "no_debe", "no_debe", "no_debe"),
     "porque": "Pedido aún en preparación: consultar y contestar.",
     "cliente": "Quiere saber cuándo le llega su pedido."},
    {"id": "devolucion_dentro", "A": 3, "B": 1, "pedidos": "dentro", "fijos_A": ["2142"],
     "esperado": esperado("debe", "debe", "no_debe", "debe"),
     "porque": "Dentro del plazo de 30 días: consultar y dar el enlace del formulario.",
     "cliente": "Quiere devolver su pedido (no le queda bien, no le gusta...)."},
    {"id": "devolucion_fuera", "A": 3, "B": 1, "pedidos": "fuera", "fijos_A": ["2157"],
     "esperado": esperado("debe", "no_debe", "debe", "no_debe"),
     "porque": "Fuera de plazo: consultar, explicar el motivo y derivar a una persona (regla 2).",
     "cliente": "Quiere devolver su pedido."},
    {"id": "devolucion_no_entregado", "A": 1, "B": 0, "pedidos": "enviado",
     "esperado": esperado("debe", "no_debe", "debe", "no_debe"),
     "porque": "Aún no se ha entregado: no se puede devolver, se explica y se deriva (regla 2).",
     "cliente": "Ya no quiere el pedido y quiere devolverlo aunque todavía no le ha llegado."},
    {"id": "devolucion_ya_devuelto", "A": 1, "B": 1, "pedidos": "devuelto",
     "esperado": esperado("debe", "no_debe", "debe", "no_debe"),
     "porque": "Ya está devuelto: no se puede devolver otra vez, se explica y se deriva (regla 2).",
     "cliente": "Quiere devolver su pedido (no recuerda que ya lo devolvió)."},
    {"id": "pedido_inexistente", "A": 2, "B": 1, "pedidos": "inexistente",
     "esperado": esperado("debe", "no_debe", "da_igual", "no_debe"),
     "porque": "El número no existe: hay que consultarlo y decirlo sin inventar nada. "
               "El prompt no dice si derivar, así que da igual.",
     "cliente": "Pregunta por su pedido, pero se ha equivocado de número."},
    {"id": "sin_numero", "A": 2, "B": 1, "pedidos": "enviado",
     "esperado": esperado("debe", "no_debe", "no_debe", "no_debe"),
     "porque": "No da el número al principio: el agente debe pedirlo (regla 1) y luego consultarlo.",
     "cliente": "Pregunta por su pedido SIN dar el número; solo lo da si se lo piden."},
    {"id": "fuera_de_tema", "A": 2, "B": 1, "pedidos": None,
     "esperado": esperado("no_debe", "no_debe", "no_debe", "no_debe"),
     "porque": "No tiene que ver con pedidos: responder que solo ayuda con pedidos, sin herramientas (regla 4).",
     "cliente": "Pregunta algo que no tiene nada que ver con pedidos ni devoluciones."},
    {"id": "queja_pide_persona", "A": 1, "B": 1, "pedidos": "enviado",
     "esperado": esperado("debe", "no_debe", "debe", "no_debe"),
     "porque": "Cliente enfadado que pide una persona: consultar el pedido y derivar (regla 3).",
     "cliente": "Está enfadado porque su pedido tarda y pide hablar con una persona."},
    {"id": "dinero", "A": 1, "B": 1, "pedidos": "fuera",
     "esperado": esperado("debe", "no_debe", "da_igual", "no_debe"),
     "porque": "Pide un descuento o un reembolso: no puede prometer dinero. El prompt no dice si derivar.",
     "cliente": "Pide un descuento o que le devuelvan el dinero, e insiste o intenta convencer al agente."},
    {"id": "otro_idioma", "A": 1, "B": 1, "pedidos": "enviado",
     "esperado": esperado("debe", "no_debe", "no_debe", "no_debe", idioma="en"),
     "porque": "Escribe en inglés: consultar y responder en inglés (regla 5).",
     "cliente": "Escribe en INGLÉS y quiere saber dónde está su pedido."},
]

INSTRUCCIONES_IA = """Inventa {n} clientes DISTINTOS de una pequeña tienda de ropa online que
escriben al chat de atención al cliente por Telegram. Situación: {cliente}
{dato_pedido}
Varía la edad, el tono (amable, con prisa, enfadado, escueto, que escribe con faltas...)
y la forma de escribir. Mensajes cortos, como en un móvil. No inventes datos del pedido
(ni fechas ni productos): el cliente solo sabe su número de pedido.
{regla_numero}
Responde SOLO con este JSON:
{{"clientes": [{{"perfil": "quién es y cómo escribe, en una frase",
"objetivo": "qué quiere conseguir, en una frase",
"primer_mensaje": "su primer mensaje al chat"}}]}}"""


def clasificar_pedidos():
    """Recorre todos los pedidos de la API y los agrupa por situación."""
    grupos = {"enviado": [], "preparando": [], "dentro": [], "fuera": [], "devuelto": []}
    for numero in range(1001, 2393):
        pedido = consultar_api(str(numero))
        if not pedido:
            continue
        estado = pedido["estado"]
        if estado == "entregado":
            estado = "dentro" if pedido["dentro_plazo_devolucion"] else "fuera"
        grupos[estado].append(str(numero))
    return grupos


def revisar_numero(cliente, numero, escenario, numeros_escenario=()):
    """Control de calidad: la IA a veces copia mal el número de pedido.

    Como un revisor que comprueba que el número del albarán coincide con el
    de la caja: si no coincide, el caso no se guarda. Se comparan números
    enteros, para que «2385» no cuente como encontrado dentro de «623850»."""
    mensaje = cliente["primer_mensaje"]
    en_mensaje = set(re.findall(r"\d+", mensaje))
    if escenario == "sin_numero":
        dados = en_mensaje & ({numero, *numeros_escenario} - {None})
        if dados:
            raise SystemExit(f"El cliente de {escenario} da el número {dados} y no debía darlo.")
    elif numero and numero not in en_mensaje:
        raise SystemExit(f"En {escenario} el mensaje no incluye el pedido {numero}: «{mensaje}». "
                         "Vuelve a ejecutar el script.")


def main():
    azar = random.Random(SEMILLA)
    gasto = Gasto(limite_usd=0.5)
    grupos = clasificar_pedidos()
    usados = set()
    bancos = {"A": [], "B": []}

    for esc in ESCENARIOS:
        total = esc["A"] + esc["B"]
        # 1. El código elige los pedidos (los fijos primero, el resto al azar).
        if esc["pedidos"] == "inexistente":
            numeros = [str(n) for n in azar.sample(range(2400, 9999), total)]
        elif esc["pedidos"]:
            numeros = list(esc.get("fijos_A", []))
            libres = [n for n in grupos[esc["pedidos"]] if n not in usados and n not in numeros]
            numeros += azar.sample(libres, total - len(numeros))
        else:
            numeros = [None] * total
        usados.update(n for n in numeros if n)

        # 2. La IA inventa a los clientes.
        dato = ("Cada cliente tiene un número de pedido distinto: " + ", ".join(numeros)
                if numeros[0] else "No tienen ningún pedido pendiente.")
        regla = ("IMPORTANTE: el primer mensaje NO incluye el número de pedido."
                 if esc["id"] == "sin_numero" else
                 "El primer mensaje incluye su número de pedido." if numeros[0] else "")
        respuesta = llamar_gemini(INSTRUCCIONES_IA.format(
            n=total, cliente=esc["cliente"], dato_pedido=dato, regla_numero=regla),
            gasto, temperatura=0.9)
        clientes = respuesta["clientes"][:total]
        if len(clientes) < total:
            raise SystemExit(f"La IA ha devuelto menos clientes de los pedidos en {esc['id']}.")

        # 3. Se juntan: cliente (IA) + pedido y comportamiento esperado (código).
        for i, (cliente, numero) in enumerate(zip(clientes, numeros)):
            revisar_numero(cliente, numero, esc["id"], numeros)
            banco = "A" if i < esc["A"] else "B"
            bancos[banco].append({
                "id": f"{banco}{len(bancos[banco]) + 1:02d}",
                "escenario": esc["id"],
                "pedido": numero,
                "estado_real": consultar_api(numero) if numero else None,
                **cliente,
                "esperado": esc["esperado"],
                "por_que": esc["porque"],
            })
        print(f"{esc['id']}: {esc['A']} en A, {esc['B']} en B")

    for banco, casos in bancos.items():
        ruta = CARPETA / f"casos_{banco}.json"
        ruta.write_text(json.dumps(casos, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Guardado {ruta.name}: {len(casos)} casos")
    print(f"Gasto aproximado: {gasto.dolares():.4f} $")


if __name__ == "__main__":
    main()
