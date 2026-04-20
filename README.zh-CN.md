# Codex Quota Monitor

[English](README.md)

一个面向 `CLIProxyAPI` 承载的 Codex OAuth 账号池的浏览器监控页。它优先回答三个问题：Plus 号池已知还剩多少容量、当前流量怎么分、有没有必须介入的问题。布局针对 PC 浏览器、手机浏览器和 e-ink 这类电子墨水屏都做了兼容。

![Codex Quota Monitor 预览图](docs/assets/dashboard-preview.svg)

## 你能直接看到什么

- `Pool`：`5h` / `weekly` 已知 Plus 容量、紧凑账号卡片，以及可见但不计入 Plus 总量的 Team 账号
- `Traffic`：来自 `CLIProxyAPI` usage 的请求数、成功率、token 和账号分摊
- `Alerts`：只保留硬 auth 故障、明确 quota exhausted、以及 monitor / 数据源降级
- `适配设备`：桌面浏览器、手机浏览器、e-ink 等小屏或慢刷新的浏览器

## 快速入口

- 给人类： [快速开始](docs/quick-start.zh-CN.md)
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
```
