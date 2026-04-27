#!/usr/bin/env python3

import datetime as dt
import json
import os
import pathlib
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock


ROOT = pathlib.Path(
    os.environ.get("CODEX_QUOTA_MONITOR_ROOT")
    or os.environ.get("CODEX_QUOTA_MONITOR_ROOT")
    or pathlib.Path(__file__).resolve().parents[1]
)
SOURCE_ROOT = ROOT if (ROOT / "codex_quota_monitor").is_dir() else ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

import codex_quota_monitor as MODULE

UNSET = object()


class CliTests(unittest.TestCase):
    def test_parse_args_defaults_to_loopback(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            args = MODULE.parse_args([])

        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 4515)
        self.assertEqual(args.weekly_to_five_hour_multiplier, 6.0)

    def test_parse_args_prefers_new_env_names_but_accepts_legacy_aliases(self):
        with mock.patch.dict(
            os.environ,
            {
                "CODEX_QUOTA_MONITOR_HOST": "0.0.0.0",
                "CODEX_MONITOR_PORT": "9000",
            },
            clear=True,
        ):
            args = MODULE.parse_args([])

        self.assertEqual(args.host, "0.0.0.0")
        self.assertEqual(args.port, 9000)

    def test_parse_args_accepts_weekly_to_five_hour_multiplier(self):
        with mock.patch.dict(
            os.environ,
            {
                "CODEX_QUOTA_MONITOR_WEEKLY_TO_FIVE_HOUR_MULTIPLIER": "3.5",
            },
            clear=True,
        ):
            args = MODULE.parse_args([])

        self.assertEqual(args.weekly_to_five_hour_multiplier, 3.5)

    def test_parse_args_accepts_cli_weekly_to_five_hour_override(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            args = MODULE.parse_args(["--weekly-to-five-hour-multiplier", "4.25"])

        self.assertEqual(args.weekly_to_five_hour_multiplier, 4.25)

    def test_parse_args_accepts_weekly_to_five_hour_opt_out(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            args = MODULE.parse_args(["--weekly-to-five-hour-multiplier", "off"])

        self.assertIsNone(args.weekly_to_five_hour_multiplier)

        with mock.patch.dict(os.environ, {"CODEX_QUOTA_MONITOR_WEEKLY_TO_FIVE_HOUR_MULTIPLIER": "none"}, clear=True):
            args = MODULE.parse_args([])

        self.assertIsNone(args.weekly_to_five_hour_multiplier)

    def test_parse_args_accepts_history_and_alert_options(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            args = MODULE.parse_args(
                [
                    "--state-db",
                    "/tmp/history.sqlite3",
                    "--history-write-seconds",
                    "5",
                    "--history-retention-days",
                    "7",
                    "--benchmark-summary",
                    "/tmp/summary.json",
                    "--alert-five-hour-min-plus",
                    "1.5",
                    "--alert-weekly-min-plus",
                    "2.5",
                    "--alert-best-accounts-min",
                    "2",
                ]
            )

        self.assertEqual(args.state_db, "/tmp/history.sqlite3")
        self.assertEqual(args.history_write_seconds, 5)
        self.assertEqual(args.history_retention_days, 7)
        self.assertEqual(args.benchmark_summary, "/tmp/summary.json")
        self.assertEqual(args.alert_five_hour_min_plus, 1.5)
        self.assertEqual(args.alert_weekly_min_plus, 2.5)
        self.assertEqual(args.alert_best_accounts_min, 2)


class RuntimeTests(unittest.TestCase):
    def test_cpa_monitor_defaults_weekly_to_five_hour_multiplier(self):
        monitor = MODULE.CPAMonitor(
            management_base_url="http://127.0.0.1:8318",
            gateway_health_url="http://127.0.0.1:8317/healthz",
            auth_dir="",
            refresh_seconds=15,
            logs_refresh_seconds=0,
            timeout_seconds=5,
        )

        self.assertEqual(monitor.weekly_to_five_hour_multiplier, 6.0)


class MetricsRenderingTests(unittest.TestCase):
    def test_prometheus_label_escape_handles_special_characters(self):
        self.assertEqual(MODULE.prometheus_escape_label('source "x"\\line\nnext'), 'source \\"x\\"\\\\line\\nnext')

    def test_prometheus_metrics_include_recommendations_capacity_and_source(self):
        sampled_at = dt.datetime(2026, 4, 20, 12, 0, tzinfo=dt.timezone.utc).astimezone()
        snapshot = MODULE.enhance_snapshot_with_history(
            build_history_dashboard(sampled_at=sampled_at, five_hour_percent=80),
            alert_thresholds={"best_accounts_min": 2},
        )
        metrics = MODULE.render_prometheus_metrics(snapshot)

        self.assertIn("codex_quota_monitor_snapshot_available 1", metrics)
        self.assertIn('codex_quota_monitor_snapshot_source{source="live"} 1', metrics)
        self.assertIn("codex_quota_monitor_gateway_up 1", metrics)
        self.assertIn("codex_quota_monitor_alert_count 1", metrics)
        self.assertIn("codex_quota_monitor_best_accounts 1", metrics)
        self.assertIn('codex_quota_monitor_capacity_known_plus_units{window="5h"} 0.8', metrics)
        self.assertIn('codex_quota_monitor_capacity_tracked_plus_units{window="week"} 1', metrics)


def build_history_dashboard(*, sampled_at, five_hour_percent, weekly_percent=80, status="active"):
    return MODULE.build_dashboard_snapshot(
        health_payload={"status": "ok"},
        auth_files_payload={
            "files": [
                {
                    "auth_index": "acct-plus",
                    "label": "account-slot",
                    "status": status,
                    "updated_at": sampled_at.isoformat(timespec="seconds"),
                    "id_token": {"plan_type": "plus"},
                }
            ]
        },
        usage_payload={
            "usage": {
                "total_requests": 4,
                "success_count": 4,
                "failure_count": 0,
                "total_tokens": 1000,
                "apis": {
                    "sk-dummy": {
                        "models": {
                            "gpt-5.4": {
                                "details": [
                                    {
                                        "timestamp": sampled_at.isoformat(timespec="seconds"),
                                        "source": "account-slot",
                                        "auth_index": "acct-plus",
                                        "tokens": {"total_tokens": 1000},
                                        "failed": False,
                                    }
                                ]
                            }
                        }
                    }
                },
            }
        },
        quota_payload={
            "status": "live",
            "eligibleCount": 1,
            "sampledCount": 1,
            "freshCount": 1,
            "staleCount": 0,
            "cycleSeconds": 15,
            "completedCycle": True,
            "degraded": False,
            "attemptedKey": "acct-plus",
            "attemptError": None,
            "samples": {
                "acct-plus": {
                    "sampledAt": sampled_at,
                    "planType": "plus",
                    "windows": {
                        "5h": {
                            "percent": five_hour_percent,
                            "resetAt": sampled_at + dt.timedelta(hours=2),
                        },
                        "week": {
                            "percent": weekly_percent,
                            "resetAt": sampled_at + dt.timedelta(days=2),
                        },
                    },
                    "lastError": None,
                    "lastErrorAt": None,
                }
            },
        },
        routing_payload={"routing": {"strategy": "round-robin"}, "codex": {"service-tier-policy": "force-priority"}},
        usage_stats_payload={"usage-statistics-enabled": True},
        request_log_payload={"request-log": True},
        logs_payload={"lines": []},
        sampled_at=sampled_at,
    )


class HistoryFeatureTests(unittest.TestCase):
    def test_sqlite_history_builds_recommendations_trends_and_audit(self):
        start = dt.datetime(2026, 4, 20, 12, 0, tzinfo=dt.timezone.utc).astimezone()
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MODULE.HistoryStore(pathlib.Path(temp_dir) / "history.sqlite3", write_seconds=1, retention_days=30)
            first = MODULE.enhance_snapshot_with_history(
                build_history_dashboard(sampled_at=start, five_hour_percent=80),
                history_store=store,
                weekly_to_five_hour_multiplier=4.0,
            )
            second = MODULE.enhance_snapshot_with_history(
                build_history_dashboard(sampled_at=start + dt.timedelta(hours=1), five_hour_percent=50),
                history_store=store,
                weekly_to_five_hour_multiplier=4.0,
            )
            third = MODULE.enhance_snapshot_with_history(
                build_history_dashboard(sampled_at=start + dt.timedelta(hours=2), five_hour_percent=0),
                history_store=store,
                weekly_to_five_hour_multiplier=4.0,
            )

        self.assertEqual(first["recommendations"]["bestCount"], 1)
        self.assertEqual(second["tabs"]["trends"]["windows"][0]["burnText"], "0.30 Plus/h")
        self.assertEqual(second["tabs"]["trends"]["windows"][0]["etaText"], "1h 40min")
        self.assertEqual(third["recommendations"]["avoidCount"], 1)
        audit_summaries = [item["summary"] for item in third["tabs"]["audit"]["items"]]
        self.assertTrue(any("5h exhausted" in summary for summary in audit_summaries))

    def test_sqlite_trends_show_latest_six_hours_downsampled(self):
        start = dt.datetime(2026, 4, 20, 12, 0, tzinfo=dt.timezone.utc).astimezone()
        snapshot = None
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MODULE.HistoryStore(pathlib.Path(temp_dir) / "history.sqlite3", write_seconds=1, retention_days=30)
            for index in range(29):
                snapshot = MODULE.enhance_snapshot_with_history(
                    build_history_dashboard(
                        sampled_at=start + dt.timedelta(minutes=15 * index),
                        five_hour_percent=100 - index,
                    ),
                    history_store=store,
                    weekly_to_five_hour_multiplier=4.0,
                )

        trends = snapshot["tabs"]["trends"]
        window = trends["windows"][0]
        self.assertIn("latest 6h", trends["summary"])
        self.assertIn("downsampled to 24 points", trends["footnote"])
        self.assertEqual(len(window["points"]), 24)
        self.assertEqual(window["points"][0]["valueText"], "0.96 Plus")
        self.assertEqual(window["points"][-1]["valueText"], "0.72 Plus")
        self.assertEqual(window["burnText"], "0.04 Plus/h")
        self.assertIn("6h 0min", window["summary"])

    def test_threshold_alerts_and_api_alert_payload_are_machine_readable(self):
        sampled_at = dt.datetime(2026, 4, 20, 12, 0, tzinfo=dt.timezone.utc).astimezone()
        snapshot = MODULE.enhance_snapshot_with_history(
            build_history_dashboard(sampled_at=sampled_at, five_hour_percent=40),
            alert_thresholds={
                "five_hour_min_plus": 0.5,
                "weekly_min_plus": 0.5,
                "best_accounts_min": 2,
            },
        )

        api_alerts = snapshot["apiAlerts"]
        self.assertFalse(api_alerts["ok"])
        self.assertEqual(api_alerts["recommendations"]["bestCount"], 1)
        self.assertIn("5h capacity below threshold", [item["title"] for item in api_alerts["items"]])
        self.assertIn("Recommended account pool below threshold", [item["title"] for item in api_alerts["items"]])

    def test_benchmark_summary_is_loaded_into_trends(self):
        sampled_at = dt.datetime(2026, 4, 20, 12, 0, tzinfo=dt.timezone.utc).astimezone()
        with tempfile.TemporaryDirectory() as temp_dir:
            summary_path = pathlib.Path(temp_dir) / "summary.json"
            summary_path.write_text(
                json.dumps(
                    {
                        "generatedAt": "2026-04-20T12:00:00+00:00",
                        "performance": {
                            "comparison": {
                                "speedup_p50": 1.25,
                                "token_overhead_ratio": 1.05,
                            }
                        },
                        "quota": {
                            "weeklyToFiveHour": {
                                "recommended_dashboard_multiplier": 3.25,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            snapshot = MODULE.enhance_snapshot_with_history(
                build_history_dashboard(sampled_at=sampled_at, five_hour_percent=80),
                benchmark_summary_path=str(summary_path),
            )

        benchmark = snapshot["tabs"]["trends"]["benchmark"]
        self.assertTrue(benchmark["available"])
        self.assertEqual(benchmark["recommendedDashboardMultiplier"], 3.25)
        self.assertIn("3.25", [metric["value"] for metric in benchmark["metrics"]])


class QuotaParsingTests(unittest.TestCase):
    def test_parse_quota_usage_payload_maps_direct_windows(self):
        parsed = MODULE.parse_quota_usage_payload(
            {
                "plan_type": "plus",
                "rate_limit": {
                    "primary_window": {
                        "used_percent": 70,
                        "reset_at": "2026-04-20T13:30:00+08:00",
                        "limit_window_seconds": 18000,
                    },
                    "secondary_window": {
                        "used_percent": 25,
                        "reset_at": "2026-04-23T00:00:00+08:00",
                        "limit_window_seconds": 604800,
                    },
                },
            }
        )

        self.assertEqual(parsed["planType"], "plus")
        self.assertEqual(parsed["windows"]["5h"]["percent"], 30)
        self.assertEqual(parsed["windows"]["week"]["percent"], 75)


class StubQuotaSampler(MODULE.QuotaSampler):
    def __init__(self, auth_dir, payloads):
        super().__init__(auth_dir=auth_dir, refresh_seconds=15, timeout_seconds=5)
        self.payloads = list(payloads)
        self.calls = []

    def _fetch_usage_payload(self, access_token, account_id):
        self.calls.append((access_token, account_id))
        return self.payloads[len(self.calls) - 1]


class QuotaSamplerTests(unittest.TestCase):
    def test_refresh_rotates_one_account_per_tick(self):
        with tempfile.TemporaryDirectory() as auth_dir:
            path_a = pathlib.Path(auth_dir) / "acct-a.json"
            path_b = pathlib.Path(auth_dir) / "acct-b.json"
            path_a.write_text(json.dumps({"access_token": "token-a", "account_id": "account-a"}), encoding="utf-8")
            path_b.write_text(json.dumps({"access_token": "token-b", "account_id": "account-b"}), encoding="utf-8")

            sampler = StubQuotaSampler(
                auth_dir,
                [
                    {
                        "plan_type": "plus",
                        "rate_limit": {
                            "primary_window": {"used_percent": 40, "limit_window_seconds": 18000},
                            "secondary_window": {"used_percent": 20, "limit_window_seconds": 604800},
                        },
                    },
                    {
                        "plan_type": "plus",
                        "rate_limit": {
                            "primary_window": {"used_percent": 60, "limit_window_seconds": 18000},
                            "secondary_window": {"used_percent": 30, "limit_window_seconds": 604800},
                        },
                    },
                ],
            )

            auth_files = [
                {
                    "auth_index": "acct-a",
                    "provider": "codex",
                    "path": str(path_a),
                    "id_token": {"plan_type": "plus", "chatgpt_account_id": "account-a"},
                },
                {
                    "auth_index": "acct-b",
                    "provider": "codex",
                    "path": str(path_b),
                    "id_token": {"plan_type": "plus", "chatgpt_account_id": "account-b"},
                },
            ]

            first = sampler.refresh(auth_files, dt.datetime(2026, 4, 20, 12, 30, tzinfo=dt.timezone.utc).astimezone())
            second = sampler.refresh(auth_files, dt.datetime(2026, 4, 20, 12, 30, 15, tzinfo=dt.timezone.utc).astimezone())

            self.assertEqual(first["attemptedKey"], "acct-a")
            self.assertEqual(second["attemptedKey"], "acct-b")
            self.assertEqual(first["sampledCount"], 1)
            self.assertEqual(second["sampledCount"], 2)
            self.assertEqual(second["status"], "live")
            self.assertEqual(sampler.calls, [("token-a", "account-a"), ("token-b", "account-b")])


class DashboardSnapshotTests(unittest.TestCase):
    def build_minimal_snapshot(self, *, auth_files, usage_details, quota_samples=None, weekly_to_five_hour_multiplier=UNSET):
        sampled_at = dt.datetime(2026, 4, 20, 12, 30, tzinfo=dt.timezone.utc).astimezone()
        total_tokens = sum(int((detail.get("tokens") or {}).get("total_tokens") or 0) for detail in usage_details)
        failure_count = sum(1 for detail in usage_details if detail.get("failed"))

        kwargs = {
            "health_payload": {"status": "ok"},
            "auth_files_payload": {"files": auth_files},
            "usage_payload": {
                "usage": {
                    "total_requests": len(usage_details),
                    "success_count": len(usage_details) - failure_count,
                    "failure_count": failure_count,
                    "total_tokens": total_tokens,
                    "apis": {
                        "sk-dummy": {
                            "models": {
                                "gpt-5.4": {
                                    "details": usage_details,
                                }
                            }
                        }
                    },
                }
            },
            "quota_payload": {
                "status": "warming",
                "eligibleCount": len(auth_files),
                "sampledCount": 0,
                "freshCount": 0,
                "staleCount": 0,
                "cycleSeconds": max(15, 15 * max(len(auth_files), 1)),
                "completedCycle": False,
                "degraded": False,
                "attemptedKey": None,
                "attemptError": None,
                "samples": quota_samples or {},
            },
            "routing_payload": {"routing": {"strategy": "round-robin"}},
            "usage_stats_payload": {"usage-statistics-enabled": True},
            "request_log_payload": {"request-log": True},
            "logs_payload": {"lines": []},
            "sampled_at": sampled_at,
        }
        if weekly_to_five_hour_multiplier is not UNSET:
            kwargs["weekly_to_five_hour_multiplier"] = weekly_to_five_hour_multiplier

        return MODULE.build_dashboard_snapshot(**kwargs)

    def test_build_dashboard_snapshot_hides_replaced_runtime_slot_with_same_source(self):
        snapshot = self.build_minimal_snapshot(
            auth_files=[
                {
                    "auth_index": "new-slot",
                    "label": "account-slot",
                    "provider": "codex",
                    "status": "active",
                    "id_token": {"plan_type": "prolite"},
                }
            ],
            usage_details=[
                {
                    "timestamp": "2026-04-20T12:20:00+08:00",
                    "source": "account-slot",
                    "auth_index": "old-slot",
                    "tokens": {"total_tokens": 800},
                    "failed": False,
                },
                {
                    "timestamp": "2026-04-20T12:22:00+08:00",
                    "source": "account-slot",
                    "auth_index": "new-slot",
                    "tokens": {"total_tokens": 200},
                    "failed": False,
                },
            ],
        )

        pool_accounts = snapshot["tabs"]["pool"]["accounts"]
        self.assertEqual([account["title"] for account in pool_accounts], ["account-slot"])
        self.assertEqual(pool_accounts[0]["badge"], "Prolite")
        self.assertEqual(pool_accounts[0]["requests"], 1)
        self.assertNotIn("Runtime", [account["badge"] for account in pool_accounts])
        self.assertFalse(any("Runtime" in item["summary"] for item in snapshot["tabs"]["traffic"]["distribution"]))
        self.assertEqual(snapshot["tabs"]["alerts"]["alertCount"], 0)

    def test_build_dashboard_snapshot_keeps_unknown_runtime_slot_without_matching_source(self):
        snapshot = self.build_minimal_snapshot(
            auth_files=[
                {
                    "auth_index": "known-slot",
                    "label": "account-slot",
                    "provider": "codex",
                    "status": "active",
                    "id_token": {"plan_type": "plus"},
                }
            ],
            usage_details=[
                {
                    "timestamp": "2026-04-20T12:20:00+08:00",
                    "source": "account-slot",
                    "auth_index": "orphan-slot",
                    "tokens": {"total_tokens": 800},
                    "failed": False,
                },
                {
                    "timestamp": "2026-04-20T12:22:00+08:00",
                    "source": "account-slot",
                    "auth_index": "known-slot",
                    "tokens": {"total_tokens": 200},
                    "failed": False,
                },
            ],
        )

        pool_accounts = snapshot["tabs"]["pool"]["accounts"]
        runtime_account = next(account for account in pool_accounts if account["badge"] == "Runtime")
        self.assertEqual(runtime_account["title"], "account-slot")
        self.assertEqual(runtime_account["statusLabel"], "Missing auth-file")
        self.assertEqual(snapshot["tabs"]["alerts"]["metrics"][0]["value"], "1")

    def test_build_dashboard_snapshot_keeps_multiple_current_slots_with_same_label(self):
        snapshot = self.build_minimal_snapshot(
            auth_files=[
                {
                    "auth_index": "plus-slot",
                    "label": "account-slot",
                    "provider": "codex",
                    "status": "active",
                    "id_token": {"plan_type": "plus"},
                },
                {
                    "auth_index": "team-slot",
                    "label": "account-slot",
                    "provider": "codex",
                    "status": "active",
                    "id_token": {"plan_type": "team"},
                },
            ],
            usage_details=[
                {
                    "timestamp": "2026-04-20T12:20:00+08:00",
                    "source": "account-slot",
                    "auth_index": "plus-slot",
                    "tokens": {"total_tokens": 800},
                    "failed": False,
                },
                {
                    "timestamp": "2026-04-20T12:22:00+08:00",
                    "source": "account-slot",
                    "auth_index": "team-slot",
                    "tokens": {"total_tokens": 200},
                    "failed": False,
                },
            ],
        )

        pool_accounts = snapshot["tabs"]["pool"]["accounts"]
        self.assertEqual(len(pool_accounts), 2)
        self.assertEqual(sorted(account["badge"] for account in pool_accounts), ["Plus", "Team"])
        self.assertEqual(snapshot["summary"]["poolPill"], "1 Plus · 1 Non-Plus")

    def test_build_dashboard_snapshot_exposes_capacity_windows_and_quota_cooldowns(self):
        sampled_at = dt.datetime(2026, 4, 20, 12, 30, tzinfo=dt.timezone.utc).astimezone()
        snapshot = MODULE.build_dashboard_snapshot(
            health_payload={"status": "ok"},
            auth_files_payload={
                "files": [
                    {
                        "auth_index": "acct-plus-known",
                        "label": "account-slot",
                        "status": "active",
                        "updated_at": "2026-04-20T12:20:00+08:00",
                        "id_token": {"plan_type": "plus"},
                        "quota_windows": {
                            "5h": {"remaining_percent": 30},
                            "weekly": {"remaining_percent": 80},
                        },
                    },
                    {
                        "auth_index": "acct-plus-limited",
                        "label": "account-slot",
                        "status": "error",
                        "unavailable": True,
                        "next_retry_after": "2026-04-20T13:40:00+08:00",
                        "status_message": (
                            '{"error":{"type":"usage_limit_reached","message":"The usage limit has been reached",'
                            '"resets_in_seconds":4200}}'
                        ),
                        "updated_at": "2026-04-20T12:18:00+08:00",
                        "id_token": {"plan_type": "plus"},
                    },
                    {
                        "auth_index": "acct-team",
                        "label": "account-slot",
                        "status": "active",
                        "updated_at": "2026-04-20T12:25:00+08:00",
                        "id_token": {"plan_type": "team"},
                    },
                ]
            },
            usage_payload={
                "usage": {
                    "total_requests": 4,
                    "success_count": 3,
                    "failure_count": 1,
                    "total_tokens": 3200,
                    "requests_by_hour": {"12": 1, "13": 3},
                    "tokens_by_hour": {"12": 1200, "13": 2000},
                    "requests_by_day": {"2026-04-20": 4},
                    "tokens_by_day": {"2026-04-20": 3200},
                    "apis": {
                        "sk-dummy": {
                            "models": {
                                "gpt-5.4": {
                                    "details": [
                                        {
                                            "timestamp": "2026-04-20T12:21:00+08:00",
                                            "source": "account-slot",
                                            "auth_index": "acct-plus-known",
                                            "tokens": {"total_tokens": 1600},
                                            "failed": False,
                                        },
                                        {
                                            "timestamp": "2026-04-20T12:22:00+08:00",
                                            "source": "account-slot",
                                            "auth_index": "acct-plus-limited",
                                            "tokens": {"total_tokens": 800},
                                            "failed": True,
                                        },
                                        {
                                            "timestamp": "2026-04-20T12:23:00+08:00",
                                            "source": "account-slot",
                                            "auth_index": "acct-team",
                                            "tokens": {"total_tokens": 400},
                                            "failed": False,
                                        },
                                        {
                                            "timestamp": "2026-04-20T12:24:00+08:00",
                                            "source": "account-slot",
                                            "auth_index": "acct-plus-known",
                                            "tokens": {"total_tokens": 400},
                                            "failed": False,
                                        },
                                    ]
                                }
                            }
                        }
                    },
                }
            },
            quota_payload={
                "status": "partial",
                "eligibleCount": 3,
                "sampledCount": 2,
                "freshCount": 1,
                "staleCount": 1,
                "cycleSeconds": 45,
                "completedCycle": False,
                "degraded": False,
                "attemptedKey": "acct-team",
                "attemptError": None,
                "samples": {
                    "acct-plus-known": {
                        "sampledAt": dt.datetime(2026, 4, 20, 12, 28, tzinfo=dt.timezone.utc).astimezone(),
                        "planType": "plus",
                        "windows": {
                            "5h": {
                                "percent": 30,
                                "resetAt": dt.datetime(2026, 4, 20, 15, 30, tzinfo=dt.timezone.utc).astimezone(),
                            },
                            "week": {
                                "percent": 80,
                                "resetAt": dt.datetime(2026, 4, 22, 20, 0, tzinfo=dt.timezone.utc).astimezone(),
                            },
                        },
                        "lastError": "usage query returned HTTP 401: token expired",
                        "lastErrorAt": dt.datetime(2026, 4, 20, 12, 29, 30, tzinfo=dt.timezone.utc).astimezone(),
                    },
                    "acct-plus-limited": {},
                    "acct-team": {
                        "sampledAt": dt.datetime(2026, 4, 20, 12, 29, 55, tzinfo=dt.timezone.utc).astimezone(),
                        "planType": "team",
                        "windows": {
                            "5h": {
                                "percent": 60,
                                "resetAt": dt.datetime(2026, 4, 20, 16, 0, tzinfo=dt.timezone.utc).astimezone(),
                            },
                            "week": {
                                "percent": 90,
                                "resetAt": dt.datetime(2026, 4, 24, 0, 0, tzinfo=dt.timezone.utc).astimezone(),
                            },
                        },
                        "lastError": None,
                        "lastErrorAt": None,
                    },
                },
            },
            routing_payload={
                "routing": {
                    "strategy": "round-robin",
                    "session-affinity": True,
                    "session-affinity-ttl": "1h",
                },
                "codex": {
                    "service-tier-policy": "force-priority",
                },
            },
            usage_stats_payload={"usage-statistics-enabled": True},
            request_log_payload={"request-log": True},
            logs_payload={"lines": []},
            sampled_at=sampled_at,
            endpoint_errors=["config: timed out"],
            source="partial",
        )

        self.assertTrue(snapshot["available"])
        self.assertEqual(snapshot["source"], "partial")
        self.assertEqual(snapshot["summary"]["poolPill"], "2 Plus · 1 Non-Plus")
        self.assertEqual(snapshot["summary"]["fastPill"], "Fast On")
        self.assertEqual(snapshot["summary"]["fiveHourPill"], "5h 0.90 Plus")
        self.assertEqual(snapshot["summary"]["weeklyPill"], "Weekly 1.70 Plus")
        self.assertEqual(snapshot["summary"]["subline"], "Round Robin + Sticky · 4 req · 3.2K tok")
        self.assertEqual(snapshot["summary"]["alertsPill"], "1 alert")
        self.assertEqual(snapshot["fastMode"]["state"], "on")
        self.assertEqual(snapshot["fastMode"]["policy"], "force-priority")
        self.assertTrue(snapshot["fastMode"]["isEnabled"])
        self.assertIn("service_tier=priority", snapshot["fastMode"]["detail"])

        pool_tab = snapshot["tabs"]["pool"]
        self.assertEqual(pool_tab["title"], "Pool Capacity")
        self.assertEqual(pool_tab["summary"], "2 Plus · 1 Non-Plus · 3 healthy · 0 issues")
        self.assertEqual(pool_tab["stats"][2]["label"], "Fast")
        self.assertEqual(pool_tab["stats"][2]["value"], "On")
        self.assertEqual(
            pool_tab["stats"][1]["detail"],
            "shown in the grid; Team counts 1:1 and Prolite counts 10:1 in capacity, other plans stay excluded",
        )
        self.assertIn("service_tier=priority", pool_tab["stats"][2]["detail"])
        self.assertEqual(pool_tab["capacityWindows"][0]["knownUnitsText"], "0.90 Plus")
        self.assertEqual(pool_tab["capacityWindows"][0]["plusTotal"], 2)
        self.assertEqual(pool_tab["capacityWindows"][0]["trackedTotal"], 3)
        self.assertIn("Unclassified 1", pool_tab["capacityWindows"][0]["summary"])
        limited_account = next(account for account in pool_tab["accounts"] if account["title"] == "account-slot")
        self.assertEqual(limited_account["statusLabel"], "Reset scheduled")
        self.assertEqual(limited_account["tone"], "warn")
        self.assertEqual(limited_account["sharePercent"], 25)
        self.assertEqual(limited_account["failed"], 1)
        self.assertEqual(limited_account["tokens"], 800)
        self.assertEqual(limited_account["windows"][0]["valueText"], "Unknown")
        self.assertIn("Resets", limited_account["note"])
        self.assertIn("direct Codex usage sampling", pool_tab["footnote"])
        self.assertIn("Team counts 1:1 and Prolite counts 10:1 in total capacity", pool_tab["footnote"])
        plus_known = next(account for account in pool_tab["accounts"] if account["title"] == "account-slot")
        self.assertEqual(plus_known["requests"], 2)
        self.assertEqual(plus_known["sharePercent"], 62)
        self.assertNotIn("stale", plus_known["windows"][0]["note"])
        self.assertNotIn("stale", plus_known["note"])
        team_account = next(account for account in pool_tab["accounts"] if account["badge"] == "Team")
        self.assertEqual(team_account["sharePercent"], 12)
        self.assertEqual(team_account["windows"][0]["valueText"], "60%")
        self.assertIn("Resets", team_account["windows"][0]["note"])
        self.assertNotIn("excluded", team_account["windows"][0]["note"])

        resets_tab = snapshot["tabs"]["resets"]
        self.assertEqual(resets_tab["title"], "Reset Schedule")
        self.assertIn("3 direct-sampled accounts", resets_tab["summary"])
        five_hour_rows = resets_tab["columns"][0]["items"]
        weekly_rows = resets_tab["columns"][1]["items"]
        self.assertEqual([row["account"] for row in five_hour_rows], ["account-slot", "account-slot", "account-slot"])
        self.assertEqual(five_hour_rows[0]["remainingText"], "3h 0min")
        self.assertEqual(five_hour_rows[0]["beijingTimeText"], "04-20 23:30")
        self.assertEqual(five_hour_rows[-1]["remainingText"], "Unknown")
        self.assertEqual(five_hour_rows[-1]["beijingTimeText"], "Unknown")
        self.assertEqual([row["account"] for row in weekly_rows], ["account-slot", "account-slot", "account-slot"])
        self.assertEqual(weekly_rows[0]["remainingText"], "2d 7h 30min")
        self.assertEqual(weekly_rows[0]["beijingTimeText"], "04-23 04:00")

        traffic_tab = snapshot["tabs"]["traffic"]
        self.assertEqual(traffic_tab["title"], "Usage Statistics")
        self.assertEqual(traffic_tab["metrics"][0]["value"], "4")
        self.assertEqual(traffic_tab["metrics"][1]["value"], "75%")
        self.assertEqual(traffic_tab["metrics"][3]["label"], "RPM")
        self.assertEqual(traffic_tab["metrics"][3]["value"], "0.03")
        self.assertEqual(traffic_tab["metrics"][4]["value"], "26.7")
        self.assertEqual(traffic_tab["charts"][0]["title"], "Requests by Hour")
        self.assertEqual(traffic_tab["charts"][0]["items"][1]["barPercent"], 100)
        self.assertEqual(traffic_tab["models"][0]["title"], "gpt-5.4")

        alerts_tab = snapshot["tabs"]["alerts"]
        self.assertEqual(alerts_tab["metrics"][0]["value"], "0")
        self.assertEqual(alerts_tab["metrics"][1]["value"], "0")
        self.assertEqual(alerts_tab["metrics"][2]["value"], "1")
        self.assertEqual(alerts_tab["items"][0]["badge"], "Monitor")
        self.assertNotIn("Quota", [item["badge"] for item in alerts_tab["items"]])
        self.assertIn("config: timed out", snapshot["statusText"])
        self.assertIn("direct Codex usage", snapshot["statusText"])
        diagnostics = snapshot["diagnostics"]
        diagnostic_by_title = {item["title"]: item for item in diagnostics["items"]}
        self.assertEqual(diagnostic_by_title["Routing config API"]["tone"], "warn")
        self.assertEqual(diagnostic_by_title["Auth files API"]["tone"], "good")
        self.assertEqual(diagnostic_by_title["Usage API"]["tone"], "good")
        self.assertEqual(diagnostic_by_title["Direct quota sampling"]["tone"], "warn")
        self.assertIn("warning", diagnostics["summary"])

    def test_build_dashboard_snapshot_keeps_non_plus_unknown_until_first_direct_sample(self):
        sampled_at = dt.datetime(2026, 4, 20, 12, 30, tzinfo=dt.timezone.utc).astimezone()
        snapshot = MODULE.build_dashboard_snapshot(
            health_payload={"status": "ok"},
            auth_files_payload={
                "files": [
                    {
                        "auth_index": "acct-plus",
                        "label": "account-slot",
                        "status": "active",
                        "updated_at": "2026-04-20T12:20:00+08:00",
                        "id_token": {"plan_type": "plus"},
                    },
                    {
                        "auth_index": "acct-enterprise",
                        "label": "account-slot",
                        "status": "active",
                        "updated_at": "2026-04-20T12:21:00+08:00",
                        "id_token": {"plan_type": "enterprise"},
                    },
                ]
            },
            usage_payload={"usage": {"total_requests": 0, "success_count": 0, "failure_count": 0, "total_tokens": 0, "apis": {}}},
            quota_payload={
                "status": "partial",
                "eligibleCount": 2,
                "sampledCount": 1,
                "freshCount": 1,
                "staleCount": 0,
                "cycleSeconds": 30,
                "completedCycle": False,
                "degraded": False,
                "attemptedKey": "acct-enterprise",
                "attemptError": None,
                "samples": {
                    "acct-plus": {
                        "sampledAt": dt.datetime(2026, 4, 20, 12, 29, 40, tzinfo=dt.timezone.utc).astimezone(),
                        "planType": "plus",
                        "windows": {
                            "5h": {"percent": 40, "resetAt": dt.datetime(2026, 4, 20, 16, 0, tzinfo=dt.timezone.utc).astimezone()},
                            "week": {"percent": 80, "resetAt": dt.datetime(2026, 4, 24, 0, 0, tzinfo=dt.timezone.utc).astimezone()},
                        },
                        "lastError": None,
                        "lastErrorAt": None,
                    },
                    "acct-enterprise": {},
                },
            },
            routing_payload={"routing": {"strategy": "round-robin"}},
            usage_stats_payload={"usage-statistics-enabled": True},
            request_log_payload={"request-log": True},
            logs_payload={"lines": []},
            sampled_at=sampled_at,
        )

        self.assertEqual(snapshot["summary"]["poolPill"], "1 Plus · 1 Non-Plus")
        self.assertEqual(snapshot["summary"]["fiveHourPill"], "5h 0.40 Plus")
        enterprise_account = next(account for account in snapshot["tabs"]["pool"]["accounts"] if account["title"] == "account-slot")
        self.assertEqual(enterprise_account["windows"][0]["valueText"], "Unknown")
        self.assertIn("Waiting for first direct sample.", enterprise_account["windows"][0]["note"])
        self.assertIn("Enterprise plan is shown in the grid but excluded from total 5h/weekly capacity.", enterprise_account["windows"][0]["note"])
        self.assertEqual(snapshot["tabs"]["pool"]["capacityWindows"][0]["knownUnitsText"], "0.40 Plus")

    def test_build_dashboard_snapshot_counts_weighted_capacity_in_live_like_mix(self):
        sampled_at = dt.datetime(2026, 4, 24, 15, 30, tzinfo=dt.timezone.utc).astimezone()
        plus_files = [
            {
                "auth_index": f"acct-plus-{index}",
                "label": f"plus-slot-{index}",
                "status": "active",
                "updated_at": "2026-04-24T23:20:00+08:00",
                "id_token": {"plan_type": "plus"},
            }
            for index in range(6)
        ]
        quota_samples = {
            f"acct-plus-{index}": {
                "sampledAt": dt.datetime(2026, 4, 24, 15, 29, 45, tzinfo=dt.timezone.utc).astimezone(),
                "planType": "plus",
                "windows": {
                    "5h": {"percent": 100, "resetAt": dt.datetime(2026, 4, 24, 19, 0, tzinfo=dt.timezone.utc).astimezone()},
                    "week": {"percent": 100, "resetAt": dt.datetime(2026, 4, 29, 0, 0, tzinfo=dt.timezone.utc).astimezone()},
                },
                "lastError": None,
                "lastErrorAt": None,
            }
            for index in range(6)
        }
        quota_samples["acct-team"] = {
            "sampledAt": dt.datetime(2026, 4, 24, 15, 29, 55, tzinfo=dt.timezone.utc).astimezone(),
            "planType": "team",
            "windows": {
                "5h": {"percent": 50, "resetAt": dt.datetime(2026, 4, 24, 19, 0, tzinfo=dt.timezone.utc).astimezone()},
                "week": {"percent": 75, "resetAt": dt.datetime(2026, 4, 29, 0, 0, tzinfo=dt.timezone.utc).astimezone()},
            },
            "lastError": None,
            "lastErrorAt": None,
        }
        quota_samples["acct-prolite"] = {
            "sampledAt": dt.datetime(2026, 4, 24, 15, 29, 58, tzinfo=dt.timezone.utc).astimezone(),
            "planType": "pro-lite",
            "windows": {
                "5h": {"percent": 50, "resetAt": dt.datetime(2026, 4, 24, 19, 0, tzinfo=dt.timezone.utc).astimezone()},
                "week": {"percent": 50, "resetAt": dt.datetime(2026, 4, 29, 0, 0, tzinfo=dt.timezone.utc).astimezone()},
            },
            "lastError": None,
            "lastErrorAt": None,
        }
        snapshot = MODULE.build_dashboard_snapshot(
            health_payload={"status": "ok"},
            auth_files_payload={
                "files": plus_files
                + [
                    {
                        "auth_index": "acct-team",
                        "label": "account-slot",
                        "status": "active",
                        "updated_at": "2026-04-24T23:25:00+08:00",
                        "id_token": {"plan_type": "team"},
                    },
                    {
                        "auth_index": "acct-prolite",
                        "label": "account-slot",
                        "status": "active",
                        "updated_at": "2026-04-24T23:26:00+08:00",
                        "id_token": {"plan_type": "pro_lite"},
                    }
                ]
            },
            usage_payload={"usage": {"total_requests": 0, "success_count": 0, "failure_count": 0, "total_tokens": 0, "apis": {}}},
            quota_payload={
                "status": "live",
                "eligibleCount": 8,
                "sampledCount": 8,
                "freshCount": 8,
                "staleCount": 0,
                "cycleSeconds": 30,
                "completedCycle": True,
                "degraded": False,
                "attemptedKey": "acct-prolite",
                "attemptError": None,
                "samples": quota_samples,
            },
            routing_payload={"routing": {"strategy": "round-robin", "session-affinity": True, "session-affinity-ttl": "1h"}},
            usage_stats_payload={"usage-statistics-enabled": True},
            request_log_payload={"request-log": True},
            logs_payload={"lines": []},
            sampled_at=sampled_at,
        )

        self.assertEqual(snapshot["summary"]["poolPill"], "6 Plus · 2 Non-Plus")
        self.assertEqual(snapshot["summary"]["fiveHourPill"], "5h 11.50 Plus")
        self.assertEqual(snapshot["summary"]["weeklyPill"], "Weekly 11.75 Plus")
        self.assertEqual(snapshot["tabs"]["pool"]["summary"], "6 Plus · 2 Non-Plus · 8 healthy · 0 issues")
        self.assertEqual(snapshot["tabs"]["pool"]["capacityWindows"][0]["plusTotal"], 6)
        self.assertEqual(snapshot["tabs"]["pool"]["capacityWindows"][0]["trackedTotal"], 8)
        self.assertEqual(snapshot["tabs"]["pool"]["capacityWindows"][0]["trackedUnits"], 17.0)
        self.assertEqual(snapshot["tabs"]["pool"]["capacityWindows"][0]["knownUnitsText"], "11.50 Plus")
        self.assertEqual(snapshot["tabs"]["pool"]["capacityWindows"][0]["knownBarPercent"], 68)
        self.assertEqual(snapshot["tabs"]["pool"]["stats"][1]["value"], "2")
        team_account = next(account for account in snapshot["tabs"]["pool"]["accounts"] if account["badge"] == "Team")
        self.assertEqual(team_account["windows"][0]["valueText"], "50%")
        self.assertNotIn("excluded", team_account["windows"][0]["note"])
        prolite_account = next(account for account in snapshot["tabs"]["pool"]["accounts"] if account["badge"] == "Pro Lite")
        self.assertEqual(prolite_account["windows"][0]["valueText"], "50%")
        self.assertNotIn("excluded", prolite_account["windows"][0]["note"])

    def test_build_dashboard_snapshot_removes_five_hour_capacity_when_weekly_is_exhausted(self):
        five_hour_reset = dt.datetime(2026, 4, 24, 20, 0, tzinfo=dt.timezone.utc).astimezone()
        weekly_reset = dt.datetime(2026, 4, 27, 9, 0, tzinfo=dt.timezone.utc).astimezone()
        snapshot = self.build_minimal_snapshot(
            auth_files=[
                {
                    "auth_index": "acct-plus",
                    "label": "account-slot",
                    "status": "active",
                    "id_token": {"plan_type": "plus"},
                }
            ],
            usage_details=[],
            quota_samples={
                "acct-plus": {
                    "sampledAt": dt.datetime(2026, 4, 24, 15, 29, 45, tzinfo=dt.timezone.utc).astimezone(),
                    "planType": "plus",
                    "windows": {
                        "5h": {"percent": 100, "resetAt": five_hour_reset},
                        "week": {"percent": 0, "resetAt": weekly_reset},
                    },
                    "lastError": None,
                    "lastErrorAt": None,
                }
            },
        )

        self.assertEqual(snapshot["summary"]["fiveHourPill"], "5h 0.00 Plus")
        five_hour = snapshot["tabs"]["pool"]["capacityWindows"][0]
        self.assertEqual(five_hour["knownUnitsText"], "0.00 Plus")
        self.assertEqual(five_hour["weeklyCappedCount"], 1)
        self.assertIn("Weekly-capped 1", five_hour["summary"])
        account = snapshot["tabs"]["pool"]["accounts"][0]
        self.assertEqual(account["windows"][0]["valueText"], "100%")
        self.assertEqual(account["windows"][1]["valueText"], "0%")
        self.assertEqual(account["windows"][0]["resetAt"], five_hour_reset.isoformat(timespec="seconds"))
        self.assertEqual(account["windows"][0]["displayResetAt"], account["windows"][1]["resetAt"])
        self.assertEqual(account["windows"][0]["displayResetSource"], "week")
        self.assertEqual(account["windows"][0]["displayResetLabel"], "Weekly reset")
        self.assertEqual(account["windows"][0]["displayRemainingText"], account["windows"][1]["remainingText"])
        self.assertIn("5h reset display uses the weekly reset", account["windows"][0]["note"])
        five_hour_reset_row = snapshot["tabs"]["resets"]["columns"][0]["items"][0]
        self.assertEqual(five_hour_reset_row["resetAt"], account["windows"][1]["resetAt"])
        self.assertEqual(five_hour_reset_row["remainingText"], account["windows"][1]["remainingText"])
        self.assertEqual(five_hour_reset_row["displayResetSource"], "week")
        self.assertIn("weekly reset", five_hour_reset_row["meta"])

    def test_build_dashboard_snapshot_caps_five_hour_capacity_from_weekly_multiplier(self):
        snapshot = self.build_minimal_snapshot(
            auth_files=[
                {
                    "auth_index": "acct-plus",
                    "label": "account-slot",
                    "status": "active",
                    "id_token": {"plan_type": "plus"},
                }
            ],
            usage_details=[],
            quota_samples={
                "acct-plus": {
                    "sampledAt": dt.datetime(2026, 4, 24, 15, 29, 45, tzinfo=dt.timezone.utc).astimezone(),
                    "planType": "plus",
                    "windows": {
                        "5h": {"percent": 100},
                        "week": {"percent": 10},
                    },
                    "lastError": None,
                    "lastErrorAt": None,
                }
            },
            weekly_to_five_hour_multiplier=3.5,
        )

        five_hour = snapshot["tabs"]["pool"]["capacityWindows"][0]
        self.assertEqual(snapshot["summary"]["fiveHourPill"], "5h 0.35 Plus")
        self.assertEqual(five_hour["knownUnitsText"], "0.35 Plus")
        self.assertEqual(five_hour["knownBarPercent"], 35)
        self.assertIn("Weekly-capped 1", five_hour["summary"])
        self.assertIn("weekly remaining times 3.50", snapshot["tabs"]["pool"]["footnote"])

    def test_build_dashboard_snapshot_defaults_to_six_times_weekly_multiplier(self):
        snapshot = self.build_minimal_snapshot(
            auth_files=[
                {
                    "auth_index": "acct-plus",
                    "label": "account-slot",
                    "status": "active",
                    "id_token": {"plan_type": "plus"},
                }
            ],
            usage_details=[],
            quota_samples={
                "acct-plus": {
                    "sampledAt": dt.datetime(2026, 4, 24, 15, 29, 45, tzinfo=dt.timezone.utc).astimezone(),
                    "planType": "plus",
                    "windows": {
                        "5h": {"percent": 100},
                        "week": {"percent": 10},
                    },
                    "lastError": None,
                    "lastErrorAt": None,
                }
            },
        )

        five_hour = snapshot["tabs"]["pool"]["capacityWindows"][0]
        self.assertEqual(snapshot["summary"]["fiveHourPill"], "5h 0.60 Plus")
        self.assertEqual(five_hour["knownUnitsText"], "0.60 Plus")
        self.assertEqual(five_hour["knownBarPercent"], 60)
        self.assertIn("Weekly-capped 1", five_hour["summary"])
        self.assertIn("weekly remaining times 6.00", snapshot["tabs"]["pool"]["footnote"])

    def test_build_dashboard_snapshot_allows_disabling_weekly_multiplier(self):
        snapshot = self.build_minimal_snapshot(
            auth_files=[
                {
                    "auth_index": "acct-plus",
                    "label": "account-slot",
                    "status": "active",
                    "id_token": {"plan_type": "plus"},
                }
            ],
            usage_details=[],
            quota_samples={
                "acct-plus": {
                    "sampledAt": dt.datetime(2026, 4, 24, 15, 29, 45, tzinfo=dt.timezone.utc).astimezone(),
                    "planType": "plus",
                    "windows": {
                        "5h": {"percent": 100},
                        "week": {"percent": 10},
                    },
                    "lastError": None,
                    "lastErrorAt": None,
                }
            },
            weekly_to_five_hour_multiplier=None,
        )

        five_hour = snapshot["tabs"]["pool"]["capacityWindows"][0]
        self.assertEqual(snapshot["summary"]["fiveHourPill"], "5h 1.00 Plus")
        self.assertEqual(five_hour["knownUnitsText"], "1.00 Plus")
        self.assertEqual(five_hour["knownBarPercent"], 100)
        self.assertNotIn("Weekly-capped", five_hour["summary"])
        self.assertIn("weekly exhaustion removes an account", snapshot["tabs"]["pool"]["footnote"])

    def test_build_dashboard_snapshot_exposes_inherit_and_unknown_fast_states(self):
        sampled_at = dt.datetime(2026, 4, 20, 12, 30, tzinfo=dt.timezone.utc).astimezone()
        base_usage = {"usage": {"total_requests": 0, "success_count": 0, "failure_count": 0, "total_tokens": 0, "apis": {}}}
        base_quota = {
            "status": "idle",
            "eligibleCount": 0,
            "sampledCount": 0,
            "freshCount": 0,
            "staleCount": 0,
            "cycleSeconds": 15,
            "completedCycle": False,
            "degraded": False,
            "attemptedKey": None,
            "attemptError": None,
            "samples": {},
        }
        inherit_snapshot = MODULE.build_dashboard_snapshot(
            health_payload={"status": "ok"},
            auth_files_payload={"files": []},
            usage_payload=base_usage,
            quota_payload=base_quota,
            routing_payload={"routing": {"strategy": "round-robin"}},
            usage_stats_payload={"usage-statistics-enabled": True},
            request_log_payload={"request-log": True},
            logs_payload={"lines": []},
            sampled_at=sampled_at,
        )
        unknown_snapshot = MODULE.build_dashboard_snapshot(
            health_payload={"status": "ok"},
            auth_files_payload={"files": []},
            usage_payload=base_usage,
            quota_payload=base_quota,
            routing_payload={"routing": {"strategy": "round-robin"}},
            usage_stats_payload={"usage-statistics-enabled": True},
            request_log_payload={"request-log": True},
            logs_payload={"lines": []},
            sampled_at=sampled_at,
            endpoint_errors=["routing: timed out"],
            source="partial",
        )

        self.assertEqual(inherit_snapshot["fastMode"]["state"], "inherit")
        self.assertEqual(inherit_snapshot["summary"]["fastPill"], "Fast Inherit")
        self.assertIn("not forcing fast", inherit_snapshot["fastMode"]["detail"])
        self.assertEqual(unknown_snapshot["fastMode"]["state"], "unknown")
        self.assertEqual(unknown_snapshot["summary"]["fastPill"], "Fast Unknown")
        self.assertIn("successful CPA config sample", unknown_snapshot["fastMode"]["detail"])

    def test_build_dashboard_snapshot_keeps_reset_scheduled_direct_exhaustion_out_of_alerts(self):
        sampled_at = dt.datetime(2026, 4, 20, 12, 30, tzinfo=dt.timezone.utc).astimezone()
        snapshot = MODULE.build_dashboard_snapshot(
            health_payload={"status": "ok"},
            auth_files_payload={
                "files": [
                    {
                        "auth_index": "acct-plus",
                        "label": "account-slot",
                        "status": "active",
                        "updated_at": "2026-04-20T12:20:00+08:00",
                        "id_token": {"plan_type": "plus"},
                    },
                    {
                        "auth_index": "acct-enterprise",
                        "label": "account-slot",
                        "status": "active",
                        "updated_at": "2026-04-20T12:21:00+08:00",
                        "id_token": {"plan_type": "enterprise"},
                    },
                ]
            },
            usage_payload={"usage": {"total_requests": 0, "success_count": 0, "failure_count": 0, "total_tokens": 0, "apis": {}}},
            quota_payload={
                "status": "live",
                "eligibleCount": 2,
                "sampledCount": 2,
                "freshCount": 2,
                "staleCount": 0,
                "cycleSeconds": 30,
                "completedCycle": True,
                "degraded": False,
                "attemptedKey": "acct-enterprise",
                "attemptError": None,
                "samples": {
                    "acct-plus": {
                        "sampledAt": dt.datetime(2026, 4, 20, 12, 29, 40, tzinfo=dt.timezone.utc).astimezone(),
                        "planType": "plus",
                        "windows": {
                            "5h": {"percent": 50, "resetAt": dt.datetime(2026, 4, 20, 16, 0, tzinfo=dt.timezone.utc).astimezone()},
                            "week": {"percent": 80, "resetAt": dt.datetime(2026, 4, 24, 0, 0, tzinfo=dt.timezone.utc).astimezone()},
                        },
                        "lastError": None,
                        "lastErrorAt": None,
                    },
                    "acct-enterprise": {
                        "sampledAt": dt.datetime(2026, 4, 20, 12, 29, 55, tzinfo=dt.timezone.utc).astimezone(),
                        "planType": "enterprise",
                        "windows": {
                            "5h": {"percent": 0, "resetAt": dt.datetime(2026, 4, 20, 16, 0, tzinfo=dt.timezone.utc).astimezone()},
                            "week": {"percent": 0, "resetAt": dt.datetime(2026, 4, 24, 0, 0, tzinfo=dt.timezone.utc).astimezone()},
                        },
                        "lastError": None,
                        "lastErrorAt": None,
                    },
                },
            },
            routing_payload={"routing": {"strategy": "round-robin"}},
            usage_stats_payload={"usage-statistics-enabled": True},
            request_log_payload={"request-log": True},
            logs_payload={"lines": []},
            sampled_at=sampled_at,
        )

        self.assertEqual(snapshot["summary"]["fiveHourPill"], "5h 0.50 Plus")
        self.assertEqual(snapshot["summary"]["weeklyPill"], "Weekly 0.80 Plus")
        enterprise_account = next(account for account in snapshot["tabs"]["pool"]["accounts"] if account["title"] == "account-slot")
        self.assertEqual(enterprise_account["statusLabel"], "Reset scheduled")
        self.assertEqual(enterprise_account["tone"], "warn")
        self.assertEqual(enterprise_account["windows"][0]["valueText"], "0%")
        self.assertIn("Enterprise plan is shown in the grid but excluded from total 5h/weekly capacity.", enterprise_account["windows"][0]["note"])
        self.assertEqual(snapshot["tabs"]["alerts"]["metrics"][1]["value"], "0")
        five_hour_reset_accounts = [row["account"] for row in snapshot["tabs"]["resets"]["columns"][0]["items"]]
        self.assertEqual(five_hour_reset_accounts, ["account-slot", "account-slot"])
        enterprise_reset = next(row for row in snapshot["tabs"]["resets"]["columns"][0]["items"] if row["account"] == "account-slot")
        self.assertEqual(enterprise_reset["valueText"], "0%")
        self.assertEqual(enterprise_reset["beijingTimeText"], "04-24 08:00")
        self.assertEqual(enterprise_reset["displayResetSource"], "week")
        self.assertIn("weekly reset", enterprise_reset["meta"])

    def test_build_dashboard_snapshot_keeps_hard_direct_exhaustion_in_alerts(self):
        sampled_at = dt.datetime(2026, 4, 20, 12, 30, tzinfo=dt.timezone.utc).astimezone()
        snapshot = self.build_minimal_snapshot(
            auth_files=[
                {
                    "auth_index": "acct-plus",
                    "label": "account-slot",
                    "status": "active",
                    "updated_at": "2026-04-20T12:20:00+08:00",
                    "id_token": {"plan_type": "plus"},
                }
            ],
            usage_details=[],
            quota_samples={
                "acct-plus": {
                    "sampledAt": sampled_at,
                    "planType": "plus",
                    "windows": {
                        "5h": {"percent": 0},
                        "week": {"percent": 80, "resetAt": dt.datetime(2026, 4, 24, 0, 0, tzinfo=dt.timezone.utc).astimezone()},
                    },
                    "lastError": None,
                    "lastErrorAt": None,
                }
            },
        )

        account = snapshot["tabs"]["pool"]["accounts"][0]
        self.assertEqual(account["statusLabel"], "Quota hit")
        self.assertEqual(account["tone"], "bad")
        self.assertEqual(snapshot["tabs"]["alerts"]["metrics"][1]["value"], "1")
        self.assertEqual(snapshot["tabs"]["alerts"]["items"][0]["badge"], "Quota")

    def test_build_dashboard_snapshot_filters_unknown_non_auth_json_entries(self):
        sampled_at = dt.datetime(2026, 4, 20, 12, 30, tzinfo=dt.timezone.utc).astimezone()
        snapshot = MODULE.build_dashboard_snapshot(
            health_payload={"status": "ok"},
            auth_files_payload={
                "files": [
                    {
                        "auth_index": "acct-plus",
                        "label": "account-slot",
                        "provider": "codex",
                        "type": "codex",
                        "status": "active",
                        "updated_at": "2026-04-20T12:20:00+08:00",
                        "id_token": {"plan_type": "plus"},
                    },
                    {
                        "auth_index": "snapshot-file",
                        "name": "usage-snapshot.json",
                        "id": "usage-snapshot.json",
                        "provider": "unknown",
                        "type": "unknown",
                        "status": "active",
                        "updated_at": "2026-04-20T12:21:00+08:00",
                    },
                ]
            },
            usage_payload={"usage": {"total_requests": 0, "success_count": 0, "failure_count": 0, "total_tokens": 0, "apis": {}}},
            quota_payload={
                "status": "warming",
                "eligibleCount": 1,
                "sampledCount": 0,
                "freshCount": 0,
                "staleCount": 0,
                "cycleSeconds": 15,
                "completedCycle": False,
                "degraded": False,
                "attemptedKey": None,
                "attemptError": None,
                "samples": {},
            },
            routing_payload={"routing": {"strategy": "round-robin"}},
            usage_stats_payload={"usage-statistics-enabled": True},
            request_log_payload={"request-log": True},
            logs_payload={"lines": []},
            sampled_at=sampled_at,
        )

        self.assertEqual(snapshot["summary"]["poolPill"], "1 Plus · 0 Non-Plus")
        self.assertEqual([account["title"] for account in snapshot["tabs"]["pool"]["accounts"]], ["account-slot"])
        self.assertEqual([item["title"] for item in snapshot["tabs"]["traffic"]["distribution"]], ["account-slot"])

    def test_build_unavailable_snapshot_has_monitor_alert(self):
        snapshot = MODULE.build_unavailable_snapshot("auth-files: connection refused")

        self.assertFalse(snapshot["available"])
        self.assertEqual(snapshot["source"], "unavailable")
        self.assertEqual(snapshot["summary"]["poolPill"], "Pool unavailable")
        self.assertEqual(snapshot["summary"]["fiveHourPill"], "5h unknown")
        self.assertEqual(snapshot["tabs"]["pool"]["title"], "Pool Capacity")
        self.assertEqual(snapshot["tabs"]["alerts"]["items"][0]["badge"], "Monitor")
        self.assertIn("connection refused", snapshot["statusText"])


class PageRenderingTests(unittest.TestCase):
    def test_render_page_references_specialized_pool_layout(self):
        page = MODULE.render_page(MODULE.build_unavailable_snapshot("usage: timed out"), refresh_seconds=15)

        self.assertIn('href="/monitor.css"', page)
        self.assertIn('src="/monitor.js"', page)
        self.assertNotIn('http-equiv="refresh"', page)
        self.assertIn("CODEX_QUOTA_MONITOR_BOOTSTRAP", page)
        self.assertIn("codex-quota-monitor-theme", page)
        self.assertIn('id="theme-toggle"', page)
        self.assertIn('id="theme-toggle-label"', page)
        self.assertIn('class="summary-rail"', page)
        self.assertIn('id="fast-pill"', page)
        self.assertIn('id="five-hour-pill"', page)
        self.assertIn('id="pool-capacity"', page)
        self.assertIn('id="pool-accounts"', page)
        self.assertIn('id="pool-recommendations"', page)
        self.assertIn('id="trends-windows"', page)
        self.assertIn('id="audit-items"', page)
        self.assertIn('id="diagnostics-items"', page)
        self.assertIn('id="usage-charts"', page)
        self.assertIn('id="usage-models"', page)
        self.assertIn(">Pool<", page)
        self.assertIn(">Trends<", page)
        self.assertIn(">Usage<", page)
        self.assertIn(">Audit<", page)
        self.assertIn(">Diagnostics<", page)
        self.assertIn(">Alerts<", page)

    def test_monitor_js_no_longer_renders_failed_chip(self):
        snapshot = MODULE.build_unavailable_snapshot("usage: timed out")
        monitor = DummyMonitor(snapshot)
        MODULE.MonitorRequestHandler.monitor = monitor
        server = ThreadingHTTPServer(("127.0.0.1", 0), MODULE.MonitorRequestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/monitor.js", timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers.get_content_type(), "application/javascript")
                script = response.read().decode("utf-8")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        render_signals = script.split("function renderAccountSignals(account) {", 1)[1].split(
            "function shouldShowWindowNote(windowData) {", 1
        )[0]
        self.assertIn("account.statusLabel", render_signals)
        self.assertNotIn("account.requests", render_signals)
        self.assertNotIn("account.tokens", render_signals)
        self.assertNotIn("account.failed", render_signals)
        self.assertNotIn('" fail"', render_signals)
        render_pool = script.split("function renderPoolAccounts(targetId, accounts) {", 1)[1].split(
            "function renderUsageCharts(targetId, charts) {", 1
        )[0]
        self.assertNotIn("account.note", render_pool)
        self.assertNotIn("account.meta", render_pool)


class DummyMonitor:
    def __init__(self, snapshot, refresh_seconds=15):
        self.snapshot = snapshot
        self.refresh_seconds = refresh_seconds

    def get_snapshot(self):
        return self.snapshot


class HandlerTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = MODULE.enhance_snapshot_with_history(
            MODULE.build_unavailable_snapshot("auth-files: connection refused")
        )
        MODULE.MonitorRequestHandler.monitor = DummyMonitor(self.snapshot)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), MODULE.MonitorRequestHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def test_root_healthz_api_and_assets(self):
        with urllib.request.urlopen(self.base_url + "/healthz", timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get_content_type(), "application/json")
            self.assertEqual(json.loads(response.read().decode("utf-8")), {"ok": True})

        with urllib.request.urlopen(self.base_url + "/api/status", timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get_content_type(), "application/json")
            payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(payload["source"], "unavailable")
            self.assertEqual(payload["fastMode"]["state"], "unknown")
            self.assertEqual(payload["summary"]["poolPill"], "Pool unavailable")
            self.assertEqual(payload["recommendations"]["bestCount"], 0)
            self.assertIn("trends", payload["tabs"])
            self.assertIn("audit", payload["tabs"])
            self.assertIn("diagnostics", payload["tabs"])
            self.assertEqual(payload["tabs"]["alerts"]["items"][0]["badge"], "Monitor")

        with urllib.request.urlopen(self.base_url + "/api/alerts", timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get_content_type(), "application/json")
            payload = json.loads(response.read().decode("utf-8"))
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["alertCount"], 1)
            self.assertEqual(payload["items"][0]["badge"], "Monitor")

        with urllib.request.urlopen(self.base_url + "/api/recommendations", timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get_content_type(), "application/json")
            payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(payload["summary"], self.snapshot["recommendations"]["summary"])
            self.assertEqual(payload["avoidCount"], 0)

        with urllib.request.urlopen(self.base_url + "/api/diagnostics", timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get_content_type(), "application/json")
            payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(payload["title"], "Diagnostics")
            self.assertIn("SQLite history", [item["title"] for item in payload["items"]])

        with urllib.request.urlopen(self.base_url + "/metrics", timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get_content_type(), "text/plain")
            payload = response.read().decode("utf-8")
            self.assertIn("codex_quota_monitor_snapshot_available 0", payload)
            self.assertIn('codex_quota_monitor_snapshot_source{source="unavailable"} 1', payload)
            self.assertIn("codex_quota_monitor_alert_count 1", payload)

        with urllib.request.urlopen(self.base_url + "/", timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get_content_type(), "text/html")
            page = response.read().decode("utf-8")
            self.assertIn('href="/monitor.css"', page)
            self.assertIn('src="/monitor.js"', page)
            self.assertIn("five-hour-pill", page)
            self.assertIn("theme-toggle", page)

        with urllib.request.urlopen(self.base_url + "/monitor.css", timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get_content_type(), "text/css")
            stylesheet = response.read().decode("utf-8")
            self.assertIn(':root[data-theme="dark"]', stylesheet)
            self.assertIn("@media (prefers-color-scheme: dark)", stylesheet)
            self.assertIn(".theme-toggle", stylesheet)
            self.assertIn(".capacity-grid", stylesheet)
            self.assertIn(".account-grid", stylesheet)
            self.assertIn(".account-chip", stylesheet)

        with urllib.request.urlopen(self.base_url + "/monitor.js", timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get_content_type(), "application/javascript")
            script = response.read().decode("utf-8")
            self.assertIn("renderPoolTab", script)
            self.assertIn("renderTrendsTab", script)
            self.assertIn("renderAuditTab", script)
            self.assertIn("renderDiagnosticsTab", script)
            self.assertIn("renderCapacityCards", script)
            self.assertIn("renderAccountSignals", script)
            self.assertIn("shouldShowWindowNote", script)
            self.assertIn("THEME_STORAGE_KEY", script)
            self.assertIn("initThemeToggle", script)
            self.assertIn("LAST_TAB_SIGNATURES", script)
            self.assertIn("window.setInterval(refreshSnapshot, REFRESH_MS);", script)
            self.assertIn("The page will keep the previous snapshot until the next retry.", script)


if __name__ == "__main__":
    unittest.main()
