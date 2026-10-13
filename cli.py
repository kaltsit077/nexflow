"""命令行入口：
    python cli.py list                 # 列出所有脚本和任务列表
    python cli.py run-script <id>      # 运行单个脚本
    python cli.py run-list <name>      # 运行一个任务列表
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

from runner import (
    RunnerCallbacks,
    append_history,
    load_config,
    run_list,
    run_single_script,
)


def _cb() -> RunnerCallbacks:
    def on_status(sid: str, status: str) -> None:
        print(f"[{datetime.now():%H:%M:%S}] {sid} -> {status}", flush=True)

    def on_output(sid: str, line: str) -> None:
        print(f"  {sid} | {line}", flush=True)

    def on_step_done(result) -> None:
        print(
            f"  done: exit={result.exit_code}  {result.duration_sec}s  "
            f"log={result.log_path}  err={result.error}",
            flush=True,
        )

    return RunnerCallbacks(on_status=on_status, on_output=on_output, on_step_done=on_step_done)


def cmd_list(_args) -> int:
    cfg = load_config()
    print("== 脚本 ==")
    for s in cfg["scripts"]:
        print(f"  [{s['id']}] {s['name']}  ({s['type']})")
    print("== 任务列表 ==")
    for lst in cfg["lists"]:
        steps = " -> ".join(f"{x['script']}({x.get('on_fail','stop')})" for x in lst["steps"])
        print(f"  - {lst['name']} [{lst.get('mode','sequential')}]: {steps}")
    return 0


def cmd_run_script(args) -> int:
    cfg = load_config()
    scripts = {s["id"]: s for s in cfg["scripts"]}
    if args.id not in scripts:
        print(f"找不到脚本: {args.id}", file=sys.stderr)
        return 2
    r = run_single_script(scripts[args.id], _cb())
    append_history({
        "when": datetime.now().isoformat(timespec="seconds"),
        "kind": "script",
        "name": r.script_id,
        "success": r.success,
        "exit_code": r.exit_code,
        "duration_sec": r.duration_sec,
        "log": r.log_path,
        "error": r.error,
    })
    return 0 if r.success else 1


def cmd_run_list(args) -> int:
    cfg = load_config()
    ok, results = run_list(cfg, args.name, _cb())
    for r in results:
        append_history({
            "when": datetime.now().isoformat(timespec="seconds"),
            "kind": "list",
            "name": r.script_id,
            "success": r.success,
            "exit_code": r.exit_code,
            "duration_sec": r.duration_sec,
            "log": r.log_path,
            "error": r.error,
        })
    print(f"== 整体{'成功' if ok else '失败'} ==")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="game-runner")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="列出脚本和列表").set_defaults(func=cmd_list)

    p_rs = sub.add_parser("run-script", help="运行单个脚本")
    p_rs.add_argument("id")
    p_rs.set_defaults(func=cmd_run_script)

    p_rl = sub.add_parser("run-list", help="运行一个任务列表")
    p_rl.add_argument("name")
    p_rl.set_defaults(func=cmd_run_list)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
