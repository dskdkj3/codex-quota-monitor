# Agent Notes

## Repo Map

- `flake.nix`: flake outputs for package, app, and NixOS module
- `default.nix`: Nix packaging for the Python application
- `nixos-module.nix`: reusable NixOS service module
- `src/codex_quota_monitor/`: runtime, HTTP handlers, snapshot logic, and static assets
- `tests/`: unit and lightweight HTTP handler tests
- `docs/`: human-facing quick-start and deployment docs

## Must Know

- `README.md` and `README.zh-CN.md` are paired. Keep meaning in sync.
- `docs/*.md` and `docs/*.zh-CN.md` are paired. Update both when behavior changes.
- Default listen address is `127.0.0.1`. LAN exposure must stay explicit.
- `services.codexQuotaMonitor.openFirewall` must remain `false` by default.
- The project is intentionally focused on `CLIProxyAPI`-backed Codex OAuth pools. Do not generalize the product surface without an explicit decision.

## Validation

- `python -m unittest discover -s tests -v`
- `nix build .#codex-quota-monitor`
- `nix run .#codex-quota-monitor -- --help`
