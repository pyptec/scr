import unittest

from db.aoki_energy import load_energy_config, reconstruct_aoki_energy


CONFIG = load_energy_config()


def signals(points):
    rows = []
    identifier = 1
    for timestamp, values in points:
        for unit_id, value in values.items():
            rows.append({"id": identifier, "timestamp_utc": timestamp, "unit_id": unit_id, "valor": value})
            identifier += 1
    return rows


class AokiEnergyReconstructionTests(unittest.TestCase):
    def interval(self, points):
        return reconstruct_aoki_energy(signals(points), CONFIG)["intervals"][0]

    def test_normal_accumulator_delta_is_measured(self):
        item = self.interval([(0, {100: 100, 61: 10}), (3600, {100: 110, 61: 10})])
        self.assertEqual(item["energyKWh"], 10)
        self.assertEqual(item["source"], "ACCUMULATOR_DELTA")
        self.assertEqual(item["quality"], "MEASURED")

    def test_accumulator_reset_is_not_absolute_and_falls_back_to_power(self):
        item = self.interval([(0, {100: 100, 61: 10}), (600, {100: 0, 61: 10})])
        self.assertEqual(item["source"], "POWER_TRAPEZOIDAL")
        self.assertEqual(item["reason"], "ACCUMULATOR_RESET")
        self.assertAlmostEqual(item["energyKWh"], 10 / 6, places=5)

    def test_physically_impossible_jump_uses_valid_power(self):
        item = self.interval([(0, {100: 0, 61: 20}), (600, {100: 1000, 61: 20})])
        self.assertEqual(item["source"], "POWER_TRAPEZOIDAL")
        self.assertEqual(item["reason"], "PHYSICALLY_IMPOSSIBLE_JUMP")

    def test_trapezoidal_power_reconstruction(self):
        item = self.interval([(0, {61: 10}), (600, {61: 20})])
        self.assertEqual(item["source"], "POWER_TRAPEZOIDAL")
        self.assertEqual(item["quality"], "RECONSTRUCTED_HIGH")
        self.assertEqual(item["energyKWh"], 2.5)

    def test_rectangular_power_with_one_endpoint(self):
        item = self.interval([(0, {61: 12}), (600, {54: 0})])
        self.assertEqual(item["source"], "POWER_RECTANGULAR")
        self.assertEqual(item["quality"], "RECONSTRUCTED_MEDIUM")
        self.assertEqual(item["energyKWh"], 2)

    def test_missing_accumulator_uses_power(self):
        item = self.interval([(0, {61: 10}), (600, {61: 10})])
        self.assertEqual(item["reason"], "ACCUMULATOR_UNAVAILABLE")

    def test_missing_power_keeps_valid_accumulator(self):
        item = self.interval([(0, {100: 10}), (600, {100: 11})])
        self.assertEqual(item["source"], "ACCUMULATOR_DELTA")
        self.assertEqual(item["energyKWh"], 1)

    def test_both_sources_invalid_remain_no_data(self):
        item = self.interval([(0, {100: "x", 61: "x"}), (600, {100: None, 61: None})])
        self.assertEqual(item["source"], "NO_DATA")
        self.assertIsNone(item["energyKWh"])

    def test_gap_total_can_be_recovered_only_by_accumulator(self):
        item = self.interval([(0, {100: 10}), (3600, {100: 20})])
        self.assertEqual(item["source"], "ACCUMULATOR_DELTA")
        self.assertEqual(item["reason"], "AGGREGATED_GAP_ENERGY")
        self.assertFalse(item["stateDataAvailable"])

    def test_gap_without_accumulator_is_not_integrated_from_endpoints(self):
        item = self.interval([(0, {61: 10}), (3600, {61: 10})])
        self.assertEqual(item["source"], "NO_DATA")
        self.assertEqual(item["reason"], "INSUFFICIENT_VALID_SOURCES")

    def test_cross_validation_rejects_inconsistent_accumulator(self):
        item = self.interval([(0, {100: 0, 61: 10}), (600, {100: 5, 61: 10})])
        self.assertEqual(item["source"], "POWER_TRAPEZOIDAL")
        self.assertEqual(item["reason"], "INCONSISTENT_ENERGY_SOURCE")
        self.assertGreater(item["crossValidationErrorPct"], 25)

    def test_traceability_contains_source_ids_and_version(self):
        item = self.interval([(0, {100: 10}), (600, {100: 11})])
        self.assertIn("sourceId", item["trace"]["start"][100])
        self.assertEqual(item["trace"]["configurationVersion"], CONFIG["version"])

    def test_current_is_not_converted_without_model(self):
        result = reconstruct_aoki_energy(signals([(0, {54: 60}), (600, {54: 60})]), CONFIG)
        self.assertFalse(result["currentModelUsed"])
        self.assertEqual(result["intervals"][0]["source"], "NO_DATA")

    def test_daily_summary_preserves_unknown_unrecoverable_energy(self):
        result = reconstruct_aoki_energy(signals([(0, {54: None}), (600, {54: None})]), CONFIG)
        self.assertIsNone(result["daily"][0]["unrecoverableEnergyKWh"])
        self.assertEqual(result["daily"][0]["noDataIntervals"], 1)

    def test_range_boundaries_without_measurements_remain_no_data(self):
        result = reconstruct_aoki_energy(
            signals([(100, {100: 10}), (700, {100: 11})]), CONFIG,
            start_utc=0, end_utc=800,
        )
        self.assertEqual(result["intervals"][0]["reason"], "RANGE_START_WITHOUT_SOURCE")
        self.assertEqual(result["intervals"][-1]["reason"], "RANGE_END_WITHOUT_SOURCE")
        self.assertTrue(all(i["source"] == "NO_DATA" for i in (result["intervals"][0], result["intervals"][-1])))


if __name__ == "__main__":
    unittest.main()
