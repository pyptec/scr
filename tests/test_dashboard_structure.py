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

    def test_menu_and_modules_have_the_eleven_expected_destinations(self):
        expected = {
            "resumen", "produccion", "calidad", "eficiencia-operacional",
            "eficiencia-energetica", "linea-base", "impacto",
            "confiabilidad", "alarmas", "variables", "gateway",
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

    def test_dashboard_exposes_traceable_reconciliation_without_treating_events_as_failures(self):
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

    def test_impact_view_uses_traceable_phase_3_contract(self):
        self.assertIn('id="impactoResidual"', self.html)
        self.assertIn('id="chartImpactoEconomico"', self.html)
        self.assertIn('id="chartImpactoAmbiental"', self.html)
        self.assertIn('id="tablaImpactoDiaria"', self.html)
        self.assertIn("/api/linea-base/impacto", self.javascript)
        self.assertIn("Tarifa no configurada", self.javascript)
        self.assertIn("Factor de emisión no configurado", self.javascript)
        self.assertIn("dia.economicImpactCop", self.javascript)
        self.assertIn("dia.co2eImpactKg", self.javascript)
        self.assertNotIn("dia.economicImpactCop || 0", self.javascript)
        self.assertNotIn('id="costoTotalizador"', self.html)
        self.assertNotIn('id="co2Totalizador"', self.html)

    def test_variable_selector_supports_gateway_variables_without_device(self):
        self.assertIn('"Variables del gateway"', self.javascript)
        self.assertIn("v.source_type", self.javascript)

    def test_maintenance_view_exposes_suggestions_without_treating_them_as_confirmed_failures(self):
        for identifier in (
            "mantPendientes", "mantCorrectivas", "mantPreventivos",
            "mantOperacionales", "mantSinDatos", "mantValidados",
            "mantFallasConfirmadas", "tablaMantenimiento",
            "filtroMantSugerencia", "filtroMantValidacion",
        ):
            self.assertIn(f'id="{identifier}"', self.html)
        self.assertIn("/api/fase4/dashboard", self.javascript)
        self.assertIn("PENDING_HUMAN_REVIEW", self.html)
        self.assertIn("Una sugerencia CORRECTIVE_FAILURE tampoco constituye", self.html)
        self.assertIn('moduloActual === "confiabilidad"', self.javascript)
        self.assertIn("/validacion", self.javascript)

    def test_maintenance_validation_and_uptime_preparation_are_visible_without_kpi(self):
        for identifier in (
            "mantEstadoPreparacion", "mantUptimeValidado",
            "mantTiempoNoResuelto", "mantEventoValidar",
            "mantBearerToken", "mantGuardarValidacion",
            "tablaVentanasOperacion", "mantGuardarVentana",
        ):
            self.assertIn(f'id="{identifier}"', self.html)
        self.assertIn("integrado.uptime", self.javascript)
        self.assertIn("/api/mantenimiento/ventanas-operacion", self.javascript)
        self.assertIn('"Authorization": `Bearer ${token}`', self.javascript)
        self.assertIn('"Idempotency-Key": idempotencyKey()', self.javascript)
        self.assertNotIn("localStorage", self.javascript)
        self.assertNotIn("sessionStorage", self.javascript)

    def test_reliability_kpi_are_gated_and_traceable(self):
        for identifier in (
            "relReparacionesCompletas", "relDowntimeValidado", "relMtbf",
            "relMttr", "relDisponibilidadTiempo", "relDisponibilidadMtbf",
            "relTasaFallas", "relEstado", "relEstadoDetalle",
            "tablaConfiabilidad",
        ):
            self.assertIn(f'id="{identifier}"', self.html)
        self.assertIn("integrado.reliability", self.javascript)

    def test_phase4_views_use_integrated_dashboard_contract(self):
        self.assertIn('/api/fase4/dashboard?inicio=', self.javascript)
        app_source = (ROOT / "api" / "app.py").read_text(encoding="utf-8")
        self.assertIn('@app.route("/api/fase4/dashboard")', app_source)
        self.assertIn('data.status === "VALID"', self.javascript)
        self.assertIn("KPI no disponibles", self.javascript)
        self.assertIn("event.includedInMtbf", self.javascript)
        self.assertIn("event.includedInMttr", self.javascript)
        self.assertNotIn("summary.mtbfHours || 0", self.javascript)
        self.assertNotIn("summary.mttrHours || 0", self.javascript)

    def test_alert_dashboard_is_read_only_deduplicated_and_traceable(self):
        for identifier in (
            "alarmasAbiertas", "alarmasCriticas", "alarmasAdvertencias",
            "alarmasInformativas", "alarmasEnergeticas", "alarmasCalidad",
            "alarmasOperacionales", "alarmasMantenimiento",
            "alarmasConfiabilidad", "alarmasVersion", "tablaAlarmas",
            "filtroAlarmaTipo", "filtroAlarmaSeveridad", "filtroAlarmaModulo",
        ):
            self.assertIn(f'id="{identifier}"', self.html)
        self.assertIn('data-module-target="alarmas"', self.html)
        self.assertIn('moduloActual === "alarmas"', self.javascript)
        self.assertIn("integrado.alerts", self.javascript)
        self.assertIn("correlatedAlarmTypes", self.javascript)
        self.assertIn("no equivale a una falla", self.html)
        alert_loader = self.javascript.split(
            "async function cargarAlarmas", 1
        )[1].split("async function cargarMantenimiento", 1)[0]
        self.assertNotIn('method: "POST"', alert_loader)


if __name__ == "__main__":
    unittest.main()
