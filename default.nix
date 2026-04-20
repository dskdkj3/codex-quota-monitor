{ lib, python3, stdenvNoCC }:

stdenvNoCC.mkDerivation {
  pname = "codex-quota-monitor";
  version = "0.1.0";

  src = ./.;
  dontUnpack = true;
  nativeBuildInputs = [ python3 ];
  doCheck = true;

  checkPhase = ''
    runHook preCheck
    ${python3}/bin/python3 -m py_compile ${./codex-quota-monitor.py}
    export CODEX_QUOTA_MONITOR_MODULE=${./codex-quota-monitor.py}
    ${python3}/bin/python3 ${./test_codex_quota_monitor.py}
    runHook postCheck
  '';

  installPhase = ''
    runHook preInstall
    install -Dm755 ${./codex-quota-monitor.py} $out/bin/codex-quota-monitor
    patchShebangs $out/bin
    runHook postInstall
  '';

  meta = {
    description = "e-ink-friendly local HTTP dashboard for CLIProxyAPI pools";
    mainProgram = "codex-quota-monitor";
    platforms = lib.platforms.linux;
  };
}
