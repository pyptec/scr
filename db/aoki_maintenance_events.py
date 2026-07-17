import hashlib
import json
import re
import unicodedata
from collections import Counter
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
TAXONOMY_PATH = ROOT / "device" / "aoki_maintenance_taxonomy.json"


def load_maintenance_taxonomy(path=TAXONOMY_PATH):
    with open(path, "r", encoding="utf-8") as file:
        taxonomy = json.load(file)
    required = {
        "CORRECTIVE_FAILURE", "PREVENTIVE_MAINTENANCE", "PREDICTIVE_MAINTENANCE",
        "OPERATIONAL_STOP", "PLANNED_STOP", "QUALITY_ADJUSTMENT",
        "MATERIAL_SHORTAGE", "CLEANING", "CHANGEOVER", "DATA_QUALITY_EVENT",
        "OTHER", "UNDETERMINED",
    }
    if taxonomy.get("version") != "aoki-maintenance-taxonomy-v1-2026-07":
        raise ValueError("Versión de taxonomía de mantenimiento no reconocida")
    if set(taxonomy.get("classifications", [])) != required:
        raise ValueError("La taxonomía de mantenimiento está incompleta")
    return taxonomy


def _normalized_text(value):
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return " ".join(text.casefold().split())


def _contains(text, pattern):
    return re.search(pattern, text, re.IGNORECASE) is not None


def _source_ids(event):
    values = []
    for key, prefix in (
        ("reportedEventIds", "reported"),
        ("electricalEventIds", "electrical"),
    ):
        for value in event.get(key, []):
            values.append(f"{prefix}:{value}")
    if not values and event.get("reconciliationId"):
        values.append(f"reconciliation:{event['reconciliationId']}")
    return sorted(set(values))


def maintenance_event_id(event):
    """Identidad estable: IDs fuente canónicos ordenados, sin taxonomyVersion."""
    source_ids = _source_ids(event)
    if not source_ids:
        raise ValueError("El evento no tiene IDs fuente canónicos")
    digest = hashlib.sha256("|".join(source_ids).encode("utf-8")).hexdigest()[:20]
    return f"maintenance-{digest}"


def _suggest(event):
    classification = event.get("classification")
    if classification == "SIN_DATOS":
        return "DATA_QUALITY_EVENT", "HIGH", [
            "La conciliación de fase 2 identifica falta de datos suficiente."
        ]

    # matchedText delimita el evento normalizado de 2.6A. rawText puede contener
    # varias paradas y solo se usa cuando no existe el fragmento delimitado.
    evidence_text = event.get("matchedText") or event.get("rawText")
    text = _normalized_text("\n".join(filter(None, (
        evidence_text, event.get("cause")
    ))))
    if not text:
        return "UNDETERMINED", "NOT_APPLICABLE", [
            "No existe evidencia textual; IDLE, OFF o SOLO_DETECTADA no determinan una falla."
        ]

    if _contains(text, r"\bfalta\s+de\s+(?:materia\s+prima|material)\b"):
        return "MATERIAL_SHORTAGE", "HIGH", ["El reporte menciona falta de material."]
    if _contains(text, r"\bcambio\s+de\s+(?:molde|producto|referencia)\b"):
        return "CHANGEOVER", "HIGH", ["El reporte menciona un cambio operacional."]
    if _contains(text, r"\b(?:ajuste|calibracion)\b.*\bcalidad\b|\bcalidad\b.*\b(?:ajuste|calibracion)\b"):
        return "QUALITY_ADJUSTMENT", "HIGH", ["El reporte identifica un ajuste de calidad."]
    if _contains(text, r"\b(?:parada|mantenimiento)\s+programad[ao]\b"):
        return "PLANNED_STOP", "HIGH", ["El reporte identifica una actividad programada."]

    corrective = _contains(
        text,
        r"\b(?:falla|fallas|averia|averias|dano|danos|roto|rotura|escape|fuga)\b"
        r"|\bno\s+(?:levanta|levantar|alcanza|alcanzar|arranca|arrancar|funciona|funcionar)\b"
        r"|\b(?:cambio|reemplazo|reparacion)\s+de\s+(?:una\s+)?(?:pieza|valvula|empaque)\b",
    )
    if corrective:
        return "CORRECTIVE_FAILURE", "MEDIUM", [
            "El texto contiene evidencia de daño, avería o acción correctiva.",
            "La sugerencia requiere validación humana y no es una falla confirmada.",
        ]

    cleaning = _contains(text, r"\b(?:limpieza|limpiar|soplar\s+filtros?)\b")
    preventive = _contains(text, r"\b(?:engrase|lubricacion|tratamiento\s+de\s+agua|aditivo\s+agua)\b")
    if cleaning and preventive:
        return "PREVENTIVE_MAINTENANCE", "MEDIUM", [
            "El reporte combina limpieza con lubricación o cuidado preventivo."
        ]
    if cleaning:
        return "CLEANING", "HIGH", ["El reporte describe limpieza sin daño explícito."]
    if preventive:
        return "PREVENTIVE_MAINTENANCE", "MEDIUM", [
            "El reporte describe lubricación o cuidado preventivo sin daño explícito."
        ]
    if _contains(text, r"\bmantenimiento\b"):
        return "UNDETERMINED", "LOW", [
            "La palabra mantenimiento no especifica daño, avería ni reparación."
        ]
    return "UNDETERMINED", "LOW", [
        "La evidencia textual no permite separar una falla de una parada operacional."
    ]


def _production_date(event):
    reported = event.get("reportedEvents") or []
    if reported:
        return reported[0].get("productionDate")
    electrical = event.get("electricalEvents") or []
    dates = electrical[0].get("productionDates", []) if electrical else []
    return dates[0] if dates else None


def _build_event(source, taxonomy):
    suggested, confidence, reasons = _suggest(source)
    return {
        "maintenanceEventId": maintenance_event_id(source),
        "taxonomyVersion": taxonomy["version"],
        "suggestedClassification": suggested,
        "suggestionConfidence": confidence,
        "suggestionReasons": reasons,
        "validatedClassification": None,
        "validationStatus": "PENDING_HUMAN_REVIEW",
        "confirmedFailure": False,
        "productionDate": _production_date(source),
        "reportedStart": source.get("startReported"),
        "reportedEnd": source.get("endReported"),
        "electricalStart": source.get("startElectrical"),
        "electricalEnd": source.get("endElectrical"),
        "reportedDurationMinutes": source.get("reportedDurationMinutes"),
        "electricalDurationMinutes": source.get("electricalDurationMinutes"),
        "cause": source.get("cause"),
        "rawText": source.get("rawText"),
        "matchedText": source.get("matchedText"),
        "sourceClassification": source.get("classification"),
        "sourceStatus": source.get("status"),
        "sourceIds": _source_ids(source),
        "reconciliationId": source.get("reconciliationId"),
        "reportedEventIds": sorted(source.get("reportedEventIds", [])),
        "electricalEventIds": sorted(source.get("electricalEventIds", [])),
        "evidence": {
            "hasReportedText": bool(source.get("rawText") or source.get("matchedText")),
            "hasElectricalEvent": bool(source.get("electricalEventIds")),
            "reconciliationReason": source.get("reason"),
        },
    }


def build_maintenance_events(phase2_contract, taxonomy=None):
    """Adapta fase 2 sin consultar ni persistir datos y sin validar clasificaciones."""
    source = deepcopy(phase2_contract)
    taxonomy = deepcopy(taxonomy or load_maintenance_taxonomy())
    reconciliation = source.get("reconciliation") or {}
    events = [_build_event(event, taxonomy) for event in reconciliation.get("events", [])]
    ids = [event["maintenanceEventId"] for event in events]
    if len(ids) != len(set(ids)):
        raise ValueError("Se generaron maintenanceEventId duplicados")
    suggestions = Counter(event["suggestedClassification"] for event in events)
    source_summary = reconciliation.get("summary") or {}
    daily = (source.get("electricalStates") or {}).get("daily") or []
    return {
        "taxonomyVersion": taxonomy["version"],
        "ranges": deepcopy(source.get("ranges")),
        "events": events,
        "summary": {
            "requestedDays": len(daily),
            "maintenanceEventCount": len(events),
            "reportedEvents": source_summary.get("totalReportadas", 0),
            "completeElectricalEvents": source_summary.get("totalDetectadas", 0),
            "soloDetectada": source_summary.get("totalSoloDetectadas", 0),
            "pendingReconciliation": source_summary.get("totalPendientesRevision", 0),
            "suggestionsByClassification": dict(sorted(suggestions.items())),
            "pendingHumanReview": len(events),
            "humanValidated": 0,
            "confirmedFailures": 0,
        },
        "methodology": {
            "source": "FASE_2_INTEGRATED_CONTRACT",
            "automaticSuggestionsOnly": True,
            "humanValidationPersistenceImplemented": False,
            "confirmedFailureRule": deepcopy(taxonomy["confirmedFailureRule"]),
            "kpiCalculated": {
                "mtbf": False,
                "mttr": False,
                "technicalAvailability": False,
                "failureRate": False,
            },
        },
    }


def find_maintenance_event(contract, maintenance_id):
    return next(
        (event for event in contract.get("events", [])
         if event.get("maintenanceEventId") == maintenance_id),
        None,
    )
