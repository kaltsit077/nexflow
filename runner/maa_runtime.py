"""In-process MaaFramework runtime (same path as MXU: Toolkit + Controller + Tasker)."""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np

from .config import LOGS_DIR, ROOT
from .maafw import DEFAULT_BIN_DIR, resolve_maapicli

# Lazy imports so CLI-only users without MaaFw still load the package.


@dataclass
class WinInfo:
    hwnd: int
    title: str
    class_name: str

    def label(self) -> str:
        t = self.title if len(self.title) <= 56 else self.title[:53] + "..."
        return f"{t}  [{self.class_name}]"


@dataclass
class AdbInfo:
    name: str
    adb_path: str
    address: str
    screencap_methods: int
    input_methods: int
    config: dict[str, Any]

    def label(self) -> str:
        return f"{self.name}  ({self.address})"


@dataclass
class PiController:
    name: str
    label: str
    type: str
    raw: dict[str, Any]


@dataclass
class PiTask:
    name: str
    label: str
    entry: str
    description: str = ""


@dataclass
class PiProject:
    root: Path
    name: str
    controllers: list[PiController]
    resources: list[tuple[str, list[Path]]]  # (name, paths)
    tasks: list[PiTask]


@dataclass
class BoxHit:
    name: str
    box: tuple[int, int, int, int]  # x,y,w,h
    hit: bool = True


LogFn = Callable[[str], None]
BoxesFn = Callable[[list[BoxHit]], None]


WIN32_SCREENCAP = {
    "FramePool": "FramePool",
    "PrintWindow": "PrintWindow",
    "DXGI_DesktopDup": "DXGI_DesktopDup",
    "DXGI_DesktopDup_Window": "DXGI_DesktopDup_Window",
    "ScreenDC": "ScreenDC",
    "Background": "Background",  # FramePool | PrintWindow
    "Foreground": "Foreground",  # DXGI window | ScreenDC
}

WIN32_INPUT = {
    "Seize": "Seize",
    "SendMessage": "SendMessage",
    "PostMessage": "PostMessage",
    # Align with MAA PC: PostMsg-WindowPos + PrintWindow for background helpers
    "PostMessageWithWindowPos": "PostMessageWithWindowPos",
    "SendMessageWithWindowPos": "SendMessageWithWindowPos",
    "SendMessageWithCursorPos": "SendMessageWithCursorPos",
    "PostMessageWithCursorPos": "PostMessageWithCursorPos",
    "LegacyEvent": "LegacyEvent",
}


def resolve_bin_dir(script: Optional[dict[str, Any]] = None) -> Path:
    """Directory containing MaaFramework.dll (same search order as MaaPiCli)."""
    try:
        cli = resolve_maapicli(script)
        return cli.parent
    except FileNotFoundError:
        if DEFAULT_BIN_DIR.is_dir():
            return DEFAULT_BIN_DIR.resolve()
        raise


_lib_lock = threading.Lock()
_lib_opened: Optional[Path] = None


def ensure_library(bin_dir: Optional[Path] = None) -> Path:
    global _lib_opened
    from maa.library import Library
    from maa.toolkit import Toolkit

    path = (bin_dir or resolve_bin_dir()).resolve()
    with _lib_lock:
        if _lib_opened is None:
            if not (path / "MaaFramework.dll").is_file():
                raise FileNotFoundError(
                    f"MaaFramework.dll missing in {path}. Run tools\\setup_maafw.bat "
                    "(needs release matching pip MaaFw)."
                )
            Library.open(path)
            user = LOGS_DIR / "maa_runtime"
            user.mkdir(parents=True, exist_ok=True)
            Toolkit.init_option(user)
            _lib_opened = path
        elif _lib_opened != path:
            raise RuntimeError(
                f"MaaFW already loaded from {_lib_opened}; cannot switch to {path} "
                "in this process. Restart Game Runner to use another bin folder."
            )
    return _lib_opened


def _enum(mod_name: str, attr: str, key: str) -> int:
    from maa import define

    enum_cls = getattr(define, attr)
    return int(getattr(enum_cls, key))


def list_windows(title_filter: str = "") -> list[WinInfo]:
    ensure_library()
    from maa.toolkit import Toolkit
    import re

    filt = title_filter.strip()
    try:
        rx = re.compile(filt, re.I) if filt else None
    except re.error:
        rx = None
        needle = filt.lower()
    else:
        needle = None

    out: list[WinInfo] = []
    for w in Toolkit.find_desktop_windows():
        title = (w.window_name or "").strip()
        if not title:
            continue
        if rx is not None:
            if not rx.search(title):
                continue
        elif needle is not None and needle not in title.lower():
            continue
        hwnd = int(w.hwnd) if w.hwnd else 0
        if not hwnd:
            continue
        out.append(WinInfo(hwnd=hwnd, title=title, class_name=w.class_name or ""))
    out.sort(key=lambda x: x.title.lower())
    return out


def list_adb_devices() -> list[AdbInfo]:
    ensure_library()
    from maa.toolkit import Toolkit

    out: list[AdbInfo] = []
    for d in Toolkit.find_adb_devices():
        out.append(
            AdbInfo(
                name=d.name,
                adb_path=str(d.adb_path),
                address=d.address,
                screencap_methods=int(d.screencap_methods),
                input_methods=int(d.input_methods),
                config=dict(d.config or {}),
            )
        )
    return out


def load_pi_project(path: str | Path) -> PiProject:
    root = Path(path)
    if root.is_file():
        root = root.parent
    iface = root / "interface.json"
    if not iface.is_file():
        raise FileNotFoundError(f"interface.json not found: {iface}")
    data = json.loads(iface.read_text(encoding="utf-8"))

    controllers = [
        PiController(
            name=c.get("name", ""),
            label=str(c.get("label") or c.get("name") or ""),
            type=str(c.get("type") or ""),
            raw=c,
        )
        for c in data.get("controller") or []
    ]
    resources: list[tuple[str, list[Path]]] = []
    for r in data.get("resource") or []:
        paths = []
        for p in r.get("path") or []:
            pp = Path(p)
            if not pp.is_absolute():
                pp = (root / pp).resolve()
            paths.append(pp)
        resources.append((str(r.get("name") or "Default"), paths))
    tasks = [
        PiTask(
            name=t.get("name", ""),
            label=str(t.get("label") or t.get("name") or ""),
            entry=str(t.get("entry") or t.get("name") or ""),
            description=str(t.get("description") or ""),
        )
        for t in data.get("task") or []
    ]
    return PiProject(
        root=root.resolve(),
        name=str(data.get("name") or root.name),
        controllers=controllers,
        resources=resources,
        tasks=tasks,
    )


class MaaSession:
    """One connected controller + optional resource/tasker (studio session)."""

    def __init__(self, log: Optional[LogFn] = None, on_boxes: Optional[BoxesFn] = None):
        self._log = log or (lambda _m: None)
        self._on_boxes = on_boxes or (lambda _b: None)
        self.controller = None
        self.resource = None
        self.tasker = None
        self.project: Optional[PiProject] = None
        self.connected = False
        self.hwnd: Optional[int] = None
        self._ctx_sink_id: Optional[int] = None
        self._task_sink_id: Optional[int] = None
        self._lock = threading.RLock()
        self._latest_boxes: list[BoxHit] = []

    def _emit(self, msg: str) -> None:
        self._log(msg)

    def _reset_locked(self) -> None:
        """Caller must hold self._lock. Drop Python refs and best-effort native teardown."""
        tasker = self.tasker
        ctrl = self.controller
        if tasker is not None:
            try:
                if getattr(tasker, "running", False) or getattr(tasker, "stopping", False):
                    tasker.post_stop()
            except Exception:  # noqa: BLE001
                pass
        self.tasker = None
        self.resource = None
        self.controller = None
        self.connected = False
        self.hwnd = None
        self._latest_boxes = []
        self._ctx_sink_id = None
        self._task_sink_id = None
        # Prefer explicit disconnect if the binding exposes it; ignore missing APIs.
        if ctrl is not None:
            for name in ("post_disconnect", "disconnect", "destroy"):
                fn = getattr(ctrl, name, None)
                if not callable(fn):
                    continue
                try:
                    fn()
                except Exception:  # noqa: BLE001
                    pass
                break

    def disconnect(self) -> None:
        with self._lock:
            self._reset_locked()
            self._emit("已断开控制器")

    def connect_win32(
        self,
        hwnd: int,
        screencap: str = "Background",
        mouse: str = "Seize",
        keyboard: str = "Seize",
    ) -> None:
        ensure_library()
        from maa.controller import Win32Controller

        sc = _enum("define", "MaaWin32ScreencapMethodEnum", WIN32_SCREENCAP.get(screencap, screencap))
        mouse_m = _enum("define", "MaaWin32InputMethodEnum", WIN32_INPUT.get(mouse, mouse))
        key_m = _enum("define", "MaaWin32InputMethodEnum", WIN32_INPUT.get(keyboard, keyboard))

        with self._lock:
            self._reset_locked()
            ctrl = Win32Controller(
                hWnd=hwnd,
                screencap_method=sc,
                mouse_method=mouse_m,
                keyboard_method=key_m,
            )
            job = ctrl.post_connection().wait()
            if not job.succeeded:
                raise RuntimeError("Win32 连接失败（可尝试管理员权限或换截图方式）")
            self.controller = ctrl
            self.connected = True
            self.hwnd = int(hwnd)
            self._emit(f"已连接 Win32 hwnd=0x{hwnd:X} screencap={screencap}")

    def connect_adb(self, device: AdbInfo) -> None:
        ensure_library()
        from maa.controller import AdbController

        with self._lock:
            self._reset_locked()
            ctrl = AdbController(
                adb_path=device.adb_path,
                address=device.address,
                screencap_methods=device.screencap_methods,
                input_methods=device.input_methods,
                config=device.config,
            )
            job = ctrl.post_connection().wait()
            if not job.succeeded:
                raise RuntimeError("ADB 连接失败")
            self.controller = ctrl
            self.connected = True
            self.hwnd = None
            self._emit(f"已连接 ADB {device.label()}")

    def win32_hwnd_alive(self) -> bool:
        """True if Win32 target still exists; ADB / unset hwnd → True (not applicable)."""
        hwnd = self.hwnd
        if not hwnd:
            return True
        if os.name != "nt":
            return True
        try:
            import ctypes

            return bool(ctypes.windll.user32.IsWindow(int(hwnd)))
        except Exception:  # noqa: BLE001
            return False

    def connect_from_pi_controller(self, ctrl: PiController, hwnd: Optional[int] = None, adb: Optional[AdbInfo] = None) -> None:
        ctype = (ctrl.type or "").lower()
        raw = ctrl.raw
        if ctype == "win32":
            win = raw.get("win32") or {}
            if hwnd is None:
                # auto-pick by regex
                class_rx = win.get("class_regex") or ".*"
                title_rx = win.get("window_regex") or ".*"
                import re

                c_re = re.compile(class_rx)
                t_re = re.compile(title_rx)
                hits = [
                    w
                    for w in list_windows()
                    if c_re.search(w.class_name) and t_re.search(w.title)
                ]
                if not hits:
                    raise RuntimeError(f"未找到窗口 class={class_rx!r} title={title_rx!r}")
                hwnd = hits[0].hwnd
                self._emit(f"自动匹配窗口: {hits[0].title}")
            self.connect_win32(
                hwnd,
                screencap=str(win.get("screencap") or "Background"),
                mouse=str(win.get("mouse") or "Seize"),
                keyboard=str(win.get("keyboard") or win.get("mouse") or "Seize"),
            )
        elif ctype == "adb":
            if adb is None:
                devices = list_adb_devices()
                if not devices:
                    raise RuntimeError("未找到 ADB 设备")
                adb = devices[0]
            self.connect_adb(adb)
        else:
            raise RuntimeError(f"暂不支持控制器类型: {ctrl.type}")

    def screencap(self) -> np.ndarray:
        with self._lock:
            if not self.controller or not self.connected:
                raise RuntimeError("未连接控制器")
            if self.hwnd and not self.win32_hwnd_alive():
                raise RuntimeError(
                    "目标窗口已关闭或句柄失效（Window no longer valid），请重新选择窗口并连接"
                )
            job = self.controller.post_screencap().wait()
            if not job.succeeded:
                if self.hwnd and not self.win32_hwnd_alive():
                    raise RuntimeError(
                        "目标窗口已关闭或句柄失效（Window no longer valid），请重新选择窗口并连接"
                    )
                raise RuntimeError(
                    "截图失败（可换截图方式 Background / PrintWindow，或确认窗口未最小化）"
                )
            img = job.get()
            if img is None:
                raise RuntimeError("截图为空")
            return img

    def click(self, x: int, y: int) -> None:
        with self._lock:
            if not self.controller:
                raise RuntimeError("未连接")
            self.controller.post_click(int(x), int(y)).wait()
            self._emit(f"Click ({x}, {y})")

    def scroll(self, dx: int, dy: int) -> None:
        """Send wheel/scroll to the connected game (not the UI page)."""
        with self._lock:
            if not self.controller:
                raise RuntimeError("未连接")
            self.controller.post_scroll(int(dx), int(dy)).wait()
            self._emit(f"Scroll dx={dx} dy={dy}")

    def swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        *,
        duration_ms: int = 300,
    ) -> None:
        with self._lock:
            if not self.controller:
                raise RuntimeError("未连接")
            self.controller.post_swipe(
                int(x1), int(y1), int(x2), int(y2), int(duration_ms)
            ).wait()
            self._emit(f"Swipe ({x1},{y1})→({x2},{y2}) {duration_ms}ms")

    def touch_down(self, x: int, y: int, *, contact: int = 0) -> None:
        with self._lock:
            if not self.controller:
                raise RuntimeError("未连接")
            self.controller.post_touch_down(int(x), int(y), int(contact)).wait()

    def touch_move(self, x: int, y: int, *, contact: int = 0) -> None:
        with self._lock:
            if not self.controller:
                raise RuntimeError("未连接")
            self.controller.post_touch_move(int(x), int(y), int(contact)).wait()

    def touch_up(self, *, contact: int = 0) -> None:
        with self._lock:
            if not self.controller:
                raise RuntimeError("未连接")
            self.controller.post_touch_up(int(contact)).wait()

    def load_project(self, project: PiProject, resource_name: Optional[str] = None) -> None:
        ensure_library()
        from maa.resource import Resource
        from maa.tasker import Tasker, TaskerEventSink
        from maa.context import ContextEventSink
        from maa.event_sink import NotificationType

        with self._lock:
            if not self.controller:
                raise RuntimeError("请先连接控制器")
            self.project = project
            res = Resource()
            bundles = project.resources
            if not bundles:
                raise RuntimeError("interface.json 无 resource")
            chosen = bundles[0]
            if resource_name:
                for name, paths in bundles:
                    if name == resource_name:
                        chosen = (name, paths)
                        break
            for p in chosen[1]:
                if not p.exists():
                    raise FileNotFoundError(f"资源路径不存在: {p}")
                job = res.post_bundle(p)
                if not job.wait().succeeded:
                    raise RuntimeError(f"加载资源失败: {p}")
            self._emit(f"已加载资源 {chosen[0]} ({len(chosen[1])} path)")

            tasker = Tasker()
            Tasker.set_save_draw(True)
            tasker.bind(res, self.controller)
            if not tasker.inited:
                raise RuntimeError("Tasker 初始化失败")

            session = self

            class _CtxSink(ContextEventSink):
                def on_node_recognition(self, context, noti_type, detail):  # noqa: ANN001
                    if noti_type != NotificationType.Succeeded:
                        return
                    try:
                        reco = context.tasker.get_recognition_detail(detail.reco_id)
                    except Exception:  # noqa: BLE001
                        return
                    if not reco:
                        return
                    boxes: list[BoxHit] = []
                    if reco.box is not None:
                        b = reco.box
                        # Rect may be tuple-like or object
                        if hasattr(b, "x"):
                            box = (int(b.x), int(b.y), int(b.w), int(b.h))
                        else:
                            box = (int(b[0]), int(b[1]), int(b[2]), int(b[3]))
                        boxes.append(BoxHit(name=str(detail.name), box=box, hit=bool(reco.hit)))
                    # also filtered results with boxes
                    for fr in reco.filtered_results or []:
                        fb = getattr(fr, "box", None)
                        if fb is None:
                            continue
                        if hasattr(fb, "x"):
                            box = (int(fb.x), int(fb.y), int(fb.w), int(fb.h))
                        else:
                            box = (int(fb[0]), int(fb[1]), int(fb[2]), int(fb[3]))
                        boxes.append(BoxHit(name=str(detail.name), box=box, hit=True))
                    if boxes:
                        session._latest_boxes = boxes
                        session._on_boxes(boxes)
                        session._emit(
                            f"识别 {detail.name}: hit={reco.hit} boxes={len(boxes)}"
                        )

            class _TaskSink(TaskerEventSink):
                def on_tasker_task(self, tasker, noti_type, detail):  # noqa: ANN001
                    session._emit(f"任务 {detail.entry}: {noti_type.name}")

            self._ctx_sink_id = tasker.add_context_sink(_CtxSink())
            self._task_sink_id = tasker.add_sink(_TaskSink())
            self.resource = res
            self.tasker = tasker

    def run_task(self, entry: str) -> None:
        with self._lock:
            if not self.tasker:
                raise RuntimeError("未加载资源/Tasker")
            if self.tasker.running:
                raise RuntimeError("已有任务在运行")
            self._latest_boxes = []
            self._emit(f"开始任务 entry={entry}")
            # async — UI polls running()
            self.tasker.post_task(entry)

    def stop_task(self) -> None:
        with self._lock:
            if self.tasker and (self.tasker.running or self.tasker.stopping):
                self.tasker.post_stop()
                self._emit("已请求停止任务")

    @property
    def task_running(self) -> bool:
        t = self.tasker
        return bool(t and t.running)

    @property
    def boxes(self) -> list[BoxHit]:
        return list(self._latest_boxes)


def numpy_to_qimage(img: np.ndarray):
    """Convert MaaFW RGB/BGR ndarray to QImage (caller imports Qt)."""
    from PySide6.QtGui import QImage

    if img is None:
        raise ValueError("empty image")
    if img.ndim == 2:
        h, w = img.shape
        q = QImage(img.data, w, h, w, QImage.Format.Format_Grayscale8)
        return q.copy()
    if img.ndim != 3:
        raise ValueError(f"unexpected shape {img.shape}")
    h, w, c = img.shape
    if c == 3:
        # MaaFW returns RGB uint8
        bytes_per_line = 3 * w
        q = QImage(img.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        return q.copy()
    if c == 4:
        q = QImage(img.data, w, h, 4 * w, QImage.Format.Format_RGBA8888)
        return q.copy()
    raise ValueError(f"unexpected channels {c}")
