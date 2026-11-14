"""Buscador de prendas: ¿de dónde es esa ropa?

Le pasas una foto o un vídeo (descargado tú, con el botón de la app) y:
  1. Gemini localiza cada prenda y la describe (tipo, color, logo visible...).
  2. El programa recorta cada prenda de la imagen.
  3. Google Lens (a través de SerpApi) busca cada recorte y devuelve
     productos reales con su enlace.
  4. Se ordena todo en «mismo producto» y «alternativas».

Regla de oro: los enlaces NUNCA los escribe la IA. Solo salen de Google Lens.

No acepta enlaces de TikTok a propósito: descargar vídeos de forma
automática va contra sus condiciones de uso (cláusula 4.5).

Solo biblioteca estándar de Python. Herramientas externas del Mac:
  - sips   (viene con macOS): convertir, recortar y reducir imágenes.
  - ffmpeg (brew install ffmpeg): sacar fotogramas de los vídeos.

Uso:
    python3 buscador_prendas.py foto.jpg
    python3 buscador_prendas.py video.mp4 --pais us --idioma en
"""

import argparse
import base64
import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

CARPETA = Path(__file__).parent
ARCHIVO_CLAVES = CARPETA / ".env"  # aquí guardas tus claves; git no lo sube
CARPETA_RESULTADOS = CARPETA / "resultados"

MODELO = "gemini-3.5-flash"
URL_GEMINI = ("https://generativelanguage.googleapis.com/v1beta/models/"
              f"{MODELO}:generateContent")
URL_SUBIDA_SERPAPI = "https://serpapi.com/image"
URL_BUSQUEDA_SERPAPI = "https://serpapi.com/search.json"

EXTENSIONES_FOTO = {".jpg", ".jpeg", ".png", ".heic", ".webp"}
EXTENSIONES_VIDEO = {".mp4", ".mov", ".m4v", ".webm"}
MAX_FOTOGRAMAS = 6         # de un vídeo cogemos como mucho 6 «capturas»
LADO_MAXIMO = 1024         # px: suficiente para ver detalles sin pesar mucho
MAX_KB_SERPAPI = 500       # SerpApi no acepta imágenes de más de 500 KB
MAX_RESULTADOS = 5         # coincidencias exactas por prenda
MAX_CANDIDATOS = 25        # resultados de Lens que revisa Gemini por prenda
MAX_POR_GAMA = 2           # alternativas que se enseñan en cada gama


class ErrorBuscador(Exception):
    """Un error que se puede enseñar tal cual al usuario."""


# ------------------------------------------------------------------- claves

def leer_claves():
    """Lee GEMINI_API_KEY y SERPAPI_API_KEY del archivo .env.

    El .env es como la caja fuerte de casa: el programa la abre para
    coger las llaves, pero nunca las enseña ni las sube a GitHub.
    """
    claves = {}
    if ARCHIVO_CLAVES.exists():
        for linea in ARCHIVO_CLAVES.read_text(encoding="utf-8").splitlines():
            if "=" in linea and not linea.strip().startswith("#"):
                nombre, valor = linea.split("=", 1)
                claves[nombre.strip()] = valor.strip().strip('"\'')
    faltan = [n for n in ("GEMINI_API_KEY", "SERPAPI_API_KEY")
              if not claves.get(n) or claves[n].startswith("pon_aqui")]
    if faltan:
        raise ErrorBuscador(
            f"Faltan claves en {ARCHIVO_CLAVES.name}: {', '.join(faltan)}. "
            "Copia .env.example como .env y rellénalo.")
    return claves


# --------------------------------------------------------- preparar imágenes

def comprobar_herramienta(nombre, como_instalar):
    if shutil.which(nombre) is None:
        raise ErrorBuscador(f"Falta la herramienta '{nombre}'. {como_instalar}")


def ejecutar(comando):
    """Ejecuta un programa del sistema y avisa si falla."""
    resultado = subprocess.run(comando, capture_output=True, text=True)
    if resultado.returncode != 0:
        raise ErrorBuscador(f"Falló {comando[0]}: {resultado.stderr.strip()}")
    return resultado.stdout


def tamano_imagen(ruta):
    """Devuelve (ancho, alto) en píxeles, preguntándoselo a sips."""
    salida = ejecutar(["sips", "-g", "pixelWidth", "-g", "pixelHeight",
                       str(ruta)])
    ancho = int(re.search(r"pixelWidth: (\d+)", salida).group(1))
    alto = int(re.search(r"pixelHeight: (\d+)", salida).group(1))
    return ancho, alto


def foto_a_jpeg(origen, destino):
    """Convierte cualquier foto (también HEIC del iPhone) a JPEG reducido.

    Las fotos del móvil no se guardan giradas: llevan una nota que dice
    «muéstrame girada 90°». Gemini respeta esa nota, pero el recorte no,
    y cortaría el trozo equivocado. Por eso ffmpeg «aplica» el giro a los
    píxeles, como fotocopiar la foto ya puesta del derecho.
    """
    comprobar_herramienta("ffmpeg", "Instálala con: brew install ffmpeg")
    intermedio = Path(destino).with_name("sin_girar.jpg")
    ejecutar(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "90",
              "-Z", str(LADO_MAXIMO), str(origen), "--out", str(intermedio)])
    ejecutar(["ffmpeg", "-v", "error", "-y", "-i", str(intermedio),
              "-q:v", "3", str(destino)])
    return destino


def sacar_fotogramas(video, carpeta):
    """Saca hasta MAX_FOTOGRAMAS capturas repartidas a lo largo del vídeo.

    Es como pausar el vídeo en 6 momentos distintos y hacer una captura
    en cada uno, para no perderse una prenda que solo sale al final.
    """
    comprobar_herramienta("ffmpeg", "Instálala con: brew install ffmpeg")
    texto = ejecutar([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(video)]).strip()
    try:
        duracion = float(texto)
    except ValueError:
        raise ErrorBuscador("No puedo leer la duración del vídeo "
                            f"(ffprobe dice: {texto or 'nada'}).")
    momentos = momentos_de_captura(duracion, MAX_FOTOGRAMAS)
    fotogramas = []
    for i, segundo in enumerate(momentos):
        destino = Path(carpeta) / f"fotograma_{i}.jpg"
        ejecutar(["ffmpeg", "-v", "error", "-y", "-ss", f"{segundo:.2f}",
                  "-i", str(video), "-frames:v", "1",
                  "-vf", f"scale='min({LADO_MAXIMO},iw)':-2",
                  "-q:v", "3", str(destino)])
        if destino.exists():
            fotogramas.append(destino)
    if not fotogramas:
        raise ErrorBuscador("No he podido sacar ningún fotograma del vídeo.")
    return fotogramas


def momentos_de_captura(duracion, cuantos):
    """Reparte 'cuantos' momentos a lo largo del vídeo, sin tocar los bordes.

    Con un vídeo de 30 s y 6 capturas: 2,5 s, 7,5 s, 12,5 s...
    (el centro de cada sexta parte, que suele estar más estable).
    """
    if duracion <= 0:
        return [0.0]
    cuantos = max(1, min(cuantos, int(duracion) or 1))
    tramo = duracion / cuantos
    return [round(tramo * i + tramo / 2, 2) for i in range(cuantos)]


def caja_a_pixeles(caja, ancho, alto, margen=0.05):
    """Convierte la caja de Gemini a píxeles para recortar.

    Gemini da la caja como [y_min, x_min, y_max, x_max] en una escala
    de 0 a 1000 (como un mapa con coordenadas en tanto por mil).
    Añadimos un 5 % de margen para no cortar mangas o bajos.
    Devuelve (x, y, ancho_recorte, alto_recorte).
    """
    y0, x0, y1, x1 = [max(0, min(1000, float(v))) for v in caja]
    if y1 <= y0 or x1 <= x0:
        raise ValueError(f"Caja no válida: {caja}")
    margen_y = (y1 - y0) * margen
    margen_x = (x1 - x0) * margen
    y0, y1 = max(0, y0 - margen_y), min(1000, y1 + margen_y)
    x0, x1 = max(0, x0 - margen_x), min(1000, x1 + margen_x)
    x = int(x0 / 1000 * ancho)
    y = int(y0 / 1000 * alto)
    ancho_r = max(1, int(x1 / 1000 * ancho) - x)
    alto_r = max(1, int(y1 / 1000 * alto) - y)
    return x, y, ancho_r, alto_r


def recortar(imagen, caja, destino):
    """Recorta una prenda y la deja por debajo de 500 KB para SerpApi."""
    ancho, alto = tamano_imagen(imagen)
    x, y, ancho_r, alto_r = caja_a_pixeles(caja, ancho, alto)
    ejecutar(["sips", "-c", str(alto_r), str(ancho_r),
              "--cropOffset", str(y), str(x),
              str(imagen), "--out", str(destino)])
    # Si aún pesa mucho, bajamos la calidad poco a poco.
    for calidad in (80, 65, 50, 35):
        if destino.stat().st_size <= MAX_KB_SERPAPI * 1024:
            break
        ejecutar(["sips", "-s", "formatOptions", str(calidad),
                  str(destino), "--out", str(destino)])
    if destino.stat().st_size > MAX_KB_SERPAPI * 1024:
        raise ErrorBuscador("El recorte pesa más de 500 KB incluso "
                            "comprimido; SerpApi no lo aceptaría.")
    return destino


# ------------------------------------------------------------------ Gemini

INSTRUCCIONES_GEMINI = """
Eres un experto en moda. Te paso {n} imagen(es) numeradas desde 0
(si son varias, son fotogramas del mismo vídeo).

Localiza cada PRENDA o ACCESORIO de moda distinto que se vea bien
(no repitas la misma prenda aunque salga en varios fotogramas: elige el
fotograma donde se vea mejor). Máximo 6 prendas.

Responde SOLO con JSON, una lista de objetos con estas claves:
- "imagen": número de la imagen donde se ve mejor (entero)
- "caja": [y_min, x_min, y_max, x_max] de la prenda, escala 0-1000
- "tipo": tipo de prenda en español (p. ej. "chaqueta bomber")
- "color": color principal
- "descripcion": 1 frase con tejido, corte y detalles
- "marca_visible": marca SOLO si se lee un logo o etiqueta; si no, null
- "marca_probable": tu suposición de marca o null si no tienes ni idea
- "confianza_marca": "alta", "media" o "baja"
- "origen": uno de "marca conocida", "artesanal o tienda local",
  "básico sin marca" o "no se sabe". Fíjate en pistas como costuras
  hechas a mano, materiales tradicionales (esparto, yute, lana cruda,
  cuero sin tratar) o acabados irregulares. Si parece artesanal, NO
  pongas una marca grande en "marca_probable": déjala en null.
- "pista_origen": 1 frase corta con la pista que te ha hecho decidir
- "busqueda": 3-6 palabras para buscarla en una tienda online

NO escribas enlaces ni URLs. NO inventes una marca visible si no la lees.
"""


def pedir_a_gemini(clave, partes):
    """Envía a Gemini texto (y fotos, si las hay) y devuelve su respuesta."""
    cuerpo = {"contents": [{"parts": partes}],
              "generationConfig": {"response_mime_type": "application/json",
                                   "temperature": 0.2}}
    peticion = urllib.request.Request(
        URL_GEMINI, data=json.dumps(cuerpo).encode(), method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": clave})
    respuesta = pedir_json(peticion, "Gemini")
    try:
        return respuesta["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise ErrorBuscador("Gemini no ha devuelto respuesta (¿imagen "
                            "bloqueada por sus filtros?).")


def limpiar_json(texto):
    """Quita el ```json ... ``` que a veces pone la IA alrededor."""
    return re.sub(r"^```(?:json)?|```$", "", texto.strip()).strip()


def llamar_gemini(clave, imagenes):
    """Pide a Gemini que localice y describa las prendas."""
    partes = [{"text": INSTRUCCIONES_GEMINI.format(n=len(imagenes))}]
    for ruta in imagenes:
        partes.append({"inline_data": {
            "mime_type": "image/jpeg",
            "data": base64.b64encode(Path(ruta).read_bytes()).decode()}})
    return validar_prendas(pedir_a_gemini(clave, partes), len(imagenes))


def validar_prendas(texto, num_imagenes):
    """Comprueba que el JSON de Gemini tiene lo que necesitamos.

    Es como el control de calidad de una fábrica: lo que llega torcido
    se aparta en lugar de estropear el resto de la cadena.
    """
    try:
        datos = json.loads(limpiar_json(texto))
    except json.JSONDecodeError:
        raise ErrorBuscador("Gemini ha respondido algo que no es JSON.")
    if isinstance(datos, dict):
        datos = datos.get("prendas", [datos])
    prendas = []
    for p in datos if isinstance(datos, list) else []:
        if not isinstance(p, dict):
            continue  # un texto suelto en la lista: no nos sirve
        caja = p.get("caja")
        if (not isinstance(caja, list) or len(caja) != 4
                or not all(isinstance(v, (int, float)) for v in caja)):
            continue
        indice = p.get("imagen", 0)
        if not isinstance(indice, int) or not 0 <= indice < num_imagenes:
            continue  # la caja sería de otro fotograma: mejor descartarla
        for clave in ("tipo", "color", "descripcion", "marca_visible",
                      "marca_probable", "origen", "pista_origen", "busqueda"):
            if p.get(clave) is not None and not isinstance(p[clave], str):
                p[clave] = str(p[clave])
        if not p.get("tipo"):
            p["tipo"] = "prenda"
        prendas.append(p)
    return prendas


# ----------------------------------------------------------------- SerpApi

def formulario_multipart(campos, nombre_archivo, contenido):
    """Prepara un envío de archivo por HTTP (multipart/form-data).

    Es como un sobre con varios compartimentos separados por una línea
    única (el 'boundary'): en uno va la clave y en otro la foto.
    """
    limite = uuid.uuid4().hex
    trozos = []
    for nombre, valor in campos.items():
        trozos.append(f'--{limite}\r\nContent-Disposition: form-data; '
                      f'name="{nombre}"\r\n\r\n{valor}\r\n'.encode())
    trozos.append(f'--{limite}\r\nContent-Disposition: form-data; '
                  f'name="image"; filename="{nombre_archivo}"\r\n'
                  'Content-Type: image/jpeg\r\n\r\n'.encode())
    trozos.append(contenido)
    trozos.append(f'\r\n--{limite}--\r\n'.encode())
    return b"".join(trozos), f"multipart/form-data; boundary={limite}"


def buscar_en_lens(clave, recorte, pais, idioma, texto=None):
    """Sube el recorte a SerpApi y lo busca en Google Lens.

    'texto' son las palabras que propone Gemini (p. ej. «camiseta rayas
    marinera»). Ayudan cuando la prenda sale pequeña o tapada: es como
    enseñar la foto al dependiente y además decirle qué buscas.
    """
    cuerpo, tipo = formulario_multipart(
        {"api_key": clave}, recorte.name, recorte.read_bytes())
    subida = pedir_json(urllib.request.Request(
        URL_SUBIDA_SERPAPI, data=cuerpo, method="POST",
        headers={"Content-Type": tipo}), "SerpApi (subida)")
    id_imagen = subida.get("image_id")
    if not id_imagen:
        raise ErrorBuscador(f"SerpApi no ha aceptado la imagen: "
                            f"{subida.get('error') or subida}")
    parametros = {
        "engine": "google_lens", "image_id": id_imagen, "type": "all",
        "country": pais, "hl": idioma, "api_key": clave}
    if texto:
        parametros["q"] = texto
    parametros = urllib.parse.urlencode(parametros)
    return pedir_json(urllib.request.Request(
        f"{URL_BUSQUEDA_SERPAPI}?{parametros}"), "SerpApi (Lens)")


def pedir_json(peticion, servicio, intentos=4):
    """Hace la petición y reintenta si el servicio está saturado (429/503)."""
    for intento in range(intentos):
        try:
            with urllib.request.urlopen(peticion, timeout=90) as r:
                return json.load(r)
        except urllib.error.HTTPError as error:
            detalle = error.read().decode(errors="replace")
            if error.code == 429 and "PerDay" in detalle:
                # Límite DIARIO: reintentar no sirve, como volver a la
                # panadería cuando ya ha cerrado hasta mañana.
                raise ErrorBuscador(
                    f"{servicio}: se ha acabado la cuota de HOY (error 429). "
                    "En el plan gratuito vuelve mañana; con facturación "
                    "activada no hay este límite.")
            detalle = detalle[:300]
            if error.code in (429, 503) and intento < intentos - 1:
                # Esperar y volver a llamar: 15 s, 30 s, 45 s. El plan
                # gratuito de Gemini limita las peticiones por minuto.
                time.sleep(15 * (intento + 1))
                continue
            if error.code == 429:
                raise ErrorBuscador(f"{servicio}: has llegado al límite de "
                                    "uso (error 429). Espera o revisa tu plan.")
            raise ErrorBuscador(f"{servicio} respondió {error.code}: {detalle}")
        except urllib.error.URLError as error:
            raise ErrorBuscador(f"No hay conexión con {servicio}: "
                                f"{error.reason}")
        except (socket.timeout, ConnectionError) as error:
            raise ErrorBuscador(f"{servicio} ha tardado demasiado o ha "
                                f"cortado la conexión ({error}).")
        except json.JSONDecodeError:
            raise ErrorBuscador(f"{servicio} ha respondido algo que no es JSON.")
    raise ErrorBuscador(f"{servicio} no responde.")


# -------------------------------------------------------- ordenar resultados

def leer_precio(resultado):
    """Saca (texto, número) del precio si Google Lens lo da. Si no, (None, None).

    No todos los resultados traen precio: nunca lo inventamos.
    """
    precio = resultado.get("price")
    if isinstance(precio, dict) and not isinstance(precio.get("value"), str):
        precio = dict(precio, value=None)
    if isinstance(precio, dict):
        numero = precio.get("extracted_value")
        return precio.get("value"), numero if isinstance(
            numero, (int, float)) else None
    if isinstance(precio, str):
        return precio, None
    return None, None


def contiene_palabra(texto, palabra):
    """¿Sale 'palabra' como palabra completa? («gap» no vale en «singapore»)."""
    if not palabra or not palabra.strip():
        return False
    patron = r"(?<!\w)" + re.escape(palabra.strip().lower()) + r"(?!\w)"
    return re.search(patron, (texto or "").lower()) is not None


def resumir_resultado(r, marca):
    texto_precio, numero = leer_precio(r)
    contenido = f"{r.get('title', '')} {r.get('source', '')}"
    return {
        "titulo": r.get("title", "(sin título)"),
        "tienda": r.get("source", "(desconocida)"),
        "enlace": r.get("link"),
        "precio": texto_precio,
        "precio_numero": numero,
        "en_stock": r.get("in_stock"),
        "coincide_marca": contiene_palabra(contenido, marca),
    }


def ordenar_resultados(respuesta_lens, prenda):
    """Separa «mismo producto» de los «candidatos a alternativa».

    - Mismo producto: lo que Lens marca como coincidencia exacta, más las
      coincidencias visuales que llevan la marca que se lee en la prenda.
    - Candidatos: el resto de coincidencias visuales, sin repetidos.
      Luego Gemini los filtra y se reparten por gamas de precio.
    Solo se quedan resultados con enlace: si no hay enlace, no sirve.
    """
    marca = prenda.get("marca_visible")
    exactos = [resumir_resultado(r, marca)
               for r in respuesta_lens.get("exact_matches", [])]
    visuales = [resumir_resultado(r, marca)
                for r in respuesta_lens.get("visual_matches", [])]
    exactos = [r for r in exactos if r["enlace"]]
    visuales = [r for r in visuales if r["enlace"]]

    mismo = exactos + [r for r in visuales if r["coincide_marca"]]
    enlaces_mismo = {r["enlace"] for r in mismo}
    candidatos = []
    vistos = {(r["titulo"], r["tienda"]) for r in mismo}
    for r in visuales:  # quitamos repetidos (mismo título en la misma tienda)
        if r["enlace"] in enlaces_mismo or (r["titulo"], r["tienda"]) in vistos:
            continue
        vistos.add((r["titulo"], r["tienda"]))
        candidatos.append(r)
    return mismo[:MAX_RESULTADOS], candidatos[:MAX_CANDIDATOS]


INSTRUCCIONES_FILTRO = """
Eres un experto en moda. Para cada prenda te paso una lista de resultados
de Google Lens (título y tienda). Muchos no tienen nada que ver (fotos de
ascensores, noticias, otra prenda que salía en el recorte...).

Para cada resultado que SÍ sea un producto en venta del mismo tipo de
prenda y de estilo parecido, devuelve un objeto con:
- "id": el id del resultado, tal cual (p. ej. "2-5")
- "descripcion": 1 frase basada SOLO en el título y la tienda.
  No añadas colores, tejidos ni datos que no estén en el título.

Responde SOLO con JSON: una lista de esos objetos. Los resultados que no
valgan, no los incluyas. NO escribas enlaces.

{lista}
"""


def filtrar_y_describir(clave, prendas):
    """Gemini descarta los resultados que no pintan nada y describe el resto.

    Es como un dependiente que revisa lo que ha traído el almacén y aparta
    lo que no es lo que pediste. Solo devuelve ids: los enlaces siguen
    saliendo de Google Lens, nunca de la IA.
    """
    lineas, por_id = [], {}
    for i, p in enumerate(prendas):
        if p.get("error"):
            continue
        lineas.append(f"\nPrenda {i}: {p['tipo']} {p.get('color', '')}")
        for j, r in enumerate(p.get("mismo", []) + p.get("candidatos", [])):
            ident = f"{i}-{j}"
            por_id[ident] = r
            lineas.append(f"  {ident}: {r['titulo']} | {r['tienda']}")
    if not por_id:
        return
    texto = INSTRUCCIONES_FILTRO.format(lista="\n".join(lineas))
    try:
        elegidos = json.loads(limpiar_json(
            pedir_a_gemini(clave, [{"text": texto}])))
    except (ErrorBuscador, json.JSONDecodeError) as error:
        for p in prendas:  # sin filtro: mejor algo sin revisar que nada
            p["aviso"] = f"Resultados sin revisar por la IA ({error})."
        for r in por_id.values():
            r["valido"] = True
        return
    for e in elegidos if isinstance(elegidos, list) else []:
        if not isinstance(e, dict):
            continue
        r = por_id.get(str(e.get("id")))
        if r is not None:
            r["valido"] = True
            if isinstance(e.get("descripcion"), str):
                r["descripcion"] = e["descripcion"]


def moneda(texto_precio):
    """Saca el símbolo o código de moneda del texto del precio («29 €*» → «€»)."""
    texto = re.sub(r"[\d\s.,*]", "", texto_precio or "")
    return texto.upper() or "?"


def repartir_por_gamas(candidatos):
    """Reparte las alternativas válidas en gama económica, media y alta.

    Las gamas son relativas a lo que ha encontrado Lens para ESA prenda:
    ordenamos por precio y partimos la lista en tres trozos iguales,
    como dividir una clase por estaturas en bajos, medianos y altos.
    Las que no traen precio van aparte: no lo inventamos.
    """
    validos = [r for r in candidatos if r.get("valido")]
    con_numero = [r for r in validos if r["precio_numero"] is not None]
    # Solo comparamos precios de la misma moneda: 25 € y 25 £ no valen igual.
    monedas = [moneda(r["precio"]) for r in con_numero]
    principal = max(set(monedas), key=monedas.count) if monedas else None
    con_precio = sorted((r for r in con_numero
                         if moneda(r["precio"]) == principal),
                        key=lambda r: r["precio_numero"])
    gamas = {"económica": [], "media": [], "alta": [],
             "sin precio": [r for r in validos if r["precio_numero"] is None],
             "otra moneda": [r for r in con_numero
                             if moneda(r["precio"]) != principal]}
    if len(con_precio) < 3:
        gamas["media"] = con_precio  # pocos datos: no tiene sentido partir
    else:
        tercio = len(con_precio) / 3
        for posicion, r in enumerate(con_precio):
            gama = ("económica", "media", "alta")[min(2, int(posicion / tercio))]
            gamas[gama].append(r)
    for gama, lista in gamas.items():
        if gama == "alta":  # en la gama alta, las más caras primero
            lista.reverse()
        gamas[gama] = lista[:MAX_POR_GAMA]
    return {g: l for g, l in gamas.items() if l}


# ------------------------------------------------------------------ informe

def texto_marca(prenda):
    if prenda.get("marca_visible"):
        return f"{prenda['marca_visible']} (la IA dice que lee un logo o etiqueta)"
    if prenda.get("marca_probable"):
        return (f"{prenda['marca_probable']}? (suposición de la IA, confianza "
                f"{prenda.get('confianza_marca', 'baja')})")
    return "desconocida"


def linea_resultado(r):
    precio = r["precio"] or "precio no indicado"
    # El nombre es SIEMPRE el título real de la tienda, nunca uno de la IA.
    lineas = [f"      - {r['titulo']} · {precio}"]
    if r.get("descripcion"):
        lineas.append(f"        {r['descripcion']} (resumen de la IA)")
    lineas.append(f"        Dónde: {r['tienda']} → {r['enlace']}")
    return "\n".join(lineas)


TITULOS_GAMA = {"económica": "Gama económica", "media": "Gama media",
                "alta": "Gama alta", "sin precio": "Sin precio indicado",
                "otra moneda": "En otra moneda (no comparada)"}


def escribir_informe(prendas):
    lineas = []
    for i, p in enumerate(prendas, 1):
        lineas.append(f"\n{i}. {p['tipo'].upper()} {p.get('color', '')}".rstrip())
        if p.get("descripcion"):
            lineas.append(f"   {p['descripcion']}")
        lineas.append(f"   Marca: {texto_marca(p)}")
        if p.get("origen") and p["origen"] != "no se sabe":
            pista = f" — {p['pista_origen']}" if p.get("pista_origen") else ""
            lineas.append(f"   Origen probable: {p['origen']}{pista}")
        if p.get("error"):
            lineas.append(f"   ⚠ No se pudo buscar: {p['error']}")
            continue
        if p.get("aviso"):
            lineas.append(f"   ⚠ {p['aviso']}")
        mismo = [r for r in p.get("mismo", []) if r.get("valido")]
        if mismo:
            lineas.append("   Mismo producto o misma marca:")
            lineas += [linea_resultado(r) for r in mismo]
        if not p.get("alternativas"):
            lineas.append("   Alternativas: no he encontrado ninguna fiable.")
        for gama, lista in p.get("alternativas", {}).items():
            lineas.append(f"   {TITULOS_GAMA[gama]}:")
            lineas += [linea_resultado(r) for r in lista]
    return "\n".join(lineas)


# -------------------------------------------------------------- programa

def preparar_imagenes(archivo, carpeta_temporal):
    extension = archivo.suffix.lower()
    if extension in EXTENSIONES_VIDEO:
        return sacar_fotogramas(archivo, carpeta_temporal)
    if extension in EXTENSIONES_FOTO:
        return [foto_a_jpeg(archivo, Path(carpeta_temporal) / "foto.jpg")]
    raise ErrorBuscador(f"Formato no admitido: {extension}. Usa una foto "
                        f"({', '.join(sorted(EXTENSIONES_FOTO))}) o un vídeo "
                        f"({', '.join(sorted(EXTENSIONES_VIDEO))}).")


def analizar(archivo, pais, idioma):
    if re.match(r"https?://", str(archivo)):
        raise ErrorBuscador(
            "No acepto enlaces, solo archivos. Descarga el vídeo con el botón "
            "de la app (si el creador lo permite) o haz una captura.")
    archivo = Path(archivo).expanduser()
    if not archivo.exists():
        raise ErrorBuscador(f"No encuentro el archivo: {archivo}")
    comprobar_herramienta("sips", "Este programa necesita macOS.")
    claves = leer_claves()

    with tempfile.TemporaryDirectory() as temporal:
        imagenes = preparar_imagenes(archivo, temporal)
        print(f"Analizando {len(imagenes)} imagen(es) con Gemini...")
        prendas = llamar_gemini(claves["GEMINI_API_KEY"], imagenes)
        if not prendas:
            raise ErrorBuscador("Gemini no ha encontrado prendas claras.")
        for i, prenda in enumerate(prendas, 1):
            print(f"Buscando en Google Lens: {prenda['tipo']} ({i}/{len(prendas)})")
            try:
                recorte = recortar(imagenes[prenda["imagen"]], prenda["caja"],
                                   Path(temporal) / f"prenda_{i}.jpg")
                respuesta = buscar_en_lens(claves["SERPAPI_API_KEY"], recorte,
                                           pais, idioma, prenda.get("busqueda"))
                prenda["mismo"], prenda["candidatos"] = ordenar_resultados(
                    respuesta, prenda)
            except (ErrorBuscador, ValueError) as error:
                prenda["error"] = str(error)  # seguimos con las demás
    print("Revisando y describiendo los resultados con Gemini...")
    filtrar_y_describir(claves["GEMINI_API_KEY"], prendas)
    for prenda in prendas:
        if not prenda.get("error"):
            prenda["alternativas"] = repartir_por_gamas(prenda["candidatos"])
    return prendas


def guardar(prendas, archivo, pais):
    CARPETA_RESULTADOS.mkdir(exist_ok=True)
    marca_tiempo = datetime.now().strftime("%Y%m%d-%H%M%S")
    destino = CARPETA_RESULTADOS / f"{Path(archivo).stem}-{marca_tiempo}.json"
    destino.write_text(json.dumps(
        {"archivo": Path(archivo).name, "pais": pais, "modelo": MODELO,
         "prendas": prendas}, ensure_ascii=False, indent=2), encoding="utf-8")
    return destino


def main():
    parser = argparse.ArgumentParser(
        description="Dime de dónde es la ropa de una foto o un vídeo.")
    parser.add_argument("archivo", help="foto o vídeo guardado en tu ordenador")
    parser.add_argument("--pais", default="es",
                        help="país de búsqueda en Google Lens (por defecto: es)")
    parser.add_argument("--idioma", default="es",
                        help="idioma de los resultados (por defecto: es)")
    args = parser.parse_args()
    try:
        prendas = analizar(args.archivo, args.pais, args.idioma)
    except ErrorBuscador as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
    destino = guardar(prendas, args.archivo, args.pais)  # primero, a salvo
    print(escribir_informe(prendas))
    print(f"\nResultado guardado en {destino}")


if __name__ == "__main__":
    main()
