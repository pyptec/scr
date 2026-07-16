from datetime import datetime, timedelta, timezone

from db.aoki_energy import query_aoki_energy_rows, reconstruct_aoki_energy
from db.aoki_events import detect_aoki_downtime_events
from db.aoki_reconciliation import (
    empty_reconciliation_result,
    extract_reported_events,
    reconcile_aoki_downtimes,
    resolve_reconciliation_range,
)
from db.aoki_states import classify_aoki_states, query_aoki_rows
from db.kpi_samee200 import resumen_kpi_samee200
from db.produccion_samee200 import obtener_modulo_produccion, obtener_produccion_periodos


BOGOTA = timezone(timedelta(hours=-5), name="America/Bogota")
TIMEZONE_NAME = "America/Bogota"


def _range_values(start_utc, end_utc):
    start_utc, end_utc = int(start_utc), int(end_utc)
    return {
        "startUtc": start_utc,
        "endUtc": end_utc,
        "startLocal": datetime.fromtimestamp(start_utc, timezone.utc).astimezone(BOGOTA).isoformat(),
        "endLocal": datetime.fromtimestamp(end_utc, timezone.utc).astimezone(BOGOTA).isoformat(),
    }


def temporal_contract(requested_start, requested_end, effective=None, reconciliable=None):
    requested = _range_values(requested_start, requested_end)
    effective_values = _range_values(*(effective or (requested_start, requested_end)))
    return {
        "requestedRange": requested,
        "effectiveRange": effective_values,
        "reconciliableRange": (
            _range_values(*reconciliable) if reconciliable is not None else None
        ),
        "timezone": TIMEZONE_NAME,
        "startInclusive": True,
        "endExclusive": True,
    }


def attach_temporal_contract(result, requested_start, requested_end, effective=None,
                             reconciliable=None):
    """Añade el contrato común sin retirar ni renombrar campos cerrados."""
    contract = temporal_contract(
        requested_start, requested_end, effective=effective, reconciliable=reconciliable
    )
    if "effectiveRange" in result:
        contract["effectiveRange"] = result["effectiveRange"]
    result.update(contract)
    return result


def _energy_known_total(energy):
    return float((energy.get("periodSummary") or {}).get("knownEnergyKWh") or 0)


def build_phase2_dashboard(conn, requested_start, requested_end):
    """Integra resultados validados de fase 2 sin persistencia ni fórmulas duplicadas."""
    requested_start, requested_end = int(requested_start), int(requested_end)
    if requested_end <= requested_start:
        raise ValueError("El fin del periodo debe ser posterior al inicio")

    ranges = temporal_contract(requested_start, requested_end)
    production = obtener_modulo_produccion(requested_start, requested_end)
    attach_temporal_contract(production, requested_start, requested_end)

    state_rows = query_aoki_rows(conn, requested_start, requested_end)
    electrical_states = classify_aoki_states(state_rows, requested_start, requested_end)
    attach_temporal_contract(electrical_states, requested_start, requested_end)
    electrical_events = detect_aoki_downtime_events(electrical_states)
    attach_temporal_contract(electrical_events, requested_start, requested_end)

    energy_rows = query_aoki_energy_rows(conn, requested_start, requested_end)
    energy = reconstruct_aoki_energy(
        energy_rows, start_utc=requested_start, end_utc=requested_end
    )
    attach_temporal_contract(energy, requested_start, requested_end)

    recon_range = resolve_reconciliation_range(conn, requested_start, requested_end)
    if recon_range is None:
        reconciliation = empty_reconciliation_result()
    else:
        recon_start, recon_end = recon_range
        if (recon_start, recon_end) == (requested_start, requested_end):
            recon_states = electrical_states
            recon_events = electrical_events
        else:
            recon_rows = query_aoki_rows(conn, recon_start, recon_end)
            recon_states = classify_aoki_states(recon_rows, recon_start, recon_end)
            recon_events = detect_aoki_downtime_events(recon_states)
        reported = extract_reported_events(
            obtener_produccion_periodos(recon_start, recon_end)
        )
        reconciliation = reconcile_aoki_downtimes(
            recon_events.get("events", []), reported, recon_states.get("segments", []),
            recon_start, recon_end,
        )
    attach_temporal_contract(
        reconciliation, requested_start, requested_end,
        effective=recon_range or (requested_start, requested_end),
        reconciliable=recon_range,
    )
    ranges = temporal_contract(
        requested_start, requested_end, reconciliable=recon_range
    )

    legacy = resumen_kpi_samee200(
        inicio=requested_start,
        fin=requested_end,
        modulo_produccion=production,
        energia_proceso_kwh=_energy_known_total(energy),
    )
    attach_temporal_contract(legacy, requested_start, requested_end)

    return {
        "datasetType": "DATOS_HISTORICOS_DE_PRUEBA",
        "production": production,
        "quality": {
            "envasesBuenos": production.get("envases_buenos"),
            "envasesMalos": production.get("envases_malos"),
            "produccionTotal": production.get("produccion_total"),
            "eficienciaCalidadPct": production.get("eficiencia_calidad_pct"),
            "tasaRechazoPct": production.get("tasa_rechazo_pct"),
            "rechazosPor1000": production.get("rechazos_por_1000"),
            **temporal_contract(requested_start, requested_end),
        },
        "energy": energy,
        "electricalStates": electrical_states,
        "electricalEvents": electrical_events,
        "reconciliation": reconciliation,
        "legacyDashboard": legacy,
        "gateway": {
            "scope": "INSTANTANEO_FUERA_DEL_FILTRO_HISTORICO",
            "endpoint": "/api/estado",
            "datasetType": "DATOS_HISTORICOS_DE_PRUEBA",
        },
        "ranges": ranges,
        "methodology": {
            "timezone": TIMEZONE_NAME,
            "interval": "[inicio, fin)",
            "productiveMeaning": "CLASIFICACION_ELECTRICA_PRELIMINAR",
            "stateCoverageField": "electricalStates.periodSummary.coveragePct",
            "energyCoverageField": "energy.periodSummary.energyCoveragePct",
            "unit61": "kW",
            "closedContractAliases": {
                "production.periodo.inicio_utc": "production.requestedRange.startUtc",
                "production.periodo.fin_utc": "production.requestedRange.endUtc",
                "reconciliation.effectiveRange": "reconciliation.reconciliableRange",
            },
        },
    }
