"""Mide cuánto acierta el buscador con fotos cuya marca ya conocemos.

Es como un examen con las respuestas en un sobre cerrado: el programa
analiza cada foto sin saber la marca y al final abrimos el sobre
(marcas_reales.txt) para corregir.

Uso:
    python3 evaluar.py "/ruta/a/la/carpeta de fotos"

La carpeta debe tener un archivo marcas_reales.txt con líneas así:
    foto.HEIC: sudadera = Zara; vaqueros = Levi's

Si una foto ya se analizó (hay un JSON en resultados/), se reutiliza
para no gastar búsquedas de SerpApi otra vez.

Se miden dos cosas por cada prenda de la lista:
  - IA: ¿Gemini dice esa marca (leída o supuesta) para alguna prenda
    de la foto?
  - Lens: ¿aparece esa marca en el título o la tienda de algún enlace
    que el buscador enseña para esa foto?
Es una medida aproximada: no comprueba que sea la misma prenda exacta.
"""

import json
import sys
import unicodedata
from pathlib import Path

import buscador_prendas as bp


def normalizar(texto):
    """Minúsculas y sin acentos ni espacios: «Massimo Dutti» → «massimodutti»."""
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return "".join(c for c in texto.lower() if c.isalnum())


def leer_marcas(archivo):
    """Lee marcas_reales.txt → {nombre_foto: [(prenda, marca), ...]}."""
    marcas = {}
    for linea in archivo.read_text(encoding="utf-8").splitlines():
        if not linea.strip() or linea.startswith("#") or ":" not in linea:
            continue
        foto, resto = linea.split(":", 1)
        pares = []
        for trozo in resto.split(";"):
            if "=" in trozo:
                prenda, marca = trozo.split("=", 1)
                pares.append((prenda.strip(), marca.strip()))
        marcas[foto.strip()] = pares
    return marcas


def ultimo_resultado(foto):
    anteriores = sorted(bp.CARPETA_RESULTADOS.glob(f"{foto.stem}-*.json"))
    if anteriores:
        prendas = json.loads(
            anteriores[-1].read_text(encoding="utf-8"))["prendas"]
        # Un análisis a medias (sin filtro de la IA o con errores) no vale
        # para medir: inflaría los aciertos. Se repite.
        if not any(p.get("aviso") or p.get("error") for p in prendas):
            return prendas
    return None


def todos_los_enlaces(prenda):
    """Los resultados que ve el usuario: mismo producto + todas las gamas."""
    enlaces = [r for r in prenda.get("mismo", []) if r.get("valido")]
    for lista in prenda.get("alternativas", {}).values():
        enlaces += lista
    return enlaces


def corregir(prendas, marca):
    """Devuelve (acierta_ia, acierta_lens) para una marca real.

    Si la «marca» real es «artesanal», la IA acierta si dice que alguna
    prenda tiene origen artesanal; Lens no se puede corregir (None).
    """
    objetivo = normalizar(marca)
    if not objetivo:
        return False, None  # sin marca real no se puede corregir
    if objetivo == "artesanal":
        return any("artesanal" in (p.get("origen") or "") for p in prendas), None
    acierta_ia = any(
        objetivo in normalizar(p.get("marca_visible"))
        or objetivo in normalizar(p.get("marca_probable"))
        for p in prendas)
    acierta_lens = any(
        objetivo in normalizar(r["titulo"]) or objetivo in normalizar(r["tienda"])
        for p in prendas
        for r in todos_los_enlaces(p))
    return acierta_ia, acierta_lens


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    carpeta = Path(sys.argv[1]).expanduser()
    marcas = leer_marcas(carpeta / "marcas_reales.txt")
    filas, total, aciertos_ia, aciertos_lens, total_lens = [], 0, 0, 0, 0
    for nombre, pares in marcas.items():
        foto = carpeta / nombre
        if not foto.exists():
            print(f"Salto {nombre}: no está en la carpeta")
            continue
        prendas = ultimo_resultado(foto)
        if prendas is None:
            print(f"Analizando {nombre}...")
            try:
                prendas = bp.analizar(foto, "es", "es")
            except bp.ErrorBuscador as error:
                print(f"  Error: {error}")
                continue
            bp.guardar(prendas, foto, "es")
        for prenda, marca in pares:
            ia, lens = corregir(prendas, marca)
            total += 1
            aciertos_ia += ia
            if lens is not None:
                total_lens += 1
                aciertos_lens += lens
            filas.append((nombre[:24], f"{prenda} {marca}", ia, lens))

    simbolo = {True: "✓", False: "·", None: "n/a"}
    print(f"\n{'Foto':<25}{'Prenda real':<32}{'IA':<5}Lens")
    for foto, prenda, ia, lens in filas:
        print(f"{foto:<25}{prenda[:31]:<32}{simbolo[ia]:<5}{simbolo[lens]}")
    if total:
        print(f"\nPrendas evaluadas: {total}")
        print(f"La IA dice la marca (u origen) correcto: {aciertos_ia}/{total} "
              f"({aciertos_ia / total:.0%})")
    if total_lens:
        print(f"La marca aparece en los enlaces: {aciertos_lens}/{total_lens} "
              f"({aciertos_lens / total_lens:.0%})")


if __name__ == "__main__":
    main()
