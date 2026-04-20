#!/usr/bin/env python3

import argparse
import copy
import datetime as dt
import html
import json
import logging
import os
import string
import threading
import time
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


BENIGN_LOG_PATTERNS = (
    "/metrics",
    '"/favicon.ico"',
    "/v0/management/system/info",
    "/v0/management/version-check",
    "/v0/management/health",
    "/v0/management/status",
    "/v0/management/models",
    "/v0/management/channels",
    "/v0/management/stats",
    '401 |            0s |       127.0.0.1 | get     "/v1/models"',
)
ALERT_LOG_PATTERNS = (
    "[warn ]",
    "[error]",
    " failed ",
    " 500 |",
    " 401 |",
)
EMPTY_TAB = {
    "title": "",
    "summary": "",
    "stats": [],
    "items": [],
    "footnote": "",
}
PAGE_TEMPLATE = string.Template(
    """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
    <meta http-equiv="refresh" content="$meta_refresh">
    <title>CPA Pool Monitor</title>
    <style>
      :root {
        --paper: #f5f3eb;
        --ink: #101010;
        --shadow: #c8c3b6;
        --line: #242424;
        --quiet: #5b5750;
        --soft: #ece7dc;
        --alert: #e9ddd1;
      }

      * {
        box-sizing: border-box;
      }

      body {
        margin: 0;
        padding: 18px 14px 24px;
        background: linear-gradient(180deg, #fbfaf5 0%, var(--paper) 100%);
        color: var(--ink);
        font-family: "Palatino Linotype", "Book Antiqua", Georgia, serif;
      }

      .sheet {
        max-width: 760px;
        margin: 0 auto;
      }

      .hero,
      .panel {
        border: 3px solid var(--line);
        background: rgba(255, 255, 255, 0.83);
        box-shadow: 6px 6px 0 var(--shadow);
      }

      .hero {
        padding: 16px 16px 14px;
      }

      .hero-kicker,
      .eyebrow {
        margin: 0;
        font-size: 13px;
        font-weight: 700;
        letter-spacing: 0.16em;
        text-transform: uppercase;
      }

      .hero-title {
        margin: 8px 0 0;
        font-size: 48px;
        line-height: 0.94;
      }

      .hero-subtitle {
        margin: 10px 0 0;
        font-size: 18px;
        color: var(--quiet);
      }

      .pill-row {
        display: flex;
        gap: 10px;
        flex-wrap: wrap;
        margin-top: 14px;
      }

      .pill {
        display: inline-flex;
        align-items: center;
        min-height: 34px;
        padding: 6px 12px;
        border: 2px solid var(--line);
        background:
          repeating-linear-gradient(
            -45deg,
            rgba(16, 16, 16, 0.04) 0,
            rgba(16, 16, 16, 0.04) 8px,
            rgba(255, 255, 255, 0.36) 8px,
            rgba(255, 255, 255, 0.36) 16px
          );
        font-size: 16px;
        font-weight: 700;
      }

      .hero-subline {
        margin: 14px 0 0;
        font-size: 16px;
        color: var(--quiet);
      }

      .stack {
        display: grid;
        gap: 14px;
        margin-top: 14px;
      }

      .panel {
        padding: 14px 14px 16px;
      }

      .status-main {
        margin: 8px 0 0;
        font-size: 22px;
        font-weight: 700;
      }

      .status-sub {
        margin: 8px 0 0;
        font-size: 16px;
        color: var(--quiet);
      }

      .status-copy {
        margin: 12px 0 0;
        font-size: 18px;
        line-height: 1.4;
      }

      .status-panel.is-alert {
        background: var(--alert);
      }

      .tab-bar {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 10px;
      }

      .tab {
        border: 3px solid var(--line);
        background: rgba(255, 255, 255, 0.78);
        color: var(--ink);
        padding: 12px 8px;
        text-align: center;
        text-decoration: none;
        font-size: 18px;
        font-weight: 700;
      }

      .tab.is-active {
        background: var(--ink);
        color: #faf8f1;
      }

      .tab-panel {
        display: none;
        gap: 12px;
        max-height: min(62vh, 560px);
        overflow: auto;
      }

      .tab-panel.is-active {
        display: grid;
      }

      .tab-title {
        margin: 8px 0 0;
        font-size: 28px;
      }

      .tab-summary,
      .tab-footnote {
        margin: 8px 0 0;
        font-size: 16px;
        color: var(--quiet);
      }

      .stats-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
      }

      .stat {
        border: 2px solid var(--line);
        background: rgba(255, 255, 255, 0.82);
        padding: 10px 12px;
      }

      .stat-label {
        font-size: 12px;
        font-weight: 700;
        letter-spacing: 0.12em;
        text-transform: uppercase;
      }

      .stat-value {
        margin-top: 6px;
        font-size: 28px;
        font-weight: 700;
        line-height: 1;
      }

      .item-list {
        display: grid;
        gap: 10px;
      }

      .item {
        border: 2px solid var(--line);
        background: rgba(255, 255, 255, 0.82);
        padding: 12px;
      }

      .item-warn {
        background: #f1eadf;
      }

      .item-bad {
        background: #eddcd4;
      }

      .item-head {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        gap: 12px;
      }

      .item-title {
        margin: 0;
        font-size: 22px;
        line-height: 1.1;
      }

      .badge {
        border: 2px solid var(--line);
        background: var(--soft);
        padding: 2px 8px;
        font-size: 14px;
        font-weight: 700;
        white-space: nowrap;
      }

      .item-meta,
      .item-detail,
      .item-note {
        margin: 8px 0 0;
        font-size: 16px;
        line-height: 1.35;
      }

      .item-meta {
        color: var(--quiet);
      }

      .item-note {
        font-style: italic;
      }

      .bar {
        height: 12px;
        margin-top: 10px;
        border: 2px solid var(--line);
        background:
          linear-gradient(90deg, rgba(16, 16, 16, 0.1), rgba(16, 16, 16, 0.02)),
          linear-gradient(180deg, #ffffff, #ebe7dd);
        overflow: hidden;
      }

      .bar-fill {
        height: 100%;
        background:
          repeating-linear-gradient(
            90deg,
            rgba(16, 16, 16, 0.96) 0,
            rgba(16, 16, 16, 0.96) 16px,
            rgba(16, 16, 16, 0.84) 16px,
            rgba(16, 16, 16, 0.84) 26px
          );
      }

      .empty {
        margin: 0;
        font-size: 18px;
      }

      @media (max-width: 560px) {
        body {
          padding: 12px 9px 20px;
        }

        .hero,
        .panel {
          box-shadow: none;
        }

        .hero-title {
          font-size: 38px;
        }

        .tab {
          font-size: 16px;
          padding: 10px 6px;
        }

        .tab-title {
          font-size: 24px;
        }

        .stat-value {
          font-size: 24px;
        }

        .item-title {
          font-size: 20px;
        }
      }
    </style>
  </head>
  <body>
    <main class="sheet">
      <section class="hero">
        <p class="hero-kicker">e-ink View</p>
        <h1 class="hero-title">CPA Pool</h1>
        <p class="hero-subtitle">A tabbed CLIProxyAPI dashboard tuned for glance checks on e-ink.</p>
        <div class="pill-row">
          <span class="pill" id="health-pill">Loading gateway</span>
          <span class="pill" id="pool-pill">Loading pool</span>
          <span class="pill" id="alerts-pill">Loading alerts</span>
        </div>
        <p class="hero-subline" id="hero-subline">Waiting for the first CPA snapshot.</p>
      </section>

      <section class="stack">
        <section class="panel status-panel" id="status-panel">
          <p class="eyebrow">Status</p>
          <div class="status-main" id="source-text">Waiting for data</div>
          <div class="status-sub" id="sampled-at">No sample yet</div>
          <p class="status-copy" id="status-text">The dashboard will poll the local CPA management API automatically.</p>
        </section>

        <nav class="tab-bar" aria-label="Dashboard tabs">
          <a class="tab" id="tab-button-pool" href="#pool" data-tab="pool">Pool</a>
          <a class="tab" id="tab-button-traffic" href="#traffic" data-tab="traffic">Traffic</a>
          <a class="tab" id="tab-button-alerts" href="#alerts" data-tab="alerts">Alerts</a>
        </nav>

        <section class="panel tab-panel" id="tab-panel-pool">
          <p class="eyebrow">Pool</p>
          <h2 class="tab-title" id="tab-title-pool">Loading</h2>
          <p class="tab-summary" id="tab-summary-pool"></p>
          <div class="stats-grid" id="tab-stats-pool"></div>
          <div class="item-list" id="tab-items-pool"></div>
          <p class="tab-footnote" id="tab-footnote-pool"></p>
        </section>

        <section class="panel tab-panel" id="tab-panel-traffic">
          <p class="eyebrow">Traffic</p>
          <h2 class="tab-title" id="tab-title-traffic">Loading</h2>
          <p class="tab-summary" id="tab-summary-traffic"></p>
          <div class="stats-grid" id="tab-stats-traffic"></div>
          <div class="item-list" id="tab-items-traffic"></div>
          <p class="tab-footnote" id="tab-footnote-traffic"></p>
        </section>

        <section class="panel tab-panel" id="tab-panel-alerts">
          <p class="eyebrow">Alerts</p>
          <h2 class="tab-title" id="tab-title-alerts">Loading</h2>
          <p class="tab-summary" id="tab-summary-alerts"></p>
          <div class="stats-grid" id="tab-stats-alerts"></div>
          <div class="item-list" id="tab-items-alerts"></div>
          <p class="tab-footnote" id="tab-footnote-alerts"></p>
        </section>
      </section>
    </main>

    <noscript>
      <p>This dashboard needs JavaScript for tab switching and live refresh.</p>
    </noscript>

    <script>
      var INITIAL_SNAPSHOT = $initial_snapshot;
      var REFRESH_MS = $refresh_ms;
      var TAB_NAMES = ["pool", "traffic", "alerts"];
      var ACTIVE_TAB = "pool";

      function text(value, fallback) {
        if (typeof value === "string" && value.length > 0) {
          return value;
        }
        return fallback;
      }

      function escapeHtml(value) {
        return text(String(value), "")
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;")
          .replace(/'/g, "&#39;");
      }

      function tabFromHash() {
        var hash = (window.location.hash || "").replace(/^#/, "");
        for (var index = 0; index < TAB_NAMES.length; index += 1) {
          if (TAB_NAMES[index] === hash) {
            return hash;
          }
        }
        return "pool";
      }

      function setActiveTab(name, updateHash) {
        ACTIVE_TAB = name;
        for (var index = 0; index < TAB_NAMES.length; index += 1) {
          var tabName = TAB_NAMES[index];
          var button = document.getElementById("tab-button-" + tabName);
          var panel = document.getElementById("tab-panel-" + tabName);
          var isActive = tabName === name;
          if (button) {
            button.className = isActive ? "tab is-active" : "tab";
          }
          if (panel) {
            panel.className = isActive ? "panel tab-panel is-active" : "panel tab-panel";
          }
        }
        if (updateHash && window.location.hash !== "#" + name) {
          window.location.hash = name;
        }
      }

      function renderStats(targetId, stats) {
        var target = document.getElementById(targetId);
        var safeStats = stats && stats.length ? stats : [];
        var htmlParts = [];

        if (!safeStats.length) {
          target.innerHTML = "";
          return;
        }

        for (var index = 0; index < safeStats.length; index += 1) {
          var stat = safeStats[index] || {};
          htmlParts.push(
            '<article class="stat">' +
              '<div class="stat-label">' + escapeHtml(text(stat.label, "Metric")) + "</div>" +
              '<div class="stat-value">' + escapeHtml(text(stat.value, "n/a")) + "</div>" +
            "</article>"
          );
        }

        target.innerHTML = htmlParts.join("");
      }

      function renderItems(targetId, items, emptyMessage) {
        var target = document.getElementById(targetId);
        var safeItems = items && items.length ? items : [];
        var htmlParts = [];

        if (!safeItems.length) {
          target.innerHTML = '<article class="item"><p class="empty">' + escapeHtml(emptyMessage) + "</p></article>";
          return;
        }

        for (var index = 0; index < safeItems.length; index += 1) {
          var item = safeItems[index] || {};
          var tone = text(item.tone, "neutral");
          var noteHtml = item.note ? '<p class="item-note">' + escapeHtml(item.note) + "</p>" : "";
          var detailHtml = item.detail ? '<p class="item-detail">' + escapeHtml(item.detail) + "</p>" : "";
          var barHtml = "";

          if (typeof item.barPercent === "number") {
            var width = item.barPercent;
            if (width < 0) {
              width = 0;
            }
            if (width > 100) {
              width = 100;
            }
            barHtml =
              '<div class="bar" aria-hidden="true">' +
                '<div class="bar-fill" style="width: ' + width + '%"></div>' +
              "</div>";
          }

          htmlParts.push(
            '<article class="item item-' + escapeHtml(tone) + '">' +
              '<div class="item-head">' +
                '<h3 class="item-title">' + escapeHtml(text(item.title, "Untitled")) + "</h3>" +
                '<span class="badge">' + escapeHtml(text(item.badge, "")) + "</span>" +
              "</div>" +
              '<p class="item-meta">' + escapeHtml(text(item.meta, "")) + "</p>" +
              detailHtml +
              noteHtml +
              barHtml +
            "</article>"
          );
        }

        target.innerHTML = htmlParts.join("");
      }

      function renderTab(tabName, tabData) {
        var safeTab = tabData || {};
        document.getElementById("tab-title-" + tabName).textContent = text(safeTab.title, "Unavailable");
        document.getElementById("tab-summary-" + tabName).textContent = text(safeTab.summary, "");
        document.getElementById("tab-footnote-" + tabName).textContent = text(safeTab.footnote, "");
        renderStats("tab-stats-" + tabName, safeTab.stats || []);
        renderItems("tab-items-" + tabName, safeTab.items || [], "Nothing to show in this tab yet.");
      }

      function renderSnapshot(snapshot) {
        var safeSnapshot = snapshot || {};
        var summary = safeSnapshot.summary || {};
        var tabs = safeSnapshot.tabs || {};
        var statusPanel = document.getElementById("status-panel");

        document.getElementById("health-pill").textContent = text(summary.gatewayPill, "Gateway unknown");
        document.getElementById("pool-pill").textContent = text(summary.poolPill, "Pool unavailable");
        document.getElementById("alerts-pill").textContent = text(summary.alertsPill, "Alerts unknown");
        document.getElementById("hero-subline").textContent = text(summary.subline, "Waiting for usage totals.");

        document.getElementById("source-text").textContent = text(safeSnapshot.sourceText, "No snapshot");
        document.getElementById("sampled-at").textContent = text(safeSnapshot.sampledAtText, "No sample yet");
        document.getElementById("status-text").textContent = text(safeSnapshot.statusText, "No status available");

        if (!safeSnapshot.available || safeSnapshot.source !== "live") {
          statusPanel.className = "panel status-panel is-alert";
        } else {
          statusPanel.className = "panel status-panel";
        }

        renderTab("pool", tabs.pool || {});
        renderTab("traffic", tabs.traffic || {});
        renderTab("alerts", tabs.alerts || {});
        setActiveTab(tabFromHash(), false);
      }

      function refreshSnapshot() {
        var request = new XMLHttpRequest();
        request.open("GET", "/api/status", true);
        request.setRequestHeader("Cache-Control", "no-store");
        request.onreadystatechange = function () {
          if (request.readyState !== 4) {
            return;
          }

          if (request.status >= 200 && request.status < 300) {
            try {
              renderSnapshot(JSON.parse(request.responseText));
            } catch (error) {
              document.getElementById("status-panel").className = "panel status-panel is-alert";
              document.getElementById("status-text").textContent =
                "Refresh returned unreadable data. The page kept the previous snapshot.";
            }
            return;
          }

          document.getElementById("status-panel").className = "panel status-panel is-alert";
          document.getElementById("status-text").textContent =
            "Refresh failed. The page will keep the previous snapshot until the next retry.";
        };
        request.send(null);
      }

      window.onhashchange = function () {
        setActiveTab(tabFromHash(), false);
      };

      renderSnapshot(INITIAL_SNAPSHOT);
      setActiveTab(tabFromHash(), false);
      window.setInterval(refreshSnapshot, REFRESH_MS);
    </script>
  </body>
</html>
"""
)


def parse_args():
    parser = argparse.ArgumentParser(description="Serve a e-ink-friendly CLIProxyAPI pool monitor.")
    parser.add_argument("--host", default=os.environ.get("CODEX_MONITOR_HOST", "0.0.0.0"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("CODEX_MONITOR_PORT", "4515")),
    )
    parser.add_argument(
        "--refresh-seconds",
        type=int,
        default=int(os.environ.get("CODEX_MONITOR_REFRESH_SECONDS", "15")),
    )
    parser.add_argument(
        "--logs-refresh-seconds",
        type=int,
        default=int(os.environ.get("CODEX_MONITOR_LOGS_REFRESH_SECONDS", "0")),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=float(os.environ.get("CODEX_MONITOR_TIMEOUT_SECONDS", "5")),
    )
    parser.add_argument(
        "--management-base-url",
        default=os.environ.get("CODEX_MONITOR_MANAGEMENT_BASE_URL", "http://127.0.0.1:8318"),
    )
    parser.add_argument(
        "--gateway-health-url",
        default=os.environ.get("CODEX_MONITOR_GATEWAY_HEALTH_URL", "http://127.0.0.1:8317/healthz"),
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("CODEX_MONITOR_LOG_LEVEL", "INFO"),
    )
    return parser.parse_args()


def now_local():
    return dt.datetime.now(dt.timezone.utc).astimezone()


def iso_timestamp(value):
    return value.isoformat(timespec="seconds")


def display_timestamp(value):
    return value.strftime("%Y-%m-%d %H:%M")


def compact_error(message, limit=180):
    text = " ".join(str(message).split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def parse_timestamp(value):
    if not value:
        return None

    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone()


def display_compact_timestamp(value, *, reference=None):
    if value is None:
        return "n/a"

    reference_value = reference or now_local()
    if value.date() == reference_value.date():
        return value.strftime("%H:%M")
    return value.strftime("%m-%d %H:%M")


def safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def format_count(value):
    return f"{safe_int(value):,}"


def format_tokens(value):
    number = safe_int(value)
    if number >= 1_000_000_000:
        return f"{number / 1_000_000_000:.2f}B".rstrip("0").rstrip(".")
    if number >= 1_000_000:
        return f"{number / 1_000_000:.2f}M".rstrip("0").rstrip(".")
    if number >= 1_000:
        return f"{number / 1_000:.1f}K".rstrip("0").rstrip(".")
    return str(number)


def format_percent(numerator, denominator):
    if denominator <= 0:
        return "n/a"
    return f"{int(round((float(numerator) / float(denominator)) * 100))}%"


def format_share_percent(metric_value, total_value):
    if total_value <= 0:
        return 0
    share = int(round((float(metric_value) / float(total_value)) * 100))
    return max(0, min(100, share))


def count_label(value, noun):
    number = safe_int(value)
    suffix = noun if number == 1 else noun + "s"
    return f"{number} {suffix}"


def titleize_slug(value, fallback="Unknown"):
    text = str(value or "").replace("_", " ").replace("-", " ").strip()
    if not text:
        return fallback
    return text.title()


def trim_text(value, limit=180):
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def join_url(base_url, path):
    return base_url.rstrip("/") + path


def auth_key(auth_file):
    if auth_file.get("auth_index"):
        return str(auth_file["auth_index"])
    for field in ("name", "id", "email", "label", "account"):
        if auth_file.get(field):
            return str(auth_file[field])
    return "unknown"


def auth_label(auth_file, usage_entry=None):
    for field in ("label", "email", "account", "name", "id"):
        if auth_file.get(field):
            return str(auth_file[field])
    if usage_entry:
        sources = usage_entry.get("sources") or []
        if sources:
            return sources[0]
    return "Unknown account"


def auth_plan(auth_file):
    plan_type = ((auth_file.get("id_token") or {}).get("plan_type") or auth_file.get("plan_type") or "").strip()
    return titleize_slug(plan_type, fallback="Unknown")


def auth_updated_at(auth_file):
    return parse_timestamp(auth_file.get("updated_at") or auth_file.get("modtime") or auth_file.get("created_at"))


def auth_health(auth_file, usage_entry):
    disabled = bool(auth_file.get("disabled"))
    unavailable = bool(auth_file.get("unavailable"))
    status = str(auth_file.get("status") or "").strip()
    status_message = str(auth_file.get("status_message") or "").strip()
    failed_requests = safe_int((usage_entry or {}).get("failed"))

    if disabled:
        return "bad", "Disabled", status_message
    if unavailable:
        return "bad", "Unavailable", status_message
    if status and status.lower() != "active":
        return "warn", titleize_slug(status, fallback="Unknown"), status_message
    if status_message:
        return "warn", "Active", status_message
    if failed_requests > 0:
        return "warn", "Active", ""
    return "good", "Active", ""


def activity_text(timestamp):
    if timestamp is None:
        return "idle"
    return "hit " + display_compact_timestamp(timestamp)


def parse_log_line(line):
    parts = str(line).split("] ", 2)
    if len(parts) >= 3:
        timestamp_text = parts[0].lstrip("[")
        timestamp = parse_timestamp(timestamp_text)
        remainder = parts[2].strip()
        if remainder.startswith("[") and "] " in remainder:
            remainder = remainder.split("] ", 1)[1].strip()
        return timestamp, remainder
    return None, str(line).strip()


def build_usage_index(usage_payload):
    usage_root = (usage_payload or {}).get("usage") or {}
    accounts = {}
    failed_items = []

    for api_entry in (usage_root.get("apis") or {}).values():
        for model_id, model_entry in (api_entry.get("models") or {}).items():
            for detail in model_entry.get("details") or []:
                key = str(detail.get("auth_index") or detail.get("source") or model_id or "unknown")
                timestamp = parse_timestamp(detail.get("timestamp"))
                tokens = safe_int((detail.get("tokens") or {}).get("total_tokens"))
                entry = accounts.setdefault(
                    key,
                    {
                        "authIndex": detail.get("auth_index") or "",
                        "sources": set(),
                        "models": set(),
                        "requests": 0,
                        "failed": 0,
                        "tokens": 0,
                        "recentTimestamp": None,
                    },
                )
                source = str(detail.get("source") or "").strip()
                if source:
                    entry["sources"].add(source)
                if model_id:
                    entry["models"].add(model_id)
                entry["requests"] += 1
                entry["tokens"] += tokens
                if detail.get("failed"):
                    entry["failed"] += 1
                    failed_items.append(
                        {
                            "timestamp": timestamp,
                            "source": source or key,
                            "model": model_id,
                            "authIndex": str(detail.get("auth_index") or ""),
                            "tokens": tokens,
                        }
                    )
                if timestamp and (entry["recentTimestamp"] is None or timestamp > entry["recentTimestamp"]):
                    entry["recentTimestamp"] = timestamp

    normalized_accounts = {}
    for key, value in accounts.items():
        normalized_accounts[key] = {
            "authIndex": value["authIndex"],
            "sources": sorted(value["sources"]),
            "models": sorted(value["models"]),
            "requests": value["requests"],
            "failed": value["failed"],
            "tokens": value["tokens"],
            "recentTimestamp": value["recentTimestamp"],
        }

    failed_items.sort(key=lambda item: item["timestamp"] or dt.datetime.min.replace(tzinfo=dt.timezone.utc), reverse=True)

    return {
        "totals": {
            "totalRequests": safe_int(usage_root.get("total_requests")),
            "successCount": safe_int(usage_root.get("success_count")),
            "failureCount": safe_int(usage_root.get("failure_count")),
            "totalTokens": safe_int(usage_root.get("total_tokens")),
        },
        "accounts": normalized_accounts,
        "failedItems": failed_items,
        "requestsByHour": (usage_payload or {}).get("requests_by_hour") or {},
        "requestsByDay": (usage_payload or {}).get("requests_by_day") or {},
        "tokensByHour": (usage_payload or {}).get("tokens_by_hour") or {},
        "tokensByDay": (usage_payload or {}).get("tokens_by_day") or {},
    }


def build_log_alerts(logs_payload):
    lines = (logs_payload or {}).get("lines") or []
    alerts = []
    seen = set()

    for line in reversed(lines):
        lowered = str(line).lower()
        if any(pattern in lowered for pattern in BENIGN_LOG_PATTERNS):
            continue
        if not any(pattern in lowered for pattern in ALERT_LOG_PATTERNS):
            continue
        if line in seen:
            continue
        seen.add(line)

        timestamp, remainder = parse_log_line(line)
        tone = "bad" if "[error]" in lowered or " 500 |" in lowered else "warn"
        alerts.append(
            {
                "tone": tone,
                "title": "CLIProxyAPI log",
                "badge": "Log",
                "meta": display_compact_timestamp(timestamp) if timestamp else "Recent log",
                "detail": trim_text(remainder, limit=150),
            }
        )
        if len(alerts) >= 6:
            break

    return alerts


def busiest_hour_text(hour_map):
    if not hour_map:
        return "No peak yet"

    hour, requests = max(
        ((str(hour), safe_int(count)) for hour, count in hour_map.items()),
        key=lambda item: item[1],
    )
    return f"{hour}:00 ({requests})"


def build_pool_items(auth_files, usage_index, reference_time):
    total_tokens = usage_index["totals"]["totalTokens"]
    total_requests = usage_index["totals"]["totalRequests"]
    items = []
    seen_keys = set()
    active_count = 0
    warning_count = 0

    for auth_file in auth_files:
        key = auth_key(auth_file)
        usage_entry = usage_index["accounts"].get(key)
        tone, status_label, status_message = auth_health(auth_file, usage_entry)
        if tone == "good":
            active_count += 1
        else:
            warning_count += 1

        requests = safe_int((usage_entry or {}).get("requests"))
        failed = safe_int((usage_entry or {}).get("failed"))
        tokens = safe_int((usage_entry or {}).get("tokens"))
        recent_timestamp = (usage_entry or {}).get("recentTimestamp")
        share_percent = format_share_percent(tokens if total_tokens > 0 else requests, total_tokens if total_tokens > 0 else total_requests)
        updated_at = auth_updated_at(auth_file)
        items.append(
            {
                "tone": tone,
                "sortKey": (
                    0 if tone == "bad" else 1 if tone == "warn" else 2,
                    -(failed > 0),
                    -requests,
                    -(recent_timestamp.timestamp() if recent_timestamp else 0),
                    auth_label(auth_file, usage_entry),
                ),
                "title": auth_label(auth_file, usage_entry),
                "badge": auth_plan(auth_file),
                "meta": f"{status_label} · {activity_text(recent_timestamp)} · upd {display_compact_timestamp(updated_at, reference=reference_time)}",
                "detail": f"{format_count(requests)} req · {format_count(failed)} fail · {format_tokens(tokens)} tok · {share_percent}% share",
                "note": trim_text(status_message, limit=140) if status_message else "",
                "barPercent": share_percent,
            }
        )
        seen_keys.add(key)

    for key, usage_entry in usage_index["accounts"].items():
        if key in seen_keys:
            continue
        requests = safe_int(usage_entry.get("requests"))
        failed = safe_int(usage_entry.get("failed"))
        tokens = safe_int(usage_entry.get("tokens"))
        recent_timestamp = usage_entry.get("recentTimestamp")
        share_percent = format_share_percent(tokens if total_tokens > 0 else requests, total_tokens if total_tokens > 0 else total_requests)
        items.append(
            {
                "tone": "warn",
                "sortKey": (1, -1, -requests, -(recent_timestamp.timestamp() if recent_timestamp else 0), key),
                "title": auth_label({}, usage_entry),
                "badge": "Runtime",
                "meta": f"Seen in usage only · {activity_text(recent_timestamp)}",
                "detail": f"{format_count(requests)} req · {format_count(failed)} fail · {format_tokens(tokens)} tok · {share_percent}% share",
                "note": "Usage references an auth slot that is missing from /auth-files.",
                "barPercent": share_percent,
            }
        )
        warning_count += 1

    items.sort(key=lambda item: item["sortKey"])
    for item in items:
        item.pop("sortKey", None)

    return items, active_count, warning_count


def build_traffic_items(auth_files, usage_index):
    auth_by_key = {auth_key(item): item for item in auth_files}
    total_tokens = usage_index["totals"]["totalTokens"]
    total_requests = usage_index["totals"]["totalRequests"]
    items = []

    for key, usage_entry in usage_index["accounts"].items():
        auth_file = auth_by_key.get(key, {})
        share_percent = format_share_percent(
            usage_entry["tokens"] if total_tokens > 0 else usage_entry["requests"],
            total_tokens if total_tokens > 0 else total_requests,
        )
        tone, status_label, _ = auth_health(auth_file, usage_entry)
        items.append(
            {
                "tone": tone,
                "sortKey": (
                    -usage_entry["tokens"],
                    -usage_entry["requests"],
                    auth_label(auth_file, usage_entry),
                ),
                "title": auth_label(auth_file, usage_entry),
                "badge": f"{share_percent}%",
                "meta": f"{format_count(usage_entry['requests'])} req · {format_count(usage_entry['failed'])} fail · {format_tokens(usage_entry['tokens'])} tok",
                "detail": f"{status_label} · {activity_text(usage_entry['recentTimestamp'])}",
                "note": f"{len(usage_entry['models'])} models seen" if usage_entry["models"] else "",
                "barPercent": share_percent,
            }
        )

    items.sort(key=lambda item: item["sortKey"])
    for item in items:
        item.pop("sortKey", None)
    return items


def build_alert_items(auth_files, usage_index, log_alerts, reference_time):
    items = []
    auth_issue_count = 0

    for auth_file in auth_files:
        usage_entry = usage_index["accounts"].get(auth_key(auth_file))
        tone, status_label, status_message = auth_health(auth_file, usage_entry)
        if tone == "good":
            continue

        auth_issue_count += 1
        requests = safe_int((usage_entry or {}).get("requests"))
        failed = safe_int((usage_entry or {}).get("failed"))
        tokens = safe_int((usage_entry or {}).get("tokens"))
        updated_at = auth_updated_at(auth_file)
        detail = trim_text(status_message, limit=150) if status_message else f"{status_label} account needs attention."
        items.append(
            {
                "tone": tone,
                "title": auth_label(auth_file, usage_entry),
                "badge": "Auth",
                "meta": f"{auth_plan(auth_file)} · upd {display_compact_timestamp(updated_at, reference=reference_time)}",
                "detail": detail,
                "note": f"{format_count(requests)} req · {format_count(failed)} fail · {format_tokens(tokens)} tok",
            }
        )

    failed_request_items = []
    for failure in usage_index["failedItems"][:5]:
        failed_request_items.append(
            {
                "tone": "bad",
                "title": failure["source"],
                "badge": "Request",
                "meta": f"{display_compact_timestamp(failure['timestamp'], reference=reference_time)} · {failure['model'] or 'model?'}",
                "detail": "CPA recorded a failed request for this auth slot.",
                "note": f"{format_tokens(failure['tokens'])} tok · auth {failure['authIndex'] or 'unknown'}",
            }
        )

    items.extend(failed_request_items)
    items.extend(log_alerts)
    if not items:
        items.append(
            {
                "tone": "good",
                "title": "No active alerts",
                "badge": "Clean",
                "meta": "The pool, request logs, and recent management logs look healthy.",
                "detail": "No auth file is disabled or unavailable, and CPA did not report a recent failed request.",
            }
        )

    return items, auth_issue_count, len(failed_request_items)


def build_dashboard_snapshot(
    *,
    health_payload,
    auth_files_payload,
    usage_payload,
    routing_payload,
    usage_stats_payload,
    request_log_payload,
    logs_payload,
    sampled_at,
    endpoint_errors=None,
    source="live",
):
    auth_files = list((auth_files_payload or {}).get("files") or [])
    usage_index = build_usage_index(usage_payload)
    log_alerts = build_log_alerts(logs_payload)
    pool_items, active_count, warning_count = build_pool_items(auth_files, usage_index, sampled_at)
    traffic_items = build_traffic_items(auth_files, usage_index)
    alert_items, auth_issue_count, failed_request_count = build_alert_items(auth_files, usage_index, log_alerts, sampled_at)

    totals = usage_index["totals"]
    total_requests = totals["totalRequests"]
    success_count = totals["successCount"]
    failure_count = totals["failureCount"]
    total_tokens = totals["totalTokens"]
    alert_count = auth_issue_count + failed_request_count + len(log_alerts)
    routing_strategy = titleize_slug((routing_payload or {}).get("strategy"), fallback="Unknown")
    gateway_ok = str((health_payload or {}).get("status") or "").lower() == "ok"
    usage_stats_enabled = bool((usage_stats_payload or {}).get("usage-statistics-enabled"))
    endpoint_errors = endpoint_errors or []

    if source == "stale":
        source_text = "Cached CPA snapshot"
        status_text = "Fresh CPA sampling failed, so this page is showing the last complete snapshot."
    elif endpoint_errors:
        source_text = "Live CPA snapshot with cached fallbacks"
        status_text = "Some CPA endpoints failed during refresh, so the page reused the latest good payload where possible."
    elif gateway_ok:
        source_text = "Live via CLIProxyAPI management API"
        status_text = "Live CPA pool data from the local gateway."
    else:
        source_text = "Management API reachable, gateway health not ok"
        status_text = "The management API responded, but /healthz did not report status=ok."

    if endpoint_errors:
        status_text += " " + "; ".join(endpoint_errors)
    if not usage_stats_enabled:
        status_text += " Usage statistics are disabled, so traffic splits may be incomplete."

    summary = {
        "gatewayPill": "Gateway OK" if gateway_ok else "Gateway down",
        "poolPill": f"{active_count}/{len(auth_files)} active" if auth_files else "Pool empty",
        "alertsPill": "Clean" if alert_count == 0 else count_label(alert_count, "alert"),
        "subline": f"{routing_strategy} · {format_count(total_requests)} req · {format_tokens(total_tokens)} tok",
    }

    return {
        "available": True,
        "source": source,
        "sourceText": source_text,
        "sampledAt": iso_timestamp(sampled_at),
        "sampledAtText": display_timestamp(sampled_at),
        "statusText": status_text,
        "error": "; ".join(endpoint_errors) if endpoint_errors else None,
        "summary": summary,
        "tabs": {
            "pool": {
                "title": "Pool Health",
                "summary": f"{len(auth_files)} auth files · {active_count} active · {warning_count} with attention",
                "stats": [
                    {"label": "Auth Files", "value": str(len(auth_files))},
                    {"label": "Active", "value": str(active_count)},
                    {"label": "Warnings", "value": str(warning_count)},
                    {"label": "Routing", "value": routing_strategy},
                ],
                "items": pool_items,
                "footnote": "Each row shows auth status, last hit time, and usage share inside the current CPA pool.",
            },
            "traffic": {
                "title": "Traffic Split",
                "summary": f"{format_count(total_requests)} requests · {format_percent(success_count, total_requests)} success · {format_tokens(total_tokens)} tokens",
                "stats": [
                    {"label": "Requests", "value": format_count(total_requests)},
                    {"label": "Success", "value": format_percent(success_count, total_requests)},
                    {"label": "Failures", "value": format_count(failure_count)},
                    {"label": "Peak Hour", "value": busiest_hour_text(usage_index["requestsByHour"])},
                ],
                "items": traffic_items,
                "footnote": "Traffic share is based on recorded CPA usage detail. Token share falls back to request share when tokens are zero.",
            },
            "alerts": {
                "title": "Alerts & Failures",
                "summary": "No active alerts." if alert_count == 0 else count_label(alert_count, "alert"),
                "stats": [
                    {"label": "Auth Issues", "value": str(auth_issue_count)},
                    {"label": "Failed Req", "value": str(failed_request_count)},
                    {"label": "Log Alerts", "value": str(len(log_alerts))},
                    {"label": "Req Log", "value": "On" if (request_log_payload or {}).get("request-log") else "Off"},
                ],
                "items": alert_items,
                "footnote": "Warn/error log lines are filtered to hide known noisy endpoints such as /metrics and dashboard discovery probes.",
            },
        },
    }


def build_unavailable_snapshot(error_text):
    sampled_at = now_local()
    message = trim_text(error_text or "No CPA data found yet.", limit=220)
    return {
        "available": False,
        "source": "unavailable",
        "sourceText": "No CPA snapshot yet",
        "sampledAt": iso_timestamp(sampled_at),
        "sampledAtText": "Waiting for first successful sample",
        "statusText": message,
        "error": message,
        "summary": {
            "gatewayPill": "Gateway unknown",
            "poolPill": "Pool unavailable",
            "alertsPill": "Alerts unknown",
            "subline": "Waiting for auth-files and usage data.",
        },
        "tabs": {
            "pool": dict(EMPTY_TAB, title="Pool Health", summary="No auth-file data yet."),
            "traffic": dict(EMPTY_TAB, title="Traffic Split", summary="No usage data yet."),
            "alerts": dict(EMPTY_TAB, title="Alerts & Failures", summary="No alerts yet."),
        },
    }


def render_page(snapshot, refresh_seconds):
    initial_snapshot = json.dumps(snapshot, separators=(",", ":")).replace("</", "<\\/")
    return PAGE_TEMPLATE.substitute(
        meta_refresh=max(refresh_seconds * 4, 60),
        initial_snapshot=initial_snapshot,
        refresh_ms=refresh_seconds * 1000,
    )


def write_payload(handler, payload):
    try:
        handler.wfile.write(payload)
    except (BrokenPipeError, ConnectionResetError):
        logging.getLogger("codex-quota-monitor.http").info("client closed connection before response finished")


def json_response(handler, status_code, payload):
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    handler.send_response(status_code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    write_payload(handler, data)


def html_response(handler, status_code, payload):
    data = payload.encode("utf-8")
    handler.send_response(status_code)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    write_payload(handler, data)


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
            "routing-strategy",
            join_url(self.management_base_url, "/v0/management/routing/strategy"),
            ttl_seconds=self.refresh_seconds,
            default_payload={"strategy": "unknown"},
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

        request_log_payload, _, _, request_log_error = self._load_json(
            "request-log",
            join_url(self.management_base_url, "/v0/management/request-log"),
            ttl_seconds=self.refresh_seconds,
            default_payload={"request-log": False},
        )
        if request_log_error:
            endpoint_errors.append("request-log: " + request_log_error)
            source = "partial"

        logs_payload, _, _, logs_error = self._load_json(
            "logs",
            join_url(self.management_base_url, "/v0/management/logs"),
            ttl_seconds=self.logs_refresh_seconds,
            default_payload={"lines": []},
        )
        if logs_error:
            endpoint_errors.append("logs: " + logs_error)
            source = "partial"

        if auth_files_payload is None or usage_payload is None:
            if self._last_snapshot:
                stale_snapshot = copy.deepcopy(self._last_snapshot)
                stale_snapshot["source"] = "stale"
                stale_snapshot["sourceText"] = "Cached CPA snapshot"
                stale_snapshot["statusText"] = "Fresh CPA sampling failed, so this page is showing the last complete snapshot."
                if endpoint_errors:
                    stale_snapshot["statusText"] += " " + "; ".join(endpoint_errors)
                stale_snapshot["error"] = "; ".join(endpoint_errors) if endpoint_errors else stale_snapshot.get("error")
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
            snapshot["tabs"]["traffic"]["stats"][0]["value"],
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

        if parsed.path == "/":
            snapshot = self.monitor.get_snapshot()
            html_response(self, HTTPStatus.OK, render_page(snapshot, self.monitor.refresh_seconds))
            return

        json_response(self, HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})


def main():
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    monitor = CPAMonitor(
        management_base_url=args.management_base_url,
        gateway_health_url=args.gateway_health_url,
        refresh_seconds=args.refresh_seconds,
        logs_refresh_seconds=args.logs_refresh_seconds,
        timeout_seconds=args.timeout_seconds,
    )

    MonitorRequestHandler.monitor = monitor
    server = ThreadingHTTPServer((args.host, args.port), MonitorRequestHandler)
    logging.getLogger("codex-quota-monitor").info(
        "listening on http://%s:%s using management_base_url=%s gateway_health_url=%s",
        args.host,
        args.port,
        args.management_base_url,
        args.gateway_health_url,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.getLogger("codex-quota-monitor").info("shutting down on keyboard interrupt")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
