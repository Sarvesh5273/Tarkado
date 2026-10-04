import csv
import json
import tempfile
import unittest
from pathlib import Path

from engine.importers import CSV_FIELDS, load_policy, load_traces, parse_json
from engine.schemas import ValidationError


FIXTURES = Path(__file__).parent / "fixtures"


class ImporterTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="tarkado-test-")
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.records = [parse_json(line) for line in (FIXTURES / "synthetic.jsonl").read_text().splitlines()]

    def write_jsonl(self, records):
        path = self.path / "metadata.jsonl"
        path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
        return path

    def test_jsonl_loads_and_preserves_exact_costs(self):
        traces = load_traces(FIXTURES / "synthetic.jsonl")
        self.assertEqual(len(traces), 10)
        self.assertEqual(sum(trace.is_baseline for trace in traces), 7)
        self.assertEqual(str(traces[1].cost_usd), "0.005")

    def test_csv_and_jsonl_load_identically(self):
        path = self.path / "metadata.csv"
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for record in self.records:
                row = {key: record[key] for key in CSV_FIELDS[:11]}
                row["task_type"] = row["task_type"] or ""
                row["risk_tags"] = json.dumps(row["risk_tags"])
                row["required_tools"] = json.dumps(record["required_tools"])
                row["context_tokens"] = record["context_tokens"]
                row["is_baseline"] = str(record["is_baseline"]).lower()
                outcome = record["outcome"]
                row.update(
                    tests_passed="" if outcome["tests_passed"] is None else str(outcome["tests_passed"]).lower(),
                    developer_override=str(outcome["developer_override"]).lower(),
                    score=outcome["score"] or "",
                )
                writer.writerow(row)
        self.assertEqual(load_traces(path), load_traces(FIXTURES / "synthetic.jsonl"))

    def test_csv_rejects_wrong_column_order(self):
        path = self.path / "metadata.csv"
        path.write_text(",".join(reversed(CSV_FIELDS)) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValidationError, "canonical order"):
            load_traces(path)

    def test_csv_rejects_wrong_row_width(self):
        path = self.path / "metadata.csv"
        path.write_text(",".join(CSV_FIELDS) + "\nonly,three,columns\n", encoding="utf-8")
        with self.assertRaisesRegex(ValidationError, "number of columns"):
            load_traces(path)

    def test_json_rejects_duplicate_keys_and_nonfinite_numbers(self):
        for value in ('{"task_id":"a","task_id":"b"}', '{"cost_usd":NaN}', '{"cost_usd":Infinity}'):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    parse_json(value)

    def test_jsonl_error_has_a_line_number_not_raw_content(self):
        path = self.path / "metadata.jsonl"
        path.write_text("\n" + '{"prompt":"private content"}\n', encoding="utf-8")
        with self.assertRaises(ValidationError) as result:
            load_traces(path)
        self.assertIn("line 2", str(result.exception))
        self.assertNotIn("private content", str(result.exception))

    def test_dataset_rejects_duplicates_missing_baselines_and_inconsistent_metadata(self):
        duplicate_id = [dict(self.records[0]), dict(self.records[1])]
        duplicate_id[1]["trace_id"] = duplicate_id[0]["trace_id"]
        duplicate_pair = [dict(self.records[0]), dict(self.records[0], trace_id="other")]
        two_baselines = [dict(self.records[0]), dict(self.records[1], is_baseline=True)]
        no_baseline = [dict(self.records[1])]
        mismatch = [dict(self.records[0]), dict(self.records[1], risk_tags=["high"])]
        for records in (duplicate_id, duplicate_pair, two_baselines, no_baseline, mismatch, []):
            with self.subTest(records=len(records)):
                with self.assertRaises(ValidationError):
                    load_traces(self.write_jsonl(records))

    def test_local_policy_loads(self):
        self.assertEqual(load_policy(FIXTURES / "policy.json").policy_version, "synthetic-static-v1")

    def test_unsupported_file_type_is_rejected(self):
        path = self.path / "metadata.txt"
        path.write_text("", encoding="utf-8")
        with self.assertRaises(ValidationError):
            load_traces(path)


if __name__ == "__main__":
    unittest.main()
