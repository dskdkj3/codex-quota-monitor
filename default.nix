{ lib, python312 }:

let
  py = python312.pkgs;
in
py.buildPythonApplication {
  pname = "codex-quota-monitor";
  version = "0.1.0";
  pyproject = true;
  src = ./.;

  nativeBuildInputs = [
    py.setuptools
    py.wheel
  ];

  pythonImportsCheck = [ "codex_quota_monitor" ];

  doCheck = false;
  doInstallCheck = true;
  installCheckPhase = ''
    runHook preInstallCheck
    export PYTHONPATH=$PWD/src
    python -m unittest discover -s tests -v
    runHook postInstallCheck
  '';

  meta = {
    description = "Browser-friendly Codex quota dashboard for CLIProxyAPI pools";
    license = lib.licenses.mit;
    mainProgram = "codex-quota-monitor";
    platforms = lib.platforms.all;
  };
}
