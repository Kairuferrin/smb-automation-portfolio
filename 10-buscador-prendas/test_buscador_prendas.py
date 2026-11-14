"""Pruebas sin internet: comprueban las piezas que no dependen de las APIs.

Ejecutar con:  python3 -m unittest test_buscador_prendas -v
"""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import buscador_prendas as bp


class PruebasCajas(unittest.TestCase):
    def test_caja_completa_ocupa_toda_la_imagen(self):
        self.assertEqual(bp.caja_a_pixeles([0, 0, 1000, 1000], 800, 600),
                         (0, 0, 800, 600))

    def test_caja_central_con_margen(self):
        # Mitad central, más un 5 % de margen por cada lado.
        x, y, ancho, alto = bp.caja_a_pixeles([250, 250, 750, 750], 1000, 1000)
        self.assertEqual((x, y, ancho, alto), (225, 225, 550, 550))

    def test_caja_invertida_da_error(self):
        with self.assertRaises(ValueError):
            bp.caja_a_pixeles([500, 500, 100, 100], 100, 100)


class PruebasMomentos(unittest.TestCase):
    def test_reparte_seis_capturas(self):
        self.assertEqual(bp.momentos_de_captura(30, 6),
                         [2.5, 7.5, 12.5, 17.5, 22.5, 27.5])

    def test_video_muy_corto(self):
        self.assertEqual(bp.momentos_de_captura(0.8, 6), [0.4])


class PruebasGemini(unittest.TestCase):
    def test_descarta_prendas_sin_caja_valida(self):
        texto = json.dumps([
            {"imagen": 0, "caja": [0, 0, 10, 10], "tipo": "gorra"},
            {"imagen": 0, "caja": "mal", "tipo": "zapato"},
            {"imagen": 9, "caja": [1, 2, 3, 4], "tipo": "bolso"},
        ])
        prendas = bp.validar_prendas(texto, num_imagenes=2)
        # El bolso apunta a la imagen 9, que no existe: se descarta.
        self.assertEqual([p["tipo"] for p in prendas], ["gorra"])

    def test_aguanta_objetos_raros(self):
        texto = json.dumps(["texto suelto",
                            {"imagen": 0, "caja": [0, 0, 5, 5], "tipo": None}])
        prendas = bp.validar_prendas(texto, 1)
        self.assertEqual([p["tipo"] for p in prendas], ["prenda"])

    def test_acepta_json_dentro_de_bloque_de_codigo(self):
        texto = '```json\n[{"imagen": 0, "caja": [0, 0, 5, 5]}]\n```'
        self.assertEqual(len(bp.validar_prendas(texto, 1)), 1)

    def test_texto_que_no_es_json(self):
        with self.assertRaises(bp.ErrorBuscador):
            bp.validar_prendas("no sé", 1)


class PruebasResultados(unittest.TestCase):
    RESPUESTA = {
        "exact_matches": [{"title": "Bomber X", "source": "Tienda A",
                           "link": "https://a.example/1"}],
        "visual_matches": [
            {"title": "Bomber cara", "source": "Tienda B",
             "link": "https://b.example/2",
             "price": {"value": "€90", "extracted_value": 90}},
            {"title": "Bomber Alpha Industries", "source": "Tienda C",
             "link": "https://c.example/3"},
            {"title": "Bomber barata", "source": "Tienda D",
             "link": "https://d.example/4",
             "price": {"value": "€20", "extracted_value": 20}},
            {"title": "Sin enlace", "source": "Tienda E"},
            {"title": "Sin precio", "source": "Tienda F",
             "link": "https://f.example/6"},
        ],
    }

    def test_separa_mismo_y_candidatos(self):
        mismo, candidatos = bp.ordenar_resultados(
            self.RESPUESTA, {"marca_visible": "Alpha Industries"})
        self.assertEqual([r["tienda"] for r in mismo], ["Tienda A", "Tienda C"])
        self.assertEqual([r["tienda"] for r in candidatos],
                         ["Tienda B", "Tienda D", "Tienda F"])

    def test_sin_marca_visible_nada_pasa_a_mismo_salvo_exactos(self):
        mismo, _ = bp.ordenar_resultados(self.RESPUESTA, {"marca_visible": None})
        self.assertEqual([r["tienda"] for r in mismo], ["Tienda A"])

    def test_precio_no_se_inventa(self):
        self.assertEqual(bp.leer_precio({}), (None, None))
        self.assertEqual(bp.leer_precio({"price": "29 €"}), ("29 €", None))


def candidato(tienda, precio, valido=True):
    return {"titulo": tienda, "tienda": tienda, "enlace": f"https://{tienda}",
            "precio": None if precio is None else f"{precio} €",
            "precio_numero": precio, "valido": valido}


class PruebasGamas(unittest.TestCase):
    def test_reparte_en_tres_gamas(self):
        lista = [candidato(f"t{n}", n) for n in (10, 20, 30, 40, 50, 60)]
        lista.append(candidato("sin", None))
        lista.append(candidato("mala", 5, valido=False))
        gamas = bp.repartir_por_gamas(lista)
        self.assertEqual([r["tienda"] for r in gamas["económica"]], ["t10", "t20"])
        self.assertEqual([r["tienda"] for r in gamas["media"]], ["t30", "t40"])
        self.assertEqual([r["tienda"] for r in gamas["alta"]], ["t60", "t50"])
        self.assertEqual([r["tienda"] for r in gamas["sin precio"]], ["sin"])

    def test_con_pocos_precios_no_parte(self):
        gamas = bp.repartir_por_gamas([candidato("a", 10), candidato("b", 90)])
        self.assertEqual(list(gamas), ["media"])

    def test_nada_valido(self):
        self.assertEqual(bp.repartir_por_gamas([candidato("a", 10, False)]), {})


class PruebasMonedasYMarcas(unittest.TestCase):
    def test_no_mezcla_monedas(self):
        lista = [candidato(f"e{n}", n) for n in (10, 20, 30)]
        libra = dict(candidato("uk", 15), precio="£15")
        gamas = bp.repartir_por_gamas(lista + [libra])
        self.assertEqual([r["tienda"] for r in gamas["otra moneda"]], ["uk"])
        self.assertEqual([r["tienda"] for r in gamas["económica"]], ["e10"])

    def test_marca_por_palabra_completa(self):
        self.assertTrue(bp.contiene_palabra("Sudadera GAP gris", "Gap"))
        self.assertFalse(bp.contiene_palabra("Singapore store", "gap"))
        self.assertFalse(bp.contiene_palabra("lo que sea", ""))


class PruebasFiltro(unittest.TestCase):
    def setUp(self):
        self.original = bp.pedir_a_gemini

    def tearDown(self):
        bp.pedir_a_gemini = self.original

    def prendas(self):
        return [{"tipo": "sudadera", "mismo": [],
                 "candidatos": [candidato("buena", 20, valido=False),
                                candidato("ascensor", None, valido=False)]}]

    def test_marca_validos_y_ignora_ids_inventados(self):
        bp.pedir_a_gemini = lambda clave, partes: json.dumps([
            {"id": "0-0", "nombre": "Sudadera gris", "descripcion": "Básica."},
            {"id": "9-9", "nombre": "Inventado"}])
        prendas = self.prendas()
        bp.filtrar_y_describir("x", prendas)
        buena, ascensor = prendas[0]["candidatos"]
        self.assertTrue(buena["valido"])
        self.assertEqual(buena["descripcion"], "Básica.")
        self.assertNotIn("nombre", buena)  # el nombre de la IA no se usa
        self.assertFalse(ascensor["valido"])

    def test_si_gemini_falla_se_ensena_todo_con_aviso(self):
        def falla(clave, partes):
            raise bp.ErrorBuscador("429")
        bp.pedir_a_gemini = falla
        prendas = self.prendas()
        bp.filtrar_y_describir("x", prendas)
        self.assertTrue(all(r["valido"] for r in prendas[0]["candidatos"]))
        self.assertIn("sin revisar", prendas[0]["aviso"])


class PruebasEntrada(unittest.TestCase):
    def test_rechaza_enlaces(self):
        with self.assertRaises(bp.ErrorBuscador) as contexto:
            bp.analizar("https://www.tiktok.com/@alguien/video/1", "es", "es")
        self.assertIn("No acepto enlaces", str(contexto.exception))

    def test_formato_no_admitido(self):
        with tempfile.TemporaryDirectory() as carpeta:
            with self.assertRaises(bp.ErrorBuscador):
                bp.preparar_imagenes(Path(carpeta) / "notas.txt", carpeta)

    def test_multipart_lleva_clave_e_imagen(self):
        cuerpo, tipo = bp.formulario_multipart({"api_key": "x"}, "a.jpg", b"JPG")
        limite = tipo.split("boundary=")[1]
        self.assertIn(b'name="api_key"\r\n\r\nx', cuerpo)
        self.assertIn(b'filename="a.jpg"', cuerpo)
        self.assertTrue(cuerpo.endswith(f"--{limite}--\r\n".encode()))


@unittest.skipUnless(shutil.which("sips") and shutil.which("ffmpeg"),
                     "necesita sips y ffmpeg")
class PruebasRecorte(unittest.TestCase):
    """Crea una imagen de prueba y comprueba que el recorte sale bien."""

    def test_recorte_tiene_el_tamano_esperado(self):
        with tempfile.TemporaryDirectory() as carpeta:
            origen = Path(carpeta) / "prueba.jpg"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                            "testsrc=size=1000x800", "-frames:v", "1",
                            str(origen)], check=True)
            destino = bp.recortar(origen, [100, 100, 600, 600],
                                  Path(carpeta) / "recorte.jpg")
            esperado = bp.caja_a_pixeles([100, 100, 600, 600], 1000, 800)
            self.assertEqual(bp.tamano_imagen(destino), esperado[2:])
            self.assertLessEqual(destino.stat().st_size, 500 * 1024)

    def test_saca_fotogramas_de_un_video(self):
        with tempfile.TemporaryDirectory() as carpeta:
            video = Path(carpeta) / "prueba.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                            "testsrc=size=640x360:duration=10", "-pix_fmt",
                            "yuv420p", str(video)], check=True)
            fotogramas = bp.sacar_fotogramas(video, carpeta)
            self.assertEqual(len(fotogramas), 6)


if __name__ == "__main__":
    unittest.main()
