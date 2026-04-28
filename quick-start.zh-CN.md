# 快速开始

[English](quick-start.md)

## 前置条件

- 一个可访问的 `CLIProxyAPI` management gateway
- 一个可访问的 gateway health endpoint
- 可选的 Codex auth 文件目录；如果你想做 direct quota sampling，就需要它

典型本机值：

- `managementBaseUrl = http://127.0.0.1:8318`
- `gatewayHealthUrl = http://127.0.0.1:8317/healthz`
- `port = 4515`

## 用 Nix 运行

```bash
nix run .#codex-quota-monitor -- \
  --management-base-url http://127.0.0.1:8318 \
  --gateway-health-url http://127.0.0.1:8317/healthz \
  --auth-dir /path/to/auth-files
```

只有在你明确需要局域网访问时才开放监听：

```bash
nix run .#codex-quota-monitor -- \
  --host 0.0.0.0 \
  --port 4515 \
  --management-base-url http://127.0.0.1:8318 \
  --gateway-health-url http://127.0.0.1:8317/healthz \
  --auth-dir /path/to/auth-files
```

默认会用 `weekly 剩余 * 6.0` 约束总 `5h` 容量。用 `--weekly-to-five-hour-multiplier <数字>` 可以覆盖倍率，用 `--weekly-to-five-hour-multiplier off` / `none` 可以关闭这个 cap。

直接 `nix run` 默认不写 SQLite 历史。需要 Trends、ETA 和 Audit 时，给它一个可写 state DB；Trends 标签页会展示最近 `6h` 的历史样本：

```bash
nix run .#codex-quota-monitor -- \
  --state-db ./result/codex-quota-monitor.sqlite3 \
  --management-base-url http://127.0.0.1:8318 \
  --gateway-health-url http://127.0.0.1:8317/healthz \
  --auth-dir /path/to/auth-files
```

## 用 Python 运行

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

进程起来之后，在浏览器打开 `http://127.0.0.1:4515/`。

## Benchmark

如果你还想测 `fast` 相对 baseline 的表现，或者想把 Team 的 quota 容量折算成 Plus 单位，见 [Benchmark 指南](benchmark.zh-CN.md)。
