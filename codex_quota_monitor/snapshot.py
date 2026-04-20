import datetime as dt

from .util import (
    EMPTY_TAB,
    activity_text,
    auth_health,
    auth_key,
    auth_label,
    auth_plan,
    auth_updated_at,
    count_label,
    display_compact_timestamp,
    display_timestamp,
    format_count,
    format_percent,
    format_share_percent,
    format_tokens,
    iso_timestamp,
    now_local,
    parse_timestamp,
    safe_int,
    titleize_slug,
    trim_text,
)


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
