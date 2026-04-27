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
- `services.codexQuotaMonitor.openFirewall`
- `services.codexQuotaMonitor.logLevel`

## Defaults

- Bind address: `127.0.0.1`
- Port: `4515`
- Firewall: closed
- Service account: `codex-quota-monitor`
- Weekly-to-5h multiplier: unset; weekly exhaustion still removes that account from total 5h capacity

If you want LAN access from a phone or e-ink, set `listenAddress = "0.0.0.0"` and `openFirewall = true`.
