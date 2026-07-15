import unittest
from datetime import datetime, timezone

from db.aoki_states import classify_aoki_states, load_thresholds, preprocess_measurements


CONFIG = load_thresholds()


def rows(samples):
    result = []
    identifier = 1
    for timestamp, current, power in samples:
        result.append({"id": identifier, "timestamp_utc": timestamp, "unit_id": 54, "valor": current})
        identifier += 1
        if power is not ...:
            result.append({"id": identifier, "timestamp_utc": timestamp, "unit_id": 61, "valor": power})
            identifier += 1
    return result


class AokiStateTests(unittest.TestCase):
    def classify(self, samples, start=0, end=None):
        end = end if end is not None else samples[-1][0] + 600
        return classify_aoki_states(rows(samples), start, end, CONFIG)

    def test_threshold_off(self):
        self.assertEqual(self.classify([(0, 27.37, 5), (600, 27.37, 5)])["segments"][0]["state"], "OFF")

    def test_threshold_idle_boundaries(self):
        result = self.classify([(0, 27.38, 20), (600, 54.57, 20)])
        self.assertEqual(result["segments"][0]["state"], "IDLE")

    def test_threshold_productive(self):
        self.assertEqual(self.classify([(0, 54.58, 40), (600, 60, 40)])["segments"][0]["state"], "PRODUCTIVE")

    def test_isolated_sample_does_not_change_state(self):
        result = self.classify([(0, 60, 40), (600, 5, 2), (1200, 60, 40)], end=1800)
        self.assertEqual({s["state"] for s in result["segments"]}, {"PRODUCTIVE"})

    def test_two_consecutive_samples_confirm_change(self):
        result = self.classify([(0, 60, 40), (600, 5, 2), (1200, 5, 2)], end=1800)
        self.assertEqual([s["state"] for s in result["segments"]], ["PRODUCTIVE", "OFF"])

    def test_twenty_minutes_confirm_change(self):
        result = self.classify([(0, 60, 40), (600, 5, 2)], end=1800)
        # El último intervalo mide exactamente veinte minutos y confirma retroactivamente.
        self.assertEqual(result["segments"][-1]["state"], "OFF")

    def test_gap_is_no_data_not_off(self):
        result = self.classify([(0, 60, 40), (1801, 5, 2)], end=2401)
        self.assertEqual(result["segments"][0]["state"], "NO_DATA")

    def test_duplicate_exact_is_removed(self):
        source = rows([(0, 60, 40), (600, 60, 40)])
        source.append(dict(source[0]))
        result = preprocess_measurements(source, CONFIG)
        self.assertEqual(result["quality"]["exactDuplicatesRemoved"], 1)

    def test_out_of_order_is_marked_and_sorted(self):
        source = rows([(600, 60, 40), (0, 60, 40)])
        result = preprocess_measurements(source, CONFIG)
        self.assertGreater(result["quality"]["outOfOrderIntervals"], 0)
        self.assertEqual(result["samples"][0]["timestampUtc"], 0)

    def test_invalid_current_becomes_no_data(self):
        result = self.classify([(0, "", 2), (600, None, 2)], end=1200)
        self.assertEqual(result["segments"][0]["state"], "NO_DATA")

    def test_segment_crossing_six_is_split(self):
        # 2026-05-01 10:50 UTC = 05:50 Colombia.
        start = int(datetime(2026, 5, 1, 10, 50, tzinfo=timezone.utc).timestamp())
        result = self.classify([(start, 60, 40), (start + 600, 60, 40)], start=start, end=start + 1200)
        self.assertEqual(len(result["daily"]), 2)
        self.assertNotEqual(result["daily"][0]["productionDate"], result["daily"][1]["productionDate"])

    def test_partial_period_sums_to_actual_duration(self):
        result = self.classify([(0, 60, 40), (600, 60, 40)], start=0, end=900)
        self.assertAlmostEqual(sum(d["scheduledHours"] for d in result["daily"]), 0.25, places=4)

    def test_valid_current_without_power_is_partial_signal(self):
        result = self.classify([(0, 60, ...), (600, 60, ...)], end=1200)
        self.assertEqual(result["segments"][0]["quality"], "PARTIAL_SIGNAL")

    def test_zero_power_with_productive_current_is_inconsistent(self):
        result = self.classify([(0, 60, 0), (600, 60, 0)], end=1200)
        self.assertEqual(result["segments"][0]["quality"], "INCONSISTENT_SIGNAL")

    def test_daily_hours_sum_by_state(self):
        result = self.classify([(0, 60, 40), (600, 60, 40)], end=1200)
        day = result["daily"][0]
        total = day["productiveHours"] + day["idleHours"] + day["offHours"] + day["noDataHours"]
        self.assertAlmostEqual(total, day["scheduledHours"], places=3)
        self.assertAlmostEqual(day["knownDataHours"], day["scheduledHours"] - day["noDataHours"], places=3)
        self.assertEqual(day["balanceStatus"], "VALID")

    def test_period_summary_validates_partial_range(self):
        result = self.classify([(0, 60, 40), (600, 60, 40)], start=0, end=900)
        summary = result["periodSummary"]
        self.assertEqual(summary["scheduledHours"], 0.25)
        self.assertEqual(summary["balanceStatus"], "VALID")
        self.assertLessEqual(summary["balanceDifferenceSeconds"], summary["balanceToleranceSeconds"])

    def test_no_data_separates_equal_states(self):
        result = self.classify([(0, 60, 40), (1801, 60, 40)], end=2401)
        self.assertEqual([s["state"] for s in result["segments"]], ["NO_DATA", "PRODUCTIVE"])


if __name__ == "__main__":
    unittest.main()
