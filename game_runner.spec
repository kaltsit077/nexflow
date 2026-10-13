# -*- mode: python ; coding: utf-8 -*-
# Optional folder (onedir) release — NOT used for daily work.
# Daily: start.bat / python main.py (whole repo folder, like MAA).
# Build: build.bat --force  →  dist/GameRunner/GameRunner.exe + deps
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None
ROOT = Path(SPECPATH)


def _project_datas():
    """Bundle PI projects but skip heavy OCR onnx (restore via setup_ocr.bat)."""
    out = []
    root = ROOT / "projects"
    if not root.is_dir():
        return out
    skip_suffix = {".onnx", ".pdb"}
    for f in root.rglob("*"):
        if not f.is_file() or f.suffix.lower() in skip_suffix:
            continue
        dest = str(f.relative_to(ROOT).parent).replace("\\", "/")
        out.append((str(f), dest))
    return out


hidden = [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "psutil",
    "numpy",
    "runner",
    "runner.config",
    "runner.executor",
    "runner.maafw",
    "runner.maa_runtime",
    "runner.catalog",
    "runner.pipeline_recorder",
    "runner.tool_catalog",
    "runner.tool_installer",
    "runner.library",
    "ui",
    "ui.main_window",
    "ui.preview_panel",
    "ui.styles",
    "ui.step_card",
    "ui.dialogs",
    "ui.catalog_dialog",
    "maa",
]
hidden += collect_submodules("PySide6")
try:
    hidden += collect_submodules("maa")
except Exception:
    pass

datas = [
    ("config.example.json", "."),
    ("scripts", "scripts"),
]
datas += _project_datas()
_maafw_readme = ROOT / "maafw" / "README.txt"
if _maafw_readme.is_file():
    datas.append(("maafw/README.txt", "maafw"))

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["fastapi", "uvicorn", "webview", "tkinter"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GameRunner",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="GameRunner",
)
