import unittest

from db.aoki_validated_uptime import build_validated_uptime


POLICY = {
    "version": "aoki-uptime-policy-v1-2026-07",
    "electricalProductiveUse": "EVIDENCE_ONLY",
}


def event(status="PENDING_HUMAN_REVIEW", confirmed=False, start=None, end=None):
    return {
        "validationStatus": status,
        "confirmedFailure": confirmed,
        "validatedStartUtc": start,
        "validatedEndUtc": end,
        "validatedDowntimeMinutes": (
            (end - start) / 60 if start is not None and end is not None else None
        ),
        "evidenceStatus": "CURRENT",
    }


def window(identifier, start, end, kind="SCHEDULED_OPERATION"):
    return {
        "windowId": identifier, "startUtc": start, "endUtc": end,
        "windowType": kind, "status": "HUMAN_VALIDATED",
    }


class ValidatedUptimeTests(unittest.TestCase):
    def test_all_readiness_states_are_producible(self):
        no_human = build_validated_uptime(
            0, 3600, [], [], policy=POLICY
        )
        self.assertEqual(no_human["status"], "NO_HUMAN_VALIDATIONS")

        human = [event("HUMAN_REJECTED")]
        no_windows = build_validated_uptime(
            0, 3600, [], human, policy=POLICY
        )
        self.assertEqual(no_windows["status"], "INSUFFICIENT_OPERATING_WINDOWS")

        scheduled = [window("s1", 0, 3600)]
        no_times = build_validated_uptime(
            0, 3600, scheduled, human, policy=POLICY
        )
        self.assertEqual(no_times["status"], "INSUFFICIENT_CORRECTIVE_TIMES")

        confirmed = [event("HUMAN_VALIDATED", True, 600, 1200)]
        ready = build_validated_uptime(
            0, 3600, scheduled, confirmed, policy=POLICY
        )
        self.assertEqual(ready["status"], "READY_FOR_RELIABILITY_KPI")

    def test_uptime_uses_validated_windows_and_interval_union(self):
        result = build_validated_uptime(
            0, 7200,
            [
                window("s1", 0, 7200),
                window("p1", 1800, 2400, "PLANNED_STOP"),
            ],
            [event("HUMAN_VALIDATED", True, 3600, 4200)],
            policy=POLICY,
        )
        self.assertEqual(result["summary"]["validatedAssetUptimeHours"], 1.666667)
        self.assertEqual(
            result["summary"]["validatedCorrectiveDowntimeHours"], 0.166667
        )

    def test_no_data_is_unresolved_and_productive_is_never_an_input(self):
        result = build_validated_uptime(
            0, 3600, [window("s1", 0, 3600)],
            [event("HUMAN_VALIDATED", True, 600, 1200)],
            [{"state": "NO_DATA", "startEpoch": 1800, "endEpoch": 2400}],
            POLICY,
        )
        self.assertEqual(result["status"], "INSUFFICIENT_OPERATING_WINDOWS")
        self.assertEqual(result["summary"]["excludedNoDataHours"], 0.166667)
        self.assertEqual(
            result["methodology"]["electricalProductiveUse"], "EVIDENCE_ONLY"
        )
        self.assertFalse(result["methodology"]["assumes24HoursPerDay"])
        self.assertFalse(result["methodology"]["calculatesMtbf"])
        self.assertNotIn("productiveHours", str(result))

    def test_range_is_start_inclusive_end_exclusive(self):
        result = build_validated_uptime(
            100, 200, [window("s1", 0, 300)],
            [event("HUMAN_VALIDATED", True, 200, 250)],
            policy=POLICY,
        )
        self.assertEqual(result["summary"]["validatedCorrectiveDowntimeHours"], 0)
        self.assertTrue(result["ranges"]["endExclusive"])


if __name__ == "__main__":
    unittest.main()
