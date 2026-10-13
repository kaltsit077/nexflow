"""Report disk use of Game Runner caches / build artifacts.

    python tools/disk_usage.py
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WATCH = (
    ".cache",
    "build",
    "dist",
    "logs",
    "library",
    "maafw",
    "projects",
    "runner",
    "ui",
)


def dir_size(path: Path) -> tuple[int, int]:
    total = 0
    n = 0
    if not path.exists():
        return 0, 0
    if path.is_file():
        return path.stat().st_size, 1
    for f in path.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
                n += 1
            except OSError:
                pass
    return total, n


def main() -> int:
    print(f"Game Runner disk usage — {ROOT}\n")
    grand = 0
    for name in WATCH:
        p = ROOT / name
        b, n = dir_size(p)
        grand += b
        status = "missing" if not p.exists() else f"{b / 1024 / 1024:8.2f} MB  ({n} files)"
        print(f"  {name:12} {status}")
    print(f"\n  {'watched sum':12} {grand / 1024 / 1024:8.2f} MB")
    cache = ROOT / ".cache"
    if cache.is_dir():
        print("\n  .cache detail:")
        for child in sorted(cache.iterdir(), key=lambda x: -dir_size(x)[0]):
            b, n = dir_size(child)
            kind = "/" if child.is_dir() else ""
            print(f"    {child.name}{kind:1}  {b / 1024 / 1024:.2f} MB")
    print("\nTips: daily → start.bat  |  clean.bat  |  packaging deferred (build.bat --force)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
