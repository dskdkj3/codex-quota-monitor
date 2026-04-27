# Codex Quota Monitor

[English](README.md)

一个面向 `CLIProxyAPI` 承载的 Codex OAuth 账号池的浏览器监控页。它优先回答三个问题：当前 `5h` / `weekly` 还剩多少以 Plus 单位表示的总容量、CPA usage statistics 和账号负载现在是什么样、有没有必须介入的问题。Team 容量会按和 Plus `1:1` 的口径计入这些总量；Prolite 按 `10:1` 计入。布局针对 PC 浏览器、手机浏览器和 e-ink 这类电子墨水屏都做了兼容。

![Codex Quota Monitor 预览图](docs/assets/dashboard-preview.svg)

## 你能直接看到什么

- `Pool`：`5h` / `weekly` 已知总容量（以 Plus 为单位展示），其中 Team 按 `1:1` 计入、Prolite 按 `10:1` 计入，其它非 Plus 账号仍可见但不影响总量；账号 weekly 已耗尽时，对总 `5h` 容量贡献为 `0`
- `Resets`：按从近到远排序展示 `5h` / `weekly` 的 reset 时间，并用紧凑的北京时间显示目标时刻；当 weekly 已耗尽时，`5h` 行会显示真正恢复可用性的 weekly reset
- `Trends`：展示最近 `6h` 的 SQLite 历史，用来计算 burn rate、预计耗尽时间，并可导入 benchmark 摘要
- `Usage`：来自 `CLIProxyAPI` usage statistics 的请求/token 总量、小时/日期 bucket、model breakdown 和账号分摊
- `Audit`：从历史快照 diff 出最近账号池、套餐、状态、quota window 和 benchmark 摘要变化
- `Diagnostics`：展示 gateway、CPA management API、direct quota sampling、SQLite history 和 benchmark import 的数据源健康状态
- `Alerts`：只保留硬 auth 故障、没有明确 reset 的硬 quota exhausted、以及 monitor / 数据源降级；有 reset 的 usage-limit cooldown 只留在 `Pool` / `Resets` 展示，不把账号卡片标红
- `Status`：gateway 连通性，以及当前 CPA 快照/刷新状态
- `Fast`：当前 CPA fast override 状态（`On`、`Off`、`Inherit` 或 `Unknown`），显示在 Pool 指标里
- `适配设备`：桌面浏览器、手机浏览器、e-ink 等小屏或慢刷新的浏览器

机器可读接口：

- `/api/status`：完整 dashboard snapshot
- `/api/recommendations`：给 agent wrapper 使用的 `Best` / `Usable` / `Avoid` 账号推荐
- `/api/diagnostics`：不包含 auth secret 内容的数据源诊断
- `/api/alerts`：适合简单 health check 的告警 payload
- `/metrics`：Prometheus text metrics，包含容量、推荐数量、告警、source 和 gateway health

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
默认会用 `weekly 剩余 * 6.0` 约束总 `5h` 容量，避免 weekly 剩余额很低的账号把 `5h` 池估得过高。传 `--weekly-to-five-hour-multiplier <数字>` 可以覆盖这个倍率；传 `--weekly-to-five-hour-multiplier off` / `none` 可以关闭这个 cap。Benchmark 报告会给一个保守推荐值。
直接 `nix run` 默认不写 SQLite 历史；需要 Trends / ETA / Audit 时传 `--state-db /path/to/history.sqlite3`。NixOS module 默认会把历史写到 `/var/lib/codex-quota-monitor/history.sqlite3`。Trends 标签页展示最近 `6h` 的历史样本。

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
  --plus-selector plus-auth-file-name.json \
  --prolite-selector prolite-auth-file-name.json
```

完整流程、selector 规则、输出文件和 weekly-to-5h multiplier 报告解释见 [Benchmark 指南](docs/benchmark.zh-CN.md)。

## 这个项目依赖什么上游

- 一个可访问的 `CLIProxyAPI` management gateway，通常是 `http://127.0.0.1:8318`
- 一个可访问的 gateway health endpoint，通常是 `http://127.0.0.1:8317/healthz`
- 可选的 Codex auth 文件目录；如果提供，监控页可以做 `5h` / `weekly` 的 direct quota sampling，而不只是显示 pool 状态
- 可选 SQLite state database；启用后会提供 Trends、ETA 和 Audit 历史
- 可选 `codex-quota-benchmark` 的 `summary.json`；配置后会在 Trends 里显示 benchmark 校准信息

## 给 Agent 的入口

如果你想让 Codex、Claude 或别的 Agent 帮你把它接进现有 NixOS 主机，直接从 [让 Agent 自动部署](docs/deploy-with-agent.zh-CN.md) 开始。那份文档是按“用户原样丢给 Agent 就能执行”的方式写的。

## 验证

改 `.nix` 文件后，用 flake 声明的 formatter 格式化本次触碰的文件：

```bash
nix fmt -- <touched .nix files>
```

```bash
python -m unittest discover -s tests -v
nix build .#codex-quota-monitor
nix run .#codex-quota-monitor -- --help
nix run .#codex-quota-benchmark -- --help
```
