import datetime as dt


EMPTY_TAB = {
    "title": "",
    "summary": "",
    "stats": [],
    "items": [],
    "footnote": "",
}


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


def format_fractional_count(value):
    number = float(value or 0.0)
    return f"{number:.2f}"


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


def normalize_key(value):
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


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
