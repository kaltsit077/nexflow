"""Used by build.bat --force to copy maafw into dist/GameRunner/maafw."""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
src = ROOT / "maafw"
dst = ROOT / "dist" / "GameRunner" / "maafw"
shutil.rmtree(dst, ignore_errors=True)
shutil.copytree(src, dst)
print("maafw", (dst / "MaaPiCli.exe").is_file())
