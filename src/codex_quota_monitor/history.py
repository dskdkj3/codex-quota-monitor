import json
import logging
import math
import pathlib
import sqlite3
import time
import datetime as dt

from .util import (
    count_label,
    display_compact_timestamp,
    format_fractional_count,
    iso_timestamp,
    normalize_key,
    now_local,
    parse_timestamp,
    safe_int,
    trim_text,
)


HISTORY_DISABLED_TAB = {
    "title": "Trends & ETA",
    "summary": "SQLite history is disabled.",
    "metrics": [],
    "windows": [],
    "benchmark": {"available": False, "summary": "No benchmark summary configured.", "metrics": []},
    "footnote": "Pass --state-db or set services.codexQuotaMonitor.stateDb to enable trends and audit history.",
}

AUDIT_DISABLED_TAB = {
    "title": "Audit Trail",
    "summary": "SQLite history is disabled.",
    "items": [],
    "footnote": "Account-pool changes are recorded only when history is enabled.",
}

WINDOW_LABELS = {"5h": "5h", "week": "Weekly"}
TREND_HISTORY_HOURS = 6
TREND_MAX_POINTS = 24
TREND_ROW_LIMIT = TREND_HISTORY_HOURS * 60 * 60


def is_disabled_path(value):
    text = str(value or "").strip()
    return not text or text.lower() in {"off", "none", "disabled", "false"}


def optional_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_units(value):
    if value is None:
        return "Unknown"
    return f"{format_fractional_count(value)} Plus"


def format_rate(value):
    if value is None:
        return "Unknown"
    if value <= 0:
        return "0.00 Plus/h"
    return f"{format_fractional_count(value)} Plus/h"


def format_duration_hours(hours):
    if hours is None:
        return "Unknown"
    if not math.isfinite(hours):
        return "Unknown"
    total_minutes = int(math.ceil(max(0.0, hours) * 60.0))
    days, remainder = divmod(total_minutes, 24 * 60)
    hours_part, minutes = divmod(remainder, 60)
    if days:
        return f"{days}d {hours_part}h"
    if hours_part:
        return f"{hours_part}h {minutes}min"
    return f"{minutes}min"


def downsample_rows(rows, max_points):
    if len(rows) <= max_points:
        return list(rows)
    if max_points <= 1:
        return [rows[-1]]

    last_index = len(rows) - 1
    selected_indexes = []
    for point_index in range(max_points):
        index = int(round((point_index * last_index) / float(max_points - 1)))
        if not selected_indexes or selected_indexes[-1] != index:
            selected_indexes.append(index)
    return [rows[index] for index in selected_indexes]


def window_by_id(account, window_id):
    for window in (account or {}).get("windows") or []:
        if window.get("id") == window_id:
            return window
    return {}


def numeric_percent(window):
    value = (window or {}).get("percent")
    if isinstance(value, (int, float)):
        return float(value)
    return None


def account_identity(account):
    return str((account or {}).get("key") or (account or {}).get("title") or "unknown")


def account_capacity_weight(account):
    value = optional_float((account or {}).get("capacityWeight"))
    if value is not None:
        return value
    badge = normalize_key((account or {}).get("badge"))
    if "plus" in badge or "team" in badge:
        return 1.0
    if badge == "prolite":
        return 10.0
    return 0.0


def recommendation_reason(account):
    status = str((account or {}).get("statusLabel") or "Unknown")
    five_hour = window_by_id(account, "5h")
    weekly = window_by_id(account, "week")
    five_percent = numeric_percent(five_hour)
    weekly_percent = numeric_percent(weekly)
    reasons = [status]
    if five_percent is None:
        reasons.append("5h unknown")
    else:
        reasons.append(f"5h {int(round(five_percent))}%")
    if weekly_percent is None:
        reasons.append("weekly unknown")
    else:
        reasons.append(f"weekly {int(round(weekly_percent))}%")
    return " · ".join(reasons)


def classify_recommendation(account):
    status = normalize_key((account or {}).get("statusLabel"))
    tone = str((account or {}).get("tone") or "unknown")
    five_hour = window_by_id(account, "5h")
    weekly = window_by_id(account, "week")
    five_percent = numeric_percent(five_hour)
    weekly_percent = numeric_percent(weekly)
    hard_states = {
        "disabled",
        "unavailable",
        "missingauthfile",
        "quotahit",
        "resetscheduled",
    }
    if tone == "bad" or status in hard_states:
        return "avoid"
    if (five_hour.get("state") == "exhausted") or (weekly.get("state") == "exhausted"):
        return "avoid"
    if five_percent is not None and five_percent <= 0:
        return "avoid"
    if weekly_percent is not None and weekly_percent <= 0:
        return "avoid"
    if tone == "good" and five_percent is not None and weekly_percent is not None:
        if five_percent >= 20 and weekly_percent >= 5:
            return "best"
    return "usable"


def recommendation_sort_key(account):
    five_percent = numeric_percent(window_by_id(account, "5h"))
    weekly_percent = numeric_percent(window_by_id(account, "week"))
    return (
        -account_capacity_weight(account),
        -(weekly_percent if weekly_percent is not None else -1),
        -(five_percent if five_percent is not None else -1),
        -safe_int((account or {}).get("sharePercent")),
        str((account or {}).get("title") or ""),
    )


def build_recommendations(snapshot):
    accounts = (((snapshot or {}).get("tabs") or {}).get("pool") or {}).get("accounts") or []
    grouped = {"best": [], "usable": [], "avoid": []}
    for account in sorted(accounts, key=recommendation_sort_key):
        bucket = classify_recommendation(account)
        grouped[bucket].append(
            {
                "tone": account.get("tone") or "unknown",
                "title": account.get("title") or "Unknown account",
                "badge": account.get("badge") or "",
                "summary": recommendation_reason(account),
                "detail": account.get("note") or account.get("summary") or "",
                "note": account.get("meta") or "",
                "capacityWeight": account_capacity_weight(account),
            }
        )

    groups = [
        {
            "id": "best",
            "title": "Best",
            "summary": count_label(len(grouped["best"]), "account"),
            "items": grouped["best"][:8],
        },
        {
            "id": "usable",
            "title": "Usable",
            "summary": count_label(len(grouped["usable"]), "account"),
            "items": grouped["usable"][:8],
        },
        {
            "id": "avoid",
            "title": "Avoid",
            "summary": count_label(len(grouped["avoid"]), "account"),
            "items": grouped["avoid"][:8],
        },
    ]
    return {
        "summary": (
            f"{len(grouped['best'])} best · {len(grouped['usable'])} usable · "
            f"{len(grouped['avoid'])} avoid"
        ),
        "bestCount": len(grouped["best"]),
        "usableCount": len(grouped["usable"]),
        "avoidCount": len(grouped["avoid"]),
        "groups": groups,
    }


def load_benchmark_summary(path):
    if is_disabled_path(path):
        return {"available": False, "configured": False, "summary": "No benchmark summary configured.", "metrics": []}
    try:
        resolved = pathlib.Path(path)
        payload = json.loads(resolved.read_text(encoding="utf-8"))
        stat = resolved.stat()
    except Exception as exc:
        return {
            "available": False,
            "configured": True,
            "summary": "Benchmark summary unavailable.",
            "error": trim_text(exc, limit=180),
            "metrics": [
                {"label": "Benchmark", "value": "Error", "detail": trim_text(exc, limit=120)},
            ],
        }

    generated_at = payload.get("generatedAt") or payload.get("generated_at") or ""
    performance = payload.get("performance") or {}
    comparison = performance.get("comparison") or {}
    quota = payload.get("quota") or {}
    weekly_to_five_hour = quota.get("weeklyToFiveHour") or {}
    recommended = weekly_to_five_hour.get("recommended_dashboard_multiplier")
    speedup = comparison.get("speedup_p50")
    token_ratio = comparison.get("token_overhead_ratio")
    metrics = [
        {
            "label": "Generated",
            "value": display_compact_timestamp(parse_timestamp(generated_at) or now_local()),
            "detail": f"mtime {time.strftime('%Y-%m-%d %H:%M', time.localtime(stat.st_mtime))}",
        },
        {
            "label": "Recommended cap",
            "value": "Unknown" if recommended is None else format_fractional_count(recommended),
            "detail": "weekly-to-5h multiplier from benchmark",
        },
        {
            "label": "Fast p50",
            "value": "n/a" if speedup is None else f"{float(speedup):.2f}x",
            "detail": "fast versus baseline latency speedup",
        },
        {
            "label": "Token ratio",
            "value": "n/a" if token_ratio is None else f"{float(token_ratio):.2f}x",
            "detail": "fast token overhead ratio",
        },
    ]
    return {
        "available": True,
        "configured": True,
        "path": str(resolved),
        "generatedAt": generated_at,
        "summary": "Latest benchmark summary loaded.",
        "recommendedDashboardMultiplier": recommended,
        "metrics": metrics,
    }


def capacity_window(snapshot, window_id):
    for item in ((((snapshot or {}).get("tabs") or {}).get("pool") or {}).get("capacityWindows") or []):
        if item.get("id") == window_id:
            return item
    return {}


def build_threshold_alerts(snapshot, recommendations, thresholds, benchmark):
    thresholds = thresholds or {}
    alerts = []
    for window_id, threshold_key, label in (
        ("5h", "five_hour_min_plus", "5h"),
        ("week", "weekly_min_plus", "Weekly"),
    ):
        threshold = optional_float(thresholds.get(threshold_key))
        if threshold is None:
            continue
        current = optional_float(capacity_window(snapshot, window_id).get("knownUnits"))
        if current is None:
            continue
        if current < threshold:
            alerts.append(
                {
                    "kind": "threshold",
                    "tone": "bad",
                    "title": f"{label} capacity below threshold",
                    "badge": "Threshold",
                    "meta": f"{format_units(current)} < {format_units(threshold)}",
                    "detail": f"Configured minimum is {format_units(threshold)}.",
                }
            )

    best_min = safe_int(thresholds.get("best_accounts_min"))
    if best_min > 0 and safe_int((recommendations or {}).get("bestCount")) < best_min:
        alerts.append(
            {
                "kind": "threshold",
                "tone": "bad",
                "title": "Recommended account pool below threshold",
                "badge": "Threshold",
                "meta": f"{recommendations.get('bestCount', 0)} best < {best_min}",
                "detail": "Too few accounts meet the best-account quota and health criteria.",
            }
        )

    if benchmark.get("configured") and not benchmark.get("available"):
        alerts.append(
            {
                "kind": "monitor",
                "tone": "warn",
                "title": "Benchmark summary unavailable",
                "badge": "Benchmark",
                "meta": "Configured benchmark file could not be read",
                "detail": benchmark.get("error") or "The benchmark summary path is configured but unavailable.",
            }
        )
    return alerts


def build_alert_api(snapshot):
    alert_items = list(((((snapshot or {}).get("tabs") or {}).get("alerts") or {}).get("items") or []))
    threshold_items = list((snapshot or {}).get("thresholdAlerts") or [])
    recommendations = (snapshot or {}).get("recommendations") or {}
    items = alert_items + threshold_items
    return {
        "ok": not any((item.get("tone") == "bad") for item in items),
        "sampledAt": (snapshot or {}).get("sampledAt"),
        "source": (snapshot or {}).get("source"),
        "sourceText": (snapshot or {}).get("sourceText"),
        "alertCount": len(items),
        "items": items,
        "recommendations": {
            "bestCount": recommendations.get("bestCount", 0),
            "usableCount": recommendations.get("usableCount", 0),
            "avoidCount": recommendations.get("avoidCount", 0),
            "summary": recommendations.get("summary", ""),
        },
    }


class HistoryStore:
    def __init__(self, db_path, *, write_seconds=60, retention_days=30):
        self.db_path = str(db_path)
        self.write_seconds = max(1, safe_int(write_seconds) or 60)
        self.retention_days = max(1, safe_int(retention_days) or 30)
        self.logger = logging.getLogger("codex-quota-monitor.history")

    def enhance(self, snapshot, *, benchmark, weekly_to_five_hour_multiplier=None):
        try:
            with self._connect() as conn:
                self._ensure_schema(conn)
                self._maybe_record(conn, snapshot, benchmark)
                return {
                    "trends": self._build_trends_tab(conn, benchmark, weekly_to_five_hour_multiplier),
                    "audit": self._build_audit_tab(conn),
                }
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            self.logger.warning("history disabled for this refresh: %s", exc)
            return {
                "trends": dict(
                    HISTORY_DISABLED_TAB,
                    summary="SQLite history is unavailable.",
                    footnote=trim_text(exc, limit=180),
                    benchmark=benchmark,
                ),
                "audit": dict(
                    AUDIT_DISABLED_TAB,
                    summary="SQLite audit is unavailable.",
                    footnote=trim_text(exc, limit=180),
                ),
            }

    def _connect(self):
        db_path = pathlib.Path(self.db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 1000")
        return conn

    def _ensure_schema(self, conn):
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS snapshots (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              sampled_at TEXT NOT NULL,
              written_at TEXT NOT NULL,
              source TEXT NOT NULL,
              source_text TEXT NOT NULL,
              gateway_pill TEXT NOT NULL,
              fast_state TEXT NOT NULL,
              fast_policy TEXT NOT NULL,
              routing_text TEXT NOT NULL,
              total_requests INTEGER NOT NULL,
              total_tokens INTEGER NOT NULL,
              alert_count INTEGER NOT NULL,
              summary_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_snapshots_sampled_at ON snapshots(sampled_at);
            CREATE TABLE IF NOT EXISTS capacity_windows (
              snapshot_id INTEGER NOT NULL,
              window_id TEXT NOT NULL,
              known_units REAL,
              tracked_units REAL,
              unknown_count INTEGER NOT NULL,
              exhausted_count INTEGER NOT NULL,
              stale_count INTEGER NOT NULL,
              weekly_capped_count INTEGER NOT NULL,
              PRIMARY KEY (snapshot_id, window_id)
            );
            CREATE TABLE IF NOT EXISTS accounts (
              snapshot_id INTEGER NOT NULL,
              account_key TEXT NOT NULL,
              title TEXT NOT NULL,
              badge TEXT NOT NULL,
              status_label TEXT NOT NULL,
              tone TEXT NOT NULL,
              requests INTEGER NOT NULL,
              tokens INTEGER NOT NULL,
              share_percent INTEGER NOT NULL,
              five_hour_state TEXT NOT NULL,
              five_hour_percent REAL,
              five_hour_reset_at TEXT,
              weekly_state TEXT NOT NULL,
              weekly_percent REAL,
              weekly_reset_at TEXT,
              PRIMARY KEY (snapshot_id, account_key)
            );
            CREATE INDEX IF NOT EXISTS idx_accounts_snapshot ON accounts(snapshot_id);
            CREATE TABLE IF NOT EXISTS events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              occurred_at TEXT NOT NULL,
              kind TEXT NOT NULL,
              tone TEXT NOT NULL,
              title TEXT NOT NULL,
              badge TEXT NOT NULL,
              summary TEXT NOT NULL,
              detail TEXT NOT NULL,
              account_key TEXT,
              window_id TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_events_occurred ON events(occurred_at);
            PRAGMA user_version = 1;
            """
        )

    def _meta_get(self, conn, key):
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def _meta_set(self, conn, key, value):
        conn.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )

    def _should_write(self, conn, sampled_at):
        last_written = parse_timestamp(self._meta_get(conn, "last_snapshot_written_at"))
        if last_written is None:
            return True
        return (sampled_at - last_written).total_seconds() >= self.write_seconds

    def _maybe_record(self, conn, snapshot, benchmark):
        if not (snapshot or {}).get("available") or (snapshot or {}).get("source") == "stale":
            return
        sampled_at = parse_timestamp(snapshot.get("sampledAt")) or now_local()
        if not self._should_write(conn, sampled_at):
            return

        previous_snapshot = self._latest_snapshot_row(conn)
        previous_accounts = self._latest_accounts(conn, previous_snapshot["id"] if previous_snapshot else None)
        snapshot_id = self._insert_snapshot(conn, snapshot, sampled_at)
        self._insert_capacity_windows(conn, snapshot_id, snapshot)
        current_accounts = self._insert_accounts(conn, snapshot_id, snapshot)
        events = self._diff_events(previous_snapshot, previous_accounts, snapshot, current_accounts, sampled_at)
        events.extend(self._benchmark_events(conn, benchmark, sampled_at))
        self._insert_events(conn, events)
        self._meta_set(conn, "last_snapshot_written_at", iso_timestamp(sampled_at))
        self._cleanup(conn, sampled_at)

    def _latest_snapshot_row(self, conn):
        return conn.execute("SELECT * FROM snapshots ORDER BY sampled_at DESC, id DESC LIMIT 1").fetchone()

    def _latest_accounts(self, conn, snapshot_id):
        if not snapshot_id:
            return {}
        rows = conn.execute("SELECT * FROM accounts WHERE snapshot_id = ?", (snapshot_id,)).fetchall()
        return {row["account_key"]: row for row in rows}

    def _insert_snapshot(self, conn, snapshot, sampled_at):
        summary = (snapshot or {}).get("summary") or {}
        fast_mode = snapshot.get("fastMode") or {}
        row = conn.execute(
            """
            INSERT INTO snapshots(
              sampled_at, written_at, source, source_text, gateway_pill, fast_state, fast_policy,
              routing_text, total_requests, total_tokens, alert_count, summary_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                iso_timestamp(sampled_at),
                iso_timestamp(now_local()),
                snapshot.get("source") or "unknown",
                snapshot.get("sourceText") or "",
                summary.get("gatewayPill") or "",
                fast_mode.get("state") or "unknown",
                fast_mode.get("policy") or "unknown",
                ((summary.get("subline") or "").split(" · ")[0] or ""),
                safe_int(snapshot.get("_totalRequests") or 0),
                safe_int(snapshot.get("_totalTokens") or 0),
                safe_int((((snapshot.get("tabs") or {}).get("alerts") or {}).get("alertCount"))),
                json.dumps(
                    {
                        "summary": summary,
                        "fastMode": fast_mode,
                    },
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
        )
        return row.lastrowid

    def _insert_capacity_windows(self, conn, snapshot_id, snapshot):
        for item in (((snapshot.get("tabs") or {}).get("pool") or {}).get("capacityWindows") or []):
            conn.execute(
                """
                INSERT INTO capacity_windows(
                  snapshot_id, window_id, known_units, tracked_units, unknown_count,
                  exhausted_count, stale_count, weekly_capped_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    item.get("id") or "",
                    optional_float(item.get("knownUnits")),
                    optional_float(item.get("trackedUnits")),
                    safe_int(item.get("unknownCount")),
                    safe_int(item.get("exhaustedCount")),
                    safe_int(item.get("staleCount")),
                    safe_int(item.get("weeklyCappedCount")),
                ),
            )

    def _insert_accounts(self, conn, snapshot_id, snapshot):
        current = {}
        for account in (((snapshot.get("tabs") or {}).get("pool") or {}).get("accounts") or []):
            key = account_identity(account)
            five_hour = window_by_id(account, "5h")
            weekly = window_by_id(account, "week")
            data = {
                "account_key": key,
                "title": account.get("title") or "Unknown account",
                "badge": account.get("badge") or "",
                "status_label": account.get("statusLabel") or "Unknown",
                "tone": account.get("tone") or "unknown",
                "requests": safe_int(account.get("requests")),
                "tokens": safe_int(account.get("tokens")),
                "share_percent": safe_int(account.get("sharePercent")),
                "five_hour_state": five_hour.get("state") or "unknown",
                "five_hour_percent": numeric_percent(five_hour),
                "five_hour_reset_at": five_hour.get("resetAt"),
                "weekly_state": weekly.get("state") or "unknown",
                "weekly_percent": numeric_percent(weekly),
                "weekly_reset_at": weekly.get("resetAt"),
            }
            conn.execute(
                """
                INSERT INTO accounts(
                  snapshot_id, account_key, title, badge, status_label, tone, requests, tokens,
                  share_percent, five_hour_state, five_hour_percent, five_hour_reset_at,
                  weekly_state, weekly_percent, weekly_reset_at
                ) VALUES (
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    snapshot_id,
                    data["account_key"],
                    data["title"],
                    data["badge"],
                    data["status_label"],
                    data["tone"],
                    data["requests"],
                    data["tokens"],
                    data["share_percent"],
                    data["five_hour_state"],
                    data["five_hour_percent"],
                    data["five_hour_reset_at"],
                    data["weekly_state"],
                    data["weekly_percent"],
                    data["weekly_reset_at"],
                ),
            )
            current[key] = data
        return current

    def _event(self, occurred_at, kind, tone, title, badge, summary, detail, account_key=None, window_id=None):
        return {
            "occurred_at": iso_timestamp(occurred_at),
            "kind": kind,
            "tone": tone,
            "title": trim_text(title, limit=140),
            "badge": badge,
            "summary": trim_text(summary, limit=160),
            "detail": trim_text(detail, limit=220),
            "account_key": account_key,
            "window_id": window_id,
        }

    def _diff_events(self, previous_snapshot, previous_accounts, snapshot, current_accounts, sampled_at):
        events = []
        if previous_snapshot:
            previous_fast = previous_snapshot["fast_state"]
            current_fast = ((snapshot.get("fastMode") or {}).get("state") or "unknown")
            if previous_fast != current_fast:
                events.append(
                    self._event(
                        sampled_at,
                        "routing",
                        "warn",
                        "Fast policy changed",
                        "Fast",
                        f"{previous_fast} -> {current_fast}",
                        (snapshot.get("fastMode") or {}).get("detail") or "",
                    )
                )

        previous_keys = set(previous_accounts)
        current_keys = set(current_accounts)
        for key in sorted(current_keys - previous_keys):
            account = current_accounts[key]
            events.append(
                self._event(
                    sampled_at,
                    "account",
                    "good",
                    account["title"],
                    "Added",
                    f"{account['badge']} · {account['status_label']}",
                    "Account appeared in the CPA auth pool.",
                    key,
                )
            )
        for key in sorted(previous_keys - current_keys):
            account = previous_accounts[key]
            events.append(
                self._event(
                    sampled_at,
                    "account",
                    "warn",
                    account["title"],
                    "Removed",
                    f"{account['badge']} · {account['status_label']}",
                    "Account disappeared from the CPA auth pool.",
                    key,
                )
            )
        for key in sorted(previous_keys & current_keys):
            before = previous_accounts[key]
            after = current_accounts[key]
            if before["badge"] != after["badge"]:
                events.append(
                    self._event(
                        sampled_at,
                        "account",
                        "warn",
                        after["title"],
                        "Plan",
                        f"{before['badge']} -> {after['badge']}",
                        "Plan label changed in the auth pool or direct quota sample.",
                        key,
                    )
                )
            if before["status_label"] != after["status_label"]:
                tone = "bad" if after["tone"] == "bad" else "warn"
                events.append(
                    self._event(
                        sampled_at,
                        "account",
                        tone,
                        after["title"],
                        "Status",
                        f"{before['status_label']} -> {after['status_label']}",
                        "Account health status changed.",
                        key,
                    )
                )
            events.extend(self._window_events(sampled_at, key, before, after))
        return events

    def _window_events(self, sampled_at, key, before, after):
        events = []
        for prefix, label, window_id in (("five_hour", "5h", "5h"), ("weekly", "Weekly", "week")):
            before_state = before[f"{prefix}_state"]
            after_state = after[f"{prefix}_state"]
            before_percent = before[f"{prefix}_percent"]
            after_percent = after[f"{prefix}_percent"]
            if before_percent is None and after_percent is not None:
                events.append(
                    self._event(
                        sampled_at,
                        "quota",
                        "good",
                        after["title"],
                        label,
                        f"{label} direct sample available",
                        f"{label} remaining is {int(round(after_percent))}%.",
                        key,
                        window_id,
                    )
                )
            if before_state != "exhausted" and after_state == "exhausted":
                events.append(
                    self._event(
                        sampled_at,
                        "quota",
                        "bad",
                        after["title"],
                        label,
                        f"{label} exhausted",
                        f"{label} remaining reached 0%.",
                        key,
                        window_id,
                    )
                )
            if before_state == "exhausted" and after_percent is not None and after_percent > 0:
                events.append(
                    self._event(
                        sampled_at,
                        "quota",
                        "good",
                        after["title"],
                        label,
                        f"{label} restored",
                        f"{label} remaining recovered to {int(round(after_percent))}%.",
                        key,
                        window_id,
                    )
                )
        return events

    def _benchmark_events(self, conn, benchmark, sampled_at):
        if not benchmark.get("configured"):
            return []
        signature = json.dumps(
            {
                "available": benchmark.get("available"),
                "generatedAt": benchmark.get("generatedAt"),
                "recommended": benchmark.get("recommendedDashboardMultiplier"),
                "error": benchmark.get("error"),
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        previous = self._meta_get(conn, "benchmark_signature")
        if previous == signature:
            return []
        self._meta_set(conn, "benchmark_signature", signature)
        return [
            self._event(
                sampled_at,
                "benchmark",
                "good" if benchmark.get("available") else "warn",
                "Benchmark summary changed",
                "Benchmark",
                benchmark.get("summary") or "Benchmark state changed.",
                benchmark.get("path") or benchmark.get("error") or "",
            )
        ]

    def _insert_events(self, conn, events):
        for event in events:
            conn.execute(
                """
                INSERT INTO events(
                  occurred_at, kind, tone, title, badge, summary, detail, account_key, window_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["occurred_at"],
                    event["kind"],
                    event["tone"],
                    event["title"],
                    event["badge"],
                    event["summary"],
                    event["detail"],
                    event.get("account_key"),
                    event.get("window_id"),
                ),
            )

    def _cleanup(self, conn, reference_time):
        cutoff = reference_time.timestamp() - (self.retention_days * 24 * 60 * 60)
        cutoff_text = iso_timestamp(dt.datetime.fromtimestamp(cutoff, dt.timezone.utc).astimezone())
        old_ids = [
            row["id"]
            for row in conn.execute("SELECT id FROM snapshots WHERE sampled_at < ?", (cutoff_text,)).fetchall()
        ]
        if old_ids:
            placeholders = ",".join("?" for _ in old_ids)
            conn.execute(f"DELETE FROM capacity_windows WHERE snapshot_id IN ({placeholders})", old_ids)
            conn.execute(f"DELETE FROM accounts WHERE snapshot_id IN ({placeholders})", old_ids)
            conn.execute(f"DELETE FROM snapshots WHERE id IN ({placeholders})", old_ids)
        conn.execute("DELETE FROM events WHERE occurred_at < ?", (cutoff_text,))

    def _build_trends_tab(self, conn, benchmark, weekly_to_five_hour_multiplier):
        windows = [self._trend_for_window(conn, "5h"), self._trend_for_window(conn, "week")]
        metrics = []
        for window in windows:
            metrics.append(
                {
                    "label": f"{window['label']} ETA",
                    "value": window["etaText"],
                    "detail": window["summary"],
                }
            )
            metrics.append(
                {
                    "label": f"{window['label']} Burn",
                    "value": window["burnText"],
                    "detail": f"current {window['currentUnitsText']}",
                }
            )
        if weekly_to_five_hour_multiplier is None:
            multiplier_text = "Off"
        else:
            multiplier_text = format_fractional_count(weekly_to_five_hour_multiplier)
        metrics.append(
            {
                "label": "5h cap",
                "value": multiplier_text,
                "detail": "weekly-to-5h multiplier currently used by the dashboard",
            }
        )
        return {
            "title": "Trends & ETA",
            "summary": f"SQLite-backed burn rate and exhaustion estimates over the latest {TREND_HISTORY_HOURS}h.",
            "metrics": metrics,
            "windows": windows,
            "benchmark": benchmark,
            "footnote": (
                f"Trend points show the latest {TREND_HISTORY_HOURS}h of stored samples, downsampled to "
                f"{TREND_MAX_POINTS} points. Burn rate uses the latest continuous samples with stable "
                "tracked capacity and unknown counts; reset or pool changes cut the segment."
            ),
        }

    def _trend_for_window(self, conn, window_id):
        rows = conn.execute(
            """
            SELECT s.sampled_at, s.source, cw.known_units, cw.tracked_units, cw.unknown_count,
                   cw.exhausted_count, cw.stale_count
            FROM capacity_windows cw
            JOIN snapshots s ON s.id = cw.snapshot_id
            WHERE cw.window_id = ?
            ORDER BY s.sampled_at DESC, s.id DESC
            LIMIT ?
            """,
            (window_id, TREND_ROW_LIMIT),
        ).fetchall()
        label = WINDOW_LABELS.get(window_id, window_id)
        if not rows:
            return {
                "id": window_id,
                "label": label,
                "currentUnits": None,
                "currentUnitsText": "Unknown",
                "burnPerHour": None,
                "burnText": "Unknown",
                "etaHours": None,
                "etaText": "Unknown",
                "summary": "Waiting for stored samples.",
                "points": [],
            }
        latest = rows[0]
        latest_time = parse_timestamp(latest["sampled_at"]) or now_local()
        latest_units = optional_float(latest["known_units"])
        horizon_seconds = TREND_HISTORY_HOURS * 60 * 60
        horizon_rows = []
        for row in rows:
            row_time = parse_timestamp(row["sampled_at"]) or latest_time
            if row_time <= latest_time and (latest_time - row_time).total_seconds() <= horizon_seconds:
                horizon_rows.append(row)
        rows = horizon_rows
        candidate = None
        for row in rows[1:]:
            row_time = parse_timestamp(row["sampled_at"])
            row_units = optional_float(row["known_units"])
            if row_time is None or row_units is None or latest_units is None:
                break
            if (latest_time - row_time).total_seconds() > horizon_seconds:
                break
            if optional_float(row["tracked_units"]) != optional_float(latest["tracked_units"]):
                break
            if safe_int(row["unknown_count"]) != safe_int(latest["unknown_count"]):
                break
            if row_units + 0.000001 < latest_units:
                break
            candidate = row
        burn = None
        eta = None
        summary = "Waiting for at least two comparable samples."
        if candidate is not None and latest_units is not None:
            candidate_time = parse_timestamp(candidate["sampled_at"]) or latest_time
            hours = max((latest_time - candidate_time).total_seconds() / 3600.0, 0.0)
            if hours > 0:
                burn = max(0.0, (optional_float(candidate["known_units"]) - latest_units) / hours)
                if burn > 0:
                    eta = latest_units / burn
                    summary = f"{format_rate(burn)} over {format_duration_hours(hours)}."
                else:
                    summary = "No active burn in the comparable sample segment."
        points = []
        for row in downsample_rows(list(reversed(rows)), TREND_MAX_POINTS):
            row_time = parse_timestamp(row["sampled_at"]) or now_local()
            points.append(
                {
                    "label": display_compact_timestamp(row_time, reference=latest_time),
                    "value": optional_float(row["known_units"]),
                    "valueText": format_units(optional_float(row["known_units"])),
                }
            )
        return {
            "id": window_id,
            "label": label,
            "currentUnits": latest_units,
            "currentUnitsText": format_units(latest_units),
            "burnPerHour": burn,
            "burnText": format_rate(burn),
            "etaHours": eta,
            "etaText": "No active burn" if burn == 0 else format_duration_hours(eta),
            "summary": summary,
            "points": points,
        }

    def _build_audit_tab(self, conn):
        rows = conn.execute("SELECT * FROM events ORDER BY occurred_at DESC, id DESC LIMIT 80").fetchall()
        items = []
        for row in rows:
            occurred_at = parse_timestamp(row["occurred_at"])
            items.append(
                {
                    "tone": row["tone"],
                    "title": row["title"],
                    "badge": row["badge"],
                    "summary": row["summary"],
                    "detail": row["detail"],
                    "note": display_compact_timestamp(occurred_at) if occurred_at else row["occurred_at"],
                }
            )
        return {
            "title": "Audit Trail",
            "summary": f"{count_label(len(items), 'recent event')} from SQLite history.",
            "items": items,
            "footnote": "Audit events are derived by diffing consecutive stored snapshots; tokens and auth JSON secrets are never stored.",
        }


def enhance_snapshot_with_history(
    snapshot,
    *,
    history_store=None,
    benchmark_summary_path=None,
    alert_thresholds=None,
    weekly_to_five_hour_multiplier=None,
):
    benchmark = load_benchmark_summary(benchmark_summary_path)
    recommendations = build_recommendations(snapshot)
    snapshot["recommendations"] = recommendations
    threshold_alerts = build_threshold_alerts(snapshot, recommendations, alert_thresholds or {}, benchmark)
    snapshot["thresholdAlerts"] = threshold_alerts
    if history_store is None:
        snapshot["tabs"]["trends"] = dict(HISTORY_DISABLED_TAB, benchmark=benchmark)
        snapshot["tabs"]["audit"] = AUDIT_DISABLED_TAB
    else:
        tabs = history_store.enhance(
            snapshot,
            benchmark=benchmark,
            weekly_to_five_hour_multiplier=weekly_to_five_hour_multiplier,
        )
        snapshot["tabs"]["trends"] = tabs["trends"]
        snapshot["tabs"]["audit"] = tabs["audit"]
    snapshot["apiAlerts"] = build_alert_api(snapshot)
    return snapshot
