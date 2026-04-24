# Codex Quota Monitor

[English](README.md)

一个面向 `CLIProxyAPI` 承载的 Codex OAuth 账号池的浏览器监控页。它优先回答三个问题：当前 `5h` / `weekly` 还剩多少以 Plus 单位表示的总容量、当前流量怎么分、有没有必须介入的问题。Team 容量会按和 Plus `1:1` 的口径计入这些总量。布局针对 PC 浏览器、手机浏览器和 e-ink 这类电子墨水屏都做了兼容。

![Codex Quota Monitor 预览图](docs/assets/dashboard-preview.svg)

## 你能直接看到什么

- `Pool`：`5h` / `weekly` 已知总容量（以 Plus 为单位展示），其中 Team 按 `1:1` 计入，其它非 Plus 账号仍可见但不影响总量
- `Traffic`：来自 `CLIProxyAPI` usage 的请求数、成功率、token 和账号分摊
- `Alerts`：只保留硬 auth 故障、明确 quota exhausted、以及 monitor / 数据源降级
- `Status`：gateway 连通性，以及当前 CPA 快照/刷新状态
- `Pool`：Plus / Non-Plus 总量、以 Plus 为单位的 `5h` / `weekly` 容量，以及当前 CPA fast override 状态（`On`、`Off`、`Inherit` 或 `Unknown`）
- `适配设备`：桌面浏览器、手机浏览器、e-ink 等小屏或慢刷新的浏览器

## 快速入口

- 给人类： [快速开始](docs/quick-start.zh-CN.md)
- Benchmark： [Benchmark 指南](docs/benchmark.zh-CN.md)
- 给 Agent： [让 Agent 自动部署](docs/deploy-with-agent.zh-CN.md)
- 给 NixOS 运维： [NixOS 模块说明](docs/nixos-module.zh-CN.md)

## 快速开始

### 用 Nix 直接运行

```bash
nix run .#codex-quota-monitor -- \
  --management-base-url http://127.0.0.1:8318 \
  --gateway-health-url http://127.0.0.1:8317/healthz \
  --auth-dir /path/to/auth-files
```

默认监听在 `127.0.0.1:4515`。如果你要让手机或 e-ink 通过局域网访问，需要显式传 `--host 0.0.0.0`，并且有意识地开放端口。

### 用 Python 运行

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
codex-quota-monitor \
  --management-base-url http://127.0.0.1:8318 \
  --gateway-health-url http://127.0.0.1:8317/healthz \
  --auth-dir /path/to/auth-files
```

然后打开 `http://127.0.0.1:4515/`。

## 跑 Benchmark

如果你想拿到 `fast` 相对 baseline 的硬数据，或者想把 Team 账号的 quota 容量换算成 Plus 单位，可以直接跑：

```bash
codex-quota-benchmark \
  --management-base-url http://127.0.0.1:8318 \
  --team-selector team-auth-file-name.json \
  --plus-selector plus-auth-file-name.json
```

完整流程、selector 规则和输出文件解释见 [Benchmark 指南](docs/benchmark.zh-CN.md)。

## 这个项目依赖什么上游

- 一个可访问的 `CLIProxyAPI` management gateway，通常是 `http://127.0.0.1:8318`
- 一个可访问的 gateway health endpoint，通常是 `http://127.0.0.1:8317/healthz`
- 可选的 Codex auth 文件目录；如果提供，监控页可以做 `5h` / `weekly` 的 direct quota sampling，而不只是显示 pool 状态

## 给 Agent 的入口

如果你想让 Codex、Claude 或别的 Agent 帮你把它接进现有 NixOS 主机，直接从 [让 Agent 自动部署](docs/deploy-with-agent.zh-CN.md) 开始。那份文档是按“用户原样丢给 Agent 就能执行”的方式写的。

## 验证

```bash
python -m unittest discover -s tests -v
nix build .#codex-quota-monitor
nix run .#codex-quota-monitor -- --help
nix run .#codex-quota-benchmark -- --help
```
