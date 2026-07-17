import copy
import unittest
from pathlib import Path

from db.aoki_alerts import (
    build_alert_contract,
    filter_alert_contract,
    find_alert,
    load_alert_rules,
)


START = 1777633200
END = START + 86400


def contracts():
    performance = {
        "ranges": {"requestedRange": {"startUtc": START, "endUtc": END}},
        "model": {"cv_rmse_pct": 3.64},
        "quality": {"thresholds": {
            "version": "quality-v1",
            "minimumEnergyCoveragePct": 98,
            "minimumStateCoveragePct": 98,
        }},
        "daily": [{
            "productionDate": "2026-05-01",
            "rangeStartUtc": "2026-05-01T11:00:00+00:00",
            "rangeEndUtc": "2026-05-02T11:00:00+00:00",
            "evaluationStatus": "VALID_PRELIMINARY",
            "performanceClassification": "UNFAVORABLE_PRELIMINARY",
            "deviationPct": 5,
            "energyCoveragePct": 99,
            "stateCoveragePct": 97,
            "qualityFlags": ["LOW_STATE_COVERAGE"],
            "modelVersion": "baseline-v1",
        }],
    }
    base100 = {"daily": [{
        "productionDate": "2026-05-01",
        "base100Index": 105,
        "base100Classification": "UNFAVORABLE_PRELIMINARY",
        "performanceQualityVersion": "quality-v1",
    }]}
    phase2 = {
        "electricalStates": {
            "thresholds": {
                "version": "states-v1",
                "maximumGapMinutes": 20,
                "minimumPersistenceMinutes": 20,
            },
            "segments": [{
                "state": "NO_DATA",
                "startUtc": "2026-05-01T12:00:00+00:00",
                "endUtc": "2026-05-01T12:30:00+00:00",
                "durationSeconds": 1800,
                "productionDate": "2026-05-01",
            }],
        },
        "electricalEvents": {"events": [{
            "eventId": "electrical-1",
            "startUtc": "2026-05-01T13:00:00+00:00",
            "endUtc": "2026-05-01T14:00:00+00:00",
            "durationMinutes": 60,
            "dominantState": "IDLE",
            "quality": "VALID_STATE",
            "thresholdVersion": "states-v1",
        }]},
        "reconciliation": {"events": [{
            "reconciliationId": "reconciliation-1",
            "classification": "SOLO_DETECTADA",
            "electricalEventIds": ["electrical-1"],
            "reportedEventIds": [],
            "reconciliationVersion": "reconciliation-v1",
        }]},
    }
    maintenance = {
        "events": [{
            "maintenanceEventId": "maintenance-1",
            "taxonomyVersion": "taxonomy-v1",
            "suggestedClassification": "CORRECTIVE_FAILURE",
            "validatedClassification": None,
            "validationStatus": "PENDING_HUMAN_REVIEW",
            "evidenceStatus": "CURRENT",
            "electricalStart": "2026-05-01T13:00:00+00:00",
            "electricalEnd": "2026-05-01T14:00:00+00:00",
            "sourceClassification": "SOLO_DETECTADA",
            "reconciliationId": "reconciliation-1",
        }],
    }
    reliability = {
        "ranges": {"requestedRange": {"startUtc": START, "endUtc": END}},
        "status": "NO_HUMAN_VALIDATIONS",
        "readinessStatus": "NO_HUMAN_VALIDATIONS",
        "quality": {"flags": []},
        "methodology": {"reliabilityMethodVersion": "reliability-v1"},
    }
    return phase2, performance, base100, maintenance, reliability


class AokiAlertTests(unittest.TestCase):
    def build(self):
        return build_alert_contract(*contracts())

    def test_deduplicates_energy_and_solo_detectada_correlations(self):
        result = self.build()
        self.assertEqual(result["summary"]["deduplicatedAlarmCount"], 6)
        self.assertEqual(
            result["summary"]["rawRuleMatches"]["UNREPORTED_ELECTRICAL_EVENT"], 1
        )
        energy = next(
            alarm for alarm in result["alarms"]
            if alarm["alarmType"] == "ENERGY_OVERCONSUMPTION"
        )
        self.assertTrue(energy["evidence"]["base100Correlated"])
        self.assertEqual(energy["evidence"]["base100Index"], 105)
        self.assertNotIn(
            "BASE100_HIGH", result["summary"]["rawRuleMatches"]
        )
        self.assertEqual(
            result["summary"]["emittedByType"]["UNREPORTED_ELECTRICAL_EVENT"], 0
        )

    def test_alarm_never_confirms_a_failure(self):
        for alarm in self.build()["alarms"]:
            self.assertFalse(alarm["isConfirmedFailure"])
        electrical = next(
            alarm for alarm in self.build()["alarms"]
            if alarm["alarmType"] == "ELECTRICAL_IDLE_EVENT"
        )
        self.assertTrue(electrical["requiresHumanReview"])
        self.assertEqual(electrical["severity"], "WARNING")

    def test_no_data_is_not_zero_and_uses_strict_threshold(self):
        result = self.build()
        no_data = next(
            alarm for alarm in result["alarms"]
            if alarm["alarmType"] == "NO_DATA_PROLONGED"
        )
        self.assertEqual(no_data["observedValue"], 30)
        self.assertEqual(no_data["thresholdValue"], 20)
        changed = list(contracts())
        changed[0]["electricalStates"]["segments"][0]["durationSeconds"] = 1200
        result = build_alert_contract(*changed)
        self.assertNotIn(
            "NO_DATA_PROLONGED",
            [alarm["alarmType"] for alarm in result["alarms"]],
        )

    def test_insufficient_energy_inputs_create_no_energy_alarm(self):
        values = list(contracts())
        values[1]["daily"][0]["evaluationStatus"] = "INSUFFICIENT_INPUTS"
        values[1]["daily"][0]["performanceClassification"] = "INSUFFICIENT_DATA"
        values[1]["daily"][0]["qualityFlags"] = []
        result = build_alert_contract(*values)
        types = [alarm["alarmType"] for alarm in result["alarms"]]
        self.assertNotIn("ENERGY_OVERCONSUMPTION", types)
        self.assertNotIn("ENERGY_FAVORABLE_DEVIATION", types)

    def test_favorable_is_informational_not_demonstrated_savings(self):
        values = list(contracts())
        day = values[1]["daily"][0]
        day["performanceClassification"] = "FAVORABLE_PRELIMINARY"
        day["deviationPct"] = -5
        values[2]["daily"][0]["base100Classification"] = "FAVORABLE_PRELIMINARY"
        values[2]["daily"][0]["base100Index"] = 95
        alarm = next(
            item for item in build_alert_contract(*values)["alarms"]
            if item["alarmType"] == "ENERGY_FAVORABLE_DEVIATION"
        )
        self.assertEqual(alarm["severity"], "INFO")
        self.assertIn("no demuestra ahorro", alarm["description"])
        self.assertEqual(alarm["evidence"]["base100Index"], 95)

    def test_stale_evidence_replaces_duplicate_review_alarm(self):
        values = list(contracts())
        values[3]["events"][0]["evidenceStatus"] = "STALE_SOURCE_EVIDENCE"
        result = build_alert_contract(*values)
        maintenance = [
            item for item in result["alarms"]
            if item["sourceModule"] == "MAINTENANCE"
        ]
        self.assertEqual(len(maintenance), 1)
        self.assertEqual(
            maintenance[0]["alarmType"], "STALE_MAINTENANCE_EVIDENCE"
        )
        self.assertIn(
            "MAINTENANCE_REVIEW_REQUIRED",
            maintenance[0]["correlatedAlarmTypes"],
        )

    def test_valid_reliability_emits_no_unavailable_alarm(self):
        values = list(contracts())
        values[4]["status"] = "VALID"
        result = build_alert_contract(*values)
        self.assertNotIn(
            "RELIABILITY_KPI_UNAVAILABLE",
            [item["alarmType"] for item in result["alarms"]],
        )

    def test_reported_only_rule_is_emitted(self):
        values = list(contracts())
        values[0]["reconciliation"]["events"].append({
            "reconciliationId": "reported-only",
            "classification": "SOLO_REPORTADA",
            "reportedEventIds": ["reported-1"],
            "electricalEventIds": [],
            "startReported": "2026-05-01T15:00:00+00:00",
            "endReported": "2026-05-01T15:30:00+00:00",
            "reportedDurationMinutes": 30,
            "reconciliationVersion": "reconciliation-v1",
        })
        result = build_alert_contract(*values)
        self.assertIn(
            "REPORTED_STOP_NOT_DETECTED",
            [item["alarmType"] for item in result["alarms"]],
        )

    def test_contract_is_deterministic_and_does_not_mutate_sources(self):
        source = contracts()
        before = copy.deepcopy(source)
        first = build_alert_contract(*source)
        second = build_alert_contract(*source)
        self.assertEqual(first, second)
        self.assertEqual(source, before)
        self.assertEqual(
            [item["alarmId"] for item in first["alarms"]],
            [item["alarmId"] for item in second["alarms"]],
        )

    def test_filter_and_find_preserve_read_only_contract(self):
        contract = self.build()
        filtered = filter_alert_contract(contract, severity="WARNING")
        self.assertTrue(filtered["alarms"])
        self.assertTrue(all(
            item["severity"] == "WARNING" for item in filtered["alarms"]
        ))
        alarm = contract["alarms"][0]
        self.assertEqual(find_alert(contract, alarm["alarmId"]), alarm)
        self.assertEqual(contract["summary"]["deduplicatedAlarmCount"], 6)

    def test_configuration_lists_only_approved_active_rules(self):
        config = load_alert_rules()
        self.assertEqual(config["version"], "aoki-alert-rules-v1-2026-07")
        self.assertEqual(len(config["activeRules"]), 12)
        self.assertIn("CUSUM_UNFAVORABLE_ACCUMULATION", config["disabledRules"])
        self.assertFalse(config["persistence"])
        self.assertFalse(config["externalNotifications"])

    def test_api_exposes_only_the_three_approved_get_routes(self):
        app_source = (
            Path(__file__).resolve().parents[1] / "api" / "app.py"
        ).read_text(encoding="utf-8")
        self.assertIn('@app.route("/api/alarmas")', app_source)
        self.assertIn('@app.route("/api/alarmas/<alarm_id>")', app_source)
        self.assertIn('@app.route("/api/alarmas/reglas")', app_source)
        self.assertNotIn(
            '@app.route("/api/alarmas", methods=["POST"])', app_source
        )
        self.assertNotIn("/ack", app_source)
        self.assertNotIn("/resolve", app_source)
        self.assertNotIn("/suppress", app_source)


if __name__ == "__main__":
    unittest.main()
