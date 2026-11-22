"""Aplica al prompt SOLO los cambios que una persona ha aprobado.

Uso:
    python3 aplicar_cambios.py propuestas/v1.json --aceptar 1,3 --salida prompts/v2.txt

El mejorador propone; la persona decide. Como un editor que sugiere cambios
en un texto y el autor acepta o rechaza cada uno.
"""

import argparse
import json

from comun import CARPETA

MARCA_FORMATO = "Formato de salida:"


def aplicar(prompt, cambios):
    for cambio in cambios:
        buscar, nuevo = cambio.get("buscar", ""), cambio["reemplazar_por"]
        if not buscar:
            # «Añadir al final de las reglas»: justo antes del formato de salida.
            antes, marca, despues = prompt.partition(MARCA_FORMATO)
            prompt = f"{antes.rstrip()}\n{nuevo.strip()}\n\n{marca}{despues}" if marca \
                else f"{prompt.rstrip()}\n{nuevo.strip()}\n"
        elif buscar in prompt:
            prompt = prompt.replace(buscar, nuevo, 1)
        else:
            raise SystemExit(f"El cambio {cambio['numero']} no encaja en el prompt.")
    return prompt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("propuestas")
    parser.add_argument("--aceptar", required=True, help="números aprobados, p. ej. 1,3")
    parser.add_argument("--salida", required=True)
    args = parser.parse_args()

    datos = json.loads((CARPETA / args.propuestas).read_text(encoding="utf-8"))
    aceptados = {int(n) for n in args.aceptar.split(",")}
    cambios = [p for p in datos["propuestas"] if p["numero"] in aceptados]
    prompt = (CARPETA / datos["prompt"]).read_text(encoding="utf-8")
    nuevo = aplicar(prompt, cambios)
    if MARCA_FORMATO not in nuevo:
        raise SystemExit("Un cambio ha borrado el formato de salida: no se guarda.")
    (CARPETA / args.salida).write_text(nuevo, encoding="utf-8")
    print(f"Guardado {args.salida} con los cambios {sorted(aceptados)} "
          f"(rechazados: {sorted({p['numero'] for p in datos['propuestas']} - aceptados)})")


if __name__ == "__main__":
    main()
