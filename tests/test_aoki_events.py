import unittest

from db.aoki_events import detect_aoki_downtime_events


THRESHOLDS = {
    "minimumConsecutiveSamples": 2,
    "minimumPersistenceMinutes": 20,
    "version": "test-v1",
}


def segment(state, start, end, samples=2, current=45, power=30, day="2026-05-01"):
    return {
        "state": state,
        "startUtc": f"2026-05-01T{start}:00+00:00",
        "endUtc": f"2026-05-01T{end}:00+00:00",
        "startLocal": f"2026-05-01T{start}:00-05:00",
        "endLocal": f"2026-05-01T{end}:00-05:00",
        "productionDate": day,
        "durationSeconds": 1200,
        "sampleCount": samples,
        "minimumCurrentA": current - 1 if current is not None else None,
        "averageCurrentA": current,
        "averagePowerKW": power,
    }


class AokiEventTests(unittest.TestCase):
    def detect(self, segments):
        return detect_aoki_downtime_events({"segments": segments, "thresholds": THRESHOLDS})

    def test_groups_consecutive_idle_and_off_as_one_event(self):
        result = self.detect([
            segment("IDLE", "10:00", "10:20", current=45),
            segment("OFF", "10:20", "10:40", current=8),
        ])
        self.assertEqual(result["summary"]["eventCount"], 1)
        self.assertEqual(result["events"][0]["durationMinutes"], 40)
        self.assertEqual(result["events"][0]["dominantState"], "OFF")

    def test_productive_and_no_data_break_events(self):
        result = self.detect([
            segment("IDLE", "10:00", "10:20"),
            segment("NO_DATA", "10:20", "10:40", current=None, power=None),
            segment("OFF", "10:40", "11:00", current=8),
            segment("PRODUCTIVE", "11:00", "11:20", current=63),
        ])
        self.assertEqual(result["summary"]["eventCount"], 2)

    def test_isolated_short_sample_is_not_an_event(self):
        item = segment("IDLE", "10:00", "10:10", samples=1)
        item["durationSeconds"] = 600
        result = self.detect([item])
        self.assertEqual(result["events"], [])

    def test_event_is_detected_but_not_classified_as_failure(self):
        event = self.detect([segment("OFF", "10:00", "10:20", current=8)])["events"][0]
        self.assertEqual(event["detectedBy"], "ME337_1")
        self.assertEqual(event["status"], "DETECTED")
        self.assertEqual(event["classification"], "SIN_CLASIFICAR")


if __name__ == "__main__":
    unittest.main()
