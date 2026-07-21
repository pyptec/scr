import copy
import unittest

from db.aoki_reported_reliability import (
    build_reported_reliability_contract,
    classify_reported_stop,
    load_reported_reliability_method,
)


RANGES = {
    "requestedRange": {"startUtc": 100, "endUtc": 200},
    "timezone": "America/Bogota", "startInclusive": True, "endExclusive": True,
}


def event(event_id, text, duration=60, status="VALID"):
    return {
        "eventId": event_id, "productionDate": "2026-05-01",
        "rawText": text, "matchedText": text, "durationMinutes": duration,
        "temporalSource": "EXPLICIT_DURATION", "status": status,
    }


class ReportedReliabilityTests(unittest.TestCase):
    def test_authorized_single_cause_classifications(self):
        cases = {
            "falla explícita del Booster": "CORRECTIVE_FAILURE",
            "mantenimiento preventivo e inspección preventiva": "PREVENTIVE_MAINTENANCE",
            "limpieza de filtros": "CLEANING",
            "cambio de molde": "CHANGEOVER",
            "falta de materia prima": "MATERIAL_SHORTAGE",
            "ajuste de calidad": "QUALITY_ADJUSTMENT",
            "parada programada": "PLANNED_STOP",
            "parada operacional": "OPERATIONAL_STOP",
        }
        for index, (text, expected) in enumerate(cases.items()):
            with self.subTest(text=text):
                result = classify_reported_stop(event(str(index), text))
                self.assertEqual(result["reportedStopSuggestedClassification"], expected)
                self.assertEqual(result["validationStatus"], "PENDING_HUMAN_REVIEW")
                self.assertIsNone(result["validatedClassification"])
                self.assertFalse(result["isConfirmedFailure"])

    def test_ambiguous_and_multiple_causes_are_undetermined(self):
        for text in (
            "temperatura de aceite", "mantenimiento del compresor",
            "limpieza de filtros y engrase general", "cambio de resortes",
        ):
            self.assertEqual(
                classify_reported_stop(event("x", text))[
                    "reportedStopSuggestedClassification"
                ],
                "UNDETERMINED",
            )

    def test_mttr_uses_only_valid_reported_corrective_durations(self):
        events = [
            event("a", "falla del Booster", 60),
            event("b", "daño de empaques", 120),
            event("c", "escape de agua", None, "PARTIAL"),
            event("d", "falla de válvula", -10),
        ]
        result = build_reported_reliability_contract(
            events, RANGES, actual_reported_operating_hours=300
        )
        self.assertEqual(result["summary"]["suggestedCorrectiveFailureCount"], 4)
        self.assertEqual(result["summary"]["suggestedCorrectiveFailuresWithDuration"], 2)
        self.assertEqual(result["summary"]["suggestedCorrectiveDowntimeHours"], 3)
        self.assertEqual(result["summary"]["reportedPreliminaryMttrHours"], 1.5)
        self.assertEqual(result["quality"]["excludedEventCount"], 2)

    def test_mtbf_and_availability_use_actual_reported_hours(self):
        result = build_reported_reliability_contract(
            [event("a", "falla del Booster", 60), event("b", "escape de agua", 60)],
            RANGES, actual_reported_operating_hours=198,
        )
        self.assertEqual(result["summary"]["reportedPreliminaryMtbfHours"], 99)
        self.assertEqual(result["summary"]["reportedPreliminaryAvailabilityPct"], 99)
        self.assertEqual(
            result["methodology"]["operatingTimeSource"],
            "ACTUAL_REPORTED_OPERATING_HOURS",
        )

    def test_scheduled_hours_are_explicitly_marked_as_estimated(self):
        result = build_reported_reliability_contract(
            [event("a", "falla del Booster", 60)], RANGES,
            scheduled_reported_hours=10,
        )
        self.assertEqual(result["summary"]["reportedOperatingHours"], 9)
        self.assertEqual(result["summary"]["reportedPreliminaryMtbfHours"], 9)
        self.assertEqual(result["summary"]["reportedPreliminaryAvailabilityPct"], 90)
        self.assertIn("ESTIMATED_REPORTED_OPERATING_TIME", result["quality"]["flags"])

    def test_no_operating_source_never_uses_calendar_or_electrical_time(self):
        result = build_reported_reliability_contract(
            [event("a", "falla del Booster", 60)], RANGES
        )
        self.assertEqual(result["status"], "INSUFFICIENT_REPORTED_OPERATING_TIME")
        self.assertIsNone(result["summary"]["reportedPreliminaryMtbfHours"])
        self.assertIsNone(result["summary"]["reportedPreliminaryAvailabilityPct"])
        self.assertFalse(result["methodology"]["usesElectricalProductiveHours"])
        self.assertFalse(result["methodology"]["usesElectricalKnownTime"])
        self.assertFalse(result["methodology"]["assumes24HoursPerDay"])

    def test_coverage_and_contract_labels_are_preliminary(self):
        source = [event("a", "falla del Booster"), event("b", "temperatura de aceite")]
        before = copy.deepcopy(source)
        result = build_reported_reliability_contract(
            source, RANGES, actual_reported_operating_hours=20
        )
        self.assertEqual(result["summary"]["classificationCoveragePct"], 50)
        self.assertEqual(result["status"], "LOW_CLASSIFICATION_COVERAGE")
        self.assertEqual(result["methodology"]["statusLabel"], "PRELIMINAR_REPORTADO")
        self.assertFalse(result["methodology"]["isTechnicalKpi"])
        self.assertTrue(result["methodology"]["isPreliminary"])
        self.assertTrue(result["methodology"]["requiresHumanValidation"])
        self.assertEqual(source, before)

    def test_electrical_and_validated_durations_are_never_inputs(self):
        source = event("a", "falla del Booster", None)
        source["electricalDurationMinutes"] = 600
        source["validatedDowntimeMinutes"] = 300
        result = build_reported_reliability_contract(
            [source], RANGES, actual_reported_operating_hours=20
        )
        self.assertEqual(result["summary"]["suggestedCorrectiveDowntimeHours"], 0)
        self.assertIsNone(result["summary"]["reportedPreliminaryMttrHours"])

    def test_method_configuration_is_nontechnical(self):
        method = load_reported_reliability_method()
        self.assertEqual(method["version"], "aoki-reported-reliability-v1-2026-07")
        self.assertFalse(method["isTechnicalKpi"])


if __name__ == "__main__":
    unittest.main()
