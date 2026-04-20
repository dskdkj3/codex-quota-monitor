import copy
import json
import logging
import threading
import time
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse

from .snapshot import build_dashboard_snapshot, build_unavailable_snapshot
from .util import compact_error, count_label, join_url, now_local, safe_int
from .web import load_asset_payload, render_page


def write_payload(handler, payload):
    try:
        handler.wfile.write(payload)
    except (BrokenPipeError, ConnectionResetError):
        logging.getLogger("codex-quota-monitor.http").info("client closed connection before response finished")


def bytes_response(handler, status_code, payload, *, content_type):
    handler.send_response(status_code)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    write_payload(handler, payload)


def json_response(handler, status_code, payload):
    bytes_response(
        handler,
        status_code,
        json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        content_type="application/json; charset=utf-8",
    )


def html_response(handler, status_code, payload):
    bytes_response(
        handler,
        status_code,
        payload.encode("utf-8"),
        content_type="text/html; charset=utf-8",
    )


def asset_response(handler, asset_name):
    payload, content_type = load_asset_payload(asset_name)
    bytes_response(handler, HTTPStatus.OK, payload, content_type=content_type)


def refresh_alerts_for_stale_snapshot(snapshot):
    alerts_tab = ((snapshot or {}).get("tabs") or {}).get("alerts") or {}
    existing_items = [
        item
        for item in (alerts_tab.get("items") or [])
        if item.get("kind") not in {"clean", "monitor"}
    ]
    existing_items.insert(
        0,
        {
            "kind": "monitor",
            "tone": "bad",
            "title": "CPA snapshot degraded",
            "badge": "Monitor",
            "meta": snapshot.get("sourceText") or "Cached CPA snapshot",
            "detail": snapshot.get("statusText") or "Fresh CPA sampling failed.",
        },
    )

    counts = {"auth": 0, "quota": 0, "monitor": 0}
    for item in existing_items:
        kind = item.get("kind")
        if kind in counts:
            counts[kind] += 1
    alert_count = sum(counts.values())

    alerts_tab["summary"] = count_label(alert_count, "alert")
    alerts_tab["metrics"] = [
        {"label": "Auth", "value": str(counts["auth"]), "detail": "disabled / unavailable / missing auth-file"},
        {"label": "Quota", "value": str(counts["quota"]), "detail": "explicit quota exhaustion"},
        {"label": "Monitor", "value": str(counts["monitor"]), "detail": "snapshot or gateway issues"},
        {"label": "Total", "value": str(alert_count), "detail": "items requiring attention"},
    ]
    alerts_tab["items"] = existing_items
    alerts_tab["footnote"] = (
        "Alerts are intentionally narrow: only hard auth failures, explicit quota exhaustion, "
        "and monitor data-source problems remain here."
    )
    snapshot["tabs"]["alerts"] = alerts_tab
    snapshot["summary"]["alertsPill"] = count_label(alert_count, "alert")
    return snapshot


class CPAMonitor:
    def __init__(self, management_base_url, gateway_health_url, refresh_seconds, logs_refresh_seconds, timeout_seconds):
        self.management_base_url = management_base_url.rstrip("/")
        self.gateway_health_url = gateway_health_url
        self.refresh_seconds = refresh_seconds
        self.logs_refresh_seconds = logs_refresh_seconds or max(refresh_seconds * 4, 60)
        self.timeout_seconds = timeout_seconds
        self.logger = logging.getLogger("codex-quota-monitor")
        self._lock = threading.Lock()
        self._last_snapshot = None
        self._last_refresh_monotonic = 0.0
        self._endpoint_cache = {}

    def get_snapshot(self):
        with self._lock:
            now_mono = time.monotonic()
            if self._last_snapshot and (now_mono - self._last_refresh_monotonic) < self.refresh_seconds:
                return copy.deepcopy(self._last_snapshot)

            snapshot = self._refresh_snapshot_locked()
            self._last_snapshot = snapshot
            self._last_refresh_monotonic = time.monotonic()
            return copy.deepcopy(snapshot)

    def _refresh_snapshot_locked(self):
        endpoint_errors = []
        source = "live"

        health_payload, _, _, health_error = self._load_json(
            "healthz",
            self.gateway_health_url,
            ttl_seconds=self.refresh_seconds,
        )
        if health_error:
            endpoint_errors.append("healthz: " + health_error)
            source = "partial"

        auth_files_payload, auth_files_stale, auth_files_fetched_at, auth_files_error = self._load_json(
            "auth-files",
            join_url(self.management_base_url, "/v0/management/auth-files"),
            ttl_seconds=self.refresh_seconds,
        )
        if auth_files_error:
            endpoint_errors.append("auth-files: " + auth_files_error)
            source = "partial"

        usage_payload, usage_stale, usage_fetched_at, usage_error = self._load_json(
            "usage",
            join_url(self.management_base_url, "/v0/management/usage"),
            ttl_seconds=self.refresh_seconds,
        )
        if usage_error:
            endpoint_errors.append("usage: " + usage_error)
            source = "partial"

        routing_payload, _, _, routing_error = self._load_json(
            "config",
            join_url(self.management_base_url, "/v0/management/config"),
            ttl_seconds=self.refresh_seconds,
            default_payload={"routing": {"strategy": "unknown", "session-affinity": False}},
        )
        if routing_error:
            endpoint_errors.append("routing: " + routing_error)
            source = "partial"

        usage_stats_payload, _, _, usage_stats_error = self._load_json(
            "usage-stats-enabled",
            join_url(self.management_base_url, "/v0/management/usage-statistics-enabled"),
            ttl_seconds=self.refresh_seconds,
            default_payload={"usage-statistics-enabled": False},
        )
        if usage_stats_error:
            endpoint_errors.append("usage-stats: " + usage_stats_error)
            source = "partial"

        request_log_payload = {"request-log": False}
        logs_payload = {"lines": []}

        if auth_files_payload is None or usage_payload is None:
            if self._last_snapshot:
                stale_snapshot = copy.deepcopy(self._last_snapshot)
                stale_snapshot["source"] = "stale"
                stale_snapshot["sourceText"] = "Cached CPA snapshot"
                stale_snapshot["statusText"] = "Fresh CPA sampling failed, so this page is showing the last complete snapshot."
                if endpoint_errors:
                    stale_snapshot["statusText"] += " " + "; ".join(endpoint_errors)
                stale_snapshot["error"] = "; ".join(endpoint_errors) if endpoint_errors else stale_snapshot.get("error")
                stale_snapshot = refresh_alerts_for_stale_snapshot(stale_snapshot)
                self.logger.warning("refresh failed, serving cached snapshot: %s", stale_snapshot["statusText"])
                return stale_snapshot

            error_text = "; ".join(endpoint_errors) if endpoint_errors else "No CPA data found yet."
            self.logger.warning("no snapshot available yet: %s", error_text)
            return build_unavailable_snapshot(error_text)

        sampled_candidates = [value for value in (auth_files_fetched_at, usage_fetched_at) if value is not None]
        sampled_at = min(sampled_candidates) if sampled_candidates else now_local()
        if auth_files_stale or usage_stale:
            source = "partial"

        snapshot = build_dashboard_snapshot(
            health_payload=health_payload,
            auth_files_payload=auth_files_payload,
            usage_payload=usage_payload,
            routing_payload=routing_payload,
            usage_stats_payload=usage_stats_payload,
            request_log_payload=request_log_payload,
            logs_payload=logs_payload,
            sampled_at=sampled_at,
            endpoint_errors=endpoint_errors,
            source=source,
        )
        self.logger.info(
            "sample source=%s auth_files=%s total_requests=%s total_tokens=%s alerts=%s",
            snapshot["source"],
            len((auth_files_payload or {}).get("files") or []),
            snapshot["tabs"]["traffic"]["metrics"][0]["value"],
            safe_int((((usage_payload or {}).get("usage") or {}).get("total_tokens"))),
            snapshot["summary"]["alertsPill"],
        )
        return snapshot

    def _load_json(self, cache_name, url, *, ttl_seconds, default_payload=None):
        cache = self._endpoint_cache.setdefault(cache_name, {})
        now_mono = time.monotonic()
        last_attempt = cache.get("last_attempt_monotonic", 0.0)

        if cache.get("payload") is not None and (now_mono - last_attempt) < ttl_seconds:
            return copy.deepcopy(cache["payload"]), False, cache.get("fetched_at"), None

        try:
            payload = self._fetch_json(url)
        except Exception as exc:  # pragma: no cover - runtime path
            cache["last_attempt_monotonic"] = now_mono
            error_text = compact_error(exc)
            if cache.get("payload") is not None:
                return copy.deepcopy(cache["payload"]), True, cache.get("fetched_at"), error_text
            if default_payload is not None:
                return copy.deepcopy(default_payload), True, None, error_text
            return None, True, None, error_text

        fetched_at = now_local()
        cache["payload"] = payload
        cache["fetched_at"] = fetched_at
        cache["last_attempt_monotonic"] = now_mono
        return copy.deepcopy(payload), False, fetched_at, None

    def _fetch_json(self, url):
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "Cache-Control": "no-store",
                "User-Agent": "codex-quota-monitor/0.2",
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return json.loads(response.read().decode(charset))


class MonitorRequestHandler(BaseHTTPRequestHandler):
    monitor = None

    def log_message(self, format_string, *args):
        logging.getLogger("codex-quota-monitor.http").info("%s - %s", self.client_address[0], format_string % args)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            json_response(self, HTTPStatus.OK, {"ok": True})
            return

        if parsed.path == "/api/status":
            snapshot = self.monitor.get_snapshot()
            json_response(self, HTTPStatus.OK, snapshot)
            return

        if parsed.path in ("/monitor.css", "/monitor.js"):
            asset_response(self, parsed.path.lstrip("/"))
            return

        if parsed.path == "/":
            snapshot = self.monitor.get_snapshot()
            html_response(self, HTTPStatus.OK, render_page(snapshot, self.monitor.refresh_seconds))
            return

        json_response(self, HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
