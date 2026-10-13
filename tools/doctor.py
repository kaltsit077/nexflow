"""Environment self-check for Game Runner (folder / source mode).

    python tools/doctor.py
Exit 0 = ready enough to launch UI; 1 = blocking issues.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _ok(msg: str) -> None:
    print(f"  OK   {msg}")


def _warn(msg: str) -> None:
    print(f"  WARN {msg}")


def _fail(msg: str) -> None:
    print(f"  FAIL {msg}")


def main() -> int:
    print(f"Game Runner doctor — {ROOT}\n")
    blocking = 0
    warnings = 0

    if sys.version_info < (3, 9):
        _fail(f"Python {sys.version.split()[0]} (< 3.9)")
        blocking += 1
    else:
        _ok(f"Python {sys.version.split()[0]}")

    for mod in ("PySide6", "psutil", "numpy"):
        if importlib.util.find_spec(mod) is None:
            _fail(f"missing pip package: {mod}  →  pip install -r requirements.txt")
            blocking += 1
        else:
            _ok(f"import {mod}")

    if importlib.util.find_spec("maa") is None:
        _warn("missing MaaFw (studio / in-process). pip install -r requirements.txt")
        warnings += 1
    else:
        _ok("import maa (MaaFw)")

    cli = ROOT / "maafw" / "MaaPiCli.exe"
    dll = ROOT / "maafw" / "MaaFramework.dll"
    if cli.is_file() and dll.is_file():
        _ok(f"maafw runtime: {cli}")
    else:
        _fail("maafw\\MaaPiCli.exe or MaaFramework.dll missing → tools\\setup_maafw.bat")
        blocking += 1

    cfg = ROOT / "config.json"
    if cfg.is_file():
        _ok("config.json present")
    else:
        _warn("config.json missing (will seed from config.example.json on first run)")
        warnings += 1

    ocr = ROOT / "projects" / "click_lab" / "resource" / "model" / "ocr" / "rec.onnx"
    if ocr.is_file():
        _ok("click_lab OCR model present")
    else:
        _warn("click_lab OCR not installed → tools\\setup_ocr.bat (only if you need OCR)")
        warnings += 1

    print()
    if blocking:
        print(f"Result: NOT READY ({blocking} blocking, {warnings} warnings)")
        print("Fix the FAIL lines, then: start.bat")
        return 1
    print(f"Result: READY to launch ({warnings} warnings)")
    print("Next: start.bat")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
