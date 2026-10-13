"""After launching a GUI helper: find window and post click(s) (e.g. MAA UI)."""
from __future__ import annotations

import re
import time
from typing import Any, Callable, Optional

from .maa_runtime import MaaSession, ensure_library, list_windows, resolve_bin_dir
from .process_launch import pick_window_for_launch

LogFn = Callable[[str], None]


def _step_from_raw(raw: dict[str, Any], *, default_window: str = "") -> Optional[dict[str, Any]]:
    try:
        x = int(raw.get("x"))
        y = int(raw.get("y"))
    except (TypeError, ValueError):
        return None
    win = str(raw.get("window_regex") or raw.get("window") or default_window or "").strip()
    if not win:
        return None
    name = str(raw.get("name") or raw.get("label") or "").strip()
    group = str(raw.get("group") or "").strip()
    out = {
        "window_regex": win,
        "x": x,
        "y": y,
        "delay_sec": float(raw.get("delay_sec") or 0),
        "name": name or f"点击 ({x},{y})",
    }
    if group:
        out["group"] = group
    return out


def normalize_after_launch(raw: Any) -> Optional[dict[str, Any]]:
    """Normalize to ``{window_regex, timeout_sec, screencap, mouse, steps:[...]}``.

    Accepts legacy single-click dict ``{window_regex,x,y,delay_sec}`` or
    multi-step ``{window_regex?, steps:[{x,y,delay_sec?,name?}, ...]}``.
    """
    if not raw:
        return None
    if not isinstance(raw, dict):
        return None

    default_win = str(raw.get("window_regex") or raw.get("window") or "").strip()
    steps_raw = raw.get("steps")
    steps: list[dict[str, Any]] = []
    if isinstance(steps_raw, list) and steps_raw:
        for item in steps_raw:
            if isinstance(item, dict):
                st = _step_from_raw(item, default_window=default_win)
                if st:
                    steps.append(st)
    else:
        # Legacy single click: top-level delay_sec = wait before find window
        st = _step_from_raw(raw, default_window=default_win)
        if st:
            st["delay_sec"] = 0.0
            steps.append(st)

    if not steps:
        return None
    if not default_win:
        default_win = str(steps[0].get("window_regex") or "").strip()
    if not default_win:
        return None

    return {
        "window_regex": default_win,
        "timeout_sec": float(raw.get("timeout_sec") or 30),
        "screencap": str(raw.get("screencap") or "PrintWindow"),
        "mouse": str(raw.get("mouse") or "PostMessageWithWindowPos"),
        "delay_sec": float(raw.get("delay_sec") or 2),
        "steps": steps,
    }


def after_launch_to_storage(spec: dict[str, Any]) -> dict[str, Any]:
    """Compact form for config.json (always steps[] for editor round-trip)."""
    steps = list(spec.get("steps") or [])
    win = str(spec.get("window_regex") or "").strip()
    return {
        "window_regex": win or (steps[0].get("window_regex") if steps else ""),
        "timeout_sec": float(spec.get("timeout_sec") or 30),
        "delay_sec": float(spec.get("delay_sec") or 2),
        "steps": [
            {
                "name": st.get("name") or f"点击 ({st['x']},{st['y']})",
                "x": int(st["x"]),
                "y": int(st["y"]),
                "delay_sec": float(st.get("delay_sec") or 0),
                **(
                    {"window_regex": st["window_regex"]}
                    if st.get("window_regex") and st.get("window_regex") != win
                    else {}
                ),
                **({"group": st["group"]} if str(st.get("group") or "").strip() else {}),
            }
            for st in steps
        ],
    }


def _find_hwnd(
    pattern: str,
    *,
    launched_pid: int,
    exe_stem: str,
    timeout_sec: float,
    should_stop: Optional[Callable[[], bool]],
    log: LogFn,
) -> tuple[int, str]:
    deadline = time.time() + max(3.0, timeout_sec)
    last_names = ""
    while time.time() < deadline:
        if should_stop and should_stop():
            raise RuntimeError("用户手动停止（启动后点击未完成）")

        wins = list_windows(pattern)
        picked = pick_window_for_launch(
            wins,
            launched_pid=int(launched_pid or 0),
            exe_stem=exe_stem,
            title_filter=pattern,
        )
        if picked is None and len(wins) == 1:
            picked = wins[0]
        if picked is None and len(wins) > 1:
            try:
                rx = re.compile(pattern, re.I)
                full = [w for w in wins if rx.fullmatch(w.title or "")]
            except re.error:
                full = []
            if len(full) == 1:
                picked = full[0]

        if picked is None and launched_pid:
            all_wins = list_windows("")
            picked = pick_window_for_launch(
                all_wins,
                launched_pid=int(launched_pid),
                exe_stem=exe_stem,
                title_filter="",
            )

        if picked is not None:
            return int(picked.hwnd), str(picked.title or "")

        if wins:
            last_names = ", ".join((w.title or "?")[:40] for w in wins[:8])
        time.sleep(0.5)

    hint = f" 候选: {last_names}" if last_names else ""
    raise RuntimeError(
        f"[after_launch] 未找到窗口（过滤/正则: {pattern!r}，pid={launched_pid}）。"
        f"{hint}"
        "请在编辑页 ② 助手连控里重新取点，或加大启动安定/启动后延迟。"
    )


def run_after_launch(
    raw: Any,
    *,
    log: Optional[LogFn] = None,
    should_stop: Optional[Callable[[], bool]] = None,
    launched_pid: int = 0,
    exe_stem: str = "",
) -> None:
    """Wait for matching window, connect Win32, run click steps in order."""
    spec = normalize_after_launch(raw)
    if not spec:
        return

    def _log(msg: str) -> None:
        if log:
            log(msg)

    delay = max(0.0, float(spec.get("delay_sec") or 0))
    if delay:
        _log(f"[after_launch] wait {delay}s before find window")
        end = time.time() + delay
        while time.time() < end:
            if should_stop and should_stop():
                raise RuntimeError("用户手动停止（启动后点击未完成）")
            time.sleep(0.2)

    ensure_library(resolve_bin_dir())
    steps = list(spec["steps"])
    default_win = spec["window_regex"]
    session = MaaSession(log=_log)
    connected_hwnd: Optional[int] = None
    try:
        for i, st in enumerate(steps):
            if should_stop and should_stop():
                raise RuntimeError("用户手动停止（启动后点击未完成）")
            step_delay = max(0.0, float(st.get("delay_sec") or 0))
            if i > 0 and step_delay:
                _log(f"[after_launch] step {i + 1} wait {step_delay}s")
                end = time.time() + step_delay
                while time.time() < end:
                    if should_stop and should_stop():
                        raise RuntimeError("用户手动停止（启动后点击未完成）")
                    time.sleep(0.1)
            pattern = str(st.get("window_regex") or default_win)
            hwnd, title = _find_hwnd(
                pattern,
                launched_pid=launched_pid,
                exe_stem=exe_stem,
                timeout_sec=float(spec["timeout_sec"]),
                should_stop=should_stop,
                log=_log,
            )
            if connected_hwnd != hwnd:
                if connected_hwnd is not None:
                    try:
                        session.disconnect()
                    except Exception:  # noqa: BLE001
                        pass
                session.connect_win32(
                    int(hwnd),
                    screencap=spec["screencap"],
                    mouse=spec["mouse"],
                    keyboard=spec["mouse"],
                )
                connected_hwnd = hwnd
            _log(
                f"[after_launch] step {i + 1}/{len(steps)} "
                f"{st.get('name')!r} window={title!r} click=({st['x']},{st['y']})"
            )
            session.click(int(st["x"]), int(st["y"]))
        _log(f"[after_launch] done ({len(steps)} steps)")
    finally:
        try:
            session.disconnect()
        except Exception:  # noqa: BLE001
            pass
