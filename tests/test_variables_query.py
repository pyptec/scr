import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class VariablesQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (ROOT / "api" / "app.py").read_text(encoding="utf-8")
        cls.source = source
        cls.endpoint = source.split('def api_variables():', 1)[1].split(
            '@app.route("/api/ultimos")', 1
        )[0]

    def test_does_not_restrict_variables_to_three_device_ids(self):
        self.assertNotIn("md.device_id IN ('24','25','26')", self.endpoint)

    def test_labels_records_without_device_as_gateway_variables(self):
        self.assertIn("Variables del gateway", self.endpoint)
        self.assertIn("md.source_type", self.endpoint)

    def test_historical_queries_use_exclusive_end(self):
        self.assertNotIn("timestamp_utc AS INTEGER) <= ?", self.source)
        self.assertNotIn("timestamp_utc AS INTEGER) BETWEEN ? AND ?", self.source)
        self.assertGreaterEqual(self.source.count("timestamp_utc AS INTEGER) < ?"), 5)

    def test_latest_values_can_be_filtered_inside_selected_range(self):
        endpoint = self.source.split("def api_ultimos():", 1)[1].split(
            '@app.route("/api/serie/<int:unit_id>")', 1
        )[0]
        self.assertIn('request.args.get("inicio", type=int)', endpoint)
        self.assertIn("HISTORICO_DENTRO_DEL_FILTRO", endpoint)
        self.assertIn("ROW_NUMBER() OVER", endpoint)
        self.assertIn("timestamp_utc AS INTEGER) < ?", endpoint)


if __name__ == "__main__":
    unittest.main()
