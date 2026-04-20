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
    ${python3}/bin/python3 - <<'PY'
    import pathlib

    paths = [pathlib.Path("${./codex-quota-monitor.py}")]
    paths.extend(sorted(pathlib.Path("${./codex_quota_monitor}").rglob("*.py")))

    for path in paths:
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
    PY
    export PYTHONPATH=${./.}
    ${python3}/bin/python3 ${./test_codex_quota_monitor.py}
    runHook postCheck
  '';

  installPhase = ''
    runHook preInstall
    install -Dm755 ${./codex-quota-monitor.py} $out/bin/codex-quota-monitor
    mkdir -p $out/lib/codex-quota-monitor/codex_quota_monitor
    cp -r ${./codex_quota_monitor}/. $out/lib/codex-quota-monitor/codex_quota_monitor/
    patchShebangs $out/bin
    runHook postInstall
  '';

  meta = {
    description = "e-ink-friendly local HTTP dashboard for CLIProxyAPI pools";
    mainProgram = "codex-quota-monitor";
    platforms = lib.platforms.linux;
  };
}
