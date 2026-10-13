"""Detect known automation tool installs from a folder / exe path."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional


def _slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_]+", "_", name.strip()).strip("_").lower()
    return s or "imported"


def _find_named(root: Path, names: list[str], depth: int = 2) -> Optional[Path]:
    want = {n.lower() for n in names}
    if root.is_file():
        return root if root.name.lower() in want else None
    if not root.is_dir():
        return None
    for p in root.iterdir():
        if p.is_file() and p.name.lower() in want:
            return p
    if depth <= 0:
        return None
    skip = {".git", "cache", "debug", "logs", "__pycache__", "externals"}
    for p in root.iterdir():
        if p.is_dir() and p.name.lower() not in skip:
            hit = _find_named(p, names, depth - 1)
            if hit:
                return hit
    return None


def detect_tool(path_str: str) -> dict[str, Any]:
    """Inspect a path (dir or file) and return a suggested script entry."""
    raw = Path(path_str.strip().strip('"'))
    if not raw.exists():
        return {"ok": False, "error": f"Path not found: {path_str}"}

    root = raw.parent if raw.is_file() else raw
    notes: list[str] = []

    # Official Arknights MAA
    maa_exe = raw if raw.is_file() and raw.name.lower() == "maa.exe" else _find_named(root, ["MAA.exe"])
    if maa_exe and (maa_exe.parent / "MaaCore.dll").exists():
        return {
            "ok": True,
            "tool_id": "maa_arknights",
            "label": "Official Arknights MAA",
            "script": {
                "id": "arknights_maa",
                "name": "Arknights (MAA)",
                "type": "exe",
                "path": str(maa_exe.resolve()),
                "args": [],
                "workdir": str(maa_exe.parent.resolve()),
                "timeout_sec": 3600,
                "wait_mode": "launch",
                "tags": ["arknights", "maa", "imported"],
                "presets": [
                    {
                        "id": "run",
                        "name": "Launch MAA",
                        "args": [],
                        "timeout_sec": 3600,
                        "description": "Starts MAA GUI with its saved config.",
                    }
                ],
            },
            "notes": notes,
        }

    # BetterGI
    bgi = (
        raw
        if raw.is_file() and "bettergi" in raw.name.lower()
        else _find_named(root, ["BetterGI.exe"])
    )
    if bgi:
        return {
            "ok": True,
            "tool_id": "bettergi",
            "label": "BetterGI",
            "script": {
                "id": "genshin_bettergi",
                "name": "Genshin (BetterGI)",
                "type": "exe",
                "path": str(bgi.resolve()),
                "args": [],
                "workdir": str(bgi.parent.resolve()),
                "timeout_sec": 1800,
                "wait_mode": "launch",
                "tags": ["genshin", "bettergi", "imported"],
                "presets": [
                    {"id": "run", "name": "Launch BetterGI", "args": [], "timeout_sec": 1800}
                ],
            },
            "notes": notes,
        }

    # March7th
    m7 = (
        raw
        if raw.is_file() and "march7" in raw.name.lower()
        else _find_named(root, ["March7thAssistant.exe", "March7th.exe"])
    )
    if m7:
        return {
            "ok": True,
            "tool_id": "march7th",
            "label": "March7thAssistant",
            "script": {
                "id": "starrail_march7th",
                "name": "Star Rail (March7th)",
                "type": "exe",
                "path": str(m7.resolve()),
                "args": [],
                "workdir": str(m7.parent.resolve()),
                "timeout_sec": 1800,
                "wait_mode": "launch",
                "tags": ["starrail", "march7th", "imported"],
                "presets": [
                    {"id": "run", "name": "Launch March7th", "args": [], "timeout_sec": 1800}
                ],
            },
            "notes": notes,
        }

    # ok-ww (Wuthering Waves / ok-script)
    okww = (
        raw
        if raw.is_file() and raw.name.lower() == "ok-ww.exe"
        else _find_named(root, ["ok-ww.exe"])
    )
    if okww:
        notes.append("Scheduler-friendly: preset task1_exit uses -t 1 -e (Nth Start-tab task).")
        return {
            "ok": True,
            "tool_id": "ok_ww",
            "label": "ok-ww (Wuthering Waves)",
            "script": {
                "id": "wuthering_okww",
                "name": "Wuthering Waves (ok-ww)",
                "type": "exe",
                "path": str(okww.resolve()),
                "args": ["-t", "1", "-e"],
                "workdir": str(okww.parent.resolve()),
                "timeout_sec": 3600,
                "wait_mode": "wait_exit",
                "tags": ["wuthering", "ok-ww", "imported"],
                "presets": [
                    {
                        "id": "task1_exit",
                        "name": "Task #1 then exit (-t 1 -e)",
                        "args": ["-t", "1", "-e"],
                        "timeout_sec": 3600,
                        "description": "Runs 1st one-time task on Start tab, then exits.",
                    },
                    {
                        "id": "gui",
                        "name": "Launch GUI only",
                        "args": [],
                        "timeout_sec": 3600,
                    },
                ],
            },
            "notes": notes,
        }

    # LCBA (Limbus Company helper) — Start.exe + PyInstaller _internal
    lcba = (
        raw
        if raw.is_file() and raw.name.lower() == "start.exe"
        else _find_named(root, ["Start.exe"])
    )
    if lcba:
        parent = lcba.parent
        looks_lcba = (parent / "_internal").is_dir() and (
            any(parent.glob("*说明书*"))
            or "lcba" in parent.name.lower()
            or (parent / "LCBA_config.txt").is_file()
        )
        if looks_lcba:
            notes.append(
                "GUI-only; no headless CLI. Use English path; configure LCBA_config.txt first."
            )
            return {
                "ok": True,
                "tool_id": "lcba",
                "label": "LCBA (Limbus Company)",
                "script": {
                    "id": "limbus_lcba",
                    "name": "Limbus Company (LCBA)",
                    "type": "exe",
                    "path": str(lcba.resolve()),
                    "args": [],
                    "workdir": str(parent.resolve()),
                    "timeout_sec": 3600,
                    "wait_mode": "launch",
                    "tags": ["limbus", "lcba", "imported"],
                    "presets": [
                        {
                            "id": "run",
                            "name": "Launch Start.exe",
                            "args": [],
                            "timeout_sec": 3600,
                            "description": "Black-box GUI; relies on LCBA_config.txt presets.",
                        }
                    ],
                },
                "notes": notes,
            }

    # Azur Lane Auto Script (Alas)
    alas = (
        raw
        if raw.is_file() and raw.name.lower() == "alas.exe"
        else _find_named(root, ["Alas.exe"])
    )
    if alas and (alas.parent / "alas.py").is_file():
        notes.append("Alas has its own in-app scheduler; Game Runner just launches the GUI.")
        return {
            "ok": True,
            "tool_id": "alas",
            "label": "AzurLaneAutoScript (Alas)",
            "script": {
                "id": "azurlane_alas",
                "name": "Azur Lane (Alas)",
                "type": "exe",
                "path": str(alas.resolve()),
                "args": [],
                "workdir": str(alas.parent.resolve()),
                "timeout_sec": 7200,
                "wait_mode": "launch",
                "tags": ["azurlane", "alas", "imported"],
                "presets": [
                    {"id": "run", "name": "Launch Alas", "args": [], "timeout_sec": 7200}
                ],
            },
            "notes": notes,
        }

    # MaaFW PI project
    iface = root / "interface.json"
    if raw.is_file() and raw.name.lower() == "interface.json":
        iface = raw
        root = raw.parent
    if iface.is_file():
        display = root.name
        sid = _slug(root.name)
        try:
            meta = json.loads(iface.read_text(encoding="utf-8"))
            sid = _slug(str(meta.get("name") or root.name))
            label = meta.get("label") or meta.get("name") or root.name
            if isinstance(label, str) and label.startswith("$"):
                label = meta.get("name") or root.name
            display = str(label)
        except Exception:
            pass

        script: dict[str, Any] = {
            "id": f"maafw_{sid}",
            "name": f"{display} (MaaFW)",
            "type": "maafw",
            "path": str(root.resolve()),
            "args": ["-d"],
            "workdir": "",
            "timeout_sec": 3600,
            "tags": ["maafw", "imported"],
            "presets": [
                {
                    "id": "run",
                    "name": "MaaPiCli -d",
                    "args": ["-d"],
                    "timeout_sec": 3600,
                    "description": "Needs config/maa_pi_config.json from one interactive setup.",
                }
            ],
        }
        local_cli = root / "maafw" / "MaaPiCli.exe"
        if local_cli.is_file():
            script["maafw_bin"] = str(local_cli.parent.resolve())
        notes.append("Run MXU or MaaPiCli once interactively before headless -d.")
        return {
            "ok": True,
            "tool_id": "maafw_project",
            "label": f"MaaFramework project: {display}",
            "script": script,
            "notes": notes,
        }

    # mxu.exe next to interface.json
    mxu = raw if raw.is_file() and raw.name.lower() == "mxu.exe" else _find_named(root, ["mxu.exe"])
    if mxu and (mxu.parent / "interface.json").is_file():
        return detect_tool(str(mxu.parent))

    # Generic exe
    if raw.is_file() and raw.suffix.lower() == ".exe":
        return {
            "ok": True,
            "tool_id": "generic_exe",
            "label": f"Generic EXE: {raw.name}",
            "script": {
                "id": _slug(raw.stem),
                "name": raw.stem,
                "type": "exe",
                "path": str(raw.resolve()),
                "args": [],
                "workdir": str(raw.parent.resolve()),
                "timeout_sec": 3600,
                "tags": ["imported", "generic"],
                "presets": [
                    {"id": "run", "name": "Launch", "args": [], "timeout_sec": 3600}
                ],
            },
            "notes": ["Unknown fingerprint; imported as generic exe."],
        }

    return {
        "ok": False,
        "error": (
            "Unrecognized path. Use a folder with MAA.exe, BetterGI.exe, "
            "March7thAssistant.exe, ok-ww.exe, LCBA Start.exe, Alas.exe, "
            "or interface.json."
        ),
    }


def known_tools_help() -> list[dict[str, str]]:
    return [
        {"id": "maa_arknights", "hint": "Folder with MAA.exe + MaaCore.dll"},
        {"id": "bettergi", "hint": "Folder with BetterGI.exe"},
        {"id": "march7th", "hint": "Folder with March7thAssistant.exe"},
        {"id": "ok_ww", "hint": "Folder with ok-ww.exe (use -t N -e for headless-ish runs)"},
        {"id": "lcba", "hint": "Folder with Start.exe + _internal (Limbus LCBA)"},
        {"id": "alas", "hint": "Folder with Alas.exe + alas.py"},
        {"id": "maafw_project", "hint": "Folder with interface.json"},
    ]


def apply_preset(script: dict[str, Any], preset_id: Optional[str]) -> dict[str, Any]:
    """Return a shallow-copied script with preset args/timeout applied."""
    import copy

    out = copy.deepcopy(script)
    if not preset_id:
        return out
    for p in out.get("presets") or []:
        if p.get("id") == preset_id:
            if "args" in p:
                out["args"] = list(p.get("args") or [])
            if p.get("timeout_sec"):
                out["timeout_sec"] = int(p["timeout_sec"])
            if p.get("workdir"):
                out["workdir"] = p["workdir"]
            if p.get("maafw_bin"):
                out["maafw_bin"] = p["maafw_bin"]
            if p.get("wait_mode"):
                out["wait_mode"] = p["wait_mode"]
            break
    return out


def sync_run_preset(script: dict[str, Any]) -> None:
    """Keep the default `run` preset aligned with the script form fields."""
    args = list(script.get("args") or [])
    timeout = int(script.get("timeout_sec") or 3600)
    wait_mode = script.get("wait_mode") or "wait_exit"
    presets = script.setdefault("presets", [])
    run = next((p for p in presets if p.get("id") == "run"), None)
    if run is None:
        presets.insert(
            0,
            {
                "id": "run",
                "name": "默认",
                "args": args,
                "timeout_sec": timeout,
                "wait_mode": wait_mode,
            },
        )
        return
    run["args"] = args
    run["timeout_sec"] = timeout
    run["wait_mode"] = wait_mode
