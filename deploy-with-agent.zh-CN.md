# 让 Agent 自动部署

[English](deploy-with-agent.md)

当你想让 Codex、Claude 或其他 coding agent 把 `codex-quota-monitor` 接进现有 NixOS 仓库时，用这份文档。

## Agent 需要知道的事实

- 哪台 host 负责运行这个 monitor
- 要添加的 flake input，例如 `github:<owner>/codex-quota-monitor`
- `CLIProxyAPI` management gateway URL
- gateway health URL
- direct quota sampling 用的 auth 目录，可选
- SQLite history 是使用默认 state DB、关闭，还是指定自定义路径
- 可选 benchmark `summary.json` 路径和机器可读阈值告警
- 监控页是只允许本机访问，还是需要局域网访问
- 是否需要自动开放防火墙

## 最小可用提示词模板

```text
把 codex-quota-monitor 接入这个 NixOS 仓库，作为 flake input 和可部署模块。

要求：
- 添加 flake input: github:<owner>/codex-quota-monitor
- 导入 inputs.codexQuotaMonitor.nixosModules.default
- 在 host <host-name> 上启用 services.codexQuotaMonitor
- managementBaseUrl = "http://127.0.0.1:8318"
- gatewayHealthUrl = "http://127.0.0.1:8317/healthz"
- authDir = "/path/to/auth-files"
- listenAddress = "127.0.0.1"
- port = 4515
- openFirewall = false
- 除非我明确说明，否则保留默认 SQLite history DB
- 除非我给出精确值，否则不要配置 threshold alerts 或 benchmarkSummary

验证：
- 跑 Nix eval/build 检查
- 除非我明确要求，否则不要直接切换线上系统
- 展示最终 diff 和精确的验证命令
```

## 局域网版本提示词

如果页面需要让手机或小屏浏览器通过局域网访问，可以改成：

```text
上面的要求保持不变，但把 dashboard 绑定到 0.0.0.0，并设置 openFirewall = true。
不要顺手扩大其他 host 暴露面。
```

## 验收检查

让 Agent 运行或回报这些命令：

```bash
systemctl status codex-quota-monitor.service --no-pager
curl -fsS http://127.0.0.1:4515/healthz
curl -fsS http://127.0.0.1:4515/api/status | jq '.summary'
curl -fsS http://127.0.0.1:4515/api/alerts | jq '.'
```

如果启用了局域网访问，再用手机或小屏浏览器打开 `http://<host-lan-ip>:4515/`，确认页面能正常渲染，而且不会出现整页闪白式 reload。
