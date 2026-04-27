import copy
import json
import logging
import threading
import time
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse

from .history import HistoryStore, enhance_snapshot_with_history, is_disabled_path
from .quota import QuotaSampler
from .snapshot import (
    DEFAULT_WEEKLY_TO_FIVE_HOUR_MULTIPLIER,
    build_dashboard_snapshot,
    build_unavailable_snapshot,
)
from .util import compact_error, count_label, join_url, now_local, safe_int
from .version import USER_AGENT
from .web import load_asset_payload, render_page


PROMETHEUS_SOURCES = ("live", "partial", "stale", "unavailable")


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


def text_response(handler, status_code, payload, *, content_type):
    bytes_response(handler, status_code, payload.encode("utf-8"), content_type=content_type)


def prometheus_escape_label(value):
    return str(value or "").replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def optional_number(value):
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def prometheus_labels(labels):
    labels = labels or {}
    if not labels:
        return ""
    parts = [
        f'{key}="{prometheus_escape_label(value)}"'
        for key, value in sorted(labels.items())
    ]
    return "{" + ",".join(parts) + "}"


def prometheus_sample(name, value, labels=None):
    number = optional_number(value)
    if number is None:
        return None
    return f"{name}{prometheus_labels(labels)} {number:g}"


def append_prometheus_sample(lines, name, value, labels=None):
    sample = prometheus_sample(name, value, labels)
    if sample is not None:
        lines.append(sample)


def render_prometheus_metrics(snapshot):
    snapshot = snapshot or {}
    lines = [
        "# HELP codex_quota_monitor_snapshot_available Whether the latest dashboard snapshot is available.",
        "# TYPE codex_quota_monitor_snapshot_available gauge",
    ]
    append_prometheus_sample(lines, "codex_quota_monitor_snapshot_available", 1 if snapshot.get("available") else 0)

    lines.extend(
        [
            "# HELP codex_quota_monitor_snapshot_source Current snapshot source as a one-hot gauge.",
            "# TYPE codex_quota_monitor_snapshot_source gauge",
        ]
    )
    current_source = str(snapshot.get("source") or "unavailable")
    for source in PROMETHEUS_SOURCES:
        append_prometheus_sample(
            lines,
            "codex_quota_monitor_snapshot_source",
            1 if current_source == source else 0,
            {"source": source},
        )

    gateway_ok = bool(snapshot.get("gatewayOk"))
    lines.extend(
        [
            "# HELP codex_quota_monitor_gateway_up Whether CLIProxyAPI gateway health is OK.",
            "# TYPE codex_quota_monitor_gateway_up gauge",
        ]
    )
    append_prometheus_sample(lines, "codex_quota_monitor_gateway_up", 1 if gateway_ok else 0)

    active_alert_count = safe_int((((snapshot.get("tabs") or {}).get("alerts") or {}).get("alertCount")))
    active_alert_count += len(snapshot.get("thresholdAlerts") or [])
    recommendations = snapshot.get("recommendations") or {}
    lines.extend(
        [
            "# HELP codex_quota_monitor_alert_count Active monitor alert count.",
            "# TYPE codex_quota_monitor_alert_count gauge",
        ]
    )
    append_prometheus_sample(lines, "codex_quota_monitor_alert_count", active_alert_count)

    for metric_name, key, help_text in (
        ("codex_quota_monitor_best_accounts", "bestCount", "Recommended best account count."),
        ("codex_quota_monitor_usable_accounts", "usableCount", "Recommended usable account count."),
        ("codex_quota_monitor_avoid_accounts", "avoidCount", "Recommended avoid account count."),
    ):
        lines.extend([f"# HELP {metric_name} {help_text}", f"# TYPE {metric_name} gauge"])
        append_prometheus_sample(lines, metric_name, recommendations.get(key, 0))

    lines.extend(
        [
            "# HELP codex_quota_monitor_capacity_known_plus_units Known remaining capacity in Plus units.",
            "# TYPE codex_quota_monitor_capacity_known_plus_units gauge",
            "# HELP codex_quota_monitor_capacity_tracked_plus_units Tracked capacity denominator in Plus units.",
            "# TYPE codex_quota_monitor_capacity_tracked_plus_units gauge",
            "# HELP codex_quota_monitor_capacity_unknown_accounts Accounts without known direct quota for this window.",
            "# TYPE codex_quota_monitor_capacity_unknown_accounts gauge",
            "# HELP codex_quota_monitor_capacity_exhausted_accounts Accounts exhausted for this window.",
            "# TYPE codex_quota_monitor_capacity_exhausted_accounts gauge",
            "# HELP codex_quota_monitor_capacity_stale_accounts Accounts with stale direct quota samples for this window.",
            "# TYPE codex_quota_monitor_capacity_stale_accounts gauge",
        ]
    )
    capacity_windows = (((snapshot.get("tabs") or {}).get("pool") or {}).get("capacityWindows") or [])
    for window in capacity_windows:
        labels = {"window": window.get("id") or window.get("label") or "unknown"}
        append_prometheus_sample(
            lines,
            "codex_quota_monitor_capacity_known_plus_units",
            window.get("knownUnits"),
            labels,
        )
        append_prometheus_sample(
            lines,
            "codex_quota_monitor_capacity_tracked_plus_units",
            window.get("trackedUnits"),
            labels,
        )
        append_prometheus_sample(
            lines,
            "codex_quota_monitor_capacity_unknown_accounts",
            window.get("unknownCount"),
            labels,
        )
        append_prometheus_sample(
            lines,
            "codex_quota_monitor_capacity_exhausted_accounts",
            window.get("exhaustedCount"),
            labels,
        )
        append_prometheus_sample(
            lines,
            "codex_quota_monitor_capacity_stale_accounts",
            window.get("staleCount"),
            labels,
        )

    return "\n".join(lines) + "\n"


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
    def __init__(
        self,
        management_base_url,
        gateway_health_url,
        auth_dir,
        refresh_seconds,
        logs_refresh_seconds,
        timeout_seconds,
        weekly_to_five_hour_multiplier=DEFAULT_WEEKLY_TO_FIVE_HOUR_MULTIPLIER,
        state_db="",
        history_write_seconds=60,
        history_retention_days=30,
        benchmark_summary_path="",
        alert_thresholds=None,
    ):
        self.management_base_url = management_base_url.rstrip("/")
        self.gateway_health_url = gateway_health_url
        self.auth_dir = auth_dir or ""
        self.refresh_seconds = refresh_seconds
        self.logs_refresh_seconds = logs_refresh_seconds or max(refresh_seconds * 4, 60)
        self.timeout_seconds = timeout_seconds
        self.weekly_to_five_hour_multiplier = weekly_to_five_hour_multiplier
        self.benchmark_summary_path = benchmark_summary_path or ""
        self.alert_thresholds = alert_thresholds or {}
        self.logger = logging.getLogger("codex-quota-monitor")
        self._lock = threading.Lock()
        self._last_snapshot = None
        self._last_refresh_monotonic = 0.0
        self._endpoint_cache = {}
        self._quota_sampler = QuotaSampler(self.auth_dir, refresh_seconds, timeout_seconds)
        self._history_store = (
            None
            if is_disabled_path(state_db)
            else HistoryStore(
                state_db,
                write_seconds=history_write_seconds,
                retention_days=history_retention_days,
            )
        )

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
                return self._enhance_snapshot(stale_snapshot)

            error_text = "; ".join(endpoint_errors) if endpoint_errors else "No CPA data found yet."
            self.logger.warning("no snapshot available yet: %s", error_text)
            return self._enhance_snapshot(build_unavailable_snapshot(error_text))

        sampled_candidates = [value for value in (auth_files_fetched_at, usage_fetched_at) if value is not None]
        sampled_at = min(sampled_candidates) if sampled_candidates else now_local()
        if auth_files_stale or usage_stale:
            source = "partial"

        quota_payload = self._quota_sampler.refresh((auth_files_payload or {}).get("files") or [], sampled_at)

        snapshot = build_dashboard_snapshot(
            health_payload=health_payload,
            auth_files_payload=auth_files_payload,
            usage_payload=usage_payload,
            quota_payload=quota_payload,
            routing_payload=routing_payload,
            usage_stats_payload=usage_stats_payload,
            request_log_payload=request_log_payload,
            logs_payload=logs_payload,
            sampled_at=sampled_at,
            endpoint_errors=endpoint_errors,
            source=source,
            weekly_to_five_hour_multiplier=self.weekly_to_five_hour_multiplier,
        )
        self.logger.info(
            "sample source=%s auth_files=%s quota_status=%s quota_fresh=%s/%s total_requests=%s total_tokens=%s alerts=%s",
            snapshot["source"],
            len((auth_files_payload or {}).get("files") or []),
            quota_payload["status"],
            quota_payload["freshCount"],
            quota_payload["eligibleCount"],
            snapshot["tabs"]["traffic"]["metrics"][0]["value"],
            safe_int((((usage_payload or {}).get("usage") or {}).get("total_tokens"))),
            snapshot["summary"]["alertsPill"],
        )
        return self._enhance_snapshot(snapshot)

    def _enhance_snapshot(self, snapshot):
        return enhance_snapshot_with_history(
            snapshot,
            history_store=self._history_store,
            benchmark_summary_path=self.benchmark_summary_path,
            alert_thresholds=self.alert_thresholds,
            weekly_to_five_hour_multiplier=self.weekly_to_five_hour_multiplier,
        )

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
                "User-Agent": USER_AGENT,
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

        if parsed.path == "/api/alerts":
            snapshot = self.monitor.get_snapshot()
            json_response(self, HTTPStatus.OK, snapshot.get("apiAlerts") or {})
            return

        if parsed.path == "/api/recommendations":
            snapshot = self.monitor.get_snapshot()
            json_response(self, HTTPStatus.OK, snapshot.get("recommendations") or {})
            return

        if parsed.path == "/api/diagnostics":
            snapshot = self.monitor.get_snapshot()
            json_response(self, HTTPStatus.OK, snapshot.get("diagnostics") or {})
            return

        if parsed.path == "/metrics":
            snapshot = self.monitor.get_snapshot()
            text_response(
                self,
                HTTPStatus.OK,
                render_prometheus_metrics(snapshot),
                content_type="text/plain; version=0.0.4; charset=utf-8",
            )
            return

        if parsed.path in ("/monitor.css", "/monitor.js"):
            asset_response(self, parsed.path.lstrip("/"))
            return

        if parsed.path == "/":
            snapshot = self.monitor.get_snapshot()
            html_response(self, HTTPStatus.OK, render_page(snapshot, self.monitor.refresh_seconds))
            return

        json_response(self, HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
