#!/usr/bin/env python3

import datetime as dt
import json
import os
import pathlib
import sys
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer


ROOT = pathlib.Path(os.environ.get("CODEX_QUOTA_MONITOR_ROOT", pathlib.Path(__file__).resolve().parent))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import codex_quota_monitor as MODULE


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


class PageRenderingTests(unittest.TestCase):
    def test_render_page_references_static_assets_and_tabs(self):
        page = MODULE.render_page(MODULE.build_unavailable_snapshot("usage: timed out"), refresh_seconds=15)

        self.assertIn('href="/monitor.css"', page)
        self.assertIn('src="/monitor.js"', page)
        self.assertIn("CPA_MONITOR_BOOTSTRAP", page)
        self.assertIn(">Pool<", page)
        self.assertIn(">Traffic<", page)
        self.assertIn(">Alerts<", page)


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
            self.assertEqual(payload["summary"]["poolPill"], "Pool unavailable")

        with urllib.request.urlopen(self.base_url + "/", timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get_content_type(), "text/html")
            page = response.read().decode("utf-8")
            self.assertIn('href="/monitor.css"', page)
            self.assertIn('src="/monitor.js"', page)
            self.assertIn("Pool", page)

        with urllib.request.urlopen(self.base_url + "/monitor.css", timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get_content_type(), "text/css")
            stylesheet = response.read().decode("utf-8")
            self.assertIn(".tab-panel", stylesheet)

        with urllib.request.urlopen(self.base_url + "/monitor.js", timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get_content_type(), "application/javascript")
            script = response.read().decode("utf-8")
            self.assertIn("renderSnapshot", script)


if __name__ == "__main__":
    unittest.main()
