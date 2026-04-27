# Benchmark Guide

[简体中文](benchmark.zh-CN.md)

Use `codex-quota-benchmark` when you want two measurements from the same CLIProxyAPI-backed Codex OAuth pool:

- `fast` versus baseline latency and token behavior
- Team-account 5h and weekly capacity expressed in Plus-account units
- the observed 5h-to-weekly drop ratio that can cap dashboard 5h totals

The benchmark isolates traffic by launching temporary loopback-only `cli-proxy-api` processes, each with exactly one copied auth file. It does not need to mutate the live gateway routing.

## Requirements

- A reachable `CLIProxyAPI` management gateway, usually `http://127.0.0.1:8318`
- Read access to the underlying Codex auth files referenced by the management API
- A local `cli-proxy-api` binary, or a running `cli-proxy-api.service` that the tool can auto-discover

## How Selectors Work

You identify accounts with selectors instead of raw paths:

- `--team-selector <value>`
- `--plus-selector <value>` (repeatable)
- `--prolite-selector <value>` (optional, repeatable; useful for weekly-to-5h cap measurement)

A selector matches against `auth_index`, file name, label, email, account, or path. The match must be unique. If the same email exists in both Team and Plus form, use the full file name or `auth_index`.

## Recommended Run

```bash
codex-quota-benchmark \
  --management-base-url http://127.0.0.1:8318 \
  --team-selector account-slot \
  --plus-selector account-slot \
  --plus-selector account-slot \
  --prolite-selector account-slot
```

By default the tool will:

- create a timestamped output directory under `./result/`
- run `10` warm-up A/B pairs and `30` measured A/B pairs for performance
- run quota batches with baseline tier until each Plus reference has dropped at least `15%` on `5h` and `5%` on `weekly`, until Team quota is exhausted, or until `40` rounds have completed

## Common Flags

- `--prompt-file <path>`: load your own prompt set instead of the built-in 30-case pack
- `--model gpt-5.4`: keep model fixed across all runs
- `--reasoning-effort <value>`: force a single reasoning setting across all runs
- `--quota-service-tier fast`: stress quota windows under the fast path instead of baseline
- `--skip-performance`: only measure Team-versus-Plus quota ratios
- `--skip-quota`: only measure fast-versus-baseline latency
- `--keep-work-dir`: keep temporary gateway configs and logs under the output directory

## Output Files

- `config.json`: resolved account metadata, selected model, and prompt count
- `requests.csv`: per-request latency, tier, prompt class, and token breakdown
- `quota_snapshots.jsonl`: per-batch before/after direct quota snapshots and window deltas
- `summary.json`: machine-readable summary
- `report.md`: human-readable conclusions and ratios

## Interpretation

- Performance A/B compares baseline requests against requests sent with `service_tier = priority`.
- Team-to-Plus ratio is computed from direct quota-window drops under matched workloads.
- `Weekly-to-5h Cap` reports `5h_drop / weekly_drop` per Team, Plus, and optional Prolite account, plus a conservative `recommended_dashboard_multiplier`; pass that value to `codex-quota-monitor --weekly-to-five-hour-multiplier` to override the default `6.0` cap.
- Pass `codex-quota-monitor --benchmark-summary /path/to/summary.json` to display the latest benchmark calibration in the dashboard Trends tab.
- If a quota window resets during a batch, that batch is marked invalid for ratio math instead of being silently averaged in.
- If the Team account reaches `0%` remaining on either `5h` or `weekly`, quota benchmarking stops immediately and the report marks the ratio section incomplete.
