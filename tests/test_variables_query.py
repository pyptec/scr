import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class VariablesQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (ROOT / "api" / "app.py").read_text(encoding="utf-8")
        cls.endpoint = source.split('def api_variables():', 1)[1].split(
            '@app.route("/api/ultimos")', 1
        )[0]

    def test_does_not_restrict_variables_to_three_device_ids(self):
        self.assertNotIn("md.device_id IN ('24','25','26')", self.endpoint)

    def test_labels_records_without_device_as_gateway_variables(self):
        self.assertIn("Variables del gateway", self.endpoint)
        self.assertIn("md.source_type", self.endpoint)


if __name__ == "__main__":
    unittest.main()
