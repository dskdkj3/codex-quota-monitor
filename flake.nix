{
  description = "Codex Quota Monitor";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs =
    { self, nixpkgs }:
    let
      lib = nixpkgs.lib;
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = lib.genAttrs systems;
      mkPkgs = system: import nixpkgs { inherit system; };
      mkPackage = system: (mkPkgs system).callPackage ./default.nix { };
      mkApp = package: program: {
        type = "app";
        program = "${package}/bin/${program}";
      };
    in
    {
      packages = forAllSystems (
        system:
        let
          package = mkPackage system;
        in
        {
          default = package;
          codex-quota-monitor = package;
        }
      );

      apps = forAllSystems (
        system:
        let
          package = mkPackage system;
        in
        {
          default = mkApp package "codex-quota-monitor";
          codex-quota-monitor = mkApp package "codex-quota-monitor";
          codex-quota-benchmark = mkApp package "codex-quota-benchmark";
        }
      );

      devShells = forAllSystems (
        system:
        let
          pkgs = mkPkgs system;
        in
        {
          default = pkgs.mkShell {
            packages = [
              pkgs.git
              pkgs.python312
            ];
          };
        }
      );

      formatter = forAllSystems (system: (mkPkgs system).nixfmt);

      nixosModules = {
        default = import ./nixos-module.nix { inherit self; };
        codex-quota-monitor = import ./nixos-module.nix { inherit self; };
      };
    };
}
