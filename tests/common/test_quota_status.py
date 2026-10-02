"""Quota displays must not turn cumulative counters into a false rolling balance."""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/common"))
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
            self.assertEqual(row["net_since_start"], None if row["backend"] == "valkey" else 991986)

    def test_valkey_reserved_counters_are_not_reported_as_net_charges(self):
        row = self.report(config("valkey"))[0]
        self.assertEqual(row["estimated_since_start"], 1170000)
        self.assertIsNone(row["net_since_start"])
        self.assertIsNone(row["orphaned"])

    def test_valkey_snapshot_counts_settlement_and_held_estimates_at_server_time(self):
        snapshot = ["1000", "999000",
                    ["settled:1:45", "995000", "expired:2:20", "999000"],
                    ["3", "100|1000000", "4", "50|990999"]]
        result = quota.valkey_balance(snapshot, 10000, 5000)
        self.assertEqual(result, {"sampled_at_ms": 1000999, "settled_tokens": 65,
                                  "held_tokens": 100, "charged": 165})

    def test_valkey_expired_reservations_stay_charged_until_the_window_boundary(self):
        for now, expected in (("1000", 100), ("1009", 100), ("1010", 0)):
            result = quota.valkey_balance([now, "0", [], ["1", "100|1000000"]], 10000, 5000)
            self.assertEqual(result["charged"], expected)
        # An unexpired reservation still counts even when the window is shorter than its timeout.
        self.assertEqual(quota.valkey_balance(["1010", "0", [], ["1", "100|1000000"]],
                                             5000, 20000)["charged"], 100)

    def test_valkey_empty_ledger_is_zero_but_unsupported_records_are_not(self):
        self.assertEqual(quota.valkey_balance(["1000", "0", [], []], 10000, 5000)["charged"], 0)
        for records, active in ((["new-format", "999000"], []), ([], ["1", "broken"]),
                                (["settled:1:3", "1.5"], []), ([], ["1"]),
                                (["settled:1:3", "1000001"], [])):
            with self.assertRaises(ValueError):
                quota.valkey_balance(["1000", "0", records, active], 10000, 5000)

    def test_valkey_uses_the_pinned_global_key_and_keeps_auth_out_of_arguments(self):
        source = config("valkey")
        item = source["filter_chains"][0]["filters"][0]
        item["backend"].update(namespace="secure-single-server:limits:test",
                               url="${TOKEN_RATE_LIMIT_VALKEY_URL}")
        item["rules"][0]["reservation_timeout"] = "5s"
        rows = self.report(source, samples="")
        with patch.object(quota, "service", side_effect=[
                '"quay.io/opendatahub/praxis-experimental@sha256:227d421e963c477038a884dc51ec880c5d0afa30098ae31028ecf85e963e40d5"',
                "redis://praxis:private%2Bpassword@praxis-valkey:6379/0",
                json.dumps(["1000", "0", ["settled:1:75", "999000"], []])]) as service:
            quota.read_valkey_balances(source, rows)
        self.assertEqual(rows[0]["charged"], 75)
        self.assertEqual(rows[0]["remaining"], 999925)
        self.assertEqual(rows[0]["basis"], "valkey ledger")
        arguments = service.call_args.args
        self.assertNotIn("private+password", str(arguments))
        self.assertEqual(service.call_args.kwargs["input_text"], "private+password\n")
        self.assertTrue(any(str(arg).startswith("#!lua flags=no-writes") for arg in arguments))

    def test_valkey_unsupported_schema_stays_unknown(self):
        source = config("valkey", key="authenticated_subject")
        rows = self.report(source)
        with patch.object(quota, "service") as service:
            quota.read_valkey_balances(source, rows)
        service.assert_not_called()
        self.assertIsNone(rows[0]["charged"])
        self.assertIn("global", rows[0]["balance_note"])

    def test_valkey_unknown_image_never_reports_an_empty_ledger(self):
        source = config("valkey")
        source["filter_chains"][0]["filters"][0]["backend"]["url"] = "${TOKEN_RATE_LIMIT_VALKEY_URL}"
        rows = self.report(source)
        with patch.object(quota, "service", return_value='"unknown-image:latest"') as service:
            quota.read_valkey_balances(source, rows)
        self.assertEqual(service.call_count, 1)
        self.assertIsNone(rows[0]["charged"])
        self.assertIn("not qualified", rows[0]["balance_note"])

    def test_valkey_default_reservation_timeout_matches_pinned_backend(self):
        source = config("valkey", window="10s")
        source["filter_chains"][0]["filters"][0]["backend"]["url"] = "${TOKEN_RATE_LIMIT_VALKEY_URL}"
        rows = self.report(source, samples="")
        with patch.object(quota, "service", side_effect=[json.dumps(quota.LEDGER_IMAGE),
                "redis://praxis:private@praxis-valkey:6379/0",
                json.dumps(["1000", "0", [], ["1", "100|960000"]])]):
            quota.read_valkey_balances(source, rows)
        # 40 seconds old: expired under the backend default 30s, outside this 10s window.
        self.assertEqual(rows[0]["charged"], 0)

    def test_valkey_connection_rejection_does_not_expose_credentials(self):
        source = config("valkey")
        source["filter_chains"][0]["filters"][0]["backend"]["url"] = "${TOKEN_RATE_LIMIT_VALKEY_URL}"
        rows = self.report(source)
        with patch.object(quota, "service", side_effect=[json.dumps(quota.LEDGER_IMAGE),
                "redis://praxis:secret-password@external.example:6379/0"]), \
             self.assertRaises(ValueError) as raised:
            quota.read_valkey_balances(source, rows)
        self.assertNotIn("secret-password", str(raised.exception))

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
