import argparse
import csv
import datetime as dt
import json
import logging
import os
import pathlib
import shutil
import socket
import statistics
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from .quota import fetch_usage_payload, load_auth_payload, parse_quota_usage_payload
from .util import compact_error, iso_timestamp, now_local, normalize_key


DEFAULT_MANAGEMENT_BASE_URL = "http://127.0.0.1:8318"
DEFAULT_MODEL = "gpt-5.4"
DEFAULT_API_KEY = "sk-bench"
DEFAULT_REQUEST_TIMEOUT_SECONDS = 180.0


@dataclass(frozen=True)
class PromptCase:
    prompt_id: str
    prompt_class: str
    input_text: str


@dataclass(frozen=True)
class ResolvedAuthFile:
    selector: str
    auth_index: str
    label: str
    plan_type: str
    path: str
    account_id: str
    name: str


class BenchmarkError(RuntimeError):
    pass


def default_output_dir():
    stamp = now_local().strftime("%Y%m%d-%H%M%S")
    return pathlib.Path.cwd() / "result" / f"codex-quota-benchmark-{stamp}"


def request_json(url, *, headers=None, payload=None, timeout_seconds=DEFAULT_REQUEST_TIMEOUT_SECONDS):
    request = urllib.request.Request(url, headers=headers or {})
    if payload is not None:
        request.data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return json.loads(response.read().decode(charset))


def fetch_auth_files(management_base_url, timeout_seconds):
    payload = request_json(
        management_base_url.rstrip("/") + "/v0/management/auth-files",
        headers={"Accept": "application/json", "Cache-Control": "no-store"},
        timeout_seconds=timeout_seconds,
    )
    return (payload or {}).get("files") or []


def auth_candidate_strings(auth_file):
    values = []
    for field in ("auth_index", "name", "label", "email", "account", "path"):
        value = str(auth_file.get(field) or "").strip()
        if value:
            values.append(value)
    return values


def match_auth_file(auth_file, selector):
    selector_text = str(selector or "").strip()
    if not selector_text:
        return False
    selector_norm = normalize_key(selector_text)
    if not selector_norm:
        return False

    for candidate in auth_candidate_strings(auth_file):
        candidate_norm = normalize_key(candidate)
        if not candidate_norm:
            continue
        if candidate_norm == selector_norm or selector_norm in candidate_norm:
            return True
    return False


def resolve_auth_file(auth_files, selector, expected_plan_kind):
    matches = [item for item in auth_files if match_auth_file(item, selector)]
    if not matches:
        raise BenchmarkError(f"selector {selector!r} did not match any auth file")
    if len(matches) > 1:
        choices = ", ".join(
            f"{item.get('auth_index') or '?'}:{item.get('name') or item.get('label') or item.get('path') or '?'}"
            for item in matches
        )
        raise BenchmarkError(f"selector {selector!r} matched multiple auth files: {choices}")

    match = matches[0]
    plan_type = str(((match.get("id_token") or {}).get("plan_type") or match.get("plan_type") or "")).strip() or "unknown"
    normalized_plan = normalize_key(plan_type)
    if expected_plan_kind == "plus" and "plus" not in normalized_plan:
        raise BenchmarkError(f"selector {selector!r} resolved to non-Plus auth file {match.get('name')!r} ({plan_type})")
    if expected_plan_kind == "team" and "team" not in normalized_plan:
        raise BenchmarkError(f"selector {selector!r} resolved to non-Team auth file {match.get('name')!r} ({plan_type})")
    if not str(match.get("path") or "").strip():
        raise BenchmarkError(f"selector {selector!r} resolved auth file without a readable path")

    account_id = str(match.get("account_id") or "").strip()
    if not account_id and isinstance(match.get("id_token"), dict):
        account_id = str(match["id_token"].get("chatgpt_account_id") or "").strip()

    return ResolvedAuthFile(
        selector=str(selector),
        auth_index=str(match.get("auth_index") or ""),
        label=str(match.get("label") or match.get("email") or match.get("account") or match.get("name") or selector),
        plan_type=plan_type,
        path=str(match.get("path") or ""),
        account_id=account_id,
        name=str(match.get("name") or match.get("id") or ""),
    )


def discover_cli_proxy_api_bin(explicit_path):
    if explicit_path:
        return explicit_path

    discovered = shutil.which("cli-proxy-api")
    if discovered:
        return discovered

    systemctl = shutil.which("systemctl")
    if systemctl:
        try:
            output = subprocess.check_output(
                [systemctl, "show", "-P", "ExecStart", "cli-proxy-api.service"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            output = ""
        if output:
            candidate = output.split(maxsplit=1)[0]
            if candidate:
                return candidate

    raise BenchmarkError("could not locate cli-proxy-api; pass --cli-proxy-api-bin explicitly")


def pick_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def yaml_scalar(value):
    return json.dumps(value)


def build_gateway_config(auth_dir, port, api_key):
    lines = [
        f"host: {yaml_scalar('127.0.0.1')}",
        f"port: {port}",
        f"auth-dir: {yaml_scalar(auth_dir)}",
        "api-keys:",
        f"  - {yaml_scalar(api_key)}",
        "logging-to-file: false",
        "request-log: false",
        "usage-statistics-enabled: false",
        "routing:",
        f"  strategy: {yaml_scalar('round-robin')}",
        "  session-affinity: false",
    ]
    return "\n".join(lines) + "\n"


def wait_for_gateway_ready(base_url, api_key, model, timeout_seconds):
    deadline = time.monotonic() + timeout_seconds
    last_error = "not started yet"
    while time.monotonic() < deadline:
        try:
            health = request_json(
                base_url.rstrip("/") + "/healthz",
                headers={"Accept": "application/json", "Cache-Control": "no-store"},
                timeout_seconds=5,
            )
            if (health or {}).get("status") != "ok":
                last_error = compact_error(health)
                time.sleep(0.5)
                continue

            models = request_json(
                base_url.rstrip("/") + "/v1/models",
                headers={"Accept": "application/json", "Authorization": "Bearer " + api_key},
                timeout_seconds=5,
            )
            ids = {item.get("id") for item in (models or {}).get("data") or [] if item.get("id")}
            if model not in ids:
                last_error = f"models endpoint missing {model}"
                time.sleep(0.5)
                continue
            return
        except Exception as exc:  # pragma: no cover - runtime path
            last_error = compact_error(exc)
            time.sleep(0.5)
    raise BenchmarkError(f"temporary gateway at {base_url} did not become ready: {last_error}")


def extract_usage(response_payload):
    usage = (response_payload or {}).get("usage") or {}
    input_details = usage.get("input_tokens_details") or {}
    output_details = usage.get("output_tokens_details") or {}
    return {
        "input_tokens": int(usage.get("input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or 0),
        "reasoning_tokens": int(output_details.get("reasoning_tokens") or 0),
        "cached_tokens": int(input_details.get("cached_tokens") or 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
    }


def percentile(values, ratio):
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    index = max(0, min(len(ordered) - 1, int(round(ratio * (len(ordered) - 1)))))
    return ordered[index]


def mean_value(values):
    return statistics.fmean(values) if values else None


def request_payload(prompt_case, model, reasoning_effort, service_tier):
    payload = {
        "model": model,
        "input": prompt_case.input_text,
        "store": False,
    }
    if reasoning_effort:
        payload["reasoning"] = {"effort": reasoning_effort}
    if service_tier:
        payload["service_tier"] = service_tier
    return payload


def run_one_request(
    *,
    phase,
    gateway_name,
    base_url,
    api_key,
    prompt_case,
    model,
    reasoning_effort,
    tier_label,
    timeout_seconds,
):
    payload = request_payload(
        prompt_case,
        model,
        reasoning_effort,
        "priority" if tier_label == "fast" else None,
    )
    started_at = now_local()
    clock_started = time.perf_counter()
    response_payload = None
    error_text = ""
    failed = False
    try:
        response_payload = request_json(
            base_url.rstrip("/") + "/v1/responses",
            headers={
                "Accept": "application/json",
                "Authorization": "Bearer " + api_key,
                "Cache-Control": "no-store",
                "Content-Type": "application/json",
            },
            payload=payload,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:  # pragma: no cover - runtime path
        failed = True
        error_text = compact_error(exc)
    latency_ms = round((time.perf_counter() - clock_started) * 1000.0, 3)
    usage = extract_usage(response_payload)
    status = str((response_payload or {}).get("status") or "")

    return {
        "phase": phase,
        "gateway": gateway_name,
        "tier": tier_label,
        "prompt_id": prompt_case.prompt_id,
        "prompt_class": prompt_case.prompt_class,
        "requested_service_tier": "priority" if tier_label == "fast" else "",
        "response_service_tier": str((response_payload or {}).get("service_tier") or ""),
        "timestamp": iso_timestamp(started_at),
        "latency_ms": latency_ms,
        "failed": failed,
        "status": status,
        "error": error_text,
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "reasoning_tokens": usage["reasoning_tokens"],
        "cached_tokens": usage["cached_tokens"],
        "total_tokens": usage["total_tokens"],
        "response_id": str((response_payload or {}).get("id") or ""),
    }


def load_prompt_cases(prompt_file):
    if not prompt_file:
        return build_default_prompt_cases()

    payload = json.loads(pathlib.Path(prompt_file).read_text(encoding="utf-8"))
    prompt_cases = []
    for index, item in enumerate(payload):
        prompt_id = str(item.get("id") or f"prompt-{index + 1:02d}")
        prompt_class = str(item.get("class") or "custom")
        input_text = str(item.get("input") or "").strip()
        if not input_text:
            raise BenchmarkError(f"prompt {prompt_id!r} has empty input")
        prompt_cases.append(PromptCase(prompt_id=prompt_id, prompt_class=prompt_class, input_text=input_text))
    return prompt_cases


def build_default_prompt_cases():
    prompt_cases = []

    short_topics = [
        "session affinity",
        "request retries",
        "cached tokens",
        "quota windows",
        "gateway health checks",
        "round robin routing",
        "worktree isolation",
        "direct quota sampling",
        "response latency",
        "reasoning effort",
    ]
    for index, topic in enumerate(short_topics, start=1):
        prompt_cases.append(
            PromptCase(
                prompt_id=f"short-{index:02d}",
                prompt_class="short",
                input_text=f"Answer in exactly one short sentence: what is the main tradeoff of {topic}?",
            )
        )

    medium_pairs = [
        ("sticky routing", "plain round robin"),
        ("direct quota sampling", "aggregated traffic counters"),
        ("temporary benchmark gateways", "live pool routing"),
        ("team quotas", "plus quotas"),
        ("baseline tier", "priority tier"),
        ("short prompts", "long prompts"),
        ("auth file selectors", "manual path lookup"),
        ("CSV records", "dashboard snapshots"),
        ("single-account isolation", "pool-wide inference"),
        ("local timing", "server-side timing"),
    ]
    for index, (left, right) in enumerate(medium_pairs, start=1):
        prompt_cases.append(
            PromptCase(
                prompt_id=f"medium-{index:02d}",
                prompt_class="medium",
                input_text=(
                    "Compare the two options in exactly three bullets. "
                    "Each bullet must be under 18 words and mention a concrete engineering tradeoff.\n\n"
                    f"Option A: {left}\n"
                    f"Option B: {right}"
                ),
            )
        )

    long_topics = [
        "quota-first monitoring",
        "temporary gateway isolation",
        "routing drift under mixed traffic",
        "why a team account is excluded from plus capacity",
        "benchmark output files",
        "direct usage payload parsing",
        "weekly-window measurement noise",
        "service-tier A/B design",
        "single-account auth resolution",
        "consumer lock updates",
    ]
    for index, topic in enumerate(long_topics, start=1):
        context = (
            f"A benchmark needs to evaluate {topic}. "
            "The operator wants speed and quota measurements without disturbing the live pool. "
            "The benchmark should isolate one account at a time, keep the same prompt set across runs, "
            "and record structured outputs that can be audited later. "
            "The report should separate latency, token usage, and real quota-window drop instead of mixing them. "
            "Any noisy or reset-crossing batch should be marked invalid rather than silently averaged. "
        ) * 4
        prompt_cases.append(
            PromptCase(
                prompt_id=f"long-{index:02d}",
                prompt_class="long",
                input_text=(
                    "Read the context and answer with exactly four bullets, each under 18 words.\n\n"
                    f"Context:\n{context}\n\n"
                    "Question: summarize the most important implementation constraints."
                ),
            )
        )

    return prompt_cases


class TemporaryGateway:
    def __init__(self, *, cli_proxy_api_bin, account, work_root, api_key, model, timeout_seconds):
        self.cli_proxy_api_bin = cli_proxy_api_bin
        self.account = account
        self.work_root = pathlib.Path(work_root)
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.port = pick_free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.gateway_dir = self.work_root / normalize_key(f"{account.plan_type}-{account.label}")[:48]
        self.auth_dir = self.gateway_dir / "auth"
        self.config_path = self.gateway_dir / "config.yaml"
        self.stdout_path = self.gateway_dir / "stdout.log"
        self.stderr_path = self.gateway_dir / "stderr.log"
        self.process = None
        self._stdout_handle = None
        self._stderr_handle = None

    @property
    def gateway_name(self):
        return f"{self.account.plan_type}:{self.account.label}"

    def __enter__(self):
        self.gateway_dir.mkdir(parents=True, exist_ok=True)
        self.auth_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.account.path, self.auth_dir / pathlib.Path(self.account.path).name)
        self.config_path.write_text(build_gateway_config(str(self.auth_dir), self.port, self.api_key), encoding="utf-8")
        self._stdout_handle = open(self.stdout_path, "w", encoding="utf-8")
        self._stderr_handle = open(self.stderr_path, "w", encoding="utf-8")
        env = dict(os.environ)
        env["HOME"] = str(self.gateway_dir)
        self.process = subprocess.Popen(
            [self.cli_proxy_api_bin, "-local-model", "-config", str(self.config_path)],
            cwd=self.gateway_dir,
            env=env,
            stdout=self._stdout_handle,
            stderr=self._stderr_handle,
        )
        try:
            wait_for_gateway_ready(self.base_url, self.api_key, self.model, self.timeout_seconds)
        except Exception:
            self.close()
            raise
        return self

    def close(self):
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
        self.process = None
        for handle_name in ("_stdout_handle", "_stderr_handle"):
            handle = getattr(self, handle_name, None)
            if handle is not None:
                handle.close()
                setattr(self, handle_name, None)

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


def sample_quota(account, timeout_seconds):
    auth_payload = load_auth_payload(account.path)
    access_token = str(auth_payload.get("access_token") or "").strip()
    if not access_token:
        raise BenchmarkError(f"auth file {account.path} has no access_token")
    account_id = account.account_id or str(auth_payload.get("account_id") or "").strip()
    usage_payload = fetch_usage_payload(access_token, account_id, timeout_seconds=timeout_seconds)
    parsed = parse_quota_usage_payload(usage_payload)
    windows = {}
    for window_id, window in (parsed.get("windows") or {}).items():
        windows[window_id] = {
            "remainingPercent": window.get("remainingPercent"),
            "percent": window.get("percent"),
            "resetAt": iso_timestamp(window["resetAt"]) if window.get("resetAt") is not None else "",
        }

    return {
        "sampledAt": iso_timestamp(now_local()),
        "planType": parsed.get("planType") or account.plan_type,
        "windows": windows,
    }


def compute_window_drop(before_window, after_window):
    if not before_window or not after_window:
        return {"valid": False, "reason": "missing-window", "drop": None}
    before_reset = str(before_window.get("resetAt") or "")
    after_reset = str(after_window.get("resetAt") or "")
    if before_reset and after_reset and before_reset != after_reset:
        return {"valid": False, "reason": "reset-changed", "drop": None}

    before_value = before_window.get("remainingPercent")
    after_value = after_window.get("remainingPercent")
    if before_value is None or after_value is None:
        return {"valid": False, "reason": "missing-remaining", "drop": None}

    drop = float(before_value) - float(after_value)
    if drop < 0:
        return {"valid": False, "reason": "remaining-increased", "drop": None}
    return {"valid": True, "reason": "", "drop": round(drop, 6)}


def exhausted_windows(sample):
    exhausted = []
    for window_id, window in (sample.get("windows") or {}).items():
        remaining = window.get("remainingPercent")
        if remaining is not None and float(remaining) <= 0.0:
            exhausted.append(window_id)
    return sorted(exhausted)


def summarize_performance(records):
    summary = {}
    by_tier = {}
    for record in records:
        if record["phase"] != "performance" or record["failed"]:
            continue
        by_tier.setdefault(record["tier"], []).append(record)

    for tier, tier_records in by_tier.items():
        latencies = [record["latency_ms"] for record in tier_records]
        total_tokens = [record["total_tokens"] for record in tier_records]
        output_tokens = [record["output_tokens"] for record in tier_records]
        summary[tier] = {
            "count": len(tier_records),
            "p50_latency_ms": percentile(latencies, 0.5),
            "p90_latency_ms": percentile(latencies, 0.9),
            "avg_total_tokens": mean_value(total_tokens),
            "avg_output_tokens": mean_value(output_tokens),
        }

    baseline = summary.get("baseline") or {}
    fast = summary.get("fast") or {}
    summary["comparison"] = {
        "speedup_p50": (
            round(float(baseline["p50_latency_ms"]) / float(fast["p50_latency_ms"]), 4)
            if baseline.get("p50_latency_ms") and fast.get("p50_latency_ms")
            else None
        ),
        "speedup_p90": (
            round(float(baseline["p90_latency_ms"]) / float(fast["p90_latency_ms"]), 4)
            if baseline.get("p90_latency_ms") and fast.get("p90_latency_ms")
            else None
        ),
        "token_overhead_ratio": (
            round((float(fast["avg_total_tokens"]) / float(baseline["avg_total_tokens"])) - 1.0, 6)
            if baseline.get("avg_total_tokens") and fast.get("avg_total_tokens")
            else None
        ),
    }
    return summary


def perform_performance_runs(args, plus_gateway, prompt_cases, request_records):
    logging.getLogger("codex-quota-benchmark").info(
        "running performance benchmark on %s with %s warm-up pairs and %s measured pairs",
        plus_gateway.gateway_name,
        args.warmup_pairs,
        args.performance_pairs,
    )

    total_pairs = args.warmup_pairs + args.performance_pairs
    for pair_index in range(total_pairs):
        prompt_case = prompt_cases[pair_index % len(prompt_cases)]
        measured = pair_index >= args.warmup_pairs
        order = ("baseline", "fast") if pair_index % 2 == 0 else ("fast", "baseline")
        for tier_label in order:
            record = run_one_request(
                phase="performance",
                gateway_name=plus_gateway.gateway_name,
                base_url=plus_gateway.base_url,
                api_key=args.api_key,
                prompt_case=prompt_case,
                model=args.model,
                reasoning_effort=args.reasoning_effort,
                tier_label=tier_label,
                timeout_seconds=args.request_timeout_seconds,
            )
            record["pair_index"] = pair_index - args.warmup_pairs + 1 if measured else 0
            record["warmup"] = not measured
            request_records.append(record)

    return summarize_performance([record for record in request_records if not record.get("warmup")])


def accumulate_quota_drop(accumulator, account_key, window_id, drop_value):
    account_windows = accumulator.setdefault(account_key, {})
    account_windows[window_id] = round(float(account_windows.get(window_id) or 0.0) + float(drop_value or 0.0), 6)


def perform_quota_runs(args, team_gateway, plus_gateways, prompt_cases, request_records):
    logging.getLogger("codex-quota-benchmark").info(
        "running quota benchmark with %s plus reference(s), batch size %s, max rounds %s",
        len(plus_gateways),
        args.quota_batch_size,
        args.quota_max_rounds,
    )
    tier_label = "fast" if args.quota_service_tier == "fast" else "baseline"
    accumulators = {"team": {}, "plus": {}}
    quota_batches = []
    stop_reason = ""
    team_exhaustion = None

    for round_index in range(1, args.quota_max_rounds + 1):
        participants = [("team", team_gateway)] + [("plus", gateway) for gateway in plus_gateways]
        for role, gateway in participants:
            before = sample_quota(gateway.account, args.request_timeout_seconds)
            for offset in range(args.quota_batch_size):
                prompt_case = prompt_cases[((round_index - 1) * args.quota_batch_size + offset) % len(prompt_cases)]
                record = run_one_request(
                    phase="quota",
                    gateway_name=gateway.gateway_name,
                    base_url=gateway.base_url,
                    api_key=args.api_key,
                    prompt_case=prompt_case,
                    model=args.model,
                    reasoning_effort=args.reasoning_effort,
                    tier_label=tier_label,
                    timeout_seconds=args.request_timeout_seconds,
                )
                record["round_index"] = round_index
                request_records.append(record)
            after = sample_quota(gateway.account, args.request_timeout_seconds)
            windows = {}
            for window_id in ("5h", "week"):
                delta = compute_window_drop((before.get("windows") or {}).get(window_id), (after.get("windows") or {}).get(window_id))
                windows[window_id] = delta
                if delta["valid"] and delta["drop"] is not None:
                    accumulate_quota_drop(accumulators[role], gateway.account.auth_index, window_id, delta["drop"])
            batch = {
                "phase": "quota",
                "round_index": round_index,
                "role": role,
                "gateway": gateway.gateway_name,
                "auth_index": gateway.account.auth_index,
                "tier": tier_label,
                "before": before,
                "after": after,
                "windows": windows,
            }
            quota_batches.append(batch)
            if role == "team":
                exhausted = exhausted_windows(after)
                if exhausted:
                    stop_reason = "team-quota-exhausted"
                    team_exhaustion = {
                        "round_index": round_index,
                        "auth_index": gateway.account.auth_index,
                        "label": gateway.account.label,
                        "windows": exhausted,
                    }
                    batch["stopReason"] = stop_reason
                    break

        if stop_reason:
            break

        plus_5h_values = [
            accumulators["plus"].get(gateway.account.auth_index, {}).get("5h", 0.0)
            for gateway in plus_gateways
        ]
        plus_week_values = [
            accumulators["plus"].get(gateway.account.auth_index, {}).get("week", 0.0)
            for gateway in plus_gateways
        ]
        team_5h_value = accumulators["team"].get(team_gateway.account.auth_index, {}).get("5h", 0.0)
        team_week_value = accumulators["team"].get(team_gateway.account.auth_index, {}).get("week", 0.0)
        if (
            plus_5h_values
            and min(plus_5h_values) >= args.quota_five_hour_threshold
            and min(plus_week_values) >= args.quota_weekly_threshold
            and team_5h_value > 0.0
            and team_week_value > 0.0
        ):
            stop_reason = "thresholds-met"
            break

    if not stop_reason:
        stop_reason = "max-rounds"

    return build_quota_summary(
        team_gateway,
        plus_gateways,
        accumulators,
        quota_batches,
        stop_reason=stop_reason,
        team_exhaustion=team_exhaustion,
    )


def build_quota_summary(team_gateway, plus_gateways, accumulators, quota_batches, *, stop_reason="", team_exhaustion=None):
    team_key = team_gateway.account.auth_index
    team_windows = accumulators.get("team", {}).get(team_key, {})
    per_plus = []
    ratio_summary = {"5h": [], "week": []}
    for gateway in plus_gateways:
        plus_windows = accumulators.get("plus", {}).get(gateway.account.auth_index, {})
        ratios = {}
        for window_id in ("5h", "week"):
            plus_drop = plus_windows.get(window_id)
            team_drop = team_windows.get(window_id)
            ratio = None
            if plus_drop and team_drop:
                ratio = round(float(plus_drop) / float(team_drop), 6)
                ratio_summary[window_id].append(ratio)
            ratios[window_id] = {
                "plus_drop": plus_drop,
                "team_drop": team_drop,
                "ratio_in_plus_units": ratio,
            }
        per_plus.append(
            {
                "plus_auth_index": gateway.account.auth_index,
                "plus_label": gateway.account.label,
                "ratios": ratios,
            }
        )

    aggregate = {}
    for window_id, values in ratio_summary.items():
        aggregate[window_id] = {
            "mean_ratio_in_plus_units": round(statistics.fmean(values), 6) if values else None,
            "min_ratio_in_plus_units": round(min(values), 6) if values else None,
            "max_ratio_in_plus_units": round(max(values), 6) if values else None,
        }

    return {
        "team_auth_index": team_key,
        "team_label": team_gateway.account.label,
        "stopReason": stop_reason,
        "complete": stop_reason == "thresholds-met",
        "teamExhaustion": team_exhaustion,
        "team_windows": team_windows,
        "per_plus": per_plus,
        "aggregate": aggregate,
        "batches": quota_batches,
    }


def write_csv(path, records):
    if not records:
        return
    fieldnames = []
    seen = set()
    for record in records:
        for key in record.keys():
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)


def write_jsonl(path, records):
    with open(path, "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n")


def format_metric(value, digits=3):
    if value is None:
        return "n/a"
    return f"{float(value):.{digits}f}"


def build_report(args, prompt_cases, performance_summary, quota_summary, output_dir):
    lines = [
        "# Codex Quota Benchmark",
        "",
        "## Run",
        "",
        f"- generated_at: `{iso_timestamp(now_local())}`",
        f"- output_dir: `{output_dir}`",
        f"- model: `{args.model}`",
        f"- reasoning_effort: `{args.reasoning_effort or 'omitted'}`",
        f"- prompt_count: `{len(prompt_cases)}`",
        f"- plus_selectors: `{', '.join(args.plus_selectors)}`",
        f"- team_selector: `{args.team_selector}`",
        "",
        "## Performance",
        "",
    ]
    if performance_summary:
        baseline = performance_summary.get("baseline") or {}
        fast = performance_summary.get("fast") or {}
        comparison = performance_summary.get("comparison") or {}
        lines.extend(
            [
                f"- baseline p50 latency ms: `{format_metric(baseline.get('p50_latency_ms'))}`",
                f"- fast p50 latency ms: `{format_metric(fast.get('p50_latency_ms'))}`",
                f"- baseline p90 latency ms: `{format_metric(baseline.get('p90_latency_ms'))}`",
                f"- fast p90 latency ms: `{format_metric(fast.get('p90_latency_ms'))}`",
                f"- speedup p50: `{format_metric(comparison.get('speedup_p50'), 4)}`",
                f"- speedup p90: `{format_metric(comparison.get('speedup_p90'), 4)}`",
                f"- token overhead ratio: `{format_metric(comparison.get('token_overhead_ratio'), 6)}`",
            ]
        )
    else:
        lines.append("- skipped")

    lines.extend(["", "## Quota Ratios", ""])
    if quota_summary:
        lines.append(f"- stop reason: `{quota_summary.get('stopReason') or 'unknown'}`")
        if quota_summary.get("teamExhaustion"):
            exhaustion = quota_summary["teamExhaustion"]
            lines.append(
                f"- Team quota exhausted at round `{exhaustion.get('round_index')}` "
                f"for windows `{', '.join(exhaustion.get('windows') or [])}`; "
                "ratios are incomplete if thresholds were not reached before that point."
            )
        aggregate = quota_summary.get("aggregate") or {}
        for window_id in ("5h", "week"):
            window_summary = aggregate.get(window_id) or {}
            lines.append(
                f"- {window_id}: mean `{format_metric(window_summary.get('mean_ratio_in_plus_units'), 4)}`"
                f", range `{format_metric(window_summary.get('min_ratio_in_plus_units'), 4)}`"
                f" .. `{format_metric(window_summary.get('max_ratio_in_plus_units'), 4)}` plus"
            )
        lines.append("")
        lines.append("| Plus Account | 5h Ratio | Weekly Ratio |")
        lines.append("| --- | ---: | ---: |")
        for item in quota_summary.get("per_plus") or []:
            lines.append(
                f"| {item['plus_label']} | "
                f"{format_metric((item['ratios'].get('5h') or {}).get('ratio_in_plus_units'), 4)} | "
                f"{format_metric((item['ratios'].get('week') or {}).get('ratio_in_plus_units'), 4)} |"
            )
    else:
        lines.append("- skipped")

    lines.extend(
        [
            "",
            "## Files",
            "",
            "- `requests.csv`: per-request latency and token records",
            "- `quota_snapshots.jsonl`: per-batch before/after quota snapshots and deltas",
            "- `summary.json`: machine-readable summary",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Benchmark fast-vs-baseline latency and Team-vs-Plus quota ratios.")
    parser.add_argument("--management-base-url", default=DEFAULT_MANAGEMENT_BASE_URL)
    parser.add_argument("--cli-proxy-api-bin", default="")
    parser.add_argument("--output-dir", default=str(default_output_dir()))
    parser.add_argument("--prompt-file", default="")
    parser.add_argument("--plus-selector", dest="plus_selectors", action="append", required=True)
    parser.add_argument("--team-selector", required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--reasoning-effort", default="")
    parser.add_argument("--api-key", default=DEFAULT_API_KEY)
    parser.add_argument("--request-timeout-seconds", type=float, default=DEFAULT_REQUEST_TIMEOUT_SECONDS)
    parser.add_argument("--warmup-pairs", type=int, default=10)
    parser.add_argument("--performance-pairs", type=int, default=30)
    parser.add_argument("--quota-batch-size", type=int, default=10)
    parser.add_argument("--quota-max-rounds", type=int, default=40)
    parser.add_argument("--quota-five-hour-threshold", type=float, default=15.0)
    parser.add_argument("--quota-weekly-threshold", type=float, default=5.0)
    parser.add_argument("--quota-service-tier", choices=("baseline", "fast"), default="baseline")
    parser.add_argument("--skip-performance", action="store_true")
    parser.add_argument("--skip-quota", action="store_true")
    parser.add_argument("--keep-work-dir", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    output_dir = pathlib.Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    prompt_cases = load_prompt_cases(args.prompt_file)
    auth_files = fetch_auth_files(args.management_base_url, args.request_timeout_seconds)
    plus_accounts = [resolve_auth_file(auth_files, selector, "plus") for selector in args.plus_selectors]
    team_account = resolve_auth_file(auth_files, args.team_selector, "team")
    cli_proxy_api_bin = discover_cli_proxy_api_bin(args.cli_proxy_api_bin)

    config_payload = {
        "generatedAt": iso_timestamp(now_local()),
        "managementBaseUrl": args.management_base_url,
        "cliProxyApiBin": cli_proxy_api_bin,
        "model": args.model,
        "reasoningEffort": args.reasoning_effort,
        "plusAccounts": [account.__dict__ for account in plus_accounts],
        "teamAccount": team_account.__dict__,
        "promptCount": len(prompt_cases),
    }
    (output_dir / "config.json").write_text(
        json.dumps(config_payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    request_records = []
    performance_summary = None
    quota_summary = None

    with tempfile.TemporaryDirectory(prefix="codex-quota-benchmark.") as temp_root:
        work_root = pathlib.Path(temp_root)
        gateways = []
        try:
            team_gateway = TemporaryGateway(
                cli_proxy_api_bin=cli_proxy_api_bin,
                account=team_account,
                work_root=work_root,
                api_key=args.api_key,
                model=args.model,
                timeout_seconds=args.request_timeout_seconds,
            )
            gateways.append(team_gateway.__enter__())
            plus_gateways = []
            for account in plus_accounts:
                gateway = TemporaryGateway(
                    cli_proxy_api_bin=cli_proxy_api_bin,
                    account=account,
                    work_root=work_root,
                    api_key=args.api_key,
                    model=args.model,
                    timeout_seconds=args.request_timeout_seconds,
                )
                plus_gateways.append(gateway.__enter__())
                gateways.append(gateway)

            if not args.skip_performance:
                performance_summary = perform_performance_runs(args, plus_gateways[0], prompt_cases, request_records)
            if not args.skip_quota:
                quota_summary = perform_quota_runs(args, team_gateway, plus_gateways, prompt_cases, request_records)

            if args.keep_work_dir:
                destination = output_dir / "gateway-workdir"
                if destination.exists():
                    shutil.rmtree(destination)
                shutil.copytree(work_root, destination)
        finally:
            for gateway in reversed(gateways):
                gateway.close()

    write_csv(output_dir / "requests.csv", request_records)
    write_jsonl(output_dir / "quota_snapshots.jsonl", (quota_summary or {}).get("batches") or [])

    summary_payload = {
        "generatedAt": iso_timestamp(now_local()),
        "performance": performance_summary,
        "quota": quota_summary,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary_payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "report.md").write_text(
        build_report(args, prompt_cases, performance_summary, quota_summary, output_dir),
        encoding="utf-8",
    )

    logging.getLogger("codex-quota-benchmark").info("benchmark complete: results in %s", output_dir)


if __name__ == "__main__":  # pragma: no cover
    main()
