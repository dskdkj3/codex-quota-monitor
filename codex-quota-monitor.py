#!/usr/bin/env python3

import argparse
import copy
import datetime as dt
import html
import json
import logging
import os
import pathlib
import select
import string
import subprocess
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


PAGE_TEMPLATE = string.Template(
    """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
    <meta http-equiv="refresh" content="$meta_refresh">
    <title>Codex Monitor</title>
    <style>
      :root {
        --paper: #f5f3eb;
        --ink: #111111;
        --shadow: #c8c3b6;
        --line: #242424;
        --quiet: #57534c;
        --alert: #2c120f;
      }

      * {
        box-sizing: border-box;
      }

      body {
        margin: 0;
        padding: 20px 16px 28px;
        background:
          linear-gradient(180deg, #fbfaf5 0%, var(--paper) 100%);
        color: var(--ink);
        font-family: "Palatino Linotype", "Book Antiqua", Georgia, serif;
      }

      .sheet {
        max-width: 760px;
        margin: 0 auto;
      }

      .hero {
        border: 3px solid var(--line);
        padding: 18px 18px 14px;
        background: rgba(255, 255, 255, 0.78);
        box-shadow: 6px 6px 0 var(--shadow);
      }

      .hero-kicker {
        margin: 0;
        font-size: 14px;
        letter-spacing: 0.18em;
        text-transform: uppercase;
      }

      .hero-title {
        margin: 8px 0 0;
        font-size: 52px;
        line-height: 0.95;
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
        margin-top: 16px;
      }

      .pill {
        display: inline-flex;
        align-items: center;
        min-height: 36px;
        padding: 6px 12px;
        border: 2px solid var(--line);
        font-size: 16px;
        font-weight: 700;
        background:
          repeating-linear-gradient(
            -45deg,
            rgba(17, 17, 17, 0.03) 0,
            rgba(17, 17, 17, 0.03) 8px,
            rgba(255, 255, 255, 0.35) 8px,
            rgba(255, 255, 255, 0.35) 16px
          );
      }

      .pill.is-hidden {
        display: none;
      }

      .grid {
        display: grid;
        gap: 14px;
        margin-top: 16px;
      }

      .panel {
        border: 3px solid var(--line);
        background: rgba(255, 255, 255, 0.82);
        padding: 14px 14px 16px;
      }

      .eyebrow {
        margin: 0 0 8px;
        font-size: 13px;
        font-weight: 700;
        letter-spacing: 0.16em;
        text-transform: uppercase;
      }

      .source-line {
        display: flex;
        flex-direction: column;
        gap: 6px;
      }

      .source-main {
        font-size: 22px;
        font-weight: 700;
      }

      .source-sub {
        font-size: 15px;
        color: var(--quiet);
      }

      .meter-head {
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        gap: 12px;
      }

      .meter-title {
        margin: 0;
        font-size: 26px;
      }

      .meter-value {
        font-size: 32px;
        font-weight: 700;
      }

      .track {
        height: 38px;
        margin-top: 14px;
        border: 3px solid var(--line);
        background:
          linear-gradient(90deg, rgba(17, 17, 17, 0.1), rgba(17, 17, 17, 0.02)),
          linear-gradient(180deg, #ffffff, #ebe7dd);
        overflow: hidden;
      }

      .fill {
        height: 100%;
        background:
          repeating-linear-gradient(
            90deg,
            rgba(17, 17, 17, 0.95) 0,
            rgba(17, 17, 17, 0.95) 22px,
            rgba(17, 17, 17, 0.82) 22px,
            rgba(17, 17, 17, 0.82) 34px
          );
        transition: width 0.35s ease;
      }

      .meter-meta {
        margin: 10px 0 0;
        font-size: 17px;
        color: var(--quiet);
      }

      .status-panel {
        border-style: dashed;
      }

      .status-panel.is-alert {
        border-style: solid;
        background: #f1e7df;
      }

      .status-copy {
        margin: 0;
        font-size: 18px;
        line-height: 1.45;
      }

      @media (max-width: 560px) {
        body {
          padding: 14px 10px 20px;
        }

        .hero,
        .panel {
          box-shadow: none;
        }

        .hero-title {
          font-size: 38px;
        }

        .meter-title {
          font-size: 22px;
        }

        .meter-value {
          font-size: 28px;
        }
      }
    </style>
  </head>
  <body>
    <main class="sheet">
      <section class="hero">
        <p class="hero-kicker">e-ink View</p>
        <h1 class="hero-title">Codex Quota</h1>
        <p class="hero-subtitle">A local monitor tuned for e-ink refresh and quick glance checks.</p>
        <div class="pill-row">
          <span class="pill" id="plan-pill">$plan_text</span>
          <span class="$credits_pill_class" id="credits-pill">$credits_text</span>
        </div>
      </section>

      <section class="grid">
        <section class="panel">
          <p class="eyebrow">Source</p>
          <div class="source-line">
            <div class="source-main" id="source-text">$source_text</div>
            <div class="source-sub" id="sampled-at">$sampled_at_text</div>
          </div>
        </section>

        $primary_meter

        $secondary_meter

        <section class="$status_panel_class" id="status-panel">
          <p class="eyebrow">Status</p>
          <p class="status-copy" id="status-text">$status_text</p>
        </section>
      </section>
    </main>

    <script>
      var INITIAL_SNAPSHOT = $initial_snapshot;
      var REFRESH_MS = $refresh_ms;

      function text(value, fallback) {
        if (typeof value === "string" && value.length > 0) {
          return value;
        }
        return fallback;
      }

      function renderMeter(prefix, meter) {
        var label = document.getElementById(prefix + "-label");
        var value = document.getElementById(prefix + "-value");
        var fill = document.getElementById(prefix + "-fill");
        var meta = document.getElementById(prefix + "-reset");
        var hasMeter = meter && typeof meter === "object";
        var rawPercent = hasMeter ? Number(meter.usedPercent) : 0;
        var usedPercent = isFinite(rawPercent) ? rawPercent : 0;

        label.textContent = text(hasMeter ? meter.label : "", prefix === "primary" ? "5h Limit" : "Weekly Limit");
        value.textContent = usedPercent + "%";
        fill.style.width = Math.max(0, Math.min(100, usedPercent)) + "%";
        meta.textContent = text(hasMeter ? meter.resetsAtText : "", "Reset time unavailable");
      }

      function renderSnapshot(snapshot) {
        var safeSnapshot = snapshot || {};
        var credits = safeSnapshot.credits || {};
        var creditsPill = document.getElementById("credits-pill");
        var statusText = document.getElementById("status-text");
        var statusPanel = document.getElementById("status-panel");

        document.getElementById("source-text").textContent = text(safeSnapshot.sourceText, "No data");
        document.getElementById("sampled-at").textContent = text(safeSnapshot.sampledAtText, "Waiting for first sample");
        document.getElementById("plan-pill").textContent = text(safeSnapshot.planTypeText, "Plan unavailable");

        if (credits.text) {
          creditsPill.textContent = credits.text;
          creditsPill.classList.remove("is-hidden");
        } else {
          creditsPill.textContent = "";
          creditsPill.classList.add("is-hidden");
        }

        renderMeter("primary", safeSnapshot.primary);
        renderMeter("secondary", safeSnapshot.secondary);

        statusText.textContent = text(safeSnapshot.statusText, "No status available");
        if (safeSnapshot.source === "session" || safeSnapshot.source === "stale" || !safeSnapshot.available) {
          statusPanel.classList.add("is-alert");
        } else {
          statusPanel.classList.remove("is-alert");
        }
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
              document.getElementById("status-panel").classList.add("is-alert");
              document.getElementById("status-text").textContent =
                "Refresh returned unreadable data. The page kept the last snapshot.";
            }
            return;
          }

          document.getElementById("status-panel").classList.add("is-alert");
          document.getElementById("status-text").textContent =
            "Refresh failed. The page will keep the last snapshot until the next retry.";
        };
        request.send(null);
      }

      renderSnapshot(INITIAL_SNAPSHOT);
      window.setInterval(refreshSnapshot, REFRESH_MS);
    </script>
  </body>
</html>
"""
)


def parse_args():
    parser = argparse.ArgumentParser(description="Serve a e-ink-friendly Codex quota monitor.")
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
        "--rpc-timeout-seconds",
        type=float,
        default=float(os.environ.get("CODEX_MONITOR_RPC_TIMEOUT_SECONDS", "3")),
    )
    parser.add_argument(
        "--codex-binary",
        default=os.environ.get("CODEX_MONITOR_CODEX_BINARY", "codex"),
    )
    parser.add_argument(
        "--codex-home",
        default=os.environ.get(
            "CODEX_MONITOR_CODEX_HOME",
            os.environ.get("CODEX_HOME", os.path.expanduser("~/.codex")),
        ),
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


def plan_label(plan_type):
    if not plan_type:
        return "Plan unavailable"
    return "Plan: " + plan_type.replace("_", " ").title()


def compact_error(message, limit=180):
    text = " ".join(str(message).split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def window_label(window_minutes, fallback):
    if window_minutes == 300:
        return "5h Limit"
    if window_minutes == 10080:
        return "Weekly Limit"
    if window_minutes:
        return f"{fallback} ({window_minutes}m)"
    return fallback


def normalize_balance(value):
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return text
    return value


def credits_payload(payload):
    if not payload:
        return {"hasCredits": False, "unlimited": False, "balance": None, "text": ""}

    has_credits = bool(payload.get("has_credits") if "has_credits" in payload else payload.get("hasCredits"))
    unlimited = bool(payload.get("unlimited"))
    balance = normalize_balance(payload.get("balance"))

    if unlimited:
        text = "Credits: Unlimited"
    elif has_credits and balance is not None:
        if isinstance(balance, float):
            if balance.is_integer():
                text = f"Credits: {int(balance)}"
            else:
                text = f"Credits: {balance:.1f}".rstrip("0").rstrip(".")
        else:
            text = f"Credits: {balance}"
    else:
        text = ""

    return {
        "hasCredits": has_credits,
        "unlimited": unlimited,
        "balance": balance,
        "text": text,
    }


def format_reset_from_epoch(epoch_seconds):
    if not epoch_seconds:
        return None, "Reset time unavailable"
    value = dt.datetime.fromtimestamp(epoch_seconds, tz=dt.timezone.utc).astimezone()
    return iso_timestamp(value), display_timestamp(value)


def format_reset_from_seconds(reset_seconds):
    if not reset_seconds:
        return None, "Reset time unavailable"
    value = now_local() + dt.timedelta(seconds=reset_seconds)
    return iso_timestamp(value), display_timestamp(value)


def make_window(label, used_percent, window_minutes, resets_at=None, resets_in_seconds=None):
    if resets_at:
        reset_iso, reset_text = format_reset_from_epoch(resets_at)
    else:
        reset_iso, reset_text = format_reset_from_seconds(resets_in_seconds)

    used = int(round(float(used_percent or 0)))
    used = max(0, min(100, used))
    return {
        "label": window_label(window_minutes, label),
        "usedPercent": used,
        "windowMinutes": int(window_minutes or 0),
        "resetsAt": reset_iso,
        "resetsAtText": reset_text,
    }


def status_text_for(snapshot):
    if not snapshot.get("available"):
        return snapshot.get("error") or "No Codex quota snapshot is available yet."

    source = snapshot.get("source")
    if source == "rpc":
        return "Live quota from local Codex app-server."
    if source == "session":
        if snapshot.get("error"):
            return f"RPC was unavailable, so this view is using the latest local Codex session log. {snapshot['error']}"
        return "RPC was unavailable, so this view is using the latest local Codex session log."
    if source == "stale":
        if snapshot.get("error"):
            return f"Fresh sampling failed. This page is showing the last known good snapshot. {snapshot['error']}"
        return "Fresh sampling failed. This page is showing the last known good snapshot."
    return "Quota data loaded."


def finalize_snapshot(snapshot):
    snapshot["planTypeText"] = plan_label(snapshot.get("planType"))
    snapshot["statusText"] = status_text_for(snapshot)
    return snapshot


class CodexMonitor:
    def __init__(self, codex_binary, codex_home, refresh_seconds, rpc_timeout_seconds):
        self.codex_binary = codex_binary
        self.codex_home = pathlib.Path(codex_home).expanduser()
        self.refresh_seconds = refresh_seconds
        self.rpc_timeout_seconds = rpc_timeout_seconds
        self.logger = logging.getLogger("codex-quota-monitor")
        self._lock = threading.Lock()
        self._last_snapshot = None
        self._last_success_snapshot = None
        self._last_refresh_monotonic = 0.0

    def get_snapshot(self):
        now_mono = time.monotonic()
        with self._lock:
            if self._last_snapshot and (now_mono - self._last_refresh_monotonic) < self.refresh_seconds:
                return copy.deepcopy(self._last_snapshot)

        snapshot = self._refresh_snapshot()

        with self._lock:
            self._last_snapshot = snapshot
            self._last_refresh_monotonic = time.monotonic()
            if snapshot.get("source") != "stale" and snapshot.get("available"):
                self._last_success_snapshot = copy.deepcopy(snapshot)
            return copy.deepcopy(snapshot)

    def _refresh_snapshot(self):
        errors = []

        try:
            snapshot = self._sample_rpc()
            self.logger.info("sample source=rpc primary=%s secondary=%s", snapshot["primary"]["usedPercent"], snapshot["secondary"]["usedPercent"])
            return snapshot
        except Exception as exc:  # pragma: no cover - runtime path
            errors.append(f"RPC: {compact_error(exc)}")
            self.logger.warning("rpc sample failed: %s", exc)

        try:
            snapshot = self._sample_session()
            snapshot["error"] = errors[-1] if errors else None
            snapshot = finalize_snapshot(snapshot)
            self.logger.info("sample source=session primary=%s secondary=%s", snapshot["primary"]["usedPercent"], snapshot["secondary"]["usedPercent"])
            return snapshot
        except Exception as exc:  # pragma: no cover - runtime path
            errors.append(f"Session: {compact_error(exc)}")
            self.logger.warning("session sample failed: %s", exc)

        with self._lock:
            if self._last_success_snapshot:
                stale = copy.deepcopy(self._last_success_snapshot)
                stale["source"] = "stale"
                stale["sourceText"] = "Cached snapshot"
                stale["error"] = " | ".join(errors)
                return finalize_snapshot(stale)

        sampled_at = now_local()
        unavailable = {
            "available": False,
            "source": "stale",
            "sourceText": "No snapshot yet",
            "sampledAt": iso_timestamp(sampled_at),
            "sampledAtText": "Waiting for first successful sample",
            "planType": None,
            "primary": make_window("Primary", 0, 300),
            "secondary": make_window("Secondary", 0, 10080),
            "credits": credits_payload(None),
            "error": " | ".join(errors) if errors else "No Codex data found.",
        }
        return finalize_snapshot(unavailable)

    def _sample_rpc(self):
        env = os.environ.copy()
        env["CODEX_HOME"] = str(self.codex_home)
        process = subprocess.Popen(
            [
                self.codex_binary,
                "-s",
                "read-only",
                "-a",
                "untrusted",
                "app-server",
            ],
            text=True,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
        )
        try:
            self._rpc_send(
                process,
                {"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "e-ink-monitor", "version": "0.1"}}},
            )
            self._rpc_read(process, expected_id=1, timeout_seconds=self.rpc_timeout_seconds)

            self._rpc_send(process, {"method": "initialized", "params": {}})
            self._rpc_send(process, {"id": 2, "method": "account/rateLimits/read", "params": {}})
            message = self._rpc_read(process, expected_id=2, timeout_seconds=self.rpc_timeout_seconds)
        finally:
            if process.stdin is not None:
                process.stdin.close()
            try:
                process.terminate()
                process.wait(timeout=1)
            except Exception:
                process.kill()
                process.wait(timeout=1)

        rate_limits = (message.get("result") or {}).get("rateLimits")
        if not rate_limits:
            raise RuntimeError("account/rateLimits/read returned no rate limits")

        primary = rate_limits.get("primary") or {}
        secondary = rate_limits.get("secondary") or {}
        if not primary.get("windowDurationMins") and not secondary.get("windowDurationMins"):
            raise RuntimeError("RPC returned empty rate-limit windows")

        sampled_at = now_local()
        snapshot = {
            "available": True,
            "source": "rpc",
            "sourceText": "Live via Codex RPC",
            "sampledAt": iso_timestamp(sampled_at),
            "sampledAtText": display_timestamp(sampled_at),
            "planType": rate_limits.get("planType"),
            "primary": make_window(
                "Primary",
                primary.get("usedPercent"),
                primary.get("windowDurationMins"),
                resets_at=primary.get("resetsAt"),
            ),
            "secondary": make_window(
                "Secondary",
                secondary.get("usedPercent"),
                secondary.get("windowDurationMins"),
                resets_at=secondary.get("resetsAt"),
            ),
            "credits": credits_payload(rate_limits.get("credits")),
            "error": None,
        }
        return finalize_snapshot(snapshot)

    def _rpc_send(self, process, payload):
        if process.stdin is None:
            raise RuntimeError("codex app-server stdin is unavailable")
        process.stdin.write(json.dumps(payload) + "\n")
        process.stdin.flush()

    def _rpc_read(self, process, expected_id, timeout_seconds):
        if process.stdout is None or process.stderr is None:
            raise RuntimeError("codex app-server pipes are unavailable")

        deadline = time.monotonic() + timeout_seconds
        stderr_lines = []

        while time.monotonic() < deadline:
            if process.poll() is not None and process.stdout.closed:
                break

            remaining = max(0.0, deadline - time.monotonic())
            readable, _, _ = select.select([process.stdout, process.stderr], [], [], remaining)
            if not readable:
                break

            for stream in readable:
                line = stream.readline()
                if not line:
                    continue
                if stream is process.stderr:
                    stderr_lines.append(line.strip())
                    continue

                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if message.get("id") == expected_id:
                    return message

        if process.poll() is not None:
            raise RuntimeError(compact_error(" ".join(stderr_lines) or f"codex app-server exited with code {process.returncode}"))

        raise RuntimeError(compact_error(" ".join(stderr_lines) or f"timed out waiting for RPC response {expected_id}"))

    def _sample_session(self):
        files = []
        for root in (self.codex_home / "sessions", self.codex_home / "archived_sessions"):
            if not root.exists():
                continue
            for path in root.rglob("*.jsonl"):
                try:
                    files.append((path.stat().st_mtime, path))
                except FileNotFoundError:
                    continue

        if not files:
            raise RuntimeError("no Codex session files found")

        files.sort(key=lambda item: item[0], reverse=True)

        for _, path in files:
            rate_limits = self._rate_limits_from_session(path)
            if rate_limits:
                primary = rate_limits.get("primary") or {}
                secondary = rate_limits.get("secondary") or {}
                sampled_at = now_local()
                snapshot = {
                    "available": True,
                    "source": "session",
                    "sourceText": "Fallback via session log",
                    "sampledAt": iso_timestamp(sampled_at),
                    "sampledAtText": display_timestamp(sampled_at),
                    "planType": rate_limits.get("plan_type"),
                    "primary": make_window(
                        "Primary",
                        primary.get("used_percent"),
                        primary.get("window_minutes"),
                        resets_at=primary.get("resets_at"),
                        resets_in_seconds=primary.get("resets_in_seconds"),
                    ),
                    "secondary": make_window(
                        "Secondary",
                        secondary.get("used_percent"),
                        secondary.get("window_minutes"),
                        resets_at=secondary.get("resets_at"),
                        resets_in_seconds=secondary.get("resets_in_seconds"),
                    ),
                    "credits": credits_payload(rate_limits.get("credits")),
                    "error": None,
                }
                return snapshot

        raise RuntimeError("no usable token_count payload found in recent sessions")

    def _rate_limits_from_session(self, path):
        last_rate_limits = None
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                payload = event.get("payload") or {}
                if event.get("type") != "event_msg" or payload.get("type") != "token_count":
                    continue

                rate_limits = payload.get("rate_limits") or {}
                primary = rate_limits.get("primary") or {}
                secondary = rate_limits.get("secondary") or {}
                if not primary.get("window_minutes") and not secondary.get("window_minutes"):
                    continue

                last_rate_limits = rate_limits

        return last_rate_limits


def render_meter(prefix, window):
    return f"""
        <section class="panel">
          <div class="meter-head">
            <h2 class="meter-title" id="{prefix}-label">{html.escape(window["label"])}</h2>
            <div class="meter-value" id="{prefix}-value">{window["usedPercent"]}%</div>
          </div>
          <div class="track" aria-hidden="true">
            <div class="fill" id="{prefix}-fill" style="width: {window["usedPercent"]}%"></div>
          </div>
          <p class="meter-meta" id="{prefix}-reset">{html.escape(window["resetsAtText"])}</p>
        </section>
    """


def render_page(snapshot, refresh_seconds):
    initial_snapshot = json.dumps(snapshot, separators=(",", ":")).replace("</", "<\\/")
    credits_pill_class = "pill" if snapshot["credits"]["text"] else "pill is-hidden"
    status_panel_class = "panel status-panel"
    if snapshot["source"] in {"session", "stale"} or not snapshot["available"]:
        status_panel_class += " is-alert"

    return PAGE_TEMPLATE.substitute(
        meta_refresh=max(refresh_seconds * 4, 60),
        plan_text=html.escape(snapshot["planTypeText"]),
        credits_text=html.escape(snapshot["credits"]["text"]),
        credits_pill_class=credits_pill_class,
        source_text=html.escape(snapshot["sourceText"]),
        sampled_at_text=html.escape(snapshot["sampledAtText"]),
        primary_meter=render_meter("primary", snapshot["primary"]),
        secondary_meter=render_meter("secondary", snapshot["secondary"]),
        status_panel_class=status_panel_class,
        status_text=html.escape(snapshot["statusText"]),
        initial_snapshot=initial_snapshot,
        refresh_ms=refresh_seconds * 1000,
    )


def json_response(handler, status_code, payload):
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    handler.send_response(status_code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def html_response(handler, status_code, payload):
    data = payload.encode("utf-8")
    handler.send_response(status_code)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


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

    monitor = CodexMonitor(
        codex_binary=args.codex_binary,
        codex_home=args.codex_home,
        refresh_seconds=args.refresh_seconds,
        rpc_timeout_seconds=args.rpc_timeout_seconds,
    )

    MonitorRequestHandler.monitor = monitor
    server = ThreadingHTTPServer((args.host, args.port), MonitorRequestHandler)
    logging.getLogger("codex-quota-monitor").info(
        "listening on http://%s:%s using codex_home=%s",
        args.host,
        args.port,
        args.codex_home,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.getLogger("codex-quota-monitor").info("shutting down on keyboard interrupt")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
