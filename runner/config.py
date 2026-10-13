"""配置加载与保存。支持源码运行与 PyInstaller 冻结。"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """Writable app root: next to the .exe when frozen, else project root."""
    if _is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def bundle_dir() -> Path:
    """Read-only bundled resources (PyInstaller _MEIPASS or project root)."""
    if _is_frozen():
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent.parent


ROOT = app_dir()
BUNDLE = bundle_dir()
CONFIG_PATH = ROOT / "config.json"
LOGS_DIR = ROOT / "logs"
SCRIPTS_DIR = ROOT / "scripts"
PROJECTS_DIR = ROOT / "projects"
HISTORY_PATH = ROOT / "history.json"


def resolve_script_dir(script: dict[str, Any]) -> Path:
    """Folder to reveal for a script: workdir > path dir > path parent."""
    wd = (script.get("workdir") or "").strip()
    if wd:
        p = Path(wd)
        if not p.is_absolute():
            p = ROOT / p
        if p.is_dir():
            return p.resolve()
    raw = (script.get("path") or "").strip()
    if not raw:
        raise FileNotFoundError("脚本未设置 path")
    p = Path(raw)
    if not p.is_absolute():
        p = ROOT / p
    p = p.resolve()
    if p.is_dir():
        return p
    if p.is_file():
        return p.parent
    if p.parent.is_dir():
        return p.parent
    raise FileNotFoundError(f"路径不存在: {p}")


def _copy_tree_if_missing(src: Path, dst: Path) -> None:
    if not src.exists() or dst.exists():
        return
    shutil.copytree(src, dst)


def prune_run_logs(
    *,
    max_files: int = 80,
    max_age_days: int = 14,
    max_maa_debug_mb: float = 32.0,
) -> None:
    """Drop old per-run logs and cap MaaFW debug log growth under logs/."""
    if not LOGS_DIR.is_dir():
        return
    now = time.time()
    max_age = max_age_days * 86400
    run_logs = [
        p
        for p in LOGS_DIR.glob("*.log")
        if p.is_file() and p.name not in ("start_errors.log", "build_errors.log", "build_last.log")
    ]
    run_logs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for i, p in enumerate(run_logs):
        try:
            stale = (now - p.stat().st_mtime) > max_age
            if i >= max_files or stale:
                p.unlink(missing_ok=True)
        except OSError:
            pass

    # Toolkit debug log can grow while studio is connected
    maa_log = LOGS_DIR / "maa_runtime" / "debug" / "maafw.log"
    try:
        if maa_log.is_file() and maa_log.stat().st_size > max_maa_debug_mb * 1024 * 1024:
            maa_log.write_text("", encoding="utf-8")
    except OSError:
        pass


def ensure_runtime_files() -> None:
    """Create logs/scripts/projects/library; seed config and demos from bundle if missing."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        from .library import ensure_library_root, migrate_legacy_tools_dir

        ensure_library_root()
        migrate_legacy_tools_dir()
    except Exception:
        pass

    if not CONFIG_PATH.exists():
        bundled = BUNDLE / "config.example.json"
        if not bundled.exists():
            bundled = BUNDLE / "config.json"
        if bundled.exists():
            shutil.copy2(bundled, CONFIG_PATH)
        else:
            CONFIG_PATH.write_text(
                json.dumps({"scripts": [], "lists": []}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    demo_src = BUNDLE / "scripts" / "hello_demo.py"
    demo_dst = SCRIPTS_DIR / "hello_demo.py"
    if demo_src.exists() and not demo_dst.exists():
        shutil.copy2(demo_src, demo_dst)

    # Official-style PI demo project
    _copy_tree_if_missing(
        BUNDLE / "projects" / "demo_click",
        PROJECTS_DIR / "demo_click",
    )

    try:
        prune_run_logs()
    except Exception:
        pass


ensure_runtime_files()


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config not found: {CONFIG_PATH}")
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg: dict[str, Any]) -> None:
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def load_history() -> list[dict[str, Any]]:
    if not HISTORY_PATH.exists():
        return []
    with HISTORY_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def append_history(entry: dict[str, Any], max_keep: int = 500) -> None:
    hist = load_history()
    hist.append(entry)
    hist = hist[-max_keep:]
    with HISTORY_PATH.open("w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)
