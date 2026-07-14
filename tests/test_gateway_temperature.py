import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GatewayTemperatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = (ROOT / "api" / "app.py").read_text(encoding="utf-8")
        cls.html = (ROOT / "templates" / "dashboard.html").read_text(encoding="utf-8")
        cls.javascript = (ROOT / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")

    def test_temperature_is_scoped_to_the_raspberry_system_device(self):
        self.assertIn("sistema raspberry", self.api)
        self.assertIn("ultima_medicion_variable(1, sistema", self.api)

    def test_api_exposes_value_and_timestamp_without_defaulting_to_zero(self):
        self.assertIn('"temperatura_sistema_c": None', self.api)
        self.assertIn('"temperatura_sistema_fecha_colombia": None', self.api)

    def test_gateway_view_renders_temperature_in_celsius(self):
        self.assertIn('id="estadoTemperaturaSistema"', self.html)
        self.assertIn('id="estadoTemperaturaFecha"', self.html)
        self.assertIn('formatearNumero(data.temperatura_sistema_c, 1)} °C', self.javascript)
        self.assertIn('"No disponible"', self.javascript)


if __name__ == "__main__":
    unittest.main()
