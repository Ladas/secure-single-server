"""Quota displays must not turn cumulative counters into a false rolling balance."""
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("quota_status", ROOT / "scripts/common/quota_status.py")
quota = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quota)

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def config(backend="memory", window="24h", key="global"):
    return {"filter_chains": [{"name": "openai", "filters": [{
        "filter": "token_rate_limit", "key": key, "backend": {"kind": backend},
        "rules": [{"name": "qwen", "algorithm": "sliding_window", "window": window,
                   "capacity": 1000000, "reserved_tokens": 10000}]}]}]}


def metrics():
    return '\n'.join([
        'praxis_ai_token_rate_limit_tokens_total{kind="estimated",rule="qwen"} 1.17e6',
        'praxis_ai_token_rate_limit_tokens_total{rule="qwen",kind="refunded"} 209846',
        'praxis_ai_token_rate_limit_tokens_total{kind="overage",rule="qwen"} 31832',
        'praxis_ai_token_rate_limit_tokens_total{kind="actual",rule="qwen"} 481986',
        'praxis_ai_token_rate_limit_requests_total{decision="admitted",rule="qwen"} 117',
        'praxis_ai_token_rate_limit_requests_total{decision="denied",rule="qwen"} 8',
        'praxis_ai_token_rate_limit_active_reservations{rule="qwen"} 0',
        'praxis_ai_token_rate_limit_active_keys{rule="qwen"} 1'])


class QuotaStatusTest(unittest.TestCase):
    def report(self, source=None, samples=None, age=3600, modified=None):
        return quota.summarize(source or config(), metrics() if samples is None else samples,
                               START, START + timedelta(seconds=age),
                               modified or START - timedelta(seconds=1))

    def test_first_window_retains_estimates_and_detects_insufficient_reservation(self):
        row = self.report()[0]
        self.assertEqual(row["charged"], 991986)
        self.assertEqual(row["remaining"], 8014)
        self.assertEqual(row["actual"], 481986)
        self.assertEqual(row["denied"], 8)
        self.assertEqual(row["basis"], "first window")
        self.assertFalse(row["room_for_reservation"])

    def test_aging_and_valkey_never_reuse_lifetime_totals_as_current_balance(self):
        for source, age in ((config(), 86400), (config(), 90000), (config("valkey"), 100)):
            row = self.report(source, age=age)[0]
            self.assertIsNone(row["charged"])
            self.assertIsNone(row["remaining"])
            self.assertIsNone(row["room_for_reservation"])
            self.assertEqual(row["actual"], 481986)
            self.assertEqual(row["net_since_start"], 991986)

    def test_missing_samples_are_unknown_not_an_unused_budget(self):
        row = self.report(samples="")[0]
        self.assertIsNone(row["charged"])
        self.assertIsNone(row["remaining"])
        self.assertIsNone(row["denied"])
        self.assertEqual(row["basis"], "no samples")

    def test_status_identifies_backends_and_explains_post_restart_missing_metrics(self):
        for backend in ("memory", "valkey"):
            rows = self.report(source=config(backend), samples="")
            self.assertEqual(rows[0]["backend"], backend)
            text = quota.format_report(rows, START)
            self.assertIn("Backend", text)
            self.assertIn(backend, text)
            self.assertIn("No samples", text)
            self.assertIn("after inference", text)
            self.assertIn("Memory quotas reset" if backend == "memory" else "Valkey retains quota usage", text)
        self.assertNotIn("No samples", quota.format_report(self.report(), START))

    def test_unemitted_zero_counters_do_not_hide_an_admitted_budget(self):
        samples = 'praxis_ai_token_rate_limit_tokens_total{kind="estimated",rule="qwen"} 10000'
        row = self.report(samples=samples)[0]
        self.assertEqual(row["charged"], 10000)
        self.assertEqual(row["remaining"], 990000)
        self.assertEqual(row["denied"], 0)
        self.assertTrue(row["room_for_reservation"])

    def test_changed_config_or_clock_disagreement_disables_reconstruction(self):
        for row in (self.report(modified=START + timedelta(seconds=1))[0], self.report(age=-1)[0]):
            self.assertIsNone(row["remaining"])

    def test_unknown_window_non_global_key_and_multiple_active_keys_are_unknown(self):
        sources = (config(window="unrecognized"), config(key="authenticated_subject"))
        for source in sources:
            self.assertIsNone(self.report(source)[0]["remaining"])
        self.assertIsNone(self.report(samples=metrics().replace('active_keys{rule="qwen"} 1',
                                                               'active_keys{rule="qwen"} 2'))[0]["remaining"])

    def test_duplicate_rule_names_or_ambiguous_samples_fail(self):
        source = config()
        source["filter_chains"] *= 2
        with self.assertRaisesRegex(ValueError, "unique"):
            self.report(source)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.report(samples=metrics() + '\n' + metrics())

    def test_invalid_or_negative_metrics_do_not_produce_a_balance(self):
        for value in ("NaN", "+Inf", "-1", "bad"):
            with self.assertRaises(ValueError):
                self.report(samples=metrics().replace("1.17e6", value))

    def test_table_labels_lifetime_accounting_separately(self):
        output = quota.format_report(self.report(age=90000), START)
        self.assertIn("unknown", output)
        self.assertIn("Since process start", output)
        self.assertIn("991,986", output)
        self.assertNotIn("8,014", output)
        self.assertIn("sudo scripts/common/quota-set --list", output)

    def test_timestamp_handles_podman_nanoseconds_on_rhel_python(self):
        self.assertEqual(quota.parse_started('2026-01-01T00:00:00.123456789Z').microsecond, 123456)

    def test_restart_during_scrape_is_rejected_instead_of_mixing_counters(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"shared-gateway.yaml"
            path.write_text("filter_chains: []")
            with patch.dict(quota.os.environ, PRAXIS_CONFIG_DIR=directory), \
                 patch.object(quota.subprocess, "run"), \
                 patch.object(quota, "service", side_effect=[
                     '"2026-01-01T00:00:00Z"', metrics(), '"2026-01-01T01:00:00Z"']):
                with self.assertRaisesRegex(ValueError, "restarted"):
                    quota.collect()


if __name__ == "__main__":
    unittest.main()
