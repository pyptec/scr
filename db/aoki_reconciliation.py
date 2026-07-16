import hashlib
import json
from collections import Counter, defaultdict, deque
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

from db.produccion_samee200 import extraer_paradas_reportadas


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "device" / "downtime_reconciliation.json"
BOGOTA = timezone(timedelta(hours=-5), name="America/Bogota")


def load_reconciliation_config(path=CONFIG_PATH):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def resolve_reconciliation_range(conn, requested_start_utc, requested_end_utc):
    """Limita el análisis a la intersección real de producción y corriente ME337_1."""
    requested_start_utc = int(requested_start_utc)
    requested_end_utc = int(requested_end_utc)
    production = conn.execute("""
        SELECT MIN(fecha_hora_inicio_utc), MAX(fecha_hora_fin_utc)
        FROM produccion_periodo
        WHERE fecha_hora_fin_utc > ? AND fecha_hora_inicio_utc < ?
    """, (requested_start_utc, requested_end_utc)).fetchone()
    electrical = conn.execute("""
        SELECT MIN(CAST(timestamp_utc AS INTEGER)), MAX(CAST(timestamp_utc AS INTEGER))
        FROM mediciones_detalle
        WHERE gateway_id = 10 AND TRIM(device_id) = '24' AND unit_id = 54
    """).fetchone()
    if not production or not electrical or production[0] is None or electrical[0] is None:
        return None
    start = max(requested_start_utc, int(production[0]), int(electrical[0]))
    end = min(requested_end_utc, int(production[1]), int(electrical[1]) + 1)
    return (start, end) if end > start else None


def extract_reported_events(periods):
    events = []
    seen = set()
    for period in periods:
        for event in extraer_paradas_reportadas(period.get("observaciones"), period.get("fecha")):
            if event["eventId"] not in seen:
                seen.add(event["eventId"])
                events.append(event)
    return events


def _parse_iso(value):
    return datetime.fromisoformat(value) if value else None


def _production_day_bounds(production_date):
    day = datetime.fromisoformat(production_date).date()
    start = datetime.combine(day, time(6), tzinfo=BOGOTA)
    return start, start + timedelta(days=1)


def _clock_on_production_day(production_date, clock_value):
    day_start, _ = _production_day_bounds(production_date)
    hour, minute = (int(part) for part in clock_value.split(":"))
    value = datetime.combine(day_start.date(), time(hour, minute), tzinfo=BOGOTA)
    return value + timedelta(days=1) if value < day_start else value


def _reported_window(event):
    if not event.get("productionDate") or not event.get("startTime") or not event.get("endTime"):
        return None
    start = _clock_on_production_day(event["productionDate"], event["startTime"])
    end = _clock_on_production_day(event["productionDate"], event["endTime"])
    if end <= start:
        end += timedelta(days=1)
    return start, end


def _overlap_minutes(start_a, end_a, start_b, end_b):
    return max(0.0, (min(end_a, end_b) - max(start_a, start_b)).total_seconds() / 60)


def _pct(numerator, denominator):
    if denominator is None or denominator <= 0:
        return None
    return round(numerator / denominator * 100, 3)


def _candidate_relation(reported, electrical, config):
    reported_window = _reported_window(reported)
    if reported_window is None:
        return None
    reported_start, reported_end = reported_window
    electrical_start = _parse_iso(electrical["startLocal"])
    electrical_end = _parse_iso(electrical["endLocal"])
    overlap = _overlap_minutes(reported_start, reported_end, electrical_start, electrical_end)
    start_difference = (electrical_start - reported_start).total_seconds() / 60
    end_difference = (electrical_end - reported_end).total_seconds() / 60
    tolerance = float(config["matchingToleranceMinutes"])
    if overlap <= 0 and abs(start_difference) > tolerance and abs(end_difference) > tolerance:
        return None
    reported_duration = reported.get("durationMinutes")
    electrical_duration = electrical.get("durationMinutes")
    reported_coverage = _pct(overlap, reported_duration)
    electrical_coverage = _pct(overlap, electrical_duration)
    significant = (
        overlap >= float(config["minimumOverlapMinutes"])
        and max(reported_coverage or 0, electrical_coverage or 0)
        >= float(config["minimumOverlapPct"])
    )
    reported_contains = reported_start <= electrical_start and reported_end >= electrical_end
    electrical_contains = electrical_start <= reported_start and electrical_end >= reported_end
    if overlap > 0:
        basis = "CONTAINMENT" if reported_contains or electrical_contains else "TEMPORAL_OVERLAP"
    else:
        basis = "BOUNDARY_PROXIMITY"
    return {
        "reportedEventId": reported["eventId"],
        "electricalEventId": electrical["eventId"],
        "overlapMinutes": round(overlap, 3),
        "reportedCoveragePct": reported_coverage,
        "electricalCoveragePct": electrical_coverage,
        "startDifferenceMinutes": round(start_difference, 3),
        "endDifferenceMinutes": round(end_difference, 3),
        "durationDifferenceMinutes": (
            round(electrical_duration - reported_duration, 3)
            if electrical_duration is not None and reported_duration is not None else None
        ),
        "significantOverlap": significant,
        "reportedContainsElectrical": reported_contains,
        "electricalContainsReported": electrical_contains,
        "basis": basis,
    }


def _interval_union_minutes(intervals):
    if not intervals:
        return 0.0
    merged = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        elif end > merged[-1][1]:
            merged[-1][1] = end
    return sum((end - start).total_seconds() / 60 for start, end in merged)


def _no_data_overlap(window, no_data_segments, tolerance_minutes=0):
    if window is None:
        return 0.0
    start, end = window
    if tolerance_minutes:
        delta = timedelta(minutes=tolerance_minutes)
        start, end = start - delta, end + delta
    intervals = []
    for segment in no_data_segments:
        segment_start = _parse_iso(segment["startLocal"])
        segment_end = _parse_iso(segment["endLocal"])
        overlap_start, overlap_end = max(start, segment_start), min(end, segment_end)
        if overlap_end > overlap_start:
            intervals.append((overlap_start, overlap_end))
    return round(_interval_union_minutes(intervals), 3)


def _reconciliation_id(reported_ids, electrical_ids, version):
    payload = "|".join([version, *sorted(reported_ids), "--", *sorted(electrical_ids)])
    return f"reconciliation-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:20]}"


def _confidence(relations, multiple, incomplete=False):
    if incomplete or not relations:
        return "NOT_APPLICABLE"
    if multiple:
        return "LOW"
    relation = relations[0]
    if (
        relation["significantOverlap"]
        and (relation["reportedCoveragePct"] or 0) >= 70
        and (relation["electricalCoveragePct"] or 0) >= 70
        and abs(relation["startDifferenceMinutes"]) <= 20
        and abs(relation["endDifferenceMinutes"]) <= 20
    ):
        return "HIGH"
    return "MEDIUM" if relation["significantOverlap"] else "LOW"


def _base_output(reported, electrical, classification, reason, version, relations=None):
    reported = list(reported)
    electrical = list(electrical)
    reported_ids = [event["eventId"] for event in reported]
    electrical_ids = [event["eventId"] for event in electrical]
    reported_windows = [window for event in reported if (window := _reported_window(event))]
    electrical_windows = [(_parse_iso(event["startLocal"]), _parse_iso(event["endLocal"])) for event in electrical]
    start_reported = min((window[0] for window in reported_windows), default=None)
    end_reported = max((window[1] for window in reported_windows), default=None)
    start_electrical = min((window[0] for window in electrical_windows), default=None)
    end_electrical = max((window[1] for window in electrical_windows), default=None)
    reported_duration = sum(
        event["durationMinutes"] for event in reported if event.get("durationMinutes") is not None
    ) if any(event.get("durationMinutes") is not None for event in reported) else None
    electrical_duration = sum(
        event["durationMinutes"] for event in electrical if event.get("durationMinutes") is not None
    ) if electrical else None
    relations = relations or []
    overlap_intervals = []
    reported_by_id = {event["eventId"]: event for event in reported}
    electrical_by_id = {event["eventId"]: event for event in electrical}
    for relation in relations:
        report_window = _reported_window(reported_by_id[relation["reportedEventId"]])
        electrical_event = electrical_by_id[relation["electricalEventId"]]
        electrical_window = (_parse_iso(electrical_event["startLocal"]), _parse_iso(electrical_event["endLocal"]))
        overlap_start = max(report_window[0], electrical_window[0])
        overlap_end = min(report_window[1], electrical_window[1])
        if overlap_end > overlap_start:
            overlap_intervals.append((overlap_start, overlap_end))
    overlap = round(_interval_union_minutes(overlap_intervals), 3) if relations else None
    return {
        "reconciliationId": _reconciliation_id(reported_ids, electrical_ids, version),
        "electricalEventIds": electrical_ids,
        "reportedEventIds": reported_ids,
        "classification": classification,
        "startReported": start_reported.isoformat() if start_reported else None,
        "endReported": end_reported.isoformat() if end_reported else None,
        "startElectrical": start_electrical.isoformat() if start_electrical else None,
        "endElectrical": end_electrical.isoformat() if end_electrical else None,
        "reportedDurationMinutes": round(reported_duration, 3) if reported_duration is not None else None,
        "electricalDurationMinutes": round(electrical_duration, 3) if electrical_duration is not None else None,
        "overlapMinutes": overlap,
        "reportedCoveragePct": _pct(overlap or 0, reported_duration) if overlap is not None else None,
        "electricalCoveragePct": _pct(overlap or 0, electrical_duration) if overlap is not None else None,
        "startDifferenceMinutes": (
            round((start_electrical - start_reported).total_seconds() / 60, 3)
            if start_reported and start_electrical else None
        ),
        "endDifferenceMinutes": (
            round((end_electrical - end_reported).total_seconds() / 60, 3)
            if end_reported and end_electrical else None
        ),
        "durationDifferenceMinutes": (
            round(electrical_duration - reported_duration, 3)
            if electrical_duration is not None and reported_duration is not None else None
        ),
        "confidence": _confidence(relations, len(reported) > 1 or len(electrical) > 1),
        "confidencePct": None,
        "rawText": "\n---\n".join(event["rawText"] for event in reported) if reported else None,
        "matchedText": "\n---\n".join(event["matchedText"] for event in reported) if reported else None,
        "cause": reported[0].get("cause") if len(reported) == 1 else None,
        "reason": reason,
        "status": "PENDING_REVIEW",
        "relations": relations,
        "reportedEvents": reported,
        "electricalEvents": electrical,
        "isFailure": False,
        "reconciliationVersion": version,
    }


def _connected_components(relations):
    graph = defaultdict(set)
    for relation in relations:
        reported_node = ("R", relation["reportedEventId"])
        electrical_node = ("E", relation["electricalEventId"])
        graph[reported_node].add(electrical_node)
        graph[electrical_node].add(reported_node)
    components = []
    visited = set()
    for node in graph:
        if node in visited:
            continue
        queue, nodes = deque([node]), set()
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            nodes.add(current)
            queue.extend(graph[current] - visited)
        components.append(nodes)
    return components


def reconcile_aoki_downtimes(electrical_events, reported_events, state_segments,
                              effective_start_utc, effective_end_utc, config=None):
    config = config or load_reconciliation_config()
    version = config["version"]
    start_local = datetime.fromtimestamp(int(effective_start_utc), timezone.utc).astimezone(BOGOTA)
    end_local = datetime.fromtimestamp(int(effective_end_utc), timezone.utc).astimezone(BOGOTA)
    electrical_events = [
        event for event in electrical_events
        if _parse_iso(event["endLocal"]) > start_local and _parse_iso(event["startLocal"]) < end_local
    ]
    reported_events = [
        event for event in reported_events
        if event.get("productionDate") and _production_day_bounds(event["productionDate"])[1] > start_local
        and _production_day_bounds(event["productionDate"])[0] < end_local
    ]
    no_data_segments = [segment for segment in state_segments if segment.get("state") == "NO_DATA"]
    reported_by_id = {event["eventId"]: event for event in reported_events}
    electrical_by_id = {event["eventId"]: event for event in electrical_events}
    relations = []
    for reported in reported_events:
        if _reported_window(reported) is None:
            continue
        for electrical in electrical_events:
            relation = _candidate_relation(reported, electrical, config)
            if relation is not None:
                relations.append(relation)

    output = []
    used_reported = set()
    used_electrical = set()
    for component in _connected_components(relations):
        reported_ids = {value for kind, value in component if kind == "R"}
        electrical_ids = {value for kind, value in component if kind == "E"}
        component_relations = [
            relation for relation in relations
            if relation["reportedEventId"] in reported_ids and relation["electricalEventId"] in electrical_ids
        ]
        component_reported = [reported_by_id[event_id] for event_id in sorted(reported_ids)]
        component_electrical = [electrical_by_id[event_id] for event_id in sorted(electrical_ids)]
        used_reported.update(reported_ids)
        used_electrical.update(electrical_ids)
        multiple = len(reported_ids) > 1 or len(electrical_ids) > 1
        significant = all(relation["significantOverlap"] for relation in component_relations)
        partial_overlap = any(
            relation["overlapMinutes"] > 0
            and not relation["reportedContainsElectrical"]
            and not relation["electricalContainsReported"]
            for relation in component_relations
        )
        unclear_cause = any(event.get("cause") is None for event in component_reported)
        no_data = sum(
            _no_data_overlap(_reported_window(event), no_data_segments)
            for event in component_reported
        )
        reported_coverage = max(
            (relation["reportedCoveragePct"] or 0 for relation in component_relations),
            default=0,
        )
        if no_data > 0 and (
            not significant or reported_coverage < float(config["minimumOverlapPct"])
        ):
            classification, reason = "SIN_DATOS", "NO_DATA impide confirmar la relación temporal"
        elif multiple:
            classification, reason = "PENDIENTE_REVISION", "Relación múltiple; requiere validar vínculos uno-a-varios o varios-a-uno"
        elif not significant:
            classification, reason = "PENDIENTE_REVISION", "Proximidad temporal sin solapamiento mínimo suficiente"
        elif partial_overlap:
            classification, reason = "PENDIENTE_REVISION", "Solapamiento parcial significativo; límites diferentes"
        elif unclear_cause:
            classification, reason = "PENDIENTE_REVISION", "Coincidencia temporal con causa reportada no clara"
        else:
            classification, reason = "REPORTADA_Y_DETECTADA", "Coincidencia temporal suficiente y trazable"
        item = _base_output(
            component_reported, component_electrical, classification, reason, version, component_relations
        )
        item["noDataOverlapMinutes"] = round(no_data, 3)
        output.append(item)

    tolerance = float(config["matchingToleranceMinutes"])
    for reported in reported_events:
        if reported["eventId"] in used_reported:
            continue
        window = _reported_window(reported)
        if window is None or reported.get("status") != "VALID":
            classification = "PENDIENTE_REVISION"
            reason = "Parada reportada sin intervalo temporal completo y verificable"
            no_data = 0.0
        else:
            no_data = _no_data_overlap(window, no_data_segments, tolerance)
            if no_data > 0:
                classification = "SIN_DATOS"
                reason = "La ventana reportada sin coincidencia está afectada por NO_DATA"
            else:
                classification = "SOLO_REPORTADA"
                reason = "Parada reportada completa sin evento eléctrico candidato"
        item = _base_output([reported], [], classification, reason, version)
        item["noDataOverlapMinutes"] = round(no_data, 3)
        output.append(item)

    for electrical in electrical_events:
        if electrical["eventId"] in used_electrical:
            continue
        classification = (
            "PENDIENTE_REVISION"
            if electrical.get("quality") == "INCONSISTENT_SIGNAL" else "SOLO_DETECTADA"
        )
        reason = (
            "Evento eléctrico con señal inconsistente; no es una falla confirmada"
            if classification == "PENDIENTE_REVISION"
            else "Evento eléctrico sin parada reportada coincidente; no es una falla confirmada"
        )
        item = _base_output([], [electrical], classification, reason, version)
        item["noDataOverlapMinutes"] = 0.0
        output.append(item)

    output.sort(key=lambda item: (
        item["startReported"] or item["startElectrical"] or "",
        item["reconciliationId"],
    ))
    counts = Counter(item["classification"] for item in output)
    reported_minutes = sum(
        event["durationMinutes"] for event in reported_events if event.get("durationMinutes") is not None
    )
    electrical_minutes = sum(event["durationMinutes"] for event in electrical_events)
    reconciled = [item for item in output if item["classification"] == "REPORTADA_Y_DETECTADA"]
    return {
        "datasetType": config.get("dataset", {}).get("type", "DATOS_HISTORICOS_DE_PRUEBA"),
        "effectiveRange": {
            "startUtc": int(effective_start_utc),
            "endUtc": int(effective_end_utc),
            "startLocal": start_local.isoformat(),
            "endLocal": end_local.isoformat(),
        },
        "config": config,
        "events": output,
        "summary": {
            "totalReportadas": len(reported_events),
            "totalDetectadas": len(electrical_events),
            "totalReportadasYDetectadas": counts["REPORTADA_Y_DETECTADA"],
            "totalSoloReportadas": counts["SOLO_REPORTADA"],
            "totalSoloDetectadas": counts["SOLO_DETECTADA"],
            "totalSinDatos": counts["SIN_DATOS"],
            "totalPendientesRevision": counts["PENDIENTE_REVISION"],
            "minutosReportados": round(reported_minutes, 3),
            "minutosElectricos": round(electrical_minutes, 3),
            "minutosConciliados": round(sum(item["overlapMinutes"] or 0 for item in reconciled), 3),
            "diferenciaTotalMinutos": round(sum(item["durationDifferenceMinutes"] or 0 for item in reconciled), 3),
        },
        "warning": (
            "Los eventos eléctricos no son fallas confirmadas. La conciliación es preliminar "
            "y requiere revisión cuando la evidencia sea incompleta."
        ),
    }


def empty_reconciliation_result(config=None):
    config = config or load_reconciliation_config()
    return {
        "datasetType": config.get("dataset", {}).get("type", "DATOS_HISTORICOS_DE_PRUEBA"),
        "effectiveRange": None,
        "config": config,
        "events": [],
        "summary": {
            "totalReportadas": 0,
            "totalDetectadas": 0,
            "totalReportadasYDetectadas": 0,
            "totalSoloReportadas": 0,
            "totalSoloDetectadas": 0,
            "totalSinDatos": 0,
            "totalPendientesRevision": 0,
            "minutosReportados": 0,
            "minutosElectricos": 0,
            "minutosConciliados": 0,
            "diferenciaTotalMinutos": 0,
        },
        "warning": (
            "Los eventos eléctricos no son fallas confirmadas. La conciliación es preliminar "
            "y requiere revisión cuando la evidencia sea incompleta."
        ),
    }
