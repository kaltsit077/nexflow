"""
统一「全部项目」目录布局（类似 mod 管理器）：

  library/                      ← 全部项目（英文路径，兼容各助手）
    <project_id>/               ← 分项目
      app/                      ← 项目本体（下载的 exe / 解压包）
      scripts/                  ← 项目脚本（本调度器侧补充、说明、自写 bat）
      meta.json                 ← 安装元数据

UI 文案用中文「全部项目 / 项目本体 / 项目脚本」。
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .config import ROOT

# Root folder name stays ASCII — many tools break on Chinese paths (e.g. LCBA).
LIBRARY_DIR = ROOT / "library"
LIBRARY_LABEL = "全部项目"
APP_DIRNAME = "app"
SCRIPTS_DIRNAME = "scripts"
META_NAME = "meta.json"

README_TEXT = """Game Runner · 全部项目（library）
==============================

目录约定（类似 mod 管理器）：

  library/                 ← 全部项目
    <分项目 id>/
      app/                 ← 项目本体（助手程序本体）
      scripts/             ← 项目脚本（说明、bat、自写补充）
      meta.json            ← 安装记录

请勿把「项目本体」直接塞在分项目根下；安装器会解压到 app\\。
国内 GitHub 慢时可设环境变量 GAME_RUNNER_GH_PROXY（如 https://ghproxy.net）。
"""


def ensure_library_root() -> Path:
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    readme = LIBRARY_DIR / "README.txt"
    if not readme.is_file():
        readme.write_text(README_TEXT, encoding="utf-8")
    return LIBRARY_DIR


def project_dir(project_id: str) -> Path:
    return LIBRARY_DIR / project_id


def app_dir(project_id: str) -> Path:
    return project_dir(project_id) / APP_DIRNAME


def scripts_dir(project_id: str) -> Path:
    return project_dir(project_id) / SCRIPTS_DIRNAME


def scan_roots_for_project(project_id: str) -> list[Path]:
    """Directories to try when fingerprint-scanning a library project.

    Prefer ``app/``, then project root, then one level of extract folders
    (e.g. manual drop of ``MAA-win-x64-…`` beside or under app).
    """
    root = project_dir(project_id)
    app = app_dir(project_id)
    out: list[Path] = []
    seen: set[Path] = set()

    def _add(p: Path) -> None:
        try:
            key = p.resolve()
        except OSError:
            return
        if key in seen or not p.is_dir():
            return
        # skip scripts-only / meta noise
        if p.name in (SCRIPTS_DIRNAME,) or p.name.startswith("."):
            return
        seen.add(key)
        out.append(p)

    _add(app)
    _add(root)
    for base in (app, root):
        if not base.is_dir():
            continue
        try:
            children = sorted(base.iterdir(), key=lambda x: x.name.lower())
        except OSError:
            continue
        for child in children[:40]:
            if child.is_dir():
                _add(child)
    return out


def meta_path(project_id: str) -> Path:
    return project_dir(project_id) / META_NAME


def ensure_project_layout(project_id: str, *, title: str = "", notes: str = "") -> Path:
    """Create 分项目 / app / scripts and a short scripts README."""
    ensure_library_root()
    root = project_dir(project_id)
    app = app_dir(project_id)
    scripts = scripts_dir(project_id)
    app.mkdir(parents=True, exist_ok=True)
    scripts.mkdir(parents=True, exist_ok=True)
    tip = scripts / "README.txt"
    if not tip.is_file():
        tip.write_text(
            f"项目脚本目录 · {title or project_id}\n"
            f"{notes}\n\n"
            "可在此放置：自定义 bat、备注、导出的 pipeline 副本等。\n"
            "助手程序本体请放在上级的 app\\ 目录。\n",
            encoding="utf-8",
        )
    return root


def write_meta(project_id: str, data: dict[str, Any]) -> Path:
    ensure_project_layout(project_id)
    payload = {
        "id": project_id,
        "updated": datetime.now().isoformat(timespec="seconds"),
        **data,
    }
    path = meta_path(project_id)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def read_meta(project_id: str) -> Optional[dict[str, Any]]:
    path = meta_path(project_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_projects() -> list[str]:
    ensure_library_root()
    return sorted(
        p.name
        for p in LIBRARY_DIR.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    )


def migrate_legacy_tools_dir() -> Optional[str]:
    """
    Move old flat tools/<id>/* into library/<id>/app/ if tools/ exists.
    Returns a short message or None.
    """
    legacy = ROOT / "tools"
    if not legacy.is_dir():
        return None
    # Don't migrate the setup_*.bat scripts folder (repo tools/)
    # Repo has tools/setup_maafw.bat — that's SOURCE tools, not install root.
    # Only migrate if it looks like install output (has subdirs without .bat at top? )
    # Actually repo `tools/` contains setup bats. Installer previously used ROOT/tools/<id>.
    # Conflict! Catalog installer used TOOLS_DIR = ROOT / "tools" which OVERLAPS repo tools/.
    #
    # New layout uses library/ to avoid clobbering tools/setup_*.bat.
    kids = [p for p in legacy.iterdir() if p.is_dir() and p.name not in ("__pycache__",)]
    # Skip if only looks like repo scripts (has setup_maafw.bat and no heavy installs)
    moved = []
    for p in kids:
        # Heuristic: treat as install if it contains exe/dll or many files
        if (p / "app").is_dir():
            continue
        has_bin = any(
            x.suffix.lower() in {".exe", ".dll"} for x in p.rglob("*") if x.is_file()
        )
        if not has_bin:
            continue
        ensure_project_layout(p.name)
        dest = app_dir(p.name)
        # move contents into app/
        for item in list(p.iterdir()):
            target = dest / item.name
            if target.exists():
                continue
            shutil.move(str(item), str(target))
        write_meta(p.name, {"migrated_from": str(p), "note": "from legacy tools/"})
        moved.append(p.name)
        try:
            p.rmdir()
        except OSError:
            pass
    if not moved:
        return None
    return f"已迁移旧安装到 library\\…\\app\\: {', '.join(moved)}"
