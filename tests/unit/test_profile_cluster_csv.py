"""Offline contract tests; no production data, services or NPU dependencies."""
import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "profile_cluster_csv", ROOT / "scripts/collect/profile_cluster_csv.py")
PROFILE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROFILE)


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, rows, headers=PROFILE.FIELDS):
        path = self.root / "requests.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)
        return path

    @staticmethod
    def row(rid="a", start="2026-09-24 07:00:00", cluster="one",
            prompt=100, total=110, cached=50, ttft=1000, tpot=20):
        return [cluster, rid, "tenant", start, prompt, total, cached, ttft, tpot]

    def args(self, path, *extra):
        return PROFILE.parser().parse_args(
            ["--input", str(path), "--output-dir", str(self.root / "out"),
             "--ttft-unit", "ms", "--tpot-unit", "ms", *extra])

    def test_end_to_end_tokens_units_empty_windows_and_utc(self):
        path = self.write([
            self.row(),
            self.row("b", "2026-09-24 07:00:02", ttft=3000, cached=0),
        ])
        before = PROFILE.digest_file(path)
        result = PROFILE.analyze(self.args(
            path, "--window-start", "2026-09-24T07:00:00Z",
            "--window-end", "2026-09-24T07:00:04Z"))
        self.assertEqual(result["overall"]["output_tokens_sum"], 20)
        self.assertEqual(result["overall"]["uncached_tokens_sum"], 150)
        self.assertAlmostEqual(result["overall"]["ttft_s_p90"], 2.8)
        self.assertEqual(result["overall"]["tpot_ms_p90"], 20)
        self.assertEqual(result["window_overview"][0]["zero_window_fraction"], .5)
        self.assertEqual(before, PROFILE.digest_file(path))
        saved = json.loads((self.root / "out/summary.json").read_text())
        self.assertEqual(saved["metadata"]["window_start_utc"], "2026-09-24T07:00:00+00:00")
        self.assertTrue((self.root / "out/CLUSTER_FLOW_PROFILE_REPORT.md").exists())

    def test_units_are_never_guessed_and_explicit_header_conflicts_fail(self):
        with self.assertRaisesRegex(ValueError, "No explicit unit"):
            PROFILE.resolve_unit("model_ttft", "auto")
        self.assertEqual(PROFILE.resolve_unit("model_ttft (毫秒)", "auto"), "ms")
        with self.assertRaisesRegex(ValueError, "Unit conflict"):
            PROFILE.resolve_unit("model_ttft_ms", "s")
        headers = list(PROFILE.FIELDS)
        headers[-2:] = ["model_ttft(ms)", "model_tpot [s]"]
        self.assertEqual(PROFILE.columns(headers)["model_tpot"], "model_tpot [s]")

    def test_unknown_units_still_allow_token_analysis(self):
        result = PROFILE.analyze(self.args(
            self.write([self.row()]), "--ttft-unit", "unknown", "--tpot-unit", "unknown"))
        self.assertEqual(result["overall"]["ttft_s_n"], 0)
        self.assertEqual(result["overall"]["prompt_tokens_sum"], 100)
        self.assertEqual(result["preceding_10s_comparison"], {})

    def test_multi_cluster_guard_and_selection(self):
        path = self.write([self.row(), self.row("b", cluster="two")])
        with self.assertRaisesRegex(ValueError, "Need one cluster"):
            PROFILE.analyze(self.args(path))
        result = PROFILE.analyze(self.args(path, "--instance-uuid", "two"))
        self.assertEqual(result["overall"]["requests"], 1)
        self.assertEqual(result["quality"]["other_cluster_rows_excluded"], 1)

    def test_duplicate_and_conflicting_identity(self):
        row = self.row()
        result = PROFILE.analyze(self.args(self.write([row, row])))
        self.assertEqual(result["overall"]["requests"], 1)
        self.assertEqual(result["quality"]["identical_duplicate_rows_excluded"], 1)
        with self.assertRaisesRegex(ValueError, "nonempty"):
            PROFILE.analyze(self.args(self.root / "requests.csv"))
        other = self.args(self.write([row, self.row(ttft=2000)]))
        other.output_dir = self.root / "different"
        with self.assertRaisesRegex(ValueError, "Conflicting rows"):
            PROFILE.analyze(other)

    def test_bad_tokens_do_not_erase_valid_latency(self):
        result = PROFILE.analyze(self.args(
            self.write([self.row(total=99, cached=101, ttft=27000)])))
        self.assertEqual(result["overall"]["ttft_slo_violation_n"], 1)
        self.assertEqual(result["overall"]["ttft_s_n"], 1)
        self.assertEqual(result["overall"]["uncached_tokens_known_n"], 0)
        self.assertEqual(result["overall"]["output_tokens_known_n"], 0)
        self.assertEqual(result["quality"]["cached_greater_than_prompt"], 1)

    def test_lookback_excludes_current_and_same_timestamp(self):
        records = [
            {"start": 0, "prompt_tokens": 10, "uncached_tokens": 5, "ttft_s": 1},
            {"start": 10, "prompt_tokens": 100, "uncached_tokens": 50, "ttft_s": 2},
            {"start": 10, "prompt_tokens": 200, "uncached_tokens": 80, "ttft_s": 3},
        ]
        result = PROFILE.preceding_work(records, 0, 2.5)
        tail = result["ttft_at_or_above_p90"]
        self.assertEqual(tail["prior_10s_count"]["mean"], 1)
        self.assertEqual(tail["prior_10s_prompt_tokens"]["mean"], 10)

    def test_timezones_and_half_open_window(self):
        self.assertEqual(PROFILE.timestamp("2026-09-24T15:00:00+08:00"),
                         PROFILE.timestamp("2026-09-24 07:00:00"))
        result = PROFILE.analyze(self.args(
            self.write([self.row(), self.row("b", "2026-09-24 07:00:01")]),
            "--window-start", "2026-09-24T07:00:00Z",
            "--window-end", "2026-09-24T07:00:01Z"))
        self.assertEqual(result["overall"]["requests"], 1)
        self.assertEqual(result["quality"]["outside_analysis_window"], 1)


if __name__ == "__main__":
    unittest.main()
