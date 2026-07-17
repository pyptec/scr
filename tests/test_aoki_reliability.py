import copy
import unittest

from db.aoki_reliability import build_reliability_contract


METHOD = {
    "version": "aoki-reliability-method-v1-2026-07",
    "failureDefinition": "HUMAN_VALIDATED_CORRECTIVE_FAILURE_CURRENT_EVIDENCE",
    "mtbfMethod": "TOTAL_VALIDATED_UPTIME_PER_CONFIRMED_FAILURE",
    "mttrMethod": "MEAN_VALIDATED_CORRECTIVE_DOWNTIME",
    "availabilityMethod": "VALIDATED_TIME_RATIO",
    "secondaryAvailabilityMethod": "MTBF_MTTR_RATIO",
    "operatingTimeSource": "VALIDATED_ASSET_UPTIME",
    "availabilityDifferenceTolerancePctPoints": 0.1,
}


def uptime(status="READY_FOR_RELIABILITY_KPI", operating=90, corrective=10,
           unresolved=0):
    return {
        "ranges": {
            "startUtc": 1000, "endUtc": 10000,
            "timezone": "America/Bogota",
            "startInclusive": True, "endExclusive": True,
        },
        "status": status,
        "summary": {
            "validatedAssetUptimeHours": operating,
            "validatedCorrectiveDowntimeHours": corrective,
            "unresolvedHours": unresolved,
        },
        "methodology": {
            "policyVersion": "aoki-uptime-policy-v1-2026-07",
        },
    }


def event(identifier="m1", start=2000, end=2600, downtime=10,
          classification="CORRECTIVE_FAILURE", validation="HUMAN_VALIDATED",
          evidence="CURRENT", suggested="CORRECTIVE_FAILURE"):
    return {
        "maintenanceEventId": identifier,
        "suggestedClassification": suggested,
        "validatedClassification": classification,
        "validationStatus": validation,
        "evidenceStatus": evidence,
        "validatedStartUtc": start,
        "validatedEndUtc": end,
        "validatedDowntimeMinutes": downtime,
        "electricalDurationMinutes": 9999,
        "reportedDurationMinutes": 8888,
        "actorId": "actor-1",
        "version": 1,
    }


def maintenance(events):
    return {
        "taxonomyVersion": "aoki-maintenance-taxonomy-v1-2026-07",
        "events": events,
    }


class AokiReliabilityTests(unittest.TestCase):
    def build(self, uptime_contract, events):
        return build_reliability_contract(
            uptime_contract, maintenance(events), METHOD
        )

    def assert_null_kpi(self, result):
        for key in (
            "mtbfHours", "mttrHours", "technicalAvailabilityPct",
            "technicalAvailabilityByTimePct", "availabilityDifferencePctPoints",
            "failureRatePer1000Hours",
        ):
            self.assertIsNone(result["summary"][key])

    def test_no_human_validations_returns_null_kpi(self):
        result = self.build(
            uptime("NO_HUMAN_VALIDATIONS", None, None, None),
            [event(validation="PENDING_HUMAN_REVIEW", classification=None)],
        )
        self.assertEqual(result["status"], "NO_HUMAN_VALIDATIONS")
        self.assert_null_kpi(result)

    def test_suggestions_and_rejections_are_not_failures(self):
        result = self.build(uptime(), [
            event(validation="PENDING_HUMAN_REVIEW", classification=None),
            event("m2", validation="HUMAN_REJECTED"),
        ])
        self.assertEqual(result["status"], "INSUFFICIENT_CONFIRMED_FAILURES")
        self.assertEqual(result["summary"]["confirmedFailureCount"], 0)
        self.assert_null_kpi(result)

    def test_ready_single_failure_calculates_only_authorized_formulas(self):
        result = self.build(uptime(), [event()])
        summary = result["summary"]
        self.assertEqual(result["status"], "VALID")
        self.assertEqual(summary["mtbfHours"], 90)
        self.assertEqual(summary["mttrHours"], 10)
        self.assertEqual(summary["technicalAvailabilityByTimePct"], 90)
        self.assertEqual(summary["technicalAvailabilityPct"], 90)
        self.assertAlmostEqual(summary["failureRatePer1000Hours"], 11.111111)
        self.assertIn("SINGLE_FAILURE_ESTIMATE", result["quality"]["flags"])

    def test_multiple_failures_use_uptime_and_human_downtime(self):
        result = self.build(
            uptime(operating=180, corrective=20),
            [event("m1", 2000, 2600, 10), event("m2", 4000, 4600, 10)],
        )
        self.assertEqual(result["summary"]["mtbfHours"], 90)
        self.assertEqual(result["summary"]["mttrHours"], 10)
        self.assertFalse(result["quality"]["singleFailureEstimate"])

    def test_right_censored_counts_mtbf_but_not_mttr(self):
        result = self.build(
            uptime(),
            [event(end=None, downtime=None)],
        )
        trace = result["events"][0]
        self.assertEqual(trace["censoringStatus"], "RIGHT_CENSORED")
        self.assertTrue(trace["includedInMtbf"])
        self.assertFalse(trace["includedInMttr"])
        self.assertEqual(result["status"], "INSUFFICIENT_REPAIR_TIME_DATA")
        self.assert_null_kpi(result)

    def test_left_censored_and_start_at_end_are_excluded(self):
        result = self.build(uptime(), [
            event("left", start=900, end=1200, downtime=5),
            event("end", start=10000, end=10100, downtime=2),
        ])
        self.assertEqual(
            [item["censoringStatus"] for item in result["events"]],
            ["LEFT_CENSORED", "OUTSIDE_RANGE"],
        )
        self.assertEqual(result["summary"]["confirmedFailureCount"], 0)
        self.assert_null_kpi(result)

    def test_stale_evidence_never_enters_kpi(self):
        result = self.build(uptime(), [event(evidence="STALE_SOURCE_EVIDENCE")])
        self.assertEqual(result["summary"]["confirmedFailureCount"], 0)
        self.assertEqual(result["quality"]["staleEvidenceCount"], 1)
        self.assertIn("STALE_SOURCE_EVIDENCE", result["quality"]["flags"])
        self.assert_null_kpi(result)

    def test_unresolved_or_nonpositive_uptime_blocks_all_kpi(self):
        unresolved = self.build(uptime(unresolved=1), [event()])
        self.assertEqual(unresolved["status"], "UNRESOLVED_OPERATING_TIME")
        self.assert_null_kpi(unresolved)
        no_uptime = self.build(uptime(operating=0), [event()])
        self.assertEqual(no_uptime["status"], "INSUFFICIENT_OPERATING_TIME")
        self.assert_null_kpi(no_uptime)

    def test_method_mismatch_is_flagged_when_populations_differ(self):
        result = self.build(
            uptime(operating=90, corrective=10),
            [event("full"), event("right", 5000, None, None)],
        )
        # El readiness sintético declara suficiencia y hay una reparación completa.
        self.assertEqual(result["status"], "VALID")
        self.assertIn("AVAILABILITY_METHOD_MISMATCH", result["quality"]["flags"])
        self.assertNotEqual(
            result["summary"]["technicalAvailabilityPct"],
            result["summary"]["technicalAvailabilityByTimePct"],
        )

    def test_service_is_pure_and_does_not_use_forbidden_fields(self):
        up = uptime()
        source = maintenance([event()])
        original = copy.deepcopy((up, source))
        result = build_reliability_contract(up, source, METHOD)
        self.assertEqual((up, source), original)
        self.assertEqual(
            result["methodology"]["operatingTimeSource"],
            "VALIDATED_ASSET_UPTIME",
        )
        self.assertFalse(result["methodology"]["usesElectricalProductiveAsUptime"])
        self.assertFalse(result["methodology"]["assumes24HoursPerDay"])
        self.assertFalse(result["methodology"]["usesElectricalOrReportedDowntime"])
        self.assertEqual(result["summary"]["mttrHours"], 10)


if __name__ == "__main__":
    unittest.main()
