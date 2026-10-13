"""Architecture / anti-hallucination checks for game-runner.

Run from repo root:
    python tools/check_architecture.py

Exit 0 = clean; 1 = violations.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "runner"
UI = ROOT / "ui"

# Module-level defs in ui widgets that look like domain logic (heuristic).
DOMAINISH_NAME = re.compile(
    r"^(build_|parse_|detect_|resolve_|kill_|install_|download_|export_|apply_|"
    r"run_list|run_single|_build_command|_kill_)",
    re.I,
)

# Qt / UI glue names allowed as module-level in ui/
UI_OK_TOPLEVEL = {
    "main",
    "app_stylesheet",
    "apply_app_palette",
    "apply_theme",
    "list_themes",
    "resolve_theme",
    "current_theme",
    "datetime_stamp",
    "_force_light_palette",
    "_sync_globals",
    "_split_csv",
}


class Finding(str):
    pass


def _py_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.rglob("*.py") if "__pycache__" not in p.parts)


def check_runner_imports_ui() -> list[Finding]:
    out: list[Finding] = []
    for path in _py_files(RUNNER):
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"^\s*(from\s+ui\b|import\s+ui\b)", text, re.M):
            out.append(Finding(f"[P0] runner → ui import: {path.relative_to(ROOT)}"))
    return out


def check_orphan_screencap() -> list[Finding]:
    """screencap.py must not gain new importers (deprecated)."""
    out: list[Finding] = []
    sc = RUNNER / "screencap.py"
    if not sc.is_file():
        return out
    importers: list[str] = []
    for path in list(_py_files(RUNNER)) + list(_py_files(UI)) + [
        ROOT / "main.py",
        ROOT / "cli.py",
    ]:
        if not path.is_file() or path.resolve() == sc.resolve():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"runner\.screencap|from\s+runner\s+import\s+.*screencap", text):
            importers.append(str(path.relative_to(ROOT)))
        if "import screencap" in text or "from .screencap" in text:
            importers.append(str(path.relative_to(ROOT)))
    if importers:
        out.append(
            Finding(
                "[P1] deprecated runner/screencap.py is imported by: "
                + ", ".join(sorted(set(importers)))
            )
        )
    return out


def check_ui_domainish_toplevel() -> list[Finding]:
    """Flag module-level functions in ui/ that look like engine logic."""
    out: list[Finding] = []
    for path in _py_files(UI):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        except SyntaxError as e:
            out.append(Finding(f"[P0] syntax error {path.relative_to(ROOT)}: {e}"))
            continue
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            name = node.name
            if name in UI_OK_TOPLEVEL or name.startswith("test_"):
                continue
            # Allow tiny helpers (< 12 statements) with non-domain names
            n_stmt = sum(1 for _ in ast.walk(node) if isinstance(_, ast.stmt))
            if DOMAINISH_NAME.match(name) or n_stmt > 20:
                out.append(
                    Finding(
                        f"[P1] ui toplevel looks like domain logic: "
                        f"{path.relative_to(ROOT)}::{name} (stmts≈{n_stmt}) "
                        f"— move to runner/"
                    )
                )
    return out


def check_ui_reimplements_executor() -> list[Finding]:
    """Heuristic: ui must not embed kill-tree / cmd construction (labels OK)."""
    out: list[Finding] = []
    banned = [
        (r"CreateToolhelp32Snapshot", "process-tree kill belongs in executor"),
        (r"taskkill\s+/F", "kill via executor._kill_process_tree"),
        (r"build_maafw_command\s*\(", "call via runner.executor, not re-wrap in ui"),
        (r"subprocess\.(Popen|run)\s*\(", "process spawn belongs in executor"),
        (r"_kill_process_tree\s*\(", "kill-tree belongs in executor"),
    ]
    for path in _py_files(UI):
        text = path.read_text(encoding="utf-8", errors="replace")
        for pat, why in banned:
            if re.search(pat, text, re.I):
                out.append(
                    Finding(f"[P0] ui embeds engine concern ({why}): {path.relative_to(ROOT)}")
                )
    return out


def check_dual_path_comment_drift() -> list[Finding]:
    """executor must still route maafw through build_maafw_command."""
    out: list[Finding] = []
    ex = RUNNER / "executor.py"
    if not ex.is_file():
        return [Finding("[P0] missing runner/executor.py")]
    text = ex.read_text(encoding="utf-8", errors="replace")
    if "build_maafw_command" not in text:
        out.append(Finding("[P0] executor.py no longer calls build_maafw_command"))
    if "MaaSession" in text:
        out.append(Finding("[P0] executor.py must not use in-process MaaSession for queues"))
    return out


def check_required_docs() -> list[Finding]:
    out: list[Finding] = []
    for rel in (
        "AGENTS.md",
        "docs/需求澄清与模糊点.md",
        ".cursor/rules/00-project-overview.mdc",
        ".cursor/rules/ui-presentation.mdc",
        ".cursor/rules/runner-engine.mdc",
    ):
        if not (ROOT / rel).is_file():
            out.append(Finding(f"[P2] missing {rel}"))
    return out


def main() -> int:
    findings: list[Finding] = []
    findings += check_runner_imports_ui()
    findings += check_ui_reimplements_executor()
    findings += check_dual_path_comment_drift()
    findings += check_orphan_screencap()
    findings += check_ui_domainish_toplevel()
    findings += check_required_docs()

    print(f"Game Runner architecture check — root: {ROOT}")
    if not findings:
        print("OK: no violations.")
        return 0
    print(f"FAIL: {len(findings)} finding(s)\n")
    for f in findings:
        print(f"  {f}")
    print("\nSee AGENTS.md and docs/需求澄清与模糊点.md")
    return 1


if __name__ == "__main__":
    sys.exit(main())
