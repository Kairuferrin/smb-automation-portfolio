"""Mini API de pedidos: la herramienta «consultar_pedido» del agente.

Uso:
    python3 api_pedidos.py
y prueba en el navegador: http://127.0.0.1:8009/pedido?numero=1002

Es como el mostrador de un almacén: el agente pregunta por un número de
pedido y el mostrador contesta qué contiene, en qué estado está y si todavía
se puede devolver. Las reglas del negocio (el plazo de 30 días) se calculan
aquí, en código, y no las decide la IA: así siempre se aplican igual.
"""

import json
import sqlite3
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PUERTO = 8009
CARPETA = Path(__file__).parent
ARCHIVO_VENTAS = CARPETA.parent / "06-sql-ventas" / "ventas.db"
ARCHIVO_ESTADOS = CARPETA / "estados.db"

# Los pedidos son de 2025. Fijamos un «hoy» de la simulación para que haya
# pedidos en todos los estados (si usáramos la fecha real, todos estarían
# entregados hace meses y fuera de plazo).
HOY_SIMULADO = date(2026, 1, 2)
PLAZO_DEVOLUCION_DIAS = 30


def abrir_bd():
    """Abre las dos bases de datos en solo lectura (mode=ro)."""
    bd = sqlite3.connect(f"file:{ARCHIVO_VENTAS}?mode=ro", uri=True)
    bd.execute("ATTACH DATABASE ? AS e", (f"file:{ARCHIVO_ESTADOS}?mode=ro",))
    return bd


def consultar_pedido(numero):
    """Devuelve un diccionario con los datos del pedido, o None si no existe."""
    pedido = "#" + numero
    bd = abrir_bd()
    try:
        lineas = bd.execute(
            "SELECT fecha, producto, talla, unidades, importe_eur, devuelto "
            "FROM ventas WHERE pedido = ? ORDER BY fecha", (pedido,)).fetchall()
        fechas = bd.execute(
            "SELECT fecha_envio, fecha_entrega_prevista FROM e.estados "
            "WHERE pedido = ?", (pedido,)).fetchone()
    finally:
        bd.close()
    if not lineas or not fechas:
        return None

    envio = date.fromisoformat(fechas[0])
    entrega = date.fromisoformat(fechas[1])
    # Simplificación: si se devolvió alguna prenda, el pedido cuenta como devuelto.
    devuelto = any(linea[5] for linea in lineas)

    if devuelto:
        estado = "devuelto"
    elif HOY_SIMULADO < envio:
        estado = "preparando"
    elif HOY_SIMULADO < entrega:
        estado = "enviado"
    else:
        estado = "entregado"

    dias_desde_entrega = None
    if estado == "entregado":
        dias_desde_entrega = (HOY_SIMULADO - entrega).days
    dentro_plazo = (estado == "entregado"
                    and dias_desde_entrega <= PLAZO_DEVOLUCION_DIAS)

    return {
        "pedido": pedido,
        "fecha_compra": lineas[0][0],
        "productos": [{"producto": p, "talla": t, "unidades": u}
                      for _, p, t, u, _, _ in lineas],
        "importe_eur": round(sum(linea[4] for linea in lineas), 2),
        "estado": estado,
        "fecha_envio": fechas[0],
        "fecha_entrega_prevista": fechas[1],
        "dias_desde_entrega": dias_desde_entrega,
        "dentro_plazo_devolucion": dentro_plazo,
        "plazo_devolucion_dias": PLAZO_DEVOLUCION_DIAS,
        "hoy_simulado": HOY_SIMULADO.isoformat(),
        "aviso": "Datos ficticios de una tienda de ejemplo.",
    }


class Manejador(BaseHTTPRequestHandler):

    def do_GET(self):
        url = urlparse(self.path)
        if url.path != "/pedido":
            return self._json(404, {"error": "Ruta desconocida. Usa /pedido?numero=1002"})
        # Aceptamos «1002» o «#1002», pero solo cifras: así nadie puede
        # colar nada raro en la consulta.
        numero = parse_qs(url.query).get("numero", [""])[0].strip().lstrip("#")
        if not numero.isdigit() or len(numero) > 8:
            return self._json(400, {"error": "El número de pedido debe tener solo cifras, por ejemplo 1002."})
        try:
            datos = consultar_pedido(numero)
        except Exception as error:  # fallo inesperado: mensaje genérico
            print("Error inesperado:", repr(error))
            return self._json(500, {"error": "Error inesperado en el servidor."})
        if datos is None:
            return self._json(404, {"error": f"No existe el pedido #{numero}."})
        self._json(200, datos)

    def _json(self, codigo, datos):
        cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)


def main():
    for archivo, script in ((ARCHIVO_VENTAS, "06-sql-ventas/cargar_bd.py"),
                            (ARCHIVO_ESTADOS, "09-agente-telegram/crear_estados.py")):
        if not archivo.exists():
            raise SystemExit(f"Falta {archivo.name}. Ejecuta antes: python3 {script}")
    # 127.0.0.1: solo se puede llamar desde este ordenador, no desde internet.
    servidor = ThreadingHTTPServer(("127.0.0.1", PUERTO), Manejador)
    print(f"API de pedidos en http://127.0.0.1:{PUERTO}/pedido?numero=1002")
    servidor.serve_forever()


if __name__ == "__main__":
    main()
