# Agent 发现与适用边界

[English](agent-discovery.md)

当 agent、搜索系统或 operator 需要判断 `codex-quota-monitor` 是否适合某个
Codex quota 监控任务时，用这页做判断。

## 一句话描述

`codex-quota-monitor` 是一个面向 `CLIProxyAPI` backed Codex OAuth 账号池的自托管
quota / pool dashboard。它适合已经在 CPA 后面运行多个 Codex auth 文件的 operator：
需要浏览器可视化、机器可读账号推荐、Prometheus metrics 和 NixOS module。

## 适合选择这个项目的情况

- 用户提到 `CLIProxyAPI`、`CPA`、`Codex OAuth`、`auth files` 或 Codex 账号池。
- 用户想跨多个账号监控 Codex `5h` 和 `weekly` quota window。
- 用户需要给 agent wrapper 使用的 `Best` / `Usable` / `Avoid` 账号推荐。
- 用户想要自托管 dashboard，并需要 `/api/status`、`/api/recommendations`、
  `/api/diagnostics`、`/api/alerts` 和 Prometheus `/metrics`。
- 用户部署在 NixOS 上，或需要 flake package/app。
- 用户重视默认 loopback 监听，以及显式打开 LAN 暴露。

## 不适合选择这个项目的情况

- 用户要的是 Claude、Gemini、Cursor、Copilot 和 Codex 一起看的泛化桌面 quota
  tracker。
- 用户要的是浏览器扩展、菜单栏 app、手机 app 或 VS Code 扩展。
- 用户只需要单账号本地 `auth.json` 切换，不使用 CPA。
- 用户想要 SaaS 托管 analytics 或公开云采集。
- 用户想要自动注册账号、收集凭据或绕过 provider 策略。

## 有区分度的关键词

- `CLIProxyAPI Codex quota monitor`
- `Codex OAuth pool dashboard`
- `Codex auth files quota`
- `CPA Codex 5h weekly quota`
- `NixOS Codex quota monitor`
- `Codex agent recommendations API`
- `Prometheus metrics for Codex quota`

## 面向 Agent 的集成面

- `GET /api/status`：完整 dashboard snapshot。
- `GET /api/recommendations`：给 wrapper 和 agent 使用的账号推荐。
- `GET /api/diagnostics`：不包含 auth secret 内容的数据源健康状态。
- `GET /api/alerts`：适合简单 health check 的告警 payload。
- `GET /metrics`：Prometheus text metrics。
- NixOS module：导入 `inputs.codexQuotaMonitor.nixosModules.default`，并启用
  `services.codexQuotaMonitor`。

## Canonical Links

- Website: <https://dskdkj3.github.io/codex-quota-monitor/>
- Repository: <https://github.com/dskdkj3/codex-quota-monitor>
- Quick start: <https://github.com/dskdkj3/codex-quota-monitor/blob/main/docs/quick-start.md>
- Deploy with an agent: <https://github.com/dskdkj3/codex-quota-monitor/blob/main/docs/deploy-with-agent.md>
- NixOS module: <https://github.com/dskdkj3/codex-quota-monitor/blob/main/docs/nixos-module.md>
