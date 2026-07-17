import copy
import unittest

from db.aoki_maintenance_events import (
    build_maintenance_events,
    maintenance_event_id,
)


def reconciliation_event(classification="PENDIENTE_REVISION", text=None,
                         reported_ids=None, electrical_ids=None, cause=None):
    return {
        "reconciliationId": "reconciliation-test",
        "classification": classification,
        "status": "PENDING_REVIEW",
        "reportedEventIds": reported_ids or [],
        "electricalEventIds": electrical_ids or [],
        "reportedEvents": [{"productionDate": "2026-05-01"}] if reported_ids else [],
        "electricalEvents": (
            [{"productionDates": ["2026-05-01"], "dominantState": "IDLE"}]
            if electrical_ids else []
        ),
        "rawText": text,
        "matchedText": text,
        "cause": cause,
        "startReported": None,
        "endReported": None,
        "startElectrical": None,
        "endElectrical": None,
        "reportedDurationMinutes": 40 if reported_ids else None,
        "electricalDurationMinutes": 40 if electrical_ids else None,
        "reason": "Prueba",
    }


def contract(events):
    return {
        "ranges": {"startInclusive": True, "endExclusive": True},
        "electricalStates": {"daily": [{"productionDate": "2026-05-01"}]},
        "reconciliation": {
            "events": events,
            "summary": {
                "totalReportadas": sum(bool(e["reportedEventIds"]) for e in events),
                "totalDetectadas": sum(bool(e["electricalEventIds"]) for e in events),
                "totalSoloDetectadas": sum(
                    e["classification"] == "SOLO_DETECTADA" for e in events
                ),
                "totalPendientesRevision": sum(
                    e["classification"] == "PENDIENTE_REVISION" for e in events
                ),
            },
        },
    }


class AokiMaintenanceEventsTests(unittest.TestCase):
    def build_one(self, event):
        return build_maintenance_events(contract([event]))["events"][0]

    def test_automatic_fields_are_never_human_validated(self):
        item = self.build_one(reconciliation_event(
            text="Se para por falla del Booster", reported_ids=["reported-1"]
        ))
        self.assertEqual(item["suggestedClassification"], "CORRECTIVE_FAILURE")
        self.assertIsNone(item["validatedClassification"])
        self.assertEqual(item["validationStatus"], "PENDING_HUMAN_REVIEW")
        self.assertFalse(item["confirmedFailure"])

    def test_idle_off_and_solo_detectada_are_undetermined_without_text(self):
        for state in ("IDLE", "OFF"):
            event = reconciliation_event(
                classification="SOLO_DETECTADA", electrical_ids=[f"electrical-{state}"]
            )
            event["electricalEvents"][0]["dominantState"] = state
            self.assertEqual(
                self.build_one(event)["suggestedClassification"], "UNDETERMINED"
            )

    def test_no_data_is_a_data_quality_event(self):
        item = self.build_one(reconciliation_event(
            classification="SIN_DATOS", reported_ids=["reported-no-data"]
        ))
        self.assertEqual(item["suggestedClassification"], "DATA_QUALITY_EVENT")

    def test_maintenance_without_damage_is_undetermined(self):
        item = self.build_one(reconciliation_event(
            text="Máquina parada por mantenimiento del compresor",
            reported_ids=["reported-maintenance"],
        ))
        self.assertEqual(item["suggestedClassification"], "UNDETERMINED")

    def test_corrective_evidence_only_creates_suggestion(self):
        texts = (
            "Falla en el Booster",
            "Daño de empaques",
            "Escape de agua",
            "El compresor no levanta presión y se cambia una pieza",
        )
        for index, text in enumerate(texts):
            item = self.build_one(reconciliation_event(
                text=text, reported_ids=[f"reported-{index}"]
            ))
            self.assertEqual(item["suggestedClassification"], "CORRECTIVE_FAILURE")
            self.assertFalse(item["confirmedFailure"])

    def test_conservative_operational_and_preventive_rules(self):
        cases = {
            "Falta de material": "MATERIAL_SHORTAGE",
            "Cambio de molde": "CHANGEOVER",
            "Ajuste de calidad": "QUALITY_ADJUSTMENT",
            "Parada programada": "PLANNED_STOP",
            "Limpieza de filtros": "CLEANING",
            "Engrase y lubricación general": "PREVENTIVE_MAINTENANCE",
        }
        for index, (text, expected) in enumerate(cases.items()):
            item = self.build_one(reconciliation_event(
                text=text, reported_ids=[f"reported-case-{index}"]
            ))
            self.assertEqual(item["suggestedClassification"], expected)

    def test_stable_id_uses_sorted_canonical_source_ids(self):
        first = reconciliation_event(
            reported_ids=["reported-b", "reported-a"],
            electrical_ids=["electrical-b", "electrical-a"],
        )
        second = copy.deepcopy(first)
        second["reportedEventIds"].reverse()
        second["electricalEventIds"].reverse()
        self.assertEqual(maintenance_event_id(first), maintenance_event_id(second))
        self.assertTrue(maintenance_event_id(first).startswith("maintenance-"))

    def test_taxonomy_version_is_not_part_of_identity(self):
        event = reconciliation_event(reported_ids=["reported-stable"])
        event["taxonomyVersion"] = "one"
        first = maintenance_event_id(event)
        event["taxonomyVersion"] = "two"
        self.assertEqual(first, maintenance_event_id(event))

    def test_matched_fragment_prevents_cross_event_cause_contamination(self):
        event = reconciliation_event(
            text="Se para para lubricación", reported_ids=["reported-fragment"]
        )
        event["rawText"] = (
            "Se para por escape de agua. Se para para lubricación."
        )
        item = self.build_one(event)
        self.assertEqual(
            item["suggestedClassification"], "PREVENTIVE_MAINTENANCE"
        )

    def test_builder_is_pure_and_reports_no_kpi(self):
        source = contract([reconciliation_event(
            classification="SOLO_DETECTADA", electrical_ids=["electrical-1"]
        )])
        original = copy.deepcopy(source)
        result = build_maintenance_events(source)
        self.assertEqual(source, original)
        self.assertEqual(result["summary"]["confirmedFailures"], 0)
        self.assertTrue(all(
            calculated is False
            for calculated in result["methodology"]["kpiCalculated"].values()
        ))
        self.assertFalse(
            result["methodology"]["humanValidationPersistenceImplemented"]
        )


if __name__ == "__main__":
    unittest.main()
