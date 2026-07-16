import unittest
import sys
import types
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

if "dotenv" not in sys.modules:
    dotenv_stub = types.ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *args, **kwargs: None
    sys.modules["dotenv"] = dotenv_stub

samee200_db_stub = types.ModuleType("db.samee200_db")
samee200_db_stub.get_conn = lambda: None
sys.modules["db.samee200_db"] = samee200_db_stub

import db.produccion_samee200 as produccion_module
from db.produccion_samee200 import calcular_modulo_produccion, extraer_paradas_reportadas


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
    def test_extrae_duracion_explicita_en_minutos(self):
        eventos = extraer_paradas_reportadas("Se para la máquina 75 minutos", "2026-07-01")
        self.assertEqual(len(eventos), 1)
        self.assertEqual(eventos[0]["durationMinutes"], 75)
        self.assertEqual(eventos[0]["status"], "VALID")
        self.assertEqual(eventos[0]["temporalSource"], "EXPLICIT_DURATION")
        self.assertEqual(eventos[0]["rawText"], "Se para la máquina 75 minutos")

    def test_extrae_intervalos_de_los_ejemplos(self):
        casos = [
            ("Se para a las 14:50 y se inicia a las 18:00", 190),
            ("Se para a las 16:15 y se reinicia a las 20:40", 265),
        ]
        for texto, esperado in casos:
            with self.subTest(texto=texto):
                self.assertEqual(extraer_paradas_reportadas(texto)[0]["durationMinutes"], esperado)

    def test_intervalo_puede_cruzar_medianoche(self):
        evento = extraer_paradas_reportadas(
            "Se detiene a las 23:30 y se reinicia a las 01:00"
        )[0]
        self.assertEqual(evento["durationMinutes"], 90)
        self.assertTrue(evento["crossesMidnight"])

    def test_suma_varias_paradas_en_una_observacion(self):
        texto = "Se para la máquina 40 minutos. Se para la máquina 75 minutos"
        eventos = extraer_paradas_reportadas(texto)
        self.assertEqual(sum(e["durationMinutes"] for e in eventos), 115)

    def test_mencion_sin_duracion_queda_pendiente(self):
        evento = extraer_paradas_reportadas("Parada por causa desconocida")[0]
        self.assertIsNone(evento["durationMinutes"])
        self.assertEqual(evento["status"], "PENDING_REVIEW")

    def test_evitar_eventos_duplicados(self):
        eventos = extraer_paradas_reportadas(
            "Se para la máquina 40 minutos. Se para la máquina 40 minutos"
        )
        self.assertEqual(len(eventos), 1)

    def test_para_limpieza_es_causa_y_no_otra_parada(self):
        texto = "T03 Se para máquina 75 minutos para limpieza de filtros."
        eventos = extraer_paradas_reportadas(texto, "2026-05-10")
        self.assertEqual(len(eventos), 1)
        self.assertEqual(eventos[0]["cause"], "limpieza")
        self.assertEqual(eventos[0]["status"], "VALID")

    def test_raw_text_conserva_observacion_completa_y_matched_text_el_fragmento(self):
        texto = "T01 Se para la máquina 40 minutos por fallas. Nota de turno."
        evento = extraer_paradas_reportadas(texto, "2026-05-01")[0]
        self.assertEqual(evento["rawText"], texto)
        self.assertEqual(evento["matchedText"], "Se para la máquina 40 minutos por fallas. Nota de turno")
        self.assertEqual(evento["cause"], "falla")

    def test_event_id_es_estable(self):
        texto = "Se para la máquina 40 minutos por mantenimiento"
        primero = extraer_paradas_reportadas(texto, "2026-05-01")[0]
        segundo = extraer_paradas_reportadas(texto, "2026-05-01")[0]
        self.assertEqual(primero["eventId"], segundo["eventId"])
        self.assertTrue(primero["eventId"].startswith("reported-"))

    def test_causa_desconocida_permanece_null(self):
        evento = extraer_paradas_reportadas("Parada por causa desconocida")[0]
        self.assertIsNone(evento["cause"])

    def test_caso_real_4_mayo_a_las(self):
        texto = (
            "T02 Se para la máquina a las 14:50 por revisión del compresor, "
            "el tecnico informa cambio de pieza y se arranca a las 18:00."
        )
        evento = extraer_paradas_reportadas(texto, "2026-05-04")[0]
        self.assertEqual((evento["startTime"], evento["endTime"]), ("14:50", "18:00"))
        self.assertEqual(evento["durationMinutes"], 190)
        self.assertEqual(evento["temporalSource"], "START_END")

    def test_caso_real_13_mayo_reibicia_y_segunda_parada(self):
        texto = (
            "T02 Se para la máquina a las 16:15 para mantenimiento al compresor, "
            "se reibicia máquina a las 20:40.\n"
            "T03 Se para la máquina 105 minutos por daño de empaques."
        )
        eventos = extraer_paradas_reportadas(texto, "2026-05-13")
        self.assertEqual(len(eventos), 2)
        self.assertEqual(eventos[0]["durationMinutes"], 265)
        self.assertEqual(eventos[0]["status"], "VALID")
        self.assertEqual(eventos[1]["durationMinutes"], 105)

    def test_caso_real_24_junio_a_la_y_cruce_medianoche(self):
        texto = (
            "T01 Se para la máquina a la 09:40 por falta de energia.\n"
            "T03 Se inicia producción a la 01:00 por falta de energia y presecado."
        )
        evento = extraer_paradas_reportadas(texto, "2026-06-24")[0]
        self.assertEqual((evento["startTime"], evento["endTime"]), ("09:40", "01:00"))
        self.assertEqual(evento["durationMinutes"], 920)
        self.assertTrue(evento["crossesMidnight"])

    def test_caso_real_18_mayo_solo_reinicio_es_partial(self):
        texto = (
            "T01 Máquina parada por mantenimiento de compresor Booster Kaeser.\n"
            "T02 Se inicia producción a las 14:00"
        )
        evento = extraer_paradas_reportadas(texto, "2026-05-18")[0]
        self.assertIsNone(evento["startTime"])
        self.assertEqual(evento["endTime"], "14:00")
        self.assertIsNone(evento["durationMinutes"])
        self.assertEqual(evento["temporalSource"], "PARTIAL_TIME")
        self.assertEqual(evento["status"], "PARTIAL")

    def test_caso_real_5_junio_duracion_y_reinicio_contextual(self):
        texto = (
            "T01 Se para la máquina 160 minutos por punto corrido y queda en ajustes.\n"
            "T02 Se inicia a las 15:30 por ajuste de macho."
        )
        evento = extraer_paradas_reportadas(texto, "2026-06-05")[0]
        self.assertIsNone(evento["startTime"])
        self.assertEqual(evento["endTime"], "15:30")
        self.assertEqual(evento["durationMinutes"], 160)
        self.assertEqual(evento["temporalSource"], "EXPLICIT_DURATION")
        self.assertEqual(evento["status"], "VALID")

    def test_duracion_mayor_a_24_horas_requiere_revision(self):
        evento = extraer_paradas_reportadas("Se para la máquina 1500 minutos")[0]
        self.assertEqual(evento["durationMinutes"], 1500)
        self.assertEqual(evento["status"], "PENDING_REVIEW")

    def test_calcula_totales_y_productividad_sin_usar_eficiencia_importada(self):
        fila = periodo(0, 86400, buenos=2400, malos=24)
        fila["eficiencia"] = 0.01
        resultado = calcular_modulo_produccion([fila], 0, 86400)

        self.assertEqual(resultado["produccion_total"], 2424)
        self.assertEqual(resultado["horas_programadas"], 24)
        self.assertEqual(resultado["horas_reales_trabajo"], 24)
        self.assertEqual(resultado["produccion_buena_hora_real"], 100)
        self.assertEqual(resultado["produccion_total_hora_real"], 101)
        self.assertEqual(resultado["disponibilidad_operacional_reportada_pct"], 100)

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

    def test_duracion_reportada_se_resta_de_horas_programadas(self):
        resultado = calcular_modulo_produccion([
            periodo(0, 86400, buenos=2300, observaciones="Se para la máquina 60 minutos")
        ], 0, 86400)
        self.assertEqual(resultado["horas_parada_reportadas"], 1)
        self.assertEqual(resultado["horas_reales_trabajo"], 23)
        self.assertEqual(resultado["produccion_buena_hora_real"], 100)
        self.assertAlmostEqual(resultado["disponibilidad_operacional_reportada_pct"], 95.833, places=3)

    def test_calidad_se_calcula_desde_totales_reportados(self):
        resultado = calcular_modulo_produccion([
            periodo(0, 86400, buenos=900, malos=100)
        ], 0, 86400)
        self.assertEqual(resultado["eficiencia_calidad_pct"], 90)
        self.assertEqual(resultado["tasa_rechazo_pct"], 10)
        self.assertEqual(resultado["rechazos_por_1000"], 100)

    def test_parada_en_periodo_parcial_sin_hora_queda_pendiente(self):
        resultado = calcular_modulo_produccion([
            periodo(0, 86400, observaciones="Se para la máquina 60 minutos")
        ], 0, 43200)
        self.assertIsNone(resultado["horas_parada_reportadas"])

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

    def test_consulta_excluye_periodos_que_solo_tocan_las_fronteras(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "production.sqlite"
            connection = sqlite3.connect(database)
            connection.execute("""
                CREATE TABLE produccion_periodo (
                    id INTEGER, fecha TEXT, fecha_hora_inicio_local TEXT,
                    fecha_hora_fin_local TEXT, fecha_hora_inicio_utc INTEGER,
                    fecha_hora_fin_utc INTEGER, linea TEXT, producto TEXT,
                    envases_buenos REAL, envases_malos REAL, eficiencia REAL,
                    turnos REAL, observaciones TEXT, fuente TEXT, archivo_origen TEXT
                )
            """)
            base = ("2026-05-01", "", "", "AOKI", "Botella", 10, 0, 1, 3, "", "test", "test")
            rows = [
                (1, base[0], base[1], base[2], 0, 100, *base[3:]),
                (2, base[0], base[1], base[2], 200, 300, *base[3:]),
                (3, base[0], base[1], base[2], 100, 200, *base[3:]),
            ]
            connection.executemany(
                "INSERT INTO produccion_periodo VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            connection.commit()
            connection.close()

            def open_connection():
                conn = sqlite3.connect(database)
                conn.row_factory = sqlite3.Row
                return conn

            with patch.object(produccion_module, "init_produccion_db", lambda: None), \
                    patch.object(produccion_module, "get_conn", open_connection):
                result = produccion_module.obtener_produccion_periodos(100, 200)
            self.assertEqual([row["id"] for row in result], [3])


if __name__ == "__main__":
    unittest.main()
