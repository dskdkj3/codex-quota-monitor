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
```

Open `http://127.0.0.1:4515/` in a browser after the process starts.

## Benchmarking

If you also want to benchmark `fast` versus baseline, or Team versus Plus quota capacity, see [Benchmark guide](benchmark.md).
