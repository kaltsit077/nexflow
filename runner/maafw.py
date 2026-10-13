"""Resolve and invoke official MaaFramework MaaPiCli (ProjectInterface client)."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any, Optional

from .config import ROOT

# Default: maafw/ next to the app (filled by tools/setup_maafw.bat)
DEFAULT_BIN_DIR = ROOT / "maafw"


def _maafw_search_dirs() -> list[Path]:
    """Dirs that may contain MaaPiCli.exe / MaaFramework.dll."""
    dirs: list[Path] = [DEFAULT_BIN_DIR]
    # Frozen onedir: dist/GameRunner/maafw；旧单文件 dist\exe 时回退到仓库根 maafw\
    if getattr(sys, "frozen", False):
        if ROOT.name.lower() == "dist":
            parent_maafw = ROOT.parent / "maafw"
            if parent_maafw not in dirs:
                dirs.append(parent_maafw)
        elif ROOT.parent.name.lower() == "dist":
            # dist/GameRunner/*.exe → also try repo maafw during local --force tests
            repo_maafw = ROOT.parent.parent / "maafw"
            if repo_maafw not in dirs:
                dirs.append(repo_maafw)
    return dirs


def resolve_maapicli(script: Optional[dict[str, Any]] = None) -> Path:
    """Find MaaPiCli.exe: script.maafw_bin > env > ./maafw > (dist→parent/maafw) > PATH."""
    candidates: list[Path] = []

    if script:
        custom = (script.get("maafw_bin") or "").strip()
        if custom:
            p = Path(custom)
            if not p.is_absolute():
                p = ROOT / p
            candidates.append(p / "MaaPiCli.exe" if p.is_dir() else p)

    env = os.environ.get("GAME_RUNNER_MAAFW", "").strip()
    if env:
        p = Path(env)
        candidates.append(p / "MaaPiCli.exe" if p.is_dir() else p)

    for d in _maafw_search_dirs():
        candidates.append(d / "MaaPiCli.exe")

    which = shutil.which("MaaPiCli") or shutil.which("MaaPiCli.exe")
    if which:
        candidates.append(Path(which))

    for c in candidates:
        if c.is_file():
            return c.resolve()

    tried = " | ".join(str(c) for c in candidates[:6])
    raise FileNotFoundError(
        "找不到 MaaPiCli.exe，无法枚举窗口。\n"
        "处理：在仓库根目录运行 tools\\setup_maafw.bat（日常用 start.bat，"
        f"保证 maafw\\ 与入口同级；当前 ROOT={ROOT}）。也可设 GAME_RUNNER_MAAFW。\n"
        f"已尝试: {tried}"
    )


def build_maafw_command(script: dict[str, Any]) -> tuple[list[str], str]:
    """Return (argv, cwd). path = PI project root (directory with interface.json)."""
    project = Path(script["path"])
    if not project.is_absolute():
        project = ROOT / project
    project = project.resolve()
    if not project.is_dir():
        raise FileNotFoundError(f"MaaFW project directory not found: {project}")
    interface = project / "interface.json"
    if not interface.is_file():
        raise FileNotFoundError(f"interface.json missing in project: {project}")

    cli = resolve_maapicli(script)
    args = list(script.get("args") or ["-d"])
    return [str(cli), *args], str(project)
