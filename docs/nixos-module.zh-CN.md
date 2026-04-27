# NixOS 模块说明

[English](nixos-module.md)

这个 flake 导出了 `nixosModules.default` 和 `nixosModules.codex-quota-monitor`。

## 最小示例

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

## 关键选项

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

## 默认值

- 监听地址：`127.0.0.1`
- 端口：`4515`
- 防火墙：默认不放行
- service 账号：`codex-quota-monitor`
- weekly-to-5h multiplier：默认 `4.0`；设 `weeklyToFiveHourMultiplier = null` 可以关闭 cap。账号 weekly 已耗尽时仍会从总 `5h` 容量里移除

如果你要让手机或 e-ink 通过局域网访问，把 `listenAddress` 设成 `0.0.0.0`，并把 `openFirewall` 设成 `true`。
