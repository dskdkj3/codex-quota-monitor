{ self }:
{ config, lib, pkgs, ... }:

let
  inherit (lib)
    escapeShellArg
    getExe
    mkEnableOption
    mkIf
    mkOption
    optionalAttrs
    optionalString
    types
    ;
  cfg = config.services.codexQuotaMonitor;
  defaultAccount = "codex-quota-monitor";
  defaultWeeklyToFiveHourMultiplier = 4;
  weeklyToFiveHourMultiplierArg =
    if cfg.weeklyToFiveHourMultiplier == null then "off" else toString cfg.weeklyToFiveHourMultiplier;
in
{
  options.services.codexQuotaMonitor = {
    enable = mkEnableOption "Codex Quota Monitor";

    package = mkOption {
      type = types.package;
      default = self.packages.${pkgs.stdenv.hostPlatform.system}.default;
      description = "Package providing the codex-quota-monitor executable.";
    };

    user = mkOption {
      type = types.str;
      default = defaultAccount;
      description = "User account used by the systemd service.";
    };

    group = mkOption {
      type = types.str;
      default = defaultAccount;
      description = "Group used by the systemd service.";
    };

    listenAddress = mkOption {
      type = types.str;
      default = "127.0.0.1";
      description = "Address the HTTP server listens on.";
    };

    port = mkOption {
      type = types.port;
      default = 4515;
      description = "TCP port exposed by the dashboard.";
    };

    managementBaseUrl = mkOption {
      type = types.str;
      default = "http://127.0.0.1:8318";
      description = "Base URL for the CLIProxyAPI management gateway.";
    };

    gatewayHealthUrl = mkOption {
      type = types.str;
      default = "http://127.0.0.1:8317/healthz";
      description = "Health endpoint for the CLIProxyAPI gateway.";
    };

    authDir = mkOption {
      type = types.nullOr types.str;
      default = null;
      description = "Optional directory of Codex OAuth JSON files used for direct quota sampling.";
    };

    refreshSeconds = mkOption {
      type = types.ints.between 5 3600;
      default = 15;
      description = "Minimum refresh interval for management and quota sampling.";
    };

    timeoutSeconds = mkOption {
      type = types.number;
      default = 5;
      description = "HTTP timeout used for upstream health and management requests.";
    };

    weeklyToFiveHourMultiplier = mkOption {
      type = types.nullOr types.number;
      default = defaultWeeklyToFiveHourMultiplier;
      description = "Cap for total 5h capacity: effective 5h percent is min(raw 5h, weekly percent times this multiplier). Set to null to disable the cap.";
    };

    openFirewall = mkOption {
      type = types.bool;
      default = false;
      description = "Whether to open the configured TCP port in the firewall.";
    };

    logLevel = mkOption {
      type = types.enum [
        "DEBUG"
        "INFO"
        "WARNING"
        "ERROR"
      ];
      default = "INFO";
      description = "Log level passed to the monitor process.";
    };
  };

  config = mkIf cfg.enable {
    users.groups = optionalAttrs (cfg.group == defaultAccount) {
      "${defaultAccount}" = { };
    };

    users.users = optionalAttrs (cfg.user == defaultAccount) {
      "${defaultAccount}" = {
        isSystemUser = true;
        group = cfg.group;
        home = "/var/lib/codex-quota-monitor";
        createHome = true;
      };
    };

    networking.firewall.allowedTCPPorts = lib.optional cfg.openFirewall cfg.port;

    systemd.services.codex-quota-monitor = {
      description = "Codex Quota Monitor";
      wantedBy = [ "multi-user.target" ];
      wants = [ "network-online.target" ];
      after = [ "network-online.target" ];

      serviceConfig = {
        Type = "simple";
        User = cfg.user;
        Group = cfg.group;
        ExecStart =
          "${getExe cfg.package} "
          + "--host ${escapeShellArg cfg.listenAddress} "
          + "--port ${toString cfg.port} "
          + "--refresh-seconds ${toString cfg.refreshSeconds} "
          + "--timeout-seconds ${toString cfg.timeoutSeconds} "
          + "--management-base-url ${escapeShellArg cfg.managementBaseUrl} "
          + "--gateway-health-url ${escapeShellArg cfg.gatewayHealthUrl} "
          + "--log-level ${escapeShellArg cfg.logLevel}"
          + optionalString (cfg.authDir != null) " --auth-dir ${escapeShellArg cfg.authDir}"
          + " --weekly-to-five-hour-multiplier ${escapeShellArg weeklyToFiveHourMultiplierArg}";
        Restart = "on-failure";
        RestartSec = "5s";
        LockPersonality = true;
        MemoryDenyWriteExecute = true;
        NoNewPrivileges = true;
        PrivateTmp = true;
        ProtectControlGroups = true;
        ProtectHome = "read-only";
        ProtectKernelModules = true;
        ProtectKernelTunables = true;
        ProtectSystem = "strict";
        RestrictAddressFamilies = [
          "AF_INET"
          "AF_INET6"
        ];
        RestrictNamespaces = true;
        SystemCallArchitectures = "native";
      };
    };
  };
}
