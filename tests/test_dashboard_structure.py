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
        self.assertIn('id="coberturaEstadosResumen"', self.html)
        self.assertIn('id="coberturaEnergiaResumen"', self.html)

    def test_dashboard_separates_reported_operation_and_electrical_classification(self):
        self.assertIn("Operación reportada", self.html)
        self.assertIn("Clasificación eléctrica preliminar", self.html)
        self.assertIn("No equivalen necesariamente al estado productivo real", self.html)
        self.assertIn('id="estadoHorasConDatos"', self.html)
        self.assertIn('id="estadoBalance"', self.html)
        self.assertIn('id="opDisponibilidadReportada"', self.html)
        self.assertIn("Horas de señal inconsistente", self.html)
        self.assertIn('id="tablaEventosAoki"', self.html)
        self.assertIn("No son fallas confirmadas", self.html)
        self.assertIn("const resumenEventos = eventosData.summary || {}", self.javascript)

    def test_dashboard_exposes_traceable_reconciliation_without_failures(self):
        for identifier in (
            "conciliacionReportadas", "conciliacionDetectadas", "conciliacionAmbas",
            "conciliacionSoloReportadas", "conciliacionSoloDetectadas",
            "conciliacionPendientes", "tablaConciliacionAoki",
            "filtroConciliacionClasificacion", "filtroConciliacionConfianza",
            "filtroConciliacionEstado", "filtroConciliacionJornada",
            "filtroConciliacionRevision",
        ):
            self.assertIn(f'id="{identifier}"', self.html)
        self.assertIn("Los eventos eléctricos no son fallas confirmadas", self.html)
        self.assertIn("/api/fase2/dashboard", self.javascript)
        self.assertIn("item.reportedDurationMinutes", self.javascript)
        self.assertIn("item.electricalDurationMinutes", self.javascript)
        self.assertIn("item.overlapMinutes", self.javascript)
        self.assertNotIn("MTBF", self.html)
        self.assertNotIn("MTTR", self.html)

    def test_dashboard_labels_historical_dataset_and_preliminary_baseline(self):
        self.assertIn("DATOS_HISTORICOS_DE_PRUEBA", self.html)
        self.assertIn("RESULTADO_PRELIMINAR", self.html)
        self.assertNotIn("Reentrenar línea base", self.html)
        self.assertNotIn("entrenarLineaBase()", self.javascript)

    def test_phase2_uses_one_integrated_contract_and_immutable_range(self):
        summary = self.javascript.split("async function cargarDashboard", 1)[1].split(
            "async function cargarEstado", 1
        )[0]
        self.assertIn("obtenerFase2(snapshot)", summary)
        self.assertNotIn("/api/dashboard", summary)
        self.assertNotIn("/api/produccion/modulo", summary)
        self.assertNotIn("/api/aoki/estados", summary)
        self.assertNotIn("reduce(", summary)
        self.assertIn("Object.freeze", self.javascript)
        self.assertIn("crearInstantaneaRango()", self.javascript)
        self.assertIn("CACHE_VERSION", self.javascript)

    def test_instantaneous_gateway_is_separated_from_historical_period(self):
        self.assertIn("Estado actual del gateway", self.html)
        self.assertIn("Información instantánea fuera del filtro histórico", self.html)
        self.assertIn("Últimos valores dentro del periodo seleccionado", self.html)
        self.assertIn("no es telemetría actual", self.html)

    def test_productive_is_never_presented_as_confirmed_real_production(self):
        self.assertIn("clasificación eléctrica preliminar", self.html)
        self.assertNotIn("PRODUCTIVE real demostrado", self.html)
        self.assertNotIn("disponibilidad técnica", self.html.lower())

    def test_energy_distinguishes_state_and_energy_no_data(self):
        self.assertIn('id="energiaReconNoDataHoras"', self.html)
        self.assertIn("no deja de ser NO_DATA para estados", self.html)

    def test_quality_uses_reported_production(self):
        self.assertIn('id="calidadEficiencia"', self.html)
        self.assertIn('id="calidadRechazo"', self.html)
        self.assertIn('moduloActual === "calidad"', self.javascript)

    def test_base_100_and_cusum_views_are_active(self):
        self.assertIn('data-linea-base-view="indice-base-100"', self.html)
        self.assertIn('data-linea-base-view="cusum"', self.html)
        self.assertNotIn("Pendiente de fase 3", self.html)
        self.assertIn('id="chartBase100Diario"', self.html)
        self.assertIn('id="tablaBase100Diaria"', self.html)
        self.assertIn("/api/linea-base/base-100", self.javascript)
        self.assertIn("dia.base100Index", self.javascript)
        self.assertIn("spanGaps: false", self.javascript)
        self.assertNotIn("dia.base100Index || 0", self.javascript)
        self.assertIn('id="chartCusumDiario"', self.html)
        self.assertIn('id="tablaCusumDiaria"', self.html)
        self.assertIn("/api/linea-base/cusum", self.javascript)
        self.assertIn("dia.cusumContributionKWh", self.javascript)
        self.assertNotIn("dia.cusumContributionKWh || 0", self.javascript)
        self.assertIn("dia.includedInCusum ? null : dia.cusumKWh", self.javascript)
        self.assertIn("function inicializarVistasLineaBase()", self.javascript)

    def test_variable_selector_supports_gateway_variables_without_device(self):
        self.assertIn('"Variables del gateway"', self.javascript)
        self.assertIn("v.source_type", self.javascript)


if __name__ == "__main__":
    unittest.main()
