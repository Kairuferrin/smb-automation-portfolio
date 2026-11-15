"""Pruebas del juez de código y de aplicar_cambios (sin llamar a ninguna IA).

Uso:
    python3 -m unittest test_examinador.py
"""

import unittest

from aplicar_cambios import aplicar
from examinar import juez_codigo
from generar_casos import revisar_numero


def turno(cliente, respuesta, *pasos, formato=True):
    return {"cliente": cliente, "agente": {
        "respuesta": respuesta, "formato_correcto": formato,
        "pasos": [{"herramienta": h, "entrada": e, "resultado": ""} for h, e in pasos]}}


CASO_DENTRO = {"pedido": "2142", "esperado": {
    "consultar_pedido": "debe", "enviar_formulario_devolucion": "debe",
    "derivar_a_persona": "no_debe", "enlace_formulario": "debe", "idioma": "es"}}
CASO_TEMA = {"pedido": None, "esperado": {
    "consultar_pedido": "no_debe", "enviar_formulario_devolucion": "no_debe",
    "derivar_a_persona": "no_debe", "enlace_formulario": "no_debe", "idioma": "es"}}


class TestJuezCodigo(unittest.TestCase):
    def test_devolucion_bien_hecha(self):
        turnos = [turno("quiero devolver el 2142", "Aquí tienes: https://x.trycloudflare.com/form/abc",
                        ("consultar_pedido", {"numero": "2142"}), ("enviar_formulario_devolucion", {}))]
        notas = juez_codigo(CASO_DENTRO, turnos)
        self.assertTrue(all(v["ok"] for v in notas.values()), notas)

    def test_numero_equivocado(self):
        turnos = [turno("devolver 2142", "https://x/form/a",
                        ("consultar_pedido", {"numero": "2143"}), ("enviar_formulario_devolucion", {}))]
        self.assertFalse(juez_codigo(CASO_DENTRO, turnos)["numero_correcto"]["ok"])

    def test_enlace_desconocido(self):
        turnos = [turno("devolver 2142", "https://x/form/a y https://instagram.com/tienda",
                        ("consultar_pedido", {"numero": "2142"}), ("enviar_formulario_devolucion", {}))]
        self.assertFalse(juez_codigo(CASO_DENTRO, turnos)["enlace"]["ok"])

    def test_derivar_tarde_no_lo_juzga_el_codigo(self):
        # El cliente se enfada en el turno 2: derivar ahí lo juzga la IA, no el código.
        turnos = [turno("¿abrís tienda física?", "Solo ayudo con pedidos."),
                  turno("¡quiero un humano!", "Te paso con el equipo.", ("derivar_a_persona", {}))]
        self.assertTrue(juez_codigo(CASO_TEMA, turnos)["derivar_a_persona"]["ok"])

    def test_derivar_en_el_primer_turno_es_fallo(self):
        turnos = [turno("¿abrís tienda física?", "Te paso con el equipo.", ("derivar_a_persona", {}))]
        self.assertFalse(juez_codigo(CASO_TEMA, turnos)["derivar_a_persona"]["ok"])

    def test_formato_incorrecto(self):
        turnos = [turno("hola", "texto suelto", formato=False)]
        self.assertFalse(juez_codigo(CASO_TEMA, turnos)["formato"]["ok"])


class TestAplicarCambios(unittest.TestCase):
    PROMPT = "Reglas:\n1. Sé amable.\n\nFormato de salida: JSON"

    def test_sustituir(self):
        nuevo = aplicar(self.PROMPT, [{"numero": 1, "buscar": "Sé amable.", "reemplazar_por": "Sé muy amable."}])
        self.assertIn("Sé muy amable.", nuevo)

    def test_anadir_antes_del_formato(self):
        nuevo = aplicar(self.PROMPT, [{"numero": 1, "buscar": "", "reemplazar_por": "2. No prometas dinero."}])
        self.assertLess(nuevo.index("No prometas"), nuevo.index("Formato de salida"))

    def test_cambio_que_no_encaja(self):
        with self.assertRaises(SystemExit):
            aplicar(self.PROMPT, [{"numero": 1, "buscar": "no existe", "reemplazar_por": "x"}])


class TestRevisarNumero(unittest.TestCase):
    def test_numero_que_no_coincide(self):
        # El fallo real del caso B08: pedido 2385, pero el mensaje decía 2364.
        with self.assertRaises(SystemExit):
            revisar_numero({"primer_mensaje": "Mi pedido 2364 no llega"}, "2385", "queja_pide_persona")

    def test_numero_correcto(self):
        revisar_numero({"primer_mensaje": "Mi pedido 2385 no llega"}, "2385", "queja_pide_persona")

    def test_sin_numero_no_debe_darlo(self):
        with self.assertRaises(SystemExit):
            revisar_numero({"primer_mensaje": "¿dónde está el 2142?"}, "2142", "sin_numero")

    def test_sin_numero_con_el_numero_de_otro_cliente(self):
        with self.assertRaises(SystemExit):
            revisar_numero({"primer_mensaje": "¿y el 2200?"}, "2142", "sin_numero", ["2142", "2200"])

    def test_sin_numero_bien(self):
        revisar_numero({"primer_mensaje": "¿dónde está mi pedido?"}, "2142", "sin_numero", ["2142"])

    def test_sin_pedido(self):
        revisar_numero({"primer_mensaje": "¿abrís tienda física?"}, None, "fuera_de_tema")

    def test_numero_dentro_de_otro_mas_largo(self):
        with self.assertRaises(SystemExit):
            revisar_numero({"primer_mensaje": "llamadme al 623850"}, "2385", "queja_pide_persona")

    def test_numero_con_almohadilla(self):
        revisar_numero({"primer_mensaje": "pedido #2385"}, "2385", "queja_pide_persona")


if __name__ == "__main__":
    unittest.main()
