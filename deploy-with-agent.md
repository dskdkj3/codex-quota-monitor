# Deploy With An Agent

[简体中文](deploy-with-agent.zh-CN.md)

Use this doc when you want Codex, Claude, or another coding agent to wire `codex-quota-monitor` into an existing NixOS repo.

## Facts The Agent Needs

- Which host should run the monitor
- The flake input to add, for example `github:<owner>/codex-quota-monitor`
- The `CLIProxyAPI` management gateway URL
- The gateway health URL
- The optional auth directory for direct quota sampling
- Whether SQLite history should use the default state DB, be disabled, or use a custom path
- Optional benchmark `summary.json` path and machine-readable alert thresholds
- Whether the dashboard should stay loopback-only or be reachable on the LAN
- Whether the firewall should be opened

## Minimal Prompt Template

```text
Add codex-quota-monitor to this NixOS repo as a flake input and deployable module.

Requirements:
- Add flake input: github:<owner>/codex-quota-monitor
- Import inputs.codexQuotaMonitor.nixosModules.default
- Enable services.codexQuotaMonitor on host <host-name>
- managementBaseUrl = "http://127.0.0.1:8318"
- gatewayHealthUrl = "http://127.0.0.1:8317/healthz"
- authDir = "/path/to/auth-files"
- listenAddress = "127.0.0.1"
- port = 4515
- openFirewall = false
- keep the default SQLite history DB unless I explicitly say otherwise
- do not configure threshold alerts or benchmarkSummary unless I provide exact values

Validation:
- run Nix eval/build checks
- do not switch the live system unless I explicitly ask
- show the final diff and the exact verification commands
```

## LAN Prompt Variant

Use this variant when the page must be reachable from a phone or small-screen browser on the local network:

```text
Same as above, but bind the dashboard to 0.0.0.0 and set openFirewall = true.
Keep the rest of the host exposure unchanged.
```

## Acceptance Checks

Ask the agent to run or report these:

```bash
systemctl status codex-quota-monitor.service --no-pager
curl -fsS http://127.0.0.1:4515/healthz
curl -fsS http://127.0.0.1:4515/api/status | jq '.summary'
curl -fsS http://127.0.0.1:4515/api/alerts | jq '.'
```

If LAN access is enabled, open `http://<host-lan-ip>:4515/` from a phone or small-screen browser and confirm the page renders without full-page reload flicker.
