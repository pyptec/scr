import unittest
import sys
import types

if "dotenv" not in sys.modules:
    dotenv_stub = types.ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *args, **kwargs: None
    sys.modules["dotenv"] = dotenv_stub

samee200_db_stub = types.ModuleType("db.samee200_db")
samee200_db_stub.get_conn = lambda: None
sys.modules["db.samee200_db"] = samee200_db_stub

from db.produccion_samee200 import calcular_modulo_produccion


def periodo(inicio, fin, buenos=100, malos=5, observaciones="", fecha="2026-07-01", turnos=3):
    return {
        "fecha": fecha,
        "fecha_hora_inicio_utc": inicio,
        "fecha_hora_fin_utc": fin,
        "envases_buenos": buenos,
        "envases_malos": malos,
        "turnos": turnos,
        "observaciones": observaciones,
        "eficiencia": 1,
    }


class ProduccionModuloTests(unittest.TestCase):
    def test_calcula_totales_y_productividad_sin_usar_eficiencia_importada(self):
        fila = periodo(0, 86400, buenos=2400, malos=24)
        fila["eficiencia"] = 0.01
        resultado = calcular_modulo_produccion([fila], 0, 86400)

        self.assertEqual(resultado["produccion_total"], 2424)
        self.assertEqual(resultado["horas_programadas"], 24)
        self.assertEqual(resultado["horas_reales_trabajo"], 24)
        self.assertEqual(resultado["produccion_buena_hora_real"], 100)
        self.assertEqual(resultado["produccion_total_hora_real"], 101)

    def test_prorratea_un_periodo_parcial_por_duracion_real(self):
        resultado = calcular_modulo_produccion(
            [periodo(0, 86400, buenos=2400, malos=0)], 0, 43200
        )
        self.assertEqual(resultado["envases_buenos"], 1200)
        self.assertEqual(resultado["horas_programadas"], 12)

    def test_observacion_ambigua_deja_parada_y_derivados_pendientes(self):
        resultado = calcular_modulo_produccion(
            [periodo(0, 86400, observaciones="Máquina detenida")], 0, 86400
        )
        self.assertIsNone(resultado["horas_parada_reportadas"])
        self.assertIsNone(resultado["horas_reales_trabajo"])
        self.assertIsNone(resultado["produccion_buena_hora_real"])
        self.assertEqual(resultado["estado_paradas"], "DATO_PENDIENTE")

    def test_no_divide_por_cero(self):
        resultado = calcular_modulo_produccion(
            [periodo(0, 3600, buenos=0, malos=0)], 0, 3600
        )
        self.assertEqual(resultado["produccion_buena_hora_real"], 0)
        self.assertEqual(resultado["produccion_total_hora_real"], 0)

    def test_consolida_varios_periodos_en_una_fila_diaria(self):
        periodos = [
            periodo(0, 43200, buenos=100, fecha="2026-07-01", turnos=1),
            periodo(43200, 86400, buenos=200, fecha="2026-07-01", turnos=1),
        ]
        resultado = calcular_modulo_produccion(periodos, 0, 86400)
        self.assertEqual(resultado["dias_produccion_incluidos"], 1)
        self.assertEqual(len(resultado["detalle_diario"]), 1)
        self.assertEqual(resultado["detalle_diario"][0]["envases_buenos"], 300)

    def test_rechaza_rango_invalido(self):
        with self.assertRaises(ValueError):
            calcular_modulo_produccion([], 100, 100)


if __name__ == "__main__":
    unittest.main()
