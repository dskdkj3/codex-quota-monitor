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


class CliTests(unittest.TestCase):
    def test_parse_args_defaults_to_loopback(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            args = MODULE.parse_args([])

        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 4515)

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
    def build_minimal_snapshot(self, *, auth_files, usage_details, quota_samples=None, weekly_to_five_hour_multiplier=None):
        sampled_at = dt.datetime(2026, 4, 20, 12, 30, tzinfo=dt.timezone.utc).astimezone()
        total_tokens = sum(int((detail.get("tokens") or {}).get("total_tokens") or 0) for detail in usage_details)
        failure_count = sum(1 for detail in usage_details if detail.get("failed"))

        return MODULE.build_dashboard_snapshot(
            health_payload={"status": "ok"},
            auth_files_payload={"files": auth_files},
            usage_payload={
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
            quota_payload={
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
            routing_payload={"routing": {"strategy": "round-robin"}},
            usage_stats_payload={"usage-statistics-enabled": True},
            request_log_payload={"request-log": True},
            logs_payload={"lines": []},
            sampled_at=sampled_at,
            weekly_to_five_hour_multiplier=weekly_to_five_hour_multiplier,
        )

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
        self.assertEqual(traffic_tab["metrics"][0]["value"], "4")
        self.assertEqual(traffic_tab["metrics"][1]["value"], "75%")
        self.assertEqual(traffic_tab["metrics"][3]["value"], "Round Robin + Sticky")

        alerts_tab = snapshot["tabs"]["alerts"]
        self.assertEqual(alerts_tab["metrics"][0]["value"], "0")
        self.assertEqual(alerts_tab["metrics"][1]["value"], "0")
        self.assertEqual(alerts_tab["metrics"][2]["value"], "1")
        self.assertEqual(alerts_tab["items"][0]["badge"], "Monitor")
        self.assertNotIn("Quota", [item["badge"] for item in alerts_tab["items"]])
        self.assertIn("config: timed out", snapshot["statusText"])
        self.assertIn("direct Codex usage", snapshot["statusText"])

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
                        "week": {"percent": 0},
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
        self.assertEqual(enterprise_reset["beijingTimeText"], "04-21 00:00")

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
        self.assertNotIn('id="fast-pill"', page)
        self.assertIn('id="five-hour-pill"', page)
        self.assertIn('id="pool-capacity"', page)
        self.assertIn('id="pool-accounts"', page)
        self.assertIn(">Pool<", page)
        self.assertIn(">Traffic<", page)
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
            "function shouldShowAccountNote(account) {", 1
        )[0]
        self.assertIn('String(account.requests) + " req"', render_signals)
        self.assertIn('formatCompactNumber(account.tokens) + " tok"', render_signals)
        self.assertNotIn("account.failed", render_signals)
        self.assertNotIn('" fail"', render_signals)


class DummyMonitor:
    def __init__(self, snapshot, refresh_seconds=15):
        self.snapshot = snapshot
        self.refresh_seconds = refresh_seconds

    def get_snapshot(self):
        return self.snapshot


class HandlerTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = MODULE.build_unavailable_snapshot("auth-files: connection refused")
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
            self.assertEqual(payload["tabs"]["alerts"]["items"][0]["badge"], "Monitor")

        with urllib.request.urlopen(self.base_url + "/", timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get_content_type(), "text/html")
            page = response.read().decode("utf-8")
            self.assertIn('href="/monitor.css"', page)
            self.assertIn('src="/monitor.js"', page)
            self.assertIn("five-hour-pill", page)

        with urllib.request.urlopen(self.base_url + "/monitor.css", timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get_content_type(), "text/css")
            stylesheet = response.read().decode("utf-8")
            self.assertIn(".capacity-grid", stylesheet)
            self.assertIn(".account-grid", stylesheet)
            self.assertIn(".account-chip", stylesheet)

        with urllib.request.urlopen(self.base_url + "/monitor.js", timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get_content_type(), "application/javascript")
            script = response.read().decode("utf-8")
            self.assertIn("renderPoolTab", script)
            self.assertIn("renderCapacityCards", script)
            self.assertIn("renderAccountSignals", script)
            self.assertIn("shouldShowWindowNote", script)
            self.assertIn("LAST_TAB_SIGNATURES", script)
            self.assertIn("window.setInterval(refreshSnapshot, REFRESH_MS);", script)
            self.assertIn("The page will keep the previous snapshot until the next retry.", script)


if __name__ == "__main__":
    unittest.main()
