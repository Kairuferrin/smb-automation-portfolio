"""Piezas compartidas: hablar con Gemini, con el agente del proyecto 9 y con la API.

Es la «caja de herramientas» que usan los demás scripts, para no repetir
el mismo código en cada uno.
"""

import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

CARPETA = Path(__file__).parent
ARCHIVO_ENV = CARPETA / ".env"

MODELO = "gemini-3.5-flash-lite"
URL_GEMINI = ("https://generativelanguage.googleapis.com/v1beta/models/"
              f"{MODELO}:generateContent")
URL_AGENTE = "http://localhost:5678/webhook/pruebas-agente"
URL_API = "http://127.0.0.1:8009/pedido"

# Precios oficiales de Gemini 3.5 Flash-Lite (dólares por millón de tokens).
PRECIO_ENTRADA = 0.30
PRECIO_SALIDA = 2.50
# El agente usa Gemini dentro de n8n y no nos dice cuánto gasta. Lo estimamos
# por turno (2 llamadas: decidir la herramienta y responder).
AGENTE_TOKENS_ENTRADA_POR_TURNO = 6000
AGENTE_TOKENS_SALIDA_POR_TURNO = 800


class Ritmo:
    """Deja pasar como mucho N peticiones por minuto, como un grifo que gotea.

    El plan gratuito de Gemini permite 15 peticiones por minuto por proyecto."""

    def __init__(self, por_minuto):
        self.espacio = 60 / por_minuto
        self.siguiente = 0.0
        self._candado = threading.Lock()

    def esperar_turno(self):
        with self._candado:
            ahora = time.monotonic()
            turno = max(ahora, self.siguiente)
            self.siguiente = turno + self.espacio
        time.sleep(max(0, turno - ahora))


# Agente y examinador comparten ahora el mismo proyecto gratuito (15 por minuto):
# 5 para el examinador + 4 turnos del agente (≈ 2 peticiones cada uno) = 13.
RITMO_GEMINI = Ritmo(por_minuto=5)
RITMO_AGENTE = Ritmo(por_minuto=4)


class ErrorExamen(Exception):
    """Un error que se explica con un mensaje claro."""


def leer_env(nombre):
    """Lee un valor del archivo .env (o de una variable de entorno)."""
    valor = os.environ.get(nombre, "").strip()
    if not valor and ARCHIVO_ENV.exists():
        for linea in ARCHIVO_ENV.read_text(encoding="utf-8").splitlines():
            clave, _, dato = linea.partition("=")
            if clave.strip() == nombre:
                valor = dato.strip().strip('"').strip("'")
    if not valor or valor.startswith("pon_aqui"):
        raise ErrorExamen(f"Falta {nombre} en el archivo .env (mira .env.example).")
    return valor


class Gasto:
    """Cuenta lo que gastamos, como el contador de un taxi.

    Si se pasa del límite, para el examen antes de gastar más."""

    def __init__(self, limite_usd):
        self.limite = limite_usd
        self.entrada = 0
        self.salida = 0
        self._candado = threading.Lock()  # varios hilos suman a la vez

    def sumar(self, entrada, salida):
        with self._candado:
            self.entrada += entrada
            self.salida += salida
            if self.dolares() > self.limite:
                raise ErrorExamen(f"Tope de gasto alcanzado ({self.limite} $). "
                                  "Examen parado.")

    def dolares(self):
        return (self.entrada * PRECIO_ENTRADA + self.salida * PRECIO_SALIDA) / 1e6


def llamar_gemini(prompt, gasto, temperatura=0.0):
    """Envía un texto a Gemini y devuelve su respuesta ya convertida de JSON."""
    cuerpo = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperatura,
                             "responseMimeType": "application/json"},
    }).encode("utf-8")
    peticion = urllib.request.Request(
        URL_GEMINI, data=cuerpo, method="POST",
        headers={"Content-Type": "application/json",
                 "x-goog-api-key": leer_env("GEMINI_API_KEY")})
    for intento in range(3):  # reintenta si Gemini está saturado un momento
        RITMO_GEMINI.esperar_turno()
        try:
            with urllib.request.urlopen(peticion, timeout=120) as respuesta:
                datos = json.loads(respuesta.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as error:
            if error.code in (429, 500, 503) and intento < 2:
                time.sleep(20 * (intento + 1))
                continue
            detalle = error.read().decode("utf-8", "replace")[:300]
            raise ErrorExamen(f"Gemini ha devuelto el error {error.code}: {detalle}") from error
    uso = datos.get("usageMetadata", {})
    gasto.sumar(uso.get("promptTokenCount", 0),
                uso.get("candidatesTokenCount", 0) + uso.get("thoughtsTokenCount", 0))
    try:
        texto = datos["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(texto)
    except (KeyError, IndexError, json.JSONDecodeError) as error:
        raise ErrorExamen("Gemini no ha devuelto un JSON válido.") from error


def hablar_con_agente(conversacion_id, texto, prompt, gasto):
    """Manda un mensaje al agente REAL del proyecto 9 por su entrada de pruebas."""
    cuerpo = json.dumps({"conversacion_id": conversacion_id, "texto": texto,
                         "nombre": "Cliente de prueba", "prompt": prompt}).encode("utf-8")
    peticion = urllib.request.Request(
        URL_AGENTE, data=cuerpo, method="POST",
        headers={"Content-Type": "application/json",
                 "X-Clave-Pruebas": leer_env("CLAVE_PRUEBAS")})
    gasto.sumar(AGENTE_TOKENS_ENTRADA_POR_TURNO, AGENTE_TOKENS_SALIDA_POR_TURNO)
    RITMO_AGENTE.esperar_turno()
    try:
        with urllib.request.urlopen(peticion, timeout=180) as respuesta:
            return json.loads(respuesta.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise ErrorExamen(f"El agente ha devuelto el error {error.code}. "
                          "¿Está n8n en marcha y el flujo publicado?") from error
    except (OSError, json.JSONDecodeError) as error:
        raise ErrorExamen(f"No se ha podido hablar con el agente: {error}") from error


def consultar_api(numero):
    """Pregunta a la API del proyecto 9. Devuelve el pedido o None si no existe."""
    try:
        with urllib.request.urlopen(f"{URL_API}?numero={numero}", timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise
