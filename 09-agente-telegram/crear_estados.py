"""Inventa el estado de envío de cada pedido (datos FICTICIOS).

La base de datos del proyecto 6 (ventas.db) dice qué se vendió y si se
devolvió, pero no cuándo se envió ni cuándo llegó. Este script se lo inventa
para cada pedido y lo guarda aparte, en estados.db, sin tocar el proyecto 6.

Usa una «semilla» fija: es como barajar las cartas siempre igual, así que
cada vez que lo ejecutas salen exactamente las mismas fechas.

Uso:
    python3 crear_estados.py
"""

import random
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

CARPETA = Path(__file__).parent
ARCHIVO_VENTAS = CARPETA.parent / "06-sql-ventas" / "ventas.db"
ARCHIVO_ESTADOS = CARPETA / "estados.db"
SEMILLA = 9

CREAR_TABLA = """
CREATE TABLE estados (
    pedido                  TEXT PRIMARY KEY,  -- p. ej. #1002
    fecha_envio             TEXT,              -- AAAA-MM-DD
    fecha_entrega_prevista  TEXT               -- AAAA-MM-DD
)
"""


def main():
    if not ARCHIVO_VENTAS.exists():
        sys.exit("Falta ventas.db. Ejecuta antes: "
                 f"python3 {ARCHIVO_VENTAS.parent / 'cargar_bd.py'}")

    # mode=ro: abrimos la base del proyecto 6 en solo lectura.
    ventas = sqlite3.connect(f"file:{ARCHIVO_VENTAS}?mode=ro", uri=True)
    pedidos = ventas.execute(
        "SELECT pedido, MIN(fecha) FROM ventas GROUP BY pedido ORDER BY pedido"
    ).fetchall()
    ventas.close()

    azar = random.Random(SEMILLA)
    filas = []
    for pedido, fecha in pedidos:
        compra = date.fromisoformat(fecha)
        envio = compra + timedelta(days=azar.randint(1, 3))     # preparar
        entrega = envio + timedelta(days=azar.randint(2, 5))    # transporte
        filas.append((pedido, envio.isoformat(), entrega.isoformat()))

    ARCHIVO_ESTADOS.unlink(missing_ok=True)  # empezamos de cero cada vez
    bd = sqlite3.connect(ARCHIVO_ESTADOS)
    bd.execute(CREAR_TABLA)
    bd.executemany("INSERT INTO estados VALUES (?, ?, ?)", filas)
    bd.commit()
    bd.close()
    print(f"Creado {ARCHIVO_ESTADOS.name} con {len(filas)} pedidos.")


if __name__ == "__main__":
    main()
