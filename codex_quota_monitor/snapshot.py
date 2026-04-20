import datetime as dt
import json

from .util import (
    EMPTY_TAB,
    activity_text,
    auth_key,
    auth_label,
    auth_plan,
    auth_updated_at,
    count_label,
    display_compact_timestamp,
    display_timestamp,
    format_count,
    format_fractional_count,
    format_percent,
    format_share_percent,
    format_tokens,
    iso_timestamp,
    normalize_key,
    now_local,
    parse_timestamp,
    safe_int,
    titleize_slug,
    trim_text,
)


WINDOW_DEFINITIONS = (
    {
        "id": "5h",
        "label": "5h",
        "title": "5h Remaining",
        "aliases": ("5h", "fivehour", "fivehr", "fivehourwindow", "rolling5h", "rollingfivehour"),
    },
    {
        "id": "week",
        "label": "Weekly",
        "title": "Weekly Remaining",
        "aliases": ("weekly", "week", "7d", "7day", "sevenday", "rolling7d", "rollingweekly"),
    },
)

PERCENT_FIELD_ALIASES = (
    "remainingpercent",
    "remainingpercentage",
    "remainingpct",
    "percentremaining",
    "availablepercent",
    "availablepercentage",
    "capacitypercent",
    "quotaremainingpercent",
)
RATIO_FIELD_ALIASES = (
    "remainingratio",
    "remainingfraction",
    "availableratio",
    "availablefraction",
)
USED_PERCENT_FIELD_ALIASES = (
    "usedpercent",
    "usedpercentage",
)
USED_RATIO_FIELD_ALIASES = (
    "usedratio",
    "usedfraction",
)
EXHAUSTED_FIELD_ALIASES = (
    "exhausted",
    "exceeded",
    "limitreached",
    "quotaexceeded",
)
QUOTA_MESSAGE_TYPES = {
    "usage_limit_reached",
    "quota_exhausted",
    "insufficient_quota",
}
QUOTA_TEXT_FRAGMENTS = (
    "usage limit has been reached",
    "usage_limit_reached",
    "quota exhausted",
    "quota_exhausted",
    "insufficient quota",
)


def parse_timestamp_value(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(float(value), tz=dt.timezone.utc).astimezone()
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return dt.datetime.fromtimestamp(float(text), tz=dt.timezone.utc).astimezone()
    return parse_timestamp(text)


def parse_status_message_payload(raw_message):
    text = str(raw_message or "").strip()
    if not text or not text.startswith(("{", "[")):
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def walk_scalars(node, path=()):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from walk_scalars(value, path + (str(key),))
        return
    if isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk_scalars(value, path + (str(index),))
        return
    yield path, node


def find_first_matching_key(node, candidates):
    wanted = {normalize_key(candidate) for candidate in candidates}
    for path, value in walk_scalars(node):
        if not path:
            continue
        if normalize_key(path[-1]) in wanted:
            return value
    return None


def human_status_message(raw_message, parsed_message):
    if isinstance(parsed_message, dict):
        error = parsed_message.get("error")
        if isinstance(error, dict):
            for field in ("message", "detail", "reason"):
                value = error.get(field)
                if value:
                    return trim_text(value, limit=140)
        for field in ("message", "detail", "reason"):
            value = parsed_message.get(field)
            if value:
                return trim_text(value, limit=140)
    return trim_text(raw_message, limit=140)


def normalize_percent_value(field_name, value):
    if isinstance(value, bool) or value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("%"):
        text = text[:-1]
    try:
        number = float(text)
    except ValueError:
        return None

    key = normalize_key(field_name)
    if any(alias in key for alias in USED_RATIO_FIELD_ALIASES):
        if 0.0 <= number <= 1.0:
            return max(0, min(100, int(round((1.0 - number) * 100))))
        return None
    if any(alias in key for alias in USED_PERCENT_FIELD_ALIASES):
        if 0.0 <= number <= 100.0:
            return max(0, min(100, int(round(100.0 - number))))
        return None
    if any(alias in key for alias in RATIO_FIELD_ALIASES):
        if 0.0 <= number <= 1.0:
            return max(0, min(100, int(round(number * 100))))
        return None
    if any(alias in key for alias in PERCENT_FIELD_ALIASES):
        if 0.0 <= number <= 100.0:
            return max(0, min(100, int(round(number))))
        return None
    return None


def extract_signal_from_container(container):
    if not isinstance(container, dict):
        return None

    for key, value in container.items():
        key_norm = normalize_key(key)
        percent = normalize_percent_value(key_norm, value)
        if percent is not None:
            return {"state": "known" if percent > 0 else "exhausted", "percent": percent}
        if any(alias in key_norm for alias in EXHAUSTED_FIELD_ALIASES) and bool(value):
            return {"state": "exhausted", "percent": 0}

    remaining_units = None
    total_units = None
    for key, value in container.items():
        key_norm = normalize_key(key)
        if value in (None, "") or isinstance(value, bool):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if key_norm in {"remainingunits", "remainingunit", "unitsremaining"}:
            remaining_units = number
        elif key_norm in {"totalunits", "totalunit", "unitstotal"}:
            total_units = number

    if remaining_units is not None and total_units and total_units > 0:
        percent = max(0, min(100, int(round((remaining_units / total_units) * 100))))
        return {"state": "known" if percent > 0 else "exhausted", "percent": percent}

    return None


def window_path_matches(path, aliases):
    path_tokens = [normalize_key(part) for part in path]
    return any(alias in token for alias in aliases for token in path_tokens)


def find_window_signal(node, aliases):
    if isinstance(node, dict):
        window_name = node.get("window") or node.get("period") or node.get("name") or node.get("id")
        if window_name and any(alias in normalize_key(window_name) for alias in aliases):
            signal = extract_signal_from_container(node)
            if signal is not None:
                return signal

        for key, value in node.items():
            key_norm = normalize_key(key)
            if any(alias in key_norm for alias in aliases):
                signal = extract_signal_from_container({key: value})
                if signal is not None:
                    return signal
                signal = extract_signal_from_container(value)
                if signal is not None:
                    return signal
            signal = find_window_signal(value, aliases)
            if signal is not None:
                return signal
        return None

    if isinstance(node, list):
        for value in node:
            signal = find_window_signal(value, aliases)
            if signal is not None:
                return signal
    return None


def is_plus_plan(plan_kind):
    return "plus" in plan_kind


def is_team_plan(plan_kind):
    return "team" in plan_kind


def short_slot(value):
    text = str(value or "").strip()
    if not text:
        return "unknown"
    return text[:6]


def routing_state(config_payload):
    routing = (config_payload or {}).get("routing") or {}
    strategy = titleize_slug(routing.get("strategy"), fallback="Unknown")
    sticky_enabled = bool(routing.get("session-affinity"))
    sticky_ttl = str(routing.get("session-affinity-ttl") or "").strip()
    text = strategy
    detail = strategy
    if sticky_enabled:
        text += " + Sticky"
        detail += " + Sticky"
        if sticky_ttl:
            detail += f" ({sticky_ttl})"
    return {
        "strategy": strategy,
        "stickyEnabled": sticky_enabled,
        "stickyTTL": sticky_ttl,
        "text": text,
        "detail": detail,
    }


def build_usage_index(usage_payload):
    usage_root = (usage_payload or {}).get("usage") or {}
    accounts = {}

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

    return {
        "totals": {
            "totalRequests": safe_int(usage_root.get("total_requests")),
            "successCount": safe_int(usage_root.get("success_count")),
            "failureCount": safe_int(usage_root.get("failure_count")),
            "totalTokens": safe_int(usage_root.get("total_tokens")),
        },
        "accounts": normalized_accounts,
        "requestsByHour": (usage_payload or {}).get("requests_by_hour") or {},
        "requestsByDay": (usage_payload or {}).get("requests_by_day") or {},
        "tokensByHour": (usage_payload or {}).get("tokens_by_hour") or {},
        "tokensByDay": (usage_payload or {}).get("tokens_by_day") or {},
    }


def build_duplicate_label_counts(auth_files, usage_index):
    counts = {}
    for auth_file in auth_files:
        label = auth_label(auth_file, usage_index["accounts"].get(auth_key(auth_file)))
        counts[label] = counts.get(label, 0) + 1
    return counts


def is_explicit_quota_hit(auth_file, raw_message, parsed_message):
    quota_state = auth_file.get("quota") or {}
    if isinstance(quota_state, dict) and quota_state.get("exceeded"):
        return True

    quota_type = ""
    if isinstance(parsed_message, dict):
        error = parsed_message.get("error")
        if isinstance(error, dict):
            quota_type = str(error.get("type") or "").strip()
        if not quota_type:
            quota_type = str(parsed_message.get("type") or "").strip()
    if quota_type in QUOTA_MESSAGE_TYPES:
        return True

    lowered = str(raw_message or "").lower()
    return any(fragment in lowered for fragment in QUOTA_TEXT_FRAGMENTS)


def extract_reset_time(auth_file, parsed_message, reference_time):
    for candidate in (
        find_first_matching_key(parsed_message, ("resets_at", "next_recover_at", "next_retry_after")),
        (auth_file.get("quota") or {}).get("next_recover_at"),
        auth_file.get("next_retry_after"),
    ):
        parsed = parse_timestamp_value(candidate)
        if parsed is not None:
            return parsed

    resets_in_seconds = find_first_matching_key(parsed_message, ("resets_in_seconds", "retry_after_seconds"))
    if resets_in_seconds not in (None, ""):
        seconds = safe_int(resets_in_seconds)
        if seconds > 0:
            return reference_time + dt.timedelta(seconds=seconds)
    return None


def build_window_state(window_definition, auth_file, parsed_message, *, plus_plan, generic_quota, reference_time):
    label = window_definition["label"]
    if not plus_plan:
        return {
            "id": window_definition["id"],
            "label": label,
            "state": "na",
            "percent": None,
            "valueText": "n/a",
            "note": "Not tracked for this plan.",
            "fillPercent": 0,
        }

    signal = find_window_signal(parsed_message, window_definition["aliases"])
    if signal is None:
        signal = find_window_signal(auth_file, window_definition["aliases"])

    if signal is not None:
        percent = max(0, min(100, int(signal["percent"])))
        note = "Explicit window signal from CPA."
        if percent <= 0:
            note = "Window exhausted."
        return {
            "id": window_definition["id"],
            "label": label,
            "state": signal["state"],
            "percent": percent,
            "valueText": f"{percent}%",
            "note": note,
            "fillPercent": percent,
        }

    note = "Unknown"
    if generic_quota:
        note = "Quota hit not classified as 5h or weekly."
    return {
        "id": window_definition["id"],
        "label": label,
        "state": "unknown",
        "percent": None,
        "valueText": "Unknown",
        "note": note,
        "fillPercent": 0,
    }


def build_auth_context(auth_file, usage_entry, duplicate_labels, reference_time, usage_totals):
    key = auth_key(auth_file)
    label = auth_label(auth_file, usage_entry)
    plan_label = auth_plan(auth_file)
    plan_kind = normalize_key(plan_label)
    plus_plan = is_plus_plan(plan_kind)
    raw_message = str(auth_file.get("status_message") or "").strip()
    parsed_message = parse_status_message_payload(raw_message)
    message_text = human_status_message(raw_message, parsed_message) if raw_message else ""
    generic_quota = is_explicit_quota_hit(auth_file, raw_message, parsed_message)
    reset_at = extract_reset_time(auth_file, parsed_message, reference_time)
    updated_at = auth_updated_at(auth_file)
    recent_timestamp = (usage_entry or {}).get("recentTimestamp")
    requests = safe_int((usage_entry or {}).get("requests"))
    failed = safe_int((usage_entry or {}).get("failed"))
    tokens = safe_int((usage_entry or {}).get("tokens"))
    total_tokens = usage_totals["totalTokens"]
    total_requests = usage_totals["totalRequests"]
    share_percent = format_share_percent(tokens if total_tokens > 0 else requests, total_tokens if total_tokens > 0 else total_requests)

    status = str(auth_file.get("status") or "").strip()
    disabled = bool(auth_file.get("disabled"))
    unavailable = bool(auth_file.get("unavailable"))
    tone = "good"
    issue_kind = None
    status_label = "Active"

    if generic_quota:
        tone = "bad"
        issue_kind = "quota"
        status_label = "Quota hit"
    elif disabled:
        tone = "bad"
        issue_kind = "auth"
        status_label = "Disabled"
    elif unavailable:
        tone = "bad"
        issue_kind = "auth"
        status_label = "Unavailable"
    elif status and status.lower() != "active":
        tone = "bad" if status.lower() in {"error", "invalid"} else "warn"
        issue_kind = "auth"
        status_label = titleize_slug(status, fallback="Unknown")
    elif raw_message:
        tone = "warn"

    if not message_text and generic_quota:
        message_text = "Quota exhausted."
    if reset_at is not None:
        reset_text = f"Resets {display_compact_timestamp(reset_at, reference=reference_time)}"
        if message_text:
            message_text = f"{message_text} {reset_text}"
        else:
            message_text = reset_text

    summary_bits = [status_label]
    if duplicate_labels.get(label, 0) > 1:
        summary_bits.append(f"slot {short_slot(key)}")
    summary = " · ".join(summary_bits)

    meta_bits = []
    if recent_timestamp is not None:
        meta_bits.append(activity_text(recent_timestamp))
    else:
        meta_bits.append("idle")
    if updated_at is not None:
        meta_bits.append(f"upd {display_compact_timestamp(updated_at, reference=reference_time)}")
    meta = " · ".join(meta_bits)

    windows = [
        build_window_state(
            definition,
            auth_file,
            parsed_message,
            plus_plan=plus_plan,
            generic_quota=generic_quota,
            reference_time=reference_time,
        )
        for definition in WINDOW_DEFINITIONS
    ]

    remaining_values = [window["percent"] for window in windows if isinstance(window["percent"], int)]
    remaining_floor = min(remaining_values) if remaining_values else 101

    return {
        "key": key,
        "title": label,
        "badge": plan_label,
        "planKind": plan_kind,
        "tone": tone,
        "issueKind": issue_kind,
        "statusLabel": status_label,
        "genericQuotaExceeded": generic_quota,
        "summary": summary,
        "meta": meta,
        "trafficText": f"{format_count(requests)} req · {format_count(failed)} fail · {format_tokens(tokens)} tok · {share_percent}% share",
        "note": message_text,
        "sharePercent": share_percent,
        "requests": requests,
        "tokens": tokens,
        "recentTimestamp": recent_timestamp,
        "updatedAt": updated_at,
        "windows": windows,
        "sortKey": (
            0 if issue_kind else 1 if plus_plan and remaining_floor <= 100 else 2 if plus_plan else 3,
            0 if issue_kind == "quota" else 1 if issue_kind else 2,
            remaining_floor,
            -share_percent,
            -(recent_timestamp.timestamp() if recent_timestamp else 0),
            label,
        ),
    }


def build_runtime_context(key, usage_entry, reference_time, usage_totals):
    requests = safe_int(usage_entry.get("requests"))
    failed = safe_int(usage_entry.get("failed"))
    tokens = safe_int(usage_entry.get("tokens"))
    recent_timestamp = usage_entry.get("recentTimestamp")
    total_tokens = usage_totals["totalTokens"]
    total_requests = usage_totals["totalRequests"]
    share_percent = format_share_percent(tokens if total_tokens > 0 else requests, total_tokens if total_tokens > 0 else total_requests)
    label = auth_label({}, usage_entry)

    return {
        "key": key,
        "title": label,
        "badge": "Runtime",
        "planKind": "runtime",
        "tone": "bad",
        "issueKind": "auth",
        "statusLabel": "Missing auth-file",
        "genericQuotaExceeded": False,
        "summary": f"Missing auth-file · slot {short_slot(key)}",
        "meta": activity_text(recent_timestamp),
        "trafficText": f"{format_count(requests)} req · {format_count(failed)} fail · {format_tokens(tokens)} tok · {share_percent}% share",
        "note": "Seen in /usage only. The matching auth slot is missing from /auth-files.",
        "sharePercent": share_percent,
        "requests": requests,
        "tokens": tokens,
        "recentTimestamp": recent_timestamp,
        "updatedAt": None,
        "windows": [
            {
                "id": definition["id"],
                "label": definition["label"],
                "state": "unknown",
                "percent": None,
                "valueText": "Unknown",
                "note": "No auth-file metadata available.",
                "fillPercent": 0,
            }
            for definition in WINDOW_DEFINITIONS
        ],
        "sortKey": (
            0,
            2,
            101,
            -share_percent,
            -(recent_timestamp.timestamp() if recent_timestamp else 0),
            label,
        ),
    }


def build_account_contexts(auth_files, usage_index, reference_time):
    duplicate_labels = build_duplicate_label_counts(auth_files, usage_index)
    contexts = []
    seen_keys = set()
    plan_counts = {"plus": 0, "team": 0, "other": 0}

    for auth_file in auth_files:
        key = auth_key(auth_file)
        usage_entry = usage_index["accounts"].get(key)
        context = build_auth_context(auth_file, usage_entry, duplicate_labels, reference_time, usage_index["totals"])
        contexts.append(context)
        seen_keys.add(key)

        if is_plus_plan(context["planKind"]):
            plan_counts["plus"] += 1
        elif is_team_plan(context["planKind"]):
            plan_counts["team"] += 1
        else:
            plan_counts["other"] += 1

    for key, usage_entry in usage_index["accounts"].items():
        if key in seen_keys:
            continue
        contexts.append(build_runtime_context(key, usage_entry, reference_time, usage_index["totals"]))

    contexts.sort(key=lambda item: item["sortKey"])
    for context in contexts:
        context.pop("sortKey", None)
    return contexts, plan_counts


def build_capacity_windows(contexts):
    plus_contexts = [context for context in contexts if is_plus_plan(context["planKind"])]
    plus_total = len(plus_contexts)
    items = []

    for definition in WINDOW_DEFINITIONS:
        known_units = 0.0
        unknown_count = 0
        exhausted_count = 0
        unclassified_count = 0

        for context in plus_contexts:
            window = next(item for item in context["windows"] if item["id"] == definition["id"])
            if window["state"] in {"known", "exhausted"} and window["percent"] is not None:
                known_units += float(window["percent"]) / 100.0
                if window["percent"] <= 0:
                    exhausted_count += 1
                continue
            if context["genericQuotaExceeded"]:
                unclassified_count += 1
            else:
                unknown_count += 1

        known_units_text = f"{format_fractional_count(known_units)} Plus"
        known_bar_percent = int(round((known_units / float(plus_total)) * 100)) if plus_total > 0 else 0
        unknown_bar_percent = int(round((unknown_count / float(plus_total)) * 100)) if plus_total > 0 else 0
        summary_bits = [f"Known {known_units_text}"]
        if unknown_count:
            summary_bits.append(f"Unknown {unknown_count}")
        if exhausted_count:
            summary_bits.append(f"Exhausted {exhausted_count}")
        if unclassified_count:
            summary_bits.append(f"Unclassified {unclassified_count}")
        if not summary_bits:
            summary_bits = ["No Plus accounts"]

        items.append(
            {
                "id": definition["id"],
                "label": definition["title"],
                "knownUnits": known_units,
                "knownUnitsText": known_units_text,
                "plusTotal": plus_total,
                "unknownCount": unknown_count,
                "exhaustedCount": exhausted_count,
                "unclassifiedCount": unclassified_count,
                "knownBarPercent": known_bar_percent,
                "unknownBarPercent": unknown_bar_percent,
                "summary": " · ".join(summary_bits) if plus_total > 0 else "No Plus accounts in the pool.",
                "pillText": (
                    f"{definition['label']} {known_units_text} · {unknown_count} unknown"
                    if unknown_count > 0
                    else f"{definition['label']} {known_units_text}"
                ),
            }
        )

    return items, plus_total


def build_pool_accounts(contexts):
    return [
        {
            "tone": context["tone"],
            "title": context["title"],
            "badge": context["badge"],
            "summary": context["summary"],
            "meta": context["meta"],
            "trafficText": context["trafficText"],
            "note": context["note"],
            "windows": context["windows"],
        }
        for context in contexts
    ]


def build_traffic_distribution(contexts):
    items = []
    for context in sorted(contexts, key=lambda item: (-item["sharePercent"], -item["requests"], item["title"])):
        items.append(
            {
                "tone": context["tone"],
                "title": context["title"],
                "badge": f"{context['sharePercent']}%",
                "summary": f"{context['badge']} · {context['summary']}",
                "detail": context["trafficText"],
                "note": context["meta"],
                "barPercent": context["sharePercent"],
            }
        )
    return items


def build_auth_alert_items(contexts, reference_time):
    items = []
    for context in contexts:
        if context["issueKind"] is None:
            continue

        badge = "Quota" if context["issueKind"] == "quota" else "Auth"
        meta = context["badge"]
        if context["updatedAt"] is not None:
            meta += f" · upd {display_compact_timestamp(context['updatedAt'], reference=reference_time)}"

        detail = context["note"] or context["summary"]
        if context["issueKind"] == "quota" and not detail:
            detail = "Quota exhausted."
        if context["issueKind"] == "auth" and not detail:
            detail = f"{context['statusLabel']} requires operator attention."

        items.append(
            {
                "kind": context["issueKind"],
                "tone": context["tone"],
                "title": context["title"],
                "badge": badge,
                "meta": meta,
                "detail": detail,
                "note": context["trafficText"],
            }
        )
    return items


def build_monitor_alert_items(*, source, source_text, gateway_ok, endpoint_errors):
    items = []
    joined_errors = "; ".join(endpoint_errors or [])
    if source in {"partial", "stale"} or endpoint_errors:
        detail = "CLIProxyAPI data was incomplete, so the monitor is using cached or partial payloads."
        if source == "stale":
            detail = "Fresh CPA sampling failed, so the page is showing the last complete snapshot."
        if source == "partial":
            detail = "Some CPA endpoints failed during refresh, so the page reused the latest good payload where possible."
        if joined_errors:
            detail += " " + joined_errors
        items.append(
            {
                "kind": "monitor",
                "tone": "bad" if source == "stale" else "warn",
                "title": "CPA snapshot degraded",
                "badge": "Monitor",
                "meta": source_text,
                "detail": trim_text(detail, limit=180),
            }
        )

    if not gateway_ok:
        items.append(
            {
                "kind": "monitor",
                "tone": "bad",
                "title": "Gateway health not OK",
                "badge": "Gateway",
                "meta": source_text,
                "detail": "The management API responded, but /healthz did not return status=ok.",
            }
        )
    return items


def build_clean_alert_item():
    return {
        "kind": "clean",
        "tone": "good",
        "title": "No intervention needed",
        "badge": "Clean",
        "meta": "The gateway, auth pool, and quota signals look healthy.",
        "detail": "This page only shows hard auth failures, explicit quota exhaustion, and monitor data-source problems.",
    }


def build_alert_section(items):
    filtered_items = [item for item in items if item]
    counts = {"auth": 0, "quota": 0, "monitor": 0}
    for item in filtered_items:
        kind = item.get("kind")
        if kind in counts:
            counts[kind] += 1
    alert_count = sum(counts.values())
    if alert_count == 0:
        filtered_items = [build_clean_alert_item()]

    return {
        "title": "Intervention Only",
        "summary": "No active alerts." if alert_count == 0 else count_label(alert_count, "alert"),
        "metrics": [
            {"label": "Auth", "value": str(counts["auth"]), "detail": "disabled / unavailable / missing auth-file"},
            {"label": "Quota", "value": str(counts["quota"]), "detail": "explicit quota exhaustion"},
            {"label": "Monitor", "value": str(counts["monitor"]), "detail": "snapshot or gateway issues"},
            {"label": "Total", "value": str(alert_count), "detail": "items requiring attention"},
        ],
        "items": filtered_items,
        "footnote": "Alerts are intentionally narrow: only hard auth failures, explicit quota exhaustion, and monitor data-source problems remain here.",
        "alertCount": alert_count,
    }


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
    contexts, plan_counts = build_account_contexts(auth_files, usage_index, sampled_at)
    pool_accounts = build_pool_accounts(contexts)
    capacity_windows, plus_total = build_capacity_windows(contexts)
    traffic_items = build_traffic_distribution(contexts)

    totals = usage_index["totals"]
    total_requests = totals["totalRequests"]
    success_count = totals["successCount"]
    failure_count = totals["failureCount"]
    total_tokens = totals["totalTokens"]
    endpoint_errors = endpoint_errors or []
    gateway_ok = str((health_payload or {}).get("status") or "").lower() == "ok"
    usage_stats_enabled = bool((usage_stats_payload or {}).get("usage-statistics-enabled"))
    routing = routing_state(routing_payload)
    auth_alert_items = build_auth_alert_items(contexts, sampled_at)

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
        status_text += " Usage statistics are disabled, so traffic numbers may lag or stay empty."

    monitor_alert_items = build_monitor_alert_items(
        source=source,
        source_text=source_text,
        gateway_ok=gateway_ok,
        endpoint_errors=endpoint_errors,
    )
    alerts = build_alert_section(auth_alert_items + monitor_alert_items)

    active_count = sum(1 for context in contexts if context["issueKind"] is None)
    hard_issue_count = sum(1 for context in contexts if context["issueKind"] == "auth")
    quota_issue_count = sum(1 for context in contexts if context["issueKind"] == "quota")

    return {
        "available": True,
        "source": source,
        "sourceText": source_text,
        "sampledAt": iso_timestamp(sampled_at),
        "sampledAtText": display_timestamp(sampled_at),
        "statusText": status_text,
        "error": "; ".join(endpoint_errors) if endpoint_errors else None,
        "summary": {
            "gatewayPill": "Gateway OK" if gateway_ok else "Gateway down",
            "poolPill": f"{plan_counts['plus']} Plus · {plan_counts['team']} Team",
            "fiveHourPill": capacity_windows[0]["pillText"] if capacity_windows else "5h unknown",
            "weeklyPill": capacity_windows[1]["pillText"] if len(capacity_windows) > 1 else "Weekly unknown",
            "alertsPill": "Clean" if alerts["alertCount"] == 0 else count_label(alerts["alertCount"], "alert"),
            "subline": f"{routing['text']} · {format_count(total_requests)} req · {format_tokens(total_tokens)} tok",
        },
        "tabs": {
            "pool": {
                "title": "Pool Capacity",
                "summary": f"{plus_total} Plus · {plan_counts['team']} Team · {active_count} healthy · {hard_issue_count + quota_issue_count} issues",
                "stats": [
                    {"label": "Plus", "value": str(plus_total), "detail": "accounts counted in capacity windows"},
                    {"label": "Team", "value": str(plan_counts["team"]), "detail": "shown in the grid, excluded from Plus capacity"},
                    {"label": "Issues", "value": str(hard_issue_count + quota_issue_count), "detail": "hard auth failures and quota hits"},
                    {"label": "Routing", "value": routing["text"], "detail": routing["detail"]},
                ],
                "capacityWindows": capacity_windows,
                "accounts": pool_accounts,
                "footnote": "Only explicit CPA quota signals count toward 5h / weekly remaining. Unknown means the current management payload does not expose that window.",
            },
            "traffic": {
                "title": "Traffic Snapshot",
                "summary": "Current CPA totals and live account split. This view does not store local history yet.",
                "metrics": [
                    {"label": "Requests", "value": format_count(total_requests), "detail": "total recorded by CPA"},
                    {"label": "Success", "value": format_percent(success_count, total_requests), "detail": f"{format_count(success_count)} ok / {format_count(total_requests)} total"},
                    {"label": "Failures", "value": format_count(failure_count), "detail": "current aggregate failures"},
                    {"label": "Routing", "value": routing["text"], "detail": routing["detail"]},
                ],
                "distribution": traffic_items,
                "footnote": "Traffic uses current CPA usage totals only. This panel deliberately does not fake trend lines or cache hit rates.",
            },
            "alerts": alerts,
        },
    }


def build_unavailable_snapshot(error_text):
    sampled_at = now_local()
    message = trim_text(error_text or "No CPA data found yet.", limit=220)
    alerts = build_alert_section(
        [
            {
                "kind": "monitor",
                "tone": "bad",
                "title": "No CPA snapshot yet",
                "badge": "Monitor",
                "meta": "Waiting for first successful sample",
                "detail": message,
            }
        ]
    )
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
            "fiveHourPill": "5h unknown",
            "weeklyPill": "Weekly unknown",
            "alertsPill": count_label(alerts["alertCount"], "alert"),
            "subline": "Waiting for auth-files and usage data.",
        },
        "tabs": {
            "pool": dict(
                EMPTY_TAB,
                title="Pool Capacity",
                summary="No auth-file data yet.",
                stats=[],
                capacityWindows=[],
                accounts=[],
                footnote="The capacity grid appears after the first successful auth-files sample.",
            ),
            "traffic": dict(
                EMPTY_TAB,
                title="Traffic Snapshot",
                summary="No usage data yet.",
                metrics=[],
                distribution=[],
                footnote="Traffic totals appear after CPA reports usage.",
            ),
            "alerts": alerts,
        },
    }
