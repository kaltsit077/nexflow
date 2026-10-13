"""核心执行器：拉起子进程、捕获日志、超时、进程树终止、失败策略。"""
from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, TextIO

import psutil

from .catalog import apply_preset
from .config import LOGS_DIR, ROOT
from .maafw import build_maafw_command
from .after_launch import run_after_launch
from .process_launch import (
    DEFAULT_RUN_AS_ADMIN,
    PidProcess,
    launch_detached,
    run_pre_launches,
)


def _python_executable() -> str:
    """When frozen, sys.executable is our .exe — use system Python for .py scripts."""
    if getattr(sys, "frozen", False):
        for name in ("python", "python3", "py"):
            found = shutil.which(name)
            if found:
                return found
        raise FileNotFoundError(
            "Frozen build needs a system Python on PATH to run type=python scripts"
        )
    return sys.executable


def _resolve_script_path(path: str) -> str:
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    return str(p)


# 脚本类型 -> 如何拼装启动命令；maafw 额外返回 cwd
def _build_command(script: dict[str, Any]) -> tuple[list[str], Optional[str]]:
    stype = script["type"].lower()
    args = list(script.get("args", []))

    if stype == "maafw":
        cmd, cwd = build_maafw_command(script)
        return cmd, cwd

    path = _resolve_script_path(script["path"])
    if stype == "python":
        return [_python_executable(), path, *args], None
    if stype == "exe":
        return [path, *args], None
    if stype == "bat":
        return ["cmd", "/c", path, *args], None
    if stype == "cmd":
        return [path, *args], None
    if stype == "powershell":
        return ["powershell", "-ExecutionPolicy", "Bypass", "-File", path, *args], None
    if stype == "ahk":
        return ["AutoHotkey.exe", path, *args], None
    raise ValueError(f"未知脚本类型: {stype}")


def _resolve_workdir(workdir: str, override: Optional[str] = None) -> Optional[str]:
    if override:
        return override
    if not workdir:
        return None
    p = Path(workdir)
    if not p.is_absolute():
        p = ROOT / p
    return str(p)


def _pump_stdout(pipe: TextIO, out_q: queue.Queue, stop_evt: threading.Event) -> None:
    """Read process stdout without blocking the timeout/stop loop."""
    try:
        while not stop_evt.is_set():
            line = pipe.readline()
            if line == "":
                break
            out_q.put(line)
    except Exception:
        pass
    finally:
        out_q.put(None)


def _kill_process_tree(pid: int) -> None:
    """终止进程及其所有子进程。"""
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    children = parent.children(recursive=True)
    for child in children:
        try:
            child.kill()
        except psutil.NoSuchProcess:
            pass
    try:
        parent.kill()
    except psutil.NoSuchProcess:
        pass
    gone, alive = psutil.wait_procs(children + [parent], timeout=3)
    for p in alive:
        try:
            p.kill()
        except psutil.NoSuchProcess:
            pass


@dataclass
class StepResult:
    script_id: str
    success: bool
    exit_code: int
    log_path: str
    duration_sec: float
    error: str = ""


@dataclass
class RunnerCallbacks:
    """UI / CLI 注入的回调。全部可选。"""
    on_status: Callable[[str, str], None] = field(default=lambda sid, status: None)
    # sid, line
    on_output: Callable[[str, str], None] = field(default=lambda sid, line: None)
    on_step_done: Callable[[StepResult], None] = field(default=lambda r: None)


class _StopFlag:
    def __init__(self) -> None:
        self._stop = False

    def request(self) -> None:
        self._stop = True

    @property
    def requested(self) -> bool:
        return self._stop


def run_single_script(
    script: dict[str, Any],
    callbacks: Optional[RunnerCallbacks] = None,
    stop_flag: Optional[_StopFlag] = None,
    preset_id: Optional[str] = None,
) -> StepResult:
    """运行单个脚本，阻塞直到结束/超时/被停止。"""
    callbacks = callbacks or RunnerCallbacks()
    stop_flag = stop_flag or _StopFlag()
    script = apply_preset(script, preset_id)
    sid = script["id"]
    timeout = script.get("timeout_sec") or 3600
    wait_mode = str(script.get("wait_mode") or "wait_exit").lower()
    if wait_mode not in ("wait_exit", "launch", "launch_wait"):
        wait_mode = "wait_exit"
    settle_sec = float(script.get("launch_settle_sec") or 3)
    cleanup = str(script.get("cleanup") or "self").lower()
    if cleanup not in ("none", "self", "self+pre"):
        cleanup = "self"

    log_path = LOGS_DIR / f"{sid}_{int(time.time())}.log"
    callbacks.on_status(sid, "running")
    start = time.time()
    exit_code: int = -999
    error = ""
    pre_pids: list[int] = []

    log_f = open(log_path, "w", encoding="utf-8", errors="replace")

    def _emit(line: str) -> None:
        log_f.write(line + "\n")
        log_f.flush()
        callbacks.on_output(sid, line)

    try:
        if script.get("pre_launch"):
            launched_pre = run_pre_launches(
                script.get("pre_launch"),
                log=_emit,
                should_stop=lambda: stop_flag.requested,
                root=ROOT,
            )
            pre_pids = [int(d.pid) for d in launched_pre]
        cmd, cwd_override = _build_command(script)
        cwd = _resolve_workdir(script.get("workdir", ""), cwd_override)
    except (FileNotFoundError, ValueError, OSError, RuntimeError, NotADirectoryError) as e:
        error = str(e)
        log_f.write(error + "\n")
        log_f.close()
        callbacks.on_status(sid, "failed")
        return StepResult(sid, False, -1, str(log_path), time.time() - start, error)

    stype = str(script.get("type") or "").lower()
    # exe GUI helpers (MAA 等) 默认管理员；maafw/python 等仍走普通子进程以便抓日志。
    if "run_as_admin" in script:
        want_admin = bool(script.get("run_as_admin"))
    else:
        want_admin = bool(DEFAULT_RUN_AS_ADMIN and stype == "exe")
    use_elevated = os.name == "nt" and want_admin and stype == "exe"

    log_f.write(f"$ {' '.join(cmd)}\n")
    log_f.write(f"cwd={cwd}\n")
    log_f.write(f"wait_mode={wait_mode} cleanup={cleanup}\n")
    if use_elevated:
        log_f.write("run_as_admin=1 (ShellExecute runas)\n")
    log_f.write("\n")
    log_f.flush()

    p: Any
    try:
        if use_elevated:
            det = launch_detached(
                cmd[0],
                workdir=cwd,
                args=cmd[1:],
                root=ROOT,
                as_admin=True,
            )
            p = PidProcess(det.pid)
            _emit(f"[Game Runner] 已管理员启动 pid={det.pid}")
        else:
            # Windows 下 CREATE_NEW_PROCESS_GROUP 便于 Ctrl+C / kill
            creationflags = 0
            if os.name == "nt":
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]

            p = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
            )
    except FileNotFoundError as e:
        error = f"找不到可执行文件: {e}"
        log_f.write(error + "\n")
        log_f.close()
        callbacks.on_status(sid, "failed")
        return StepResult(sid, False, -1, str(log_path), time.time() - start, error)
    except RuntimeError as e:
        error = str(e)
        log_f.write(error + "\n")
        log_f.close()
        callbacks.on_status(sid, "failed")
        return StepResult(sid, False, -1, str(log_path), time.time() - start, error)

    # Drain stdout when present; elevated GUI launches have no pipe.
    timed_out = False
    launched_ok = False
    launch_wait_done = False
    line_q: queue.Queue = queue.Queue()
    pump_stop = threading.Event()
    if p.stdout is not None:
        pump = threading.Thread(
            target=_pump_stdout, args=(p.stdout, line_q, pump_stop), daemon=True
        )
        pump.start()
    else:
        # No stdout: synthetic EOF after first empty poll cycle via sentinel None later
        line_q.put(None)

    def _drain_line() -> Optional[str]:
        try:
            line = line_q.get(timeout=0.2)
        except queue.Empty:
            return ""
        if line is None:
            return None
        if line:
            log_f.write(line)
            log_f.flush()
            callbacks.on_output(sid, line.rstrip("\n"))
        return line

    def _run_after_launch_phase() -> bool:
        """Return True if after_launch ok (or none)."""
        if not script.get("after_launch") or stop_flag.requested:
            return True
        try:
            run_after_launch(
                script.get("after_launch"),
                log=_emit,
                should_stop=lambda: stop_flag.requested,
                launched_pid=int(p.pid),
                exe_stem=Path(str(script.get("path") or "")).stem,
            )
            return True
        except Exception as e:  # noqa: BLE001
            nonlocal error
            error = str(e)
            _emit(error)
            return False

    try:
        deadline = start + timeout
        settle_until = start + settle_sec
        settled = False
        while True:
            if stop_flag.requested:
                _kill_process_tree(p.pid)
                try:
                    p.wait(timeout=8)
                except Exception:  # noqa: BLE001
                    pass
                error = "用户手动停止"
                break
            line = _drain_line()
            if line is None and p.stdout is not None:
                # Pipe EOF for non-elevated: process likely exiting
                p.poll()
                if wait_mode == "launch" and not settled:
                    break
                if wait_mode != "launch":
                    break
            code = p.poll()
            now = time.time()
            if now > deadline:
                timed_out = True
                _kill_process_tree(p.pid)
                try:
                    p.wait(timeout=8)
                except Exception:  # noqa: BLE001
                    pass
                error = f"超时 ({timeout}s)"
                break

            if wait_mode == "wait_exit":
                if code is not None:
                    break
                continue

            # launch / launch_wait: wait settle first
            if not settled:
                if code is not None:
                    break
                if now >= settle_until:
                    settled = True
                    if wait_mode == "launch":
                        launched_ok = True
                        _emit(
                            f"[Game Runner] wait_mode=launch: settled {settle_sec}s; "
                            f"left running (pid={p.pid})"
                        )
                        if not _run_after_launch_phase():
                            launched_ok = False
                        break
                    # launch_wait: after_launch then keep waiting for exit
                    _emit(
                        f"[Game Runner] wait_mode=launch_wait: settled {settle_sec}s; "
                        f"after_launch then wait exit (pid={p.pid})"
                    )
                    if not _run_after_launch_phase():
                        break
                    continue
                continue

            # launch_wait post-settle: wait until process exits
            if code is not None:
                launch_wait_done = True
                break
        pump_stop.set()
        if launched_ok:
            exit_code = 0 if not error else -1
        elif launch_wait_done or wait_mode == "wait_exit" or (
            wait_mode == "launch_wait" and p.poll() is not None and not error
        ):
            if p.returncode is None:
                try:
                    p.wait(timeout=5)
                except Exception:  # noqa: BLE001
                    p.poll()
            exit_code = p.returncode if p.returncode is not None else -1
            if wait_mode == "launch_wait" and exit_code == 0 and not error:
                launch_wait_done = True
        else:
            if p.returncode is None:
                try:
                    p.wait(timeout=5)
                except Exception:  # noqa: BLE001
                    p.poll()
            exit_code = p.returncode if p.returncode is not None else -1
    finally:
        pump_stop.set()
        log_f.close()

    success = (
        (launched_ok or launch_wait_done or (exit_code == 0 and wait_mode == "wait_exit"))
        and not timed_out
        and not stop_flag.requested
        and not error
    )
    # launch_wait: success only if process exited cleanly after after_launch
    if wait_mode == "launch_wait":
        success = (
            launch_wait_done
            and exit_code == 0
            and not timed_out
            and not stop_flag.requested
            and not error
        )

    if success and wait_mode != "launch" and cleanup != "none":
        _cleanup_after_success(
            cleanup=cleanup,
            main_pid=int(p.pid),
            pre_pids=pre_pids,
            log=callbacks.on_output,
            sid=sid,
        )

    status = "success" if success else "failed"
    callbacks.on_status(sid, status)
    result = StepResult(
        script_id=sid,
        success=success,
        exit_code=exit_code,
        log_path=str(log_path),
        duration_sec=round(time.time() - start, 2),
        error=error,
    )
    callbacks.on_step_done(result)
    return result


def _cleanup_after_success(
    *,
    cleanup: str,
    main_pid: int,
    pre_pids: list[int],
    log: Callable[[str, str], None],
    sid: str,
) -> None:
    """Kill remaining processes after a successful non-launch step."""
    targets: list[int] = []
    if cleanup in ("self", "self+pre"):
        targets.append(main_pid)
    if cleanup == "self+pre":
        targets.extend(pre_pids)
    seen: set[int] = set()
    for pid in targets:
        if pid in seen or pid <= 0:
            continue
        seen.add(pid)
        try:
            if psutil.pid_exists(pid):
                log(sid, f"cleanup: kill pid={pid}")
                _kill_process_tree(pid)
        except (psutil.Error, ValueError, TypeError, OSError):
            pass


def _resolve_lane(step: dict[str, Any], script: Optional[dict[str, Any]]) -> str:
    raw = step.get("lane")
    if raw is None or str(raw).strip() == "":
        raw = (script or {}).get("lane")
    lane = str(raw or "default").strip()
    return lane or "default"


def _clamp_max_parallel(value: Any) -> int:
    try:
        n = int(value if value is not None else 2)
    except (TypeError, ValueError):
        n = 2
    return max(1, min(8, n))


def _run_one_step(
    step: dict[str, Any],
    scripts: dict[str, dict[str, Any]],
    callbacks: RunnerCallbacks,
    stop_flag: _StopFlag,
) -> tuple[bool, bool, list[StepResult]]:
    """跑队列中一步（含 retry / fallback）。

    返回 (step_ok, should_stop_scheduling, 本步产生的 StepResult 列表)。
    should_stop_scheduling：on_fail=stop 或用户停止；并行时不杀已跑步。
    """
    sid = step["script"]
    results: list[StepResult] = []
    if sid not in scripts:
        callbacks.on_status(sid, "failed")
        results.append(StepResult(sid, False, -1, "", 0, "脚本未注册"))
        on_fail = step.get("on_fail", "stop")
        should_stop = on_fail == "stop" or stop_flag.requested
        return False, should_stop, results

    on_fail = step.get("on_fail", "stop")
    retry = int(step.get("retry", 0))
    preset_id = step.get("preset") or None
    fallback = step.get("fallback_script") or None

    attempt = 0
    last: Optional[StepResult] = None
    while attempt <= retry:
        if stop_flag.requested:
            break
        spec = dict(scripts[sid])
        if step.get("wait_mode"):
            spec["wait_mode"] = step["wait_mode"]
        last = run_single_script(spec, callbacks, stop_flag, preset_id)
        results.append(last)
        if last.success:
            break
        attempt += 1
        if attempt <= retry:
            callbacks.on_status(sid, f"retry({attempt})")

    if last is not None and not last.success and fallback and not stop_flag.requested:
        if fallback in scripts:
            callbacks.on_status(fallback, "fallback")
            fb = run_single_script(scripts[fallback], callbacks, stop_flag)
            results.append(fb)
            last = fb
        else:
            results.append(
                StepResult(str(fallback), False, -1, "", 0, "fallback 脚本未注册")
            )

    step_ok = bool(last and last.success)
    should_stop = (not step_ok and on_fail == "stop") or stop_flag.requested
    return step_ok, should_stop, results


def _run_list_sequential(
    steps: list[dict[str, Any]],
    scripts: dict[str, dict[str, Any]],
    callbacks: RunnerCallbacks,
    stop_flag: _StopFlag,
) -> tuple[bool, list[StepResult]]:
    results: list[StepResult] = []
    step_ok_flags: list[bool] = []
    for step in steps:
        if stop_flag.requested:
            break
        step_ok, should_stop, step_results = _run_one_step(
            step, scripts, callbacks, stop_flag
        )
        results.extend(step_results)
        step_ok_flags.append(step_ok)
        if should_stop:
            break
    overall = bool(step_ok_flags) and all(step_ok_flags)
    return overall, results


def _run_list_parallel(
    steps: list[dict[str, Any]],
    scripts: dict[str, dict[str, Any]],
    callbacks: RunnerCallbacks,
    stop_flag: _StopFlag,
    max_parallel: int,
) -> tuple[bool, list[StepResult]]:
    """有限并行：同 lane 互斥；从前到后扫描，启动所有不冲突且未满槽的步。"""
    n = len(steps)
    if n == 0:
        return False, []

    lock = threading.Lock()
    results: list[StepResult] = []
    step_ok_flags: list[Optional[bool]] = [None] * n
    done = [False] * n
    started = [False] * n
    active_lanes: dict[str, int] = {}
    halt_new = False  # on_fail=stop / 用户停：不再启新步，已跑步自行结束
    futures: dict[int, Future] = {}

    def lane_of(i: int) -> str:
        step = steps[i]
        sid = step.get("script", "")
        return _resolve_lane(step, scripts.get(sid))

    def _worker(idx: int) -> tuple[int, bool, bool, list[StepResult]]:
        step_ok, should_stop, step_results = _run_one_step(
            steps[idx], scripts, callbacks, stop_flag
        )
        return idx, step_ok, should_stop, step_results

    with ThreadPoolExecutor(max_workers=max_parallel) as pool:
        while not all(done):
            with lock:
                if stop_flag.requested:
                    halt_new = True
                pending_start: list[int] = []
                if not halt_new:
                    active_count = sum(1 for i in range(n) if started[i] and not done[i])
                    for i in range(n):
                        if done[i] or started[i]:
                            continue
                        lane = lane_of(i)
                        if active_lanes.get(lane, 0) > 0:
                            continue
                        if active_count >= max_parallel:
                            break
                        active_lanes[lane] = active_lanes.get(lane, 0) + 1
                        active_count += 1
                        started[i] = True
                        pending_start.append(i)

                for i in pending_start:
                    futures[i] = pool.submit(_worker, i)

                in_flight = [futures[i] for i in range(n) if started[i] and not done[i]]

            if not in_flight:
                # 无在跑：要么全完成，要么 halt 后留下未起步
                break

            done_set, _ = wait(in_flight, return_when=FIRST_COMPLETED)
            for fut in done_set:
                idx, step_ok, should_stop, step_results = fut.result()
                with lock:
                    if done[idx]:
                        continue
                    results.extend(step_results)
                    step_ok_flags[idx] = step_ok
                    done[idx] = True
                    lane = lane_of(idx)
                    active_lanes[lane] = max(0, active_lanes.get(lane, 1) - 1)
                    if active_lanes.get(lane, 0) == 0:
                        active_lanes.pop(lane, None)
                    if should_stop:
                        halt_new = True

    finished = [ok for ok in step_ok_flags if ok is not None]
    overall = bool(finished) and all(finished)
    return overall, results


def run_list(
    cfg: dict[str, Any],
    list_name: str,
    callbacks: Optional[RunnerCallbacks] = None,
    stop_flag: Optional[_StopFlag] = None,
) -> tuple[bool, list[StepResult]]:
    """运行一个任务列表。返回 (整体是否成功, 每步结果)。"""
    callbacks = callbacks or RunnerCallbacks()
    lists = {l["name"]: l for l in cfg["lists"]}
    if list_name not in lists:
        raise KeyError(f"列表不存在: {list_name}")
    target = lists[list_name]
    scripts = {s["id"]: s for s in cfg["scripts"]}

    stop_flag = stop_flag or _StopFlag()
    mode = str(target.get("mode") or "sequential").lower()
    steps = list(target.get("steps") or [])

    if mode == "parallel":
        max_parallel = _clamp_max_parallel(target.get("max_parallel"))
        return _run_list_parallel(
            steps, scripts, callbacks, stop_flag, max_parallel
        )
    return _run_list_sequential(steps, scripts, callbacks, stop_flag)


def make_stop_flag() -> _StopFlag:
    return _StopFlag()
