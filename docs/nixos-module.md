# NixOS Module

[简体中文](nixos-module.zh-CN.md)

The flake exports `nixosModules.default` and `nixosModules.codex-quota-monitor`.

## Minimal Example

```nix
{
  inputs.codexQuotaMonitor.url = "github:<owner>/codex-quota-monitor";

  outputs = inputs@{ self, nixpkgs, codexQuotaMonitor, ... }: {
    nixosConfigurations.my-host = nixpkgs.lib.nixosSystem {
      system = "x86_64-linux";
      modules = [
        codexQuotaMonitor.nixosModules.default
        ({ ... }: {
          services.codexQuotaMonitor = {
            enable = true;
            managementBaseUrl = "http://127.0.0.1:8318";
            gatewayHealthUrl = "http://127.0.0.1:8317/healthz";
            authDir = "/path/to/auth-files";
          };
        })
      ];
    };
  };
}
```

## Key Options

- `services.codexQuotaMonitor.enable`
- `services.codexQuotaMonitor.package`
- `services.codexQuotaMonitor.user`
- `services.codexQuotaMonitor.group`
- `services.codexQuotaMonitor.listenAddress`
- `services.codexQuotaMonitor.port`
- `services.codexQuotaMonitor.managementBaseUrl`
- `services.codexQuotaMonitor.gatewayHealthUrl`
- `services.codexQuotaMonitor.authDir`
- `services.codexQuotaMonitor.refreshSeconds`
- `services.codexQuotaMonitor.timeoutSeconds`
- `services.codexQuotaMonitor.weeklyToFiveHourMultiplier`
- `services.codexQuotaMonitor.stateDb`
- `services.codexQuotaMonitor.historyWriteSeconds`
- `services.codexQuotaMonitor.historyRetentionDays`
- `services.codexQuotaMonitor.benchmarkSummary`
- `services.codexQuotaMonitor.alertFiveHourMinPlus`
- `services.codexQuotaMonitor.alertWeeklyMinPlus`
- `services.codexQuotaMonitor.alertBestAccountsMin`
- `services.codexQuotaMonitor.openFirewall`
- `services.codexQuotaMonitor.logLevel`

## Defaults

- Bind address: `127.0.0.1`
- Port: `4515`
- Firewall: closed
- Service account: `codex-quota-monitor`
- Weekly-to-5h multiplier: `6.0`; set `weeklyToFiveHourMultiplier = null` to disable the cap. Weekly exhaustion still removes that account from total 5h capacity.
- SQLite history DB: `/var/lib/codex-quota-monitor/history.sqlite3`; set `stateDb = null` to disable Trends and Audit persistence.
- History write interval: `60` seconds
- History retention: `30` days
- Benchmark summary: disabled until `benchmarkSummary` points to a `codex-quota-benchmark` `summary.json`
- Threshold alerts: disabled until an `alert*` option is set; they are exposed through `/api/alerts`

If you want LAN access from a phone or small-screen browser, set `listenAddress = "0.0.0.0"` and `openFirewall = true`.
