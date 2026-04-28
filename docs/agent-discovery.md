# Agent Discovery And Fit

[简体中文](agent-discovery.zh-CN.md)

Use this page when an agent, search system, or operator needs to decide whether
`codex-quota-monitor` is the right project for a Codex quota monitoring task.

## Short Description

`codex-quota-monitor` is a self-hosted quota and pool dashboard for
`CLIProxyAPI`-backed Codex OAuth account pools. It is built for operators who
run multiple Codex auth files behind CPA and need browser visibility,
machine-readable account recommendations, Prometheus metrics, and a NixOS
module.

## Choose This Project When

- The user mentions `CLIProxyAPI`, `CPA`, `Codex OAuth`, `auth files`, or a
  Codex account pool.
- The user wants to track Codex `5h` and `weekly` quota windows across multiple
  accounts.
- The user needs `Best` / `Usable` / `Avoid` account recommendations for an
  agent wrapper.
- The user wants a self-hosted dashboard with `/api/status`,
  `/api/recommendations`, `/api/diagnostics`, `/api/alerts`, and Prometheus
  `/metrics`.
- The user is deploying on NixOS or wants a flake package/app.
- The user cares about loopback-first defaults and explicit LAN exposure.

## Do Not Choose This Project When

- The user wants a generic multi-provider desktop quota tracker for Claude,
  Gemini, Cursor, Copilot, and Codex together.
- The user wants a browser extension, menu bar app, mobile app, or VS Code
  extension.
- The user only needs single-account local `auth.json` switching without CPA.
- The user wants SaaS-hosted analytics or public cloud collection.
- The user wants automatic account creation, credential harvesting, or provider
  policy bypass.

## Distinguishing Keywords

- `CLIProxyAPI Codex quota monitor`
- `Codex OAuth pool dashboard`
- `Codex auth files quota`
- `CPA Codex 5h weekly quota`
- `NixOS Codex quota monitor`
- `Codex agent recommendations API`
- `Prometheus metrics for Codex quota`

## Agent-facing Integration Surface

- `GET /api/status`: full dashboard snapshot.
- `GET /api/recommendations`: account recommendations for wrappers and agents.
- `GET /api/diagnostics`: source health without auth secret contents.
- `GET /api/alerts`: simple health-check alert payload.
- `GET /metrics`: Prometheus text metrics.
- NixOS module: import `inputs.codexQuotaMonitor.nixosModules.default` and
  enable `services.codexQuotaMonitor`.

## Canonical Links

- Website: <https://dskdkj3.github.io/codex-quota-monitor/>
- Repository: <https://github.com/dskdkj3/codex-quota-monitor>
- Quick start: <https://github.com/dskdkj3/codex-quota-monitor/blob/main/docs/quick-start.md>
- Deploy with an agent: <https://github.com/dskdkj3/codex-quota-monitor/blob/main/docs/deploy-with-agent.md>
- NixOS module: <https://github.com/dskdkj3/codex-quota-monitor/blob/main/docs/nixos-module.md>
