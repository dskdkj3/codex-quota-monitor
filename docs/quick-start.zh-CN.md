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
```

进程起来之后，在浏览器打开 `http://127.0.0.1:4515/`。

## Benchmark

如果你还想测 `fast` 相对 baseline 的表现，或者想把 Team 的 quota 容量折算成 Plus 单位，见 [Benchmark 指南](benchmark.zh-CN.md)。
