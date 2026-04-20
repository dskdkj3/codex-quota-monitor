#!/usr/bin/env python3

import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parent
PACKAGE_ROOTS = (
    ROOT,
    ROOT.parent / "lib" / "codex-quota-monitor",
)

for package_root in PACKAGE_ROOTS:
    if (package_root / "codex_quota_monitor").is_dir():
        sys.path.insert(0, str(package_root))
        break

from codex_quota_monitor.cli import main


if __name__ == "__main__":
    main()
