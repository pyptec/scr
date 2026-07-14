import re
import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DashboardHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.modules = []
        self.targets = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if "data-module" in attributes:
            self.modules.append(attributes["data-module"])
        if "data-module-target" in attributes:
            self.targets.append(attributes["data-module-target"])


class DashboardStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "templates" / "dashboard.html").read_text(encoding="utf-8")
        cls.javascript = (ROOT / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")
        cls.parser = DashboardHTMLParser()
        cls.parser.feed(cls.html)

    def test_menu_and_modules_have_the_ten_expected_destinations(self):
        expected = {
            "resumen", "produccion", "calidad", "eficiencia-operacional",
            "eficiencia-energetica", "linea-base", "impacto",
            "confiabilidad", "variables", "gateway",
        }
        self.assertEqual(set(self.parser.targets), expected)
        self.assertEqual(set(self.parser.modules), expected)

    def test_resumen_is_the_only_visible_initial_module(self):
        tags = re.findall(r'<section[^>]+data-module="([^"]+)"[^>]*>', self.html)
        visible = [name for name in tags if not re.search(
            rf'<section[^>]+data-module="{re.escape(name)}"[^>]+hidden', self.html
        )]
        self.assertEqual(visible, ["resumen"])

    def test_filter_and_effective_period_are_global(self):
        first_module = self.html.index('data-module="resumen"')
        self.assertLess(self.html.index('id="rangoTiempo"'), first_module)
        self.assertLess(self.html.index('id="periodoEfectivo"'), first_module)

    def test_productive_day_boundaries_use_six_oclock(self):
        self.assertIn("rangoJornadaActual(1)", self.javascript)
        self.assertIn("rangoJornadaActual(7)", self.javascript)
        self.assertIn("rangoJornadaActual(30)", self.javascript)
        self.assertIn("unixDesdeColombia(year, month, 1, 6, 0, 0)", self.javascript)

    def test_module_loader_does_not_call_every_data_source_unconditionally(self):
        actualizar = self.javascript.split("async function actualizarTodo()", 1)[1]
        actualizar = actualizar.split("async function navegarAModulo", 1)[0]
        self.assertIn('moduloActual === "produccion"', actualizar)
        self.assertIn('moduloActual === "variables"', actualizar)
        self.assertNotIn("await cargarProduccion();\n        await cargarLineaBase();", actualizar)

    def test_summary_prepares_productive_and_downtime_cards(self):
        self.assertIn('id="horasProductivasResumen"', self.html)
        self.assertIn('id="horasParadaResumen"', self.html)
        self.assertIn("No disponible", self.html)

    def test_base_100_and_cusum_are_separate_pending_phase_3_views(self):
        self.assertIn('data-linea-base-view="indice-base-100"', self.html)
        self.assertIn('data-linea-base-view="cusum"', self.html)
        self.assertEqual(self.html.count("Pendiente de fase 3"), 2)
        self.assertIn("function inicializarVistasLineaBase()", self.javascript)


if __name__ == "__main__":
    unittest.main()
