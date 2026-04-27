# Codex Quota Monitor

[简体中文](README.zh-CN.md)

Browser-friendly quota and pool dashboard for `CLIProxyAPI`-backed Codex OAuth pools. It gives a fast read of remaining 5h/weekly capacity in Plus units, CPA usage statistics, current pool load, and only the alerts that actually require intervention. Team capacity counts 1:1 with Plus in those totals; Prolite counts 10:1. The layout is tuned for desktop browsers, phone screens, and small e-ink browsers.

![Codex Quota Monitor preview](docs/assets/dashboard-preview.svg)

## At A Glance

- `Pool`: 5h and weekly known capacity in Plus units, with Team counted 1:1, Prolite counted 10:1, and other non-Plus plans remaining visible without affecting those totals; an account with exhausted weekly quota contributes `0` to total 5h capacity
- `Resets`: 5h and weekly reset schedules sorted from nearest to latest, with compact Beijing-time targets; when weekly quota is exhausted, the 5h row displays the weekly reset that actually restores availability
- `Trends`: latest 6h of SQLite-backed burn rate, ETA, and optional benchmark summary import
- `Usage`: request/token totals, hourly/day buckets, model breakdown, and account split from `CLIProxyAPI` usage statistics
- `Audit`: recent account-pool, plan, status, quota-window, and benchmark-summary changes derived from stored snapshots
- `Diagnostics`: data-source health for the gateway, CPA management APIs, direct quota sampling, SQLite history, and benchmark import
- `Alerts`: only hard auth failures, hard quota exhaustion without a scheduled reset, and monitor/source degradation; reset-scheduled usage-limit cooldowns stay visible in `Pool` / `Resets` without turning the account card red
- `Status`: gateway reachability and refresh health for the current CPA snapshot
- `Fast`: current CPA fast override state (`On`, `Off`, `Inherit`, or `Unknown`) in the Pool metrics
- `Target devices`: desktop, mobile, and small-screen browsers

Machine-readable endpoints:

- `/api/status`: full dashboard snapshot
- `/api/recommendations`: `Best` / `Usable` / `Avoid` account recommendations for agent wrappers
- `/api/diagnostics`: data-source diagnosis without auth secret contents
- `/api/alerts`: alert payload for simple health checks
- `/metrics`: Prometheus text metrics for capacity, recommendation counts, alerts, source, and gateway health

## Quick Links

- Humans: [Quick start](docs/quick-start.md)
- Benchmarking: [Benchmark guide](docs/benchmark.md)
- Agents: [Deploy with an agent](docs/deploy-with-agent.md)
- NixOS operators: [NixOS module](docs/nixos-module.md)

## Quick Start

### Run With Nix

```bash
nix run .#codex-quota-monitor -- \
  --management-base-url http://127.0.0.1:8318 \
  --gateway-health-url http://127.0.0.1:8317/healthz \
  --auth-dir /path/to/auth-files
```

The default bind is `127.0.0.1:4515`. If you want phone or e-ink access on the local network, pass `--host 0.0.0.0` and expose the port intentionally.
By default, total `5h` capacity is capped by `weekly remaining * 6.0`, so an account with low weekly quota cannot overstate the `5h` pool. Pass `--weekly-to-five-hour-multiplier <number>` to override that relationship, or `--weekly-to-five-hour-multiplier off` / `none` to disable the cap. The benchmark report includes a conservative recommended value.
Direct `nix run` keeps SQLite history off unless you pass `--state-db /path/to/history.sqlite3`. The NixOS module enables history by default under `/var/lib/codex-quota-monitor/history.sqlite3`. The Trends tab displays the latest 6h of stored samples.

### Run With Python

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
codex-quota-monitor \
  --management-base-url http://127.0.0.1:8318 \
  --gateway-health-url http://127.0.0.1:8317/healthz \
  --auth-dir /path/to/auth-files
```

Then open `http://127.0.0.1:4515/`.

## Benchmark The Pool

When you want hard numbers for `fast` versus baseline, or Team versus Plus quota capacity, run:

```bash
codex-quota-benchmark \
  --management-base-url http://127.0.0.1:8318 \
  --team-selector team-auth-file-name.json \
  --plus-selector plus-auth-file-name.json \
  --prolite-selector prolite-auth-file-name.json
```

The full workflow, selector rules, output files, and weekly-to-5h multiplier report are documented in [Benchmark guide](docs/benchmark.md).

## What The Monitor Needs

- A reachable `CLIProxyAPI` management gateway, usually something like `http://127.0.0.1:8318`
- A reachable gateway health endpoint, usually something like `http://127.0.0.1:8317/healthz`
- Optional direct Codex auth files if you want 5h and weekly quota sampling instead of pool-only visibility
- Optional SQLite state database if you want Trends, ETA, and Audit history
- Optional `codex-quota-benchmark` `summary.json` if you want the Trends tab to display benchmark calibration

## For Agents

If you want Codex, Claude, or another agent to wire this into an existing NixOS host, start with [Deploy with an agent](docs/deploy-with-agent.md). That doc is written so a user can hand it to an agent as-is, with minimal extra interpretation.

## Validation

For Nix edits, use the flake formatter on the files you touched:

```bash
nix fmt -- <touched .nix files>
```

```bash
python -m unittest discover -s tests -v
nix build .#codex-quota-monitor
nix run .#codex-quota-monitor -- --help
nix run .#codex-quota-benchmark -- --help
```
