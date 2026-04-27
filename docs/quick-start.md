# Quick Start

[简体中文](quick-start.zh-CN.md)

## Requirements

- A reachable `CLIProxyAPI` management gateway
- A reachable gateway health endpoint
- Optional Codex auth files if you want direct quota sampling

Typical local values:

- `managementBaseUrl = http://127.0.0.1:8318`
- `gatewayHealthUrl = http://127.0.0.1:8317/healthz`
- `port = 4515`

## Nix

Run directly from the flake:

```bash
nix run .#codex-quota-monitor -- \
  --management-base-url http://127.0.0.1:8318 \
  --gateway-health-url http://127.0.0.1:8317/healthz \
  --auth-dir /path/to/auth-files
```

Expose it to the local network only when you mean to:

```bash
nix run .#codex-quota-monitor -- \
  --host 0.0.0.0 \
  --port 4515 \
  --management-base-url http://127.0.0.1:8318 \
  --gateway-health-url http://127.0.0.1:8317/healthz \
  --auth-dir /path/to/auth-files
```

By default, total `5h` capacity is capped by `weekly remaining * 6.0`. Use `--weekly-to-five-hour-multiplier <number>` to override it, or `--weekly-to-five-hour-multiplier off` / `none` to disable the cap.

Direct `nix run` keeps SQLite history disabled by default. Add a writable state DB when you want Trends, ETA, and Audit history; the Trends tab shows the latest 6h of stored samples:

```bash
nix run .#codex-quota-monitor -- \
  --state-db ./result/codex-quota-monitor.sqlite3 \
  --management-base-url http://127.0.0.1:8318 \
  --gateway-health-url http://127.0.0.1:8317/healthz \
  --auth-dir /path/to/auth-files
```

## Python

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
codex-quota-monitor \
  --management-base-url http://127.0.0.1:8318 \
  --gateway-health-url http://127.0.0.1:8317/healthz \
  --auth-dir /path/to/auth-files
```

## Smoke Test

```bash
curl -fsS http://127.0.0.1:4515/healthz
curl -fsS http://127.0.0.1:4515/api/status | jq '.summary'
curl -fsS http://127.0.0.1:4515/api/recommendations | jq '.summary'
curl -fsS http://127.0.0.1:4515/api/diagnostics | jq '.summary'
curl -fsS http://127.0.0.1:4515/api/alerts | jq '.'
curl -fsS http://127.0.0.1:4515/metrics | sed -n '1,20p'
```

Open `http://127.0.0.1:4515/` in a browser after the process starts.

## Benchmarking

If you also want to benchmark `fast` versus baseline, or Team versus Plus quota capacity, see [Benchmark guide](benchmark.md).
