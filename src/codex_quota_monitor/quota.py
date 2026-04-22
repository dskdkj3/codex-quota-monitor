import copy
import datetime as dt
import json
import logging
import os
import urllib.request

from .version import USER_AGENT
from urllib.error import HTTPError

from .util import compact_error, normalize_key, now_local, parse_timestamp


DIRECT_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
WINDOW_IDS_BY_SECONDS = {
    18_000: "5h",
    604_800: "week",
}


def parse_quota_timestamp(value):
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


def parse_float(value):
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_window_seconds(window_payload):
    if not isinstance(window_payload, dict):
        return 0
    value = parse_float(
        window_payload.get("limit_window_seconds")
        or window_payload.get("window_duration_seconds")
        or window_payload.get("window_seconds")
    )
    if value is not None and value > 0:
        return int(round(value))

    minutes = parse_float(window_payload.get("window_duration_mins") or window_payload.get("window_minutes"))
    if minutes is not None and minutes > 0:
        return int(round(minutes * 60.0))

    return 0


def parse_quota_window(window_payload):
    seconds = parse_window_seconds(window_payload)
    window_id = WINDOW_IDS_BY_SECONDS.get(seconds)
    if not window_id:
        return None

    remaining = parse_float(window_payload.get("remaining_percent"))
    if remaining is None:
        used = parse_float(window_payload.get("used_percent"))
        if used is None:
            return None
        remaining = 100.0 - used

    remaining_percent = max(0.0, min(100.0, float(remaining)))
    percent = max(0, min(100, int(round(remaining_percent))))
    return {
        "id": window_id,
        "remainingPercent": remaining_percent,
        "percent": percent,
        "resetAt": parse_quota_timestamp(window_payload.get("reset_at") or window_payload.get("resets_at")),
    }


def parse_quota_usage_payload(payload):
    rate_limit = (payload or {}).get("rate_limit") or {}
    rate_limits = (payload or {}).get("rate_limits") or {}
    candidates = []

    for container in (rate_limit, rate_limits):
        if not isinstance(container, dict):
            continue
        candidates.extend(
            [
                container.get("primary_window"),
                container.get("secondary_window"),
                container.get("primary"),
                container.get("secondary"),
            ]
        )
        for value in container.values():
            if isinstance(value, dict):
                candidates.append(value)

    windows = {}
    for candidate in candidates:
        parsed = parse_quota_window(candidate)
        if parsed is None:
            continue
        windows[parsed["id"]] = parsed

    plan_type = str(
        (payload or {}).get("plan_type")
        or (((payload or {}).get("account") or {}).get("chatgpt") or {}).get("plan_type")
        or ""
    ).strip()

    if not plan_type and not windows:
        raise ValueError("usage payload has no plan_type or quota windows")

    return {
        "planType": plan_type,
        "windows": windows,
    }


def load_auth_payload(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def fetch_usage_payload(access_token, account_id, *, usage_url=DIRECT_USAGE_URL, timeout_seconds=5):
    request = urllib.request.Request(
        usage_url,
        headers={
            "Accept": "application/json",
            "Authorization": "Bearer " + access_token,
            "Cache-Control": "no-store",
            "User-Agent": USER_AGENT,
        },
    )
    if account_id:
        request.add_header("ChatGPT-Account-Id", account_id)

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return json.loads(response.read().decode(charset))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp is not None else ""
        detail = compact_error(body or exc.reason or "")
        raise RuntimeError(f"usage query returned HTTP {exc.code}: {detail}") from exc


def quota_sample_age_seconds(sample, reference_time):
    sampled_at = (sample or {}).get("sampledAt")
    if sampled_at is None or reference_time is None:
        return None
    return max(0.0, (reference_time - sampled_at).total_seconds())


def is_quota_sample_stale(sample, reference_time, cycle_seconds):
    age_seconds = quota_sample_age_seconds(sample, reference_time)
    if age_seconds is None or cycle_seconds <= 0:
        return False
    return age_seconds > float(cycle_seconds)


class QuotaSampler:
    def __init__(self, auth_dir, refresh_seconds, timeout_seconds, *, usage_url=DIRECT_USAGE_URL):
        self.auth_dir = auth_dir or ""
        self.refresh_seconds = max(1, int(refresh_seconds or 15))
        self.timeout_seconds = timeout_seconds
        self.usage_url = usage_url
        self.logger = logging.getLogger("codex-quota-monitor.quota")
        self._samples = {}
        self._eligible_keys = ()
        self._cursor = 0
        self._attempts_in_cycle = 0

    def refresh(self, auth_files, reference_time=None):
        reference_time = reference_time or now_local()
        eligible_accounts = self._build_eligible_accounts(auth_files)
        self._sync_inventory(eligible_accounts)

        attempted_key = None
        attempt_error = None
        if eligible_accounts:
            account = eligible_accounts[self._cursor % len(eligible_accounts)]
            self._cursor = (self._cursor + 1) % len(eligible_accounts)
            self._attempts_in_cycle = min(len(eligible_accounts), self._attempts_in_cycle + 1)
            attempted_key = account["key"]
            attempt_error = self._refresh_account(account, reference_time)

        cycle_seconds = max(self.refresh_seconds * max(len(eligible_accounts), 1), self.refresh_seconds)
        samples = {
            account["key"]: copy.deepcopy(self._samples.get(account["key"], {}))
            for account in eligible_accounts
        }

        sampled_count = 0
        fresh_count = 0
        stale_count = 0
        has_any_error = False
        for sample in samples.values():
            if sample.get("sampledAt") is not None:
                sampled_count += 1
                if is_quota_sample_stale(sample, reference_time, cycle_seconds):
                    stale_count += 1
                else:
                    fresh_count += 1
            if sample.get("lastError"):
                has_any_error = True

        completed_cycle = bool(eligible_accounts) and self._attempts_in_cycle >= len(eligible_accounts)
        degraded = bool(eligible_accounts) and completed_cycle and fresh_count == 0 and has_any_error

        if not eligible_accounts:
            status = "disabled"
        elif degraded:
            status = "degraded"
        elif sampled_count == 0:
            status = "warming"
        elif stale_count > 0 or sampled_count < len(eligible_accounts):
            status = "partial"
        else:
            status = "live"

        return {
            "samples": samples,
            "status": status,
            "eligibleCount": len(eligible_accounts),
            "sampledCount": sampled_count,
            "freshCount": fresh_count,
            "staleCount": stale_count,
            "cycleSeconds": cycle_seconds,
            "completedCycle": completed_cycle,
            "degraded": degraded,
            "attemptedKey": attempted_key,
            "attemptError": attempt_error,
        }

    def _sync_inventory(self, eligible_accounts):
        eligible_keys = tuple(account["key"] for account in eligible_accounts)
        if eligible_keys != self._eligible_keys:
            self._attempts_in_cycle = 0
            self._eligible_keys = eligible_keys

        self._samples = {
            key: sample
            for key, sample in self._samples.items()
            if key in eligible_keys
        }
        if self._cursor >= len(eligible_keys):
            self._cursor = 0

    def _build_eligible_accounts(self, auth_files):
        accounts = []
        for auth_file in auth_files or []:
            provider = normalize_key(auth_file.get("provider") or auth_file.get("type"))
            if provider != "codex":
                continue

            key = str(auth_file.get("auth_index") or "").strip()
            if not key:
                continue

            path = self._resolve_auth_file_path(auth_file)
            if not path:
                continue

            account_id = str(auth_file.get("account_id") or "").strip()
            id_token = auth_file.get("id_token") or {}
            if not account_id and isinstance(id_token, dict):
                account_id = str(id_token.get("chatgpt_account_id") or "").strip()

            accounts.append(
                {
                    "key": key,
                    "path": path,
                    "accountId": account_id,
                }
            )
        return accounts

    def _resolve_auth_file_path(self, auth_file):
        raw_path = str(auth_file.get("path") or "").strip()
        if raw_path:
            return raw_path

        name = str(auth_file.get("name") or "").strip()
        if not name or not self.auth_dir:
            return ""
        return os.path.join(self.auth_dir, name)

    def _refresh_account(self, account, reference_time):
        sample = self._samples.setdefault(account["key"], {})
        sample["lastAttemptAt"] = reference_time

        try:
            auth_payload = self._load_auth_payload(account["path"])
            access_token = str(auth_payload.get("access_token") or "").strip()
            if not access_token:
                raise RuntimeError("auth file has no access_token")

            account_id = account["accountId"] or str(auth_payload.get("account_id") or "").strip()
            usage_payload = self._fetch_usage_payload(access_token, account_id)
            parsed = parse_quota_usage_payload(usage_payload)

            sample["sampledAt"] = reference_time
            sample["planType"] = parsed.get("planType") or sample.get("planType") or ""
            sample["windows"] = parsed.get("windows") or {}
            sample["lastError"] = None
            sample["lastErrorAt"] = None
            return None
        except Exception as exc:  # pragma: no cover - runtime path
            error_text = compact_error(exc)
            sample["lastError"] = error_text
            sample["lastErrorAt"] = reference_time
            self.logger.warning("quota sample failed key=%s: %s", account["key"], error_text)
            return error_text

    def _load_auth_payload(self, path):
        return load_auth_payload(path)

    def _fetch_usage_payload(self, access_token, account_id):
        return fetch_usage_payload(
            access_token,
            account_id,
            usage_url=self.usage_url,
            timeout_seconds=self.timeout_seconds,
        )
