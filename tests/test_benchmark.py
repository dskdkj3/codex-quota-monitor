#!/usr/bin/env python3

import json
import os
import pathlib
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


ROOT = pathlib.Path(
    os.environ.get("CODEX_QUOTA_MONITOR_ROOT")
    or os.environ.get("CODEX_QUOTA_MONITOR_ROOT")
    or pathlib.Path(__file__).resolve().parents[1]
)
SOURCE_ROOT = ROOT if (ROOT / "codex_quota_monitor").is_dir() else ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from codex_quota_monitor.benchmark import (  # noqa: E402
    PromptCase,
    build_default_prompt_cases,
    build_quota_summary,
    build_report,
    build_gateway_config,
    compute_window_drop,
    extract_usage,
    resolve_auth_file,
    run_one_request,
    write_csv,
)
from codex_quota_monitor.quota import parse_quota_usage_payload  # noqa: E402


class BenchmarkHelperTests(unittest.TestCase):
    def test_parse_quota_usage_payload_keeps_raw_remaining_percent(self):
        parsed = parse_quota_usage_payload(
            {
                "plan_type": "team",
                "rate_limit": {
                    "primary_window": {
                        "remaining_percent": 96.4,
                        "reset_at": "2026-04-20T13:30:00+08:00",
                        "limit_window_seconds": 18000,
                    }
                },
            }
        )

        self.assertEqual(parsed["planType"], "team")
        self.assertAlmostEqual(parsed["windows"]["5h"]["remainingPercent"], 96.4)
        self.assertEqual(parsed["windows"]["5h"]["percent"], 96)

    def test_resolve_auth_file_requires_unique_match_and_expected_plan(self):
        auth_files = [
            {
                "auth_index": "plus-slot",
                "label": "account-slot",
                "name": "plus.json",
                "path": "/tmp/plus.json",
                "id_token": {"plan_type": "plus", "chatgpt_account_id": "acct-plus"},
            },
            {
                "auth_index": "team-slot",
                "label": "account-slot",
                "name": "team.json",
                "path": "/tmp/team.json",
                "id_token": {"plan_type": "team", "chatgpt_account_id": "acct-team"},
            },
        ]

        plus = resolve_auth_file(auth_files, "plus-slot", "plus")
        team = resolve_auth_file(auth_files, "team.json", "team")

        self.assertEqual(plus.plan_type, "plus")
        self.assertEqual(team.account_id, "acct-team")

        with self.assertRaisesRegex(Exception, "non-Plus"):
            resolve_auth_file(auth_files, "team-slot", "plus")

    def test_build_default_prompt_cases_has_three_balanced_classes(self):
        prompts = build_default_prompt_cases()

        self.assertEqual(len(prompts), 30)
        counts = {}
        for prompt in prompts:
            counts[prompt.prompt_class] = counts.get(prompt.prompt_class, 0) + 1
        self.assertEqual(counts, {"short": 10, "medium": 10, "long": 10})

    def test_build_gateway_config_is_minimal_yaml(self):
        config_text = build_gateway_config("/tmp/auth", 9911, "sk-bench")

        self.assertIn('host: "127.0.0.1"', config_text)
        self.assertIn("port: 9911", config_text)
        self.assertIn('auth-dir: "/tmp/auth"', config_text)
        self.assertIn('  - "sk-bench"', config_text)
        self.assertIn("session-affinity: false", config_text)

    def test_compute_window_drop_rejects_reset_change(self):
        invalid = compute_window_drop(
            {"remainingPercent": 50.0, "resetAt": "2026-04-23T01:00:00+08:00"},
            {"remainingPercent": 40.0, "resetAt": "2026-04-23T06:00:00+08:00"},
        )
        valid = compute_window_drop(
            {"remainingPercent": 50.0, "resetAt": "2026-04-23T01:00:00+08:00"},
            {"remainingPercent": 40.5, "resetAt": "2026-04-23T01:00:00+08:00"},
        )

        self.assertFalse(invalid["valid"])
        self.assertEqual(invalid["reason"], "reset-changed")
        self.assertTrue(valid["valid"])
        self.assertAlmostEqual(valid["drop"], 9.5)

    def test_extract_usage_reads_cached_and_reasoning_tokens(self):
        usage = extract_usage(
            {
                "usage": {
                    "input_tokens": 12,
                    "input_tokens_details": {"cached_tokens": 3},
                    "output_tokens": 7,
                    "output_tokens_details": {"reasoning_tokens": 2},
                    "total_tokens": 19,
                }
            }
        )

        self.assertEqual(
            usage,
            {
                "input_tokens": 12,
                "output_tokens": 7,
                "reasoning_tokens": 2,
                "cached_tokens": 3,
                "total_tokens": 19,
            },
        )


class ResponseHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length") or "0")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        response = {
            "id": "resp_test",
            "status": "completed",
            "usage": {
                "input_tokens": 11,
                "input_tokens_details": {"cached_tokens": 1},
                "output_tokens": 5,
                "output_tokens_details": {"reasoning_tokens": 0},
                "total_tokens": 16,
            },
            "service_tier": payload.get("service_tier") or "default",
        }
        encoded = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *args, **kwargs):
        pass


class RequestRecordingTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ResponseHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def test_run_one_request_records_expected_fields(self):
        record = run_one_request(
            phase="performance",
            gateway_name="plus:account-slot",
            base_url=self.base_url,
            api_key="sk-bench",
            prompt_case=PromptCase(prompt_id="short-01", prompt_class="short", input_text="answer with ok"),
            model="gpt-5.4",
            reasoning_effort="",
            tier_label="fast",
            timeout_seconds=5,
        )

        self.assertEqual(record["phase"], "performance")
        self.assertEqual(record["response_service_tier"], "priority")
        self.assertEqual(record["input_tokens"], 11)
        self.assertEqual(record["cached_tokens"], 1)
        self.assertEqual(record["total_tokens"], 16)
        self.assertFalse(record["failed"])


class QuotaSummaryTests(unittest.TestCase):
    def test_build_quota_summary_reports_plus_unit_ratios(self):
        team_gateway = type(
            "Gateway",
            (),
            {"account": type("Account", (), {"auth_index": "team-slot", "label": "account-slot"})()},
        )()
        plus_gateway = type(
            "Gateway",
            (),
            {"account": type("Account", (), {"auth_index": "plus-slot", "label": "account-slot"})()},
        )()

        summary = build_quota_summary(
            team_gateway,
            [plus_gateway],
            {
                "team": {"team-slot": {"5h": 2.0, "week": 1.0}},
                "plus": {"plus-slot": {"5h": 10.0, "week": 5.0}},
            },
            [],
        )

        self.assertEqual(summary["aggregate"]["5h"]["mean_ratio_in_plus_units"], 5.0)
        self.assertEqual(summary["aggregate"]["week"]["mean_ratio_in_plus_units"], 5.0)
        self.assertEqual(summary["per_plus"][0]["plus_label"], "account-slot")

    def test_build_report_mentions_summary_files(self):
        report = build_report(
            type(
                "Args",
                (),
                {
                    "model": "gpt-5.4",
                    "reasoning_effort": "",
                    "plus_selectors": ["plus-slot"],
                    "team_selector": "team-slot",
                },
            )(),
            [PromptCase("short-01", "short", "hello")],
            {"baseline": {"p50_latency_ms": 20.0, "p90_latency_ms": 25.0}, "fast": {"p50_latency_ms": 10.0, "p90_latency_ms": 15.0}, "comparison": {"speedup_p50": 2.0, "speedup_p90": 1.6667, "token_overhead_ratio": 0.1}},
            {"aggregate": {"5h": {"mean_ratio_in_plus_units": 5.0, "min_ratio_in_plus_units": 5.0, "max_ratio_in_plus_units": 5.0}, "week": {"mean_ratio_in_plus_units": 4.5, "min_ratio_in_plus_units": 4.5, "max_ratio_in_plus_units": 4.5}}, "per_plus": [{"plus_label": "account-slot", "ratios": {"5h": {"ratio_in_plus_units": 5.0}, "week": {"ratio_in_plus_units": 4.5}}}]},
            pathlib.Path("/tmp/out"),
        )

        self.assertIn("requests.csv", report)
        self.assertIn("summary.json", report)
        self.assertIn("account-slot", report)

    def test_write_csv_supports_mixed_phase_fields(self):
        rows = [
            {"phase": "performance", "pair_index": 1, "tier": "fast"},
            {"phase": "quota", "round_index": 2, "tier": "baseline"},
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = pathlib.Path(temp_dir) / "requests.csv"
            write_csv(output_path, rows)
            text = output_path.read_text(encoding="utf-8")

        self.assertIn("pair_index", text)
        self.assertIn("round_index", text)


if __name__ == "__main__":
    unittest.main()
