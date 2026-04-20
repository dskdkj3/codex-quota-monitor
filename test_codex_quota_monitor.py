#!/usr/bin/env python3

import datetime as dt
import importlib.util
import os
import pathlib
import unittest


MODULE_PATH = pathlib.Path(os.environ.get("CODEX_QUOTA_MONITOR_MODULE", pathlib.Path(__file__).with_name("codex-quota-monitor.py")))
SPEC = importlib.util.spec_from_file_location("codex_quota_monitor", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DashboardSnapshotTests(unittest.TestCase):
    def test_build_dashboard_snapshot_prefers_problem_accounts_and_filters_logs(self):
        sampled_at = dt.datetime(2026, 4, 20, 11, 10, tzinfo=dt.timezone.utc).astimezone()
        snapshot = MODULE.build_dashboard_snapshot(
            health_payload={"status": "ok"},
            auth_files_payload={
                "files": [
                    {
                        "auth_index": "acct-good",
                        "label": "account-slot",
                        "status": "active",
                        "updated_at": "2026-04-20T11:00:00+08:00",
                        "id_token": {"plan_type": "plus"},
                    },
                    {
                        "auth_index": "acct-bad",
                        "label": "account-slot",
                        "status": "active",
                        "unavailable": True,
                        "status_message": "OAuth refresh failed",
                        "updated_at": "2026-04-20T10:59:00+08:00",
                        "id_token": {"plan_type": "team"},
                    },
                ]
            },
            usage_payload={
                "usage": {
                    "total_requests": 3,
                    "success_count": 2,
                    "failure_count": 1,
                    "total_tokens": 3000,
                    "apis": {
                        "sk-dummy": {
                            "models": {
                                "gpt-5.4": {
                                    "details": [
                                        {
                                            "timestamp": "2026-04-20T11:05:00+08:00",
                                            "source": "account-slot",
                                            "auth_index": "acct-good",
                                            "tokens": {"total_tokens": 1800},
                                            "failed": False,
                                        },
                                        {
                                            "timestamp": "2026-04-20T11:06:00+08:00",
                                            "source": "account-slot",
                                            "auth_index": "acct-bad",
                                            "tokens": {"total_tokens": 1200},
                                            "failed": False,
                                        },
                                        {
                                            "timestamp": "2026-04-20T11:07:00+08:00",
                                            "source": "account-slot",
                                            "auth_index": "acct-bad",
                                            "tokens": {"total_tokens": 0},
                                            "failed": True,
                                        },
                                    ]
                                }
                            }
                        }
                    },
                },
                "requests_by_hour": {"11": 3},
            },
            routing_payload={"strategy": "round-robin"},
            usage_stats_payload={"usage-statistics-enabled": True},
            request_log_payload={"request-log": True},
            logs_payload={
                "lines": [
                    '[2026-04-20 11:00:00] [--------] [warn ] [gin_logger.go:91] 404 | 0s | 127.0.0.1 | GET "/metrics"',
                    "[2026-04-20 11:08:00] [--------] [error] [config_reload.go:86] failed to reload config",
                ]
            },
            sampled_at=sampled_at,
            endpoint_errors=["logs: timed out"],
            source="partial",
        )

        self.assertTrue(snapshot["available"])
        self.assertEqual(snapshot["source"], "partial")
        self.assertEqual(snapshot["summary"]["alertsPill"], "3 alerts")
        self.assertEqual(snapshot["tabs"]["pool"]["items"][0]["title"], "account-slot")
        self.assertIn("1 fail", snapshot["tabs"]["pool"]["items"][0]["detail"])
        self.assertEqual(snapshot["tabs"]["traffic"]["stats"][0]["value"], "3")
        self.assertEqual(snapshot["tabs"]["traffic"]["stats"][1]["value"], "67%")
        self.assertEqual(snapshot["tabs"]["alerts"]["stats"][0]["value"], "1")
        self.assertEqual(snapshot["tabs"]["alerts"]["stats"][1]["value"], "1")
        self.assertEqual(snapshot["tabs"]["alerts"]["stats"][2]["value"], "1")
        self.assertEqual(snapshot["tabs"]["alerts"]["items"][0]["badge"], "Auth")
        self.assertEqual(snapshot["tabs"]["alerts"]["items"][1]["badge"], "Request")
        self.assertEqual(snapshot["tabs"]["alerts"]["items"][2]["badge"], "Log")
        self.assertIn("logs: timed out", snapshot["statusText"])

    def test_build_unavailable_snapshot_has_expected_placeholders(self):
        snapshot = MODULE.build_unavailable_snapshot("auth-files: connection refused")

        self.assertFalse(snapshot["available"])
        self.assertEqual(snapshot["source"], "unavailable")
        self.assertEqual(snapshot["summary"]["poolPill"], "Pool unavailable")
        self.assertEqual(snapshot["tabs"]["pool"]["title"], "Pool Health")
        self.assertIn("connection refused", snapshot["statusText"])


if __name__ == "__main__":
    unittest.main()
