"""Detached GUI launch for studio connect and script pre_launch."""
from __future__ import annotations

import ctypes
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Sequence, TypeVar

import psutil

from .config import ROOT

LogFn = Callable[[str], None]
W = TypeVar("W")  # WinInfo-like: .hwnd .title

# Windows GUI / helpers default to UAC elevation (MAA PC 端等需要管理员).
DEFAULT_RUN_AS_ADMIN = True

SEE_MASK_NOCLOSEPROCESS = 0x00000040
SW_SHOWNORMAL = 1
ERROR_CANCELLED = 1223


@dataclass(frozen=True)
class DetachedProcess:
    pid: int
    path: Path
    workdir: Path
    elevated: bool = False


class PidProcess:
    """Minimal process handle for elevated launches (no stdout pipe)."""

    def __init__(self, pid: int) -> None:
        self.pid = int(pid)
        self.returncode: Optional[int] = None
        self.stdout = None

    def poll(self) -> Optional[int]:
        if self.returncode is not None:
            return self.returncode
        try:
            if not psutil.pid_exists(self.pid):
                self.returncode = 0
                return self.returncode
        except (psutil.Error, ValueError, TypeError):
            self.returncode = 0
            return self.returncode
        return None

    def wait(self, timeout: Optional[float] = None) -> int:
        code = self.poll()
        if code is not None:
            return code
        try:
            proc = psutil.Process(self.pid)
            self.returncode = int(proc.wait(timeout=timeout) or 0)
        except psutil.TimeoutExpired as e:
            raise TimeoutError(str(e)) from e
        except (psutil.Error, ValueError, TypeError):
            self.returncode = 0
        return int(self.returncode if self.returncode is not None else 0)


def resolve_launch_path(path: str | Path, *, root: Optional[Path] = None) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute() and root is not None:
        p = (root / p).resolve()
    else:
        p = p.resolve()
    if not p.is_file():
        raise FileNotFoundError(f"找不到可启动文件: {p}")
    return p


def _quote_win_arg(arg: str) -> str:
    if not arg:
        return '""'
    if any(c in arg for c in (' ', '\t', '"')):
        return '"' + arg.replace('"', '\\"') + '"'
    return arg


def _launch_runas(
    exe: Path,
    cwd: Path,
    args: Sequence[str],
) -> DetachedProcess:
    """ShellExecuteEx W with verb runas; returns pid when possible."""

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_ulong),
            ("fMask", ctypes.c_ulong),
            ("hwnd", ctypes.c_void_p),
            ("lpVerb", ctypes.c_wchar_p),
            ("lpFile", ctypes.c_wchar_p),
            ("lpParameters", ctypes.c_wchar_p),
            ("lpDirectory", ctypes.c_wchar_p),
            ("nShow", ctypes.c_int),
            ("hInstApp", ctypes.c_void_p),
            ("lpIDList", ctypes.c_void_p),
            ("lpClass", ctypes.c_wchar_p),
            ("hkeyClass", ctypes.c_void_p),
            ("dwHotKey", ctypes.c_ulong),
            ("hIconOrMonitor", ctypes.c_void_p),
            ("hProcess", ctypes.c_void_p),
        ]

    params = " ".join(_quote_win_arg(str(a)) for a in args)
    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(SHELLEXECUTEINFOW)
    info.fMask = SEE_MASK_NOCLOSEPROCESS
    info.hwnd = None
    info.lpVerb = "runas"
    info.lpFile = str(exe)
    info.lpParameters = params or None
    info.lpDirectory = str(cwd)
    info.nShow = SW_SHOWNORMAL
    ok = ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info))
    if not ok:
        err = ctypes.GetLastError()
        if err == ERROR_CANCELLED:
            raise RuntimeError("已取消管理员提权（UAC）")
        raise RuntimeError(f"管理员启动失败 (WinError {err})")
    pid = 0
    if info.hProcess:
        pid = int(ctypes.windll.kernel32.GetProcessId(info.hProcess))
        ctypes.windll.kernel32.CloseHandle(info.hProcess)
    if pid <= 0:
        raise RuntimeError("管理员启动成功但未能取得进程 PID")
    return DetachedProcess(pid=pid, path=exe, workdir=cwd, elevated=True)


def launch_detached(
    path: str | Path,
    *,
    workdir: str | Path | None = None,
    args: Sequence[str] | None = None,
    root: Optional[Path] = None,
    as_admin: Optional[bool] = None,
) -> DetachedProcess:
    """Start a GUI/helper process; do not wait for exit or capture stdio.

    On Windows, ``as_admin`` defaults to True (UAC ``runas``). Pass False to skip.
    """
    exe = resolve_launch_path(path, root=root)
    if workdir:
        cwd = Path(workdir).expanduser()
        if not cwd.is_absolute() and root is not None:
            cwd = (root / cwd).resolve()
        else:
            cwd = cwd.resolve()
    else:
        cwd = exe.parent
    if not cwd.is_dir():
        raise NotADirectoryError(f"工作目录不存在: {cwd}")

    arg_list = [str(a) for a in (args or ())]
    elevate = DEFAULT_RUN_AS_ADMIN if as_admin is None else bool(as_admin)
    if os.name == "nt" and elevate:
        return _launch_runas(exe, cwd, arg_list)

    cmd = [str(exe), *arg_list]
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    try:
        p = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
        )
    except OSError as e:
        raise RuntimeError(f"启动失败: {e}") from e
    return DetachedProcess(pid=int(p.pid), path=exe, workdir=cwd, elevated=False)


def wait_settle(seconds: float) -> None:
    time.sleep(max(0.0, float(seconds)))


def hwnd_pid(hwnd: int) -> int:
    """Owner process id for a Win32 HWND (0 if unknown)."""
    if os.name != "nt" or not hwnd:
        return 0
    pid = ctypes.c_ulong(0)
    ctypes.windll.user32.GetWindowThreadProcessId(int(hwnd), ctypes.byref(pid))
    return int(pid.value)


def related_pids(root_pid: int) -> set[int]:
    """Root pid + recursive children (best-effort)."""
    out = {int(root_pid)}
    try:
        proc = psutil.Process(int(root_pid))
        for child in proc.children(recursive=True):
            out.add(int(child.pid))
    except (psutil.Error, ValueError, TypeError):
        pass
    return out


def pick_window_for_launch(
    windows: Sequence[W],
    *,
    launched_pid: int,
    exe_stem: str = "",
    title_filter: str = "",
) -> Optional[W]:
    """Choose the window that belongs to the launched app — never 'first alphabetically'.

    Priority:
    1. HWND owned by launched pid / its children
    2. Title contains exe stem (e.g. ``MAA``)
    3. If title_filter was non-empty and list already filtered → single/best match
    4. Otherwise None (caller should ask user to pick)
    """
    if not windows:
        return None
    related = related_pids(launched_pid)
    by_pid = [w for w in windows if hwnd_pid(int(getattr(w, "hwnd", 0))) in related]
    if by_pid:
        stem = (exe_stem or "").lower()
        if stem:
            named = [w for w in by_pid if stem in (getattr(w, "title", "") or "").lower()]
            if named:
                return named[0]
        return by_pid[0]

    stem = (exe_stem or "").lower()
    if stem:
        named = [w for w in windows if stem in (getattr(w, "title", "") or "").lower()]
        if len(named) == 1:
            return named[0]
        if named:
            # Prefer shorter title (main frame often shorter than splash/tooltips)
            return min(named, key=lambda w: len(getattr(w, "title", "") or ""))

    if title_filter.strip():
        if len(windows) == 1:
            return windows[0]
        # Filtered but ambiguous — still don't guess alphabetically
        if stem:
            named = [w for w in windows if stem in (getattr(w, "title", "") or "").lower()]
            if named:
                return named[0]
        return None

    return None


def normalize_pre_launch(raw: Any) -> list[dict[str, Any]]:
    """Accept list of dicts, or a single path string."""
    if not raw:
        return []
    if isinstance(raw, str):
        p = raw.strip()
        return [{"path": p}] if p else []
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append({"path": item.strip()})
        elif isinstance(item, dict) and str(item.get("path") or "").strip():
            out.append(dict(item))
    return out


def run_pre_launches(
    items: Any,
    *,
    log: Optional[LogFn] = None,
    should_stop: Optional[Callable[[], bool]] = None,
    root: Optional[Path] = None,
) -> list[DetachedProcess]:
    """Launch each pre_launch entry (settle between). Used before script body."""
    base = root if root is not None else ROOT
    launched: list[DetachedProcess] = []
    for i, item in enumerate(normalize_pre_launch(items)):
        if should_stop and should_stop():
            raise RuntimeError("用户手动停止（前置启动未完成）")
        path = str(item.get("path") or "").strip()
        workdir = str(item.get("workdir") or "").strip() or None
        args = item.get("args") or []
        if isinstance(args, str):
            args = [a.strip() for a in args.split(",") if a.strip()]
        settle = float(item.get("settle_sec") or 3)
        if "run_as_admin" in item:
            as_admin: Optional[bool] = bool(item.get("run_as_admin"))
        else:
            as_admin = None  # platform default (Windows: elevate)
        if log:
            log(f"[pre_launch {i + 1}] {path}" + (" (管理员)" if as_admin is not False else ""))
        proc = launch_detached(
            path, workdir=workdir, args=args, root=base, as_admin=as_admin
        )
        launched.append(proc)
        if log:
            elev = " elevated" if proc.elevated else ""
            log(f"[pre_launch {i + 1}] pid={proc.pid}{elev} settle={settle}s")
        wait_settle(settle)
    return launched
