"""MaaFW studio tab: connect / live screencap / run task / recognition boxes (MXU-parity)."""
from __future__ import annotations

import re
import time
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QRect, QRunnable, QSize, QStringListModel, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from runner.after_launch import after_launch_to_storage, normalize_after_launch
from runner.config import LOGS_DIR, PROJECTS_DIR, ROOT
from ui import styles
from ui.dialog_chrome import bind_collapsible_group
from ui.styles import GAP, GAP_SM, PAD
from runner.pipeline_recorder import (
    Recording,
    RecordStep,
    crop_template_png,
    export_pipeline,
)
from runner.process_launch import (
    hwnd_pid,
    launch_detached,
    pick_window_for_launch,
    related_pids,
    wait_settle,
)
from runner.maa_runtime import (
    WIN32_INPUT,
    WIN32_SCREENCAP,
    AdbInfo,
    BoxHit,
    MaaSession,
    PiProject,
    ensure_library,
    list_adb_devices,
    list_windows,
    load_pi_project,
    numpy_to_qimage,
    resolve_bin_dir,
)


class _JobSignals(QObject):
    ok = Signal(object)
    err = Signal(str)
    log = Signal(str)


class _FnJob(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.signals = _JobSignals()

    @Slot()
    def run(self) -> None:
        try:
            self.signals.ok.emit(self.fn())
        except Exception as e:  # noqa: BLE001
            self.signals.err.emit(str(e))


class PreviewCanvas(QLabel):
    """Live frame; left-click / drag / wheel → game input (image coordinates)."""

    clicked = Signal(int, int)  # image x,y — short tap
    scrolled = Signal(int, int)  # dx, dy → game wheel
    touch_down = Signal(int, int)
    touch_move = Signal(int, int)
    touch_up = Signal()

    _MIN_W = 420
    _MIN_H = 280
    _DRAG_THRESH = 8  # widget px before drag starts

    def __init__(self) -> None:
        super().__init__()
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(self._MIN_W, self._MIN_H)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.setObjectName("previewCanvas")
        self.setText("暂无截图\n请先连接设备")
        self.setMouseTracking(False)
        self._image: QImage | None = None
        self._boxes: list[BoxHit] = []
        self._scaled = QPixmap()
        self._offset = QPoint(0, 0)
        self._scale = 1.0
        self._press_img: tuple[int, int] | None = None
        self._press_pos: QPoint | None = None
        self._dragging = False
        self._paint_key: tuple | None = None
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(48)
        self._resize_timer.timeout.connect(self._repaint_pixmap)

    def minimumSizeHint(self) -> QSize:
        return QSize(self._MIN_W, self._MIN_H)

    def sizeHint(self) -> QSize:
        return QSize(640, 480)

    def set_frame(self, image: QImage, boxes: list[BoxHit] | None = None) -> None:
        self._image = image
        if boxes is not None:
            self._boxes = boxes
        self._paint_key = None
        self._repaint_pixmap()

    def set_boxes(self, boxes: list[BoxHit]) -> None:
        self._boxes = boxes
        self._paint_key = None
        if self._image is not None:
            self._repaint_pixmap()

    def clear_frame(self) -> None:
        self._resize_timer.stop()
        self._image = None
        self._boxes = []
        self._scaled = QPixmap()
        self._offset = QPoint(0, 0)
        self._scale = 1.0
        self._paint_key = None
        self._press_img = None
        self._press_pos = None
        self._dragging = False
        self.clear()
        self.setText("暂无截图\n请先连接设备")

    def _map_to_image(self, pos: QPoint) -> tuple[int, int] | None:
        if self._image is None or self._scaled.isNull() or self._scale <= 0:
            return None
        lx = pos.x() - self._offset.x()
        ly = pos.y() - self._offset.y()
        if lx < 0 or ly < 0 or lx >= self._scaled.width() or ly >= self._scaled.height():
            return None
        return int(lx / self._scale), int(ly / self._scale)

    def _frame_key(self) -> tuple:
        img = self._image
        if img is None:
            return (0, 0, 0, 0, 0)
        return (
            img.cacheKey(),
            self.width(),
            self.height(),
            len(self._boxes),
            id(self._boxes) if self._boxes else 0,
        )

    def _repaint_pixmap(self) -> None:
        if self._image is None:
            return
        tw, th = self.width(), self.height()
        if tw < 2 or th < 2:
            return
        key = self._frame_key()
        if key == self._paint_key and not self._scaled.isNull():
            return
        # Fast scale first (live preview); draw ROI boxes on the smaller pixmap.
        pix = QPixmap.fromImage(self._image)
        scaled = pix.scaled(
            tw,
            th,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        scale = scaled.width() / max(1, pix.width())
        if self._boxes and scale > 0:
            painted = QPixmap(scaled)
            p = QPainter(painted)
            pen = QPen(QColor(styles.ACCENT))
            pen.setWidth(max(2, int(2 * scale) or 2))
            p.setPen(pen)
            for b in self._boxes:
                x, y, w, h = b.box
                p.drawRect(
                    QRect(
                        int(x * scale),
                        int(y * scale),
                        max(1, int(w * scale)),
                        max(1, int(h * scale)),
                    )
                )
                p.drawText(int(x * scale) + 2, max(12, int(y * scale) - 4), b.name)
            p.end()
            scaled = painted
        self._scaled = scaled
        self._scale = scale
        ox = (tw - scaled.width()) // 2
        oy = (th - scaled.height()) // 2
        self._offset = QPoint(ox, oy)
        self._paint_key = key
        self.setPixmap(scaled)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._image is not None:
            self._paint_key = None
            self._resize_timer.start()

    def wheelEvent(self, event) -> None:  # noqa: N802
        # Game scroll (Maa post_scroll), not the dialog page.
        delta = event.angleDelta()
        dx, dy = int(delta.x()), int(delta.y())
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            # Shift+wheel → horizontal in game
            if abs(dy) > abs(dx):
                dx, dy = dy, 0
        if dx == 0 and dy == 0:
            pixel = event.pixelDelta()
            dx, dy = int(pixel.x()), int(pixel.y())
        if dx or dy:
            self.scrolled.emit(dx, dy)
        event.accept()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        mapped = self._map_to_image(pos)
        if mapped is None:
            return
        self._press_img = mapped
        self._press_pos = pos
        self._dragging = False
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._press_img is None or self._press_pos is None:
            super().mouseMoveEvent(event)
            return
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        if not self._dragging:
            dist = (pos - self._press_pos).manhattanLength()
            if dist < self._DRAG_THRESH:
                return
            self._dragging = True
            self.touch_down.emit(self._press_img[0], self._press_img[1])
        mapped = self._map_to_image(pos)
        if mapped is not None:
            self.touch_move.emit(mapped[0], mapped[1])
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return
        if self._press_img is None:
            return
        if self._dragging:
            self.touch_up.emit()
        else:
            self.clicked.emit(self._press_img[0], self._press_img[1])
        self._press_img = None
        self._press_pos = None
        self._dragging = False
        event.accept()


class PreviewPanel(QWidget):
    """maafw: record PI draft. assistant: connect/click to capture after_launch point."""

    after_launch_picked = Signal(str, int, int)  # legacy single-step notify
    after_launch_changed = Signal(object)  # full after_launch dict for config
    save_script_requested = Signal()  # editor should persist full script from ②
    test_after_launch_requested = Signal()  # editor runs click trial

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = MaaSession(log=self._append_log, on_boxes=self._on_boxes_from_session)
        self._project: PiProject | None = None
        self._windows = []
        self._adb: list[AdbInfo] = []
        self._playing = False
        self._busy = False
        self._launch_busy = False
        self._launch_settle_sec = 3.0
        self._panel_mode = "maafw"
        self._screencap_fail_streak = 0
        self._last_click: tuple[int, int] | None = None
        self._last_image: QImage | None = None
        self._asst_steps: list[dict] = []
        self._asst_loading = False
        self._asst_list_map: list[tuple[str, object]] = []  # ("group"|"step", key)
        self._asst_collapsed: set[str] = set()
        self._asst_name_history: list[str] = []
        self._asst_delay_locked = False
        self._recording = Recording()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick_screencap)
        self._task_poll = QTimer(self)
        self._task_poll.setInterval(400)
        self._task_poll.timeout.connect(self._poll_task)
        self._build()
        self._try_init_library()

    def minimumSizeHint(self) -> QSize:
        # Tall enough that scroll_page scrolls instead of crushing preview.
        return QSize(920, 620)

    def sizeHint(self) -> QSize:
        return QSize(980, 660)

    def _try_init_library(self) -> None:
        try:
            path = ensure_library(resolve_bin_dir())
            self._append_log(f"MaaFW 已加载: {path}")
        except Exception as e:  # noqa: BLE001
            self._append_log(f"MaaFW 未就绪: {e}")

    def _build(self) -> None:
        # Containment: tip → connect zone → workspace (steps|preview) → log.
        # Connect/log are Preferred; workspace stretch=1 is the visual focus.
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root = QVBoxLayout(self)
        root.setContentsMargins(GAP_SM, GAP_SM, GAP_SM, GAP_SM)
        root.setSpacing(GAP)

        self._mode_hint = QLabel("")
        self._mode_hint.setObjectName("muted")
        self._mode_hint.setWordWrap(True)
        root.addWidget(self._mode_hint)

        self._left = QWidget()
        ll = QVBoxLayout(self._left)
        ll.setContentsMargins(PAD, PAD, PAD, PAD)
        ll.setSpacing(GAP_SM)
        self._rec_loading = False
        self._last_export_entry: str | None = None
        self._build_maafw_record(ll)

        # Hidden task list kept for export reload / trial-run lookup
        self._box_proj = QWidget()
        self._box_proj.setVisible(False)
        self._box_tasks = QWidget()
        self._box_tasks.setVisible(False)
        self._box_rec = self._left
        self.task_list = QListWidget()
        self.task_list.setVisible(False)
        self.run_task_btn = QPushButton("开始任务")
        self.run_task_btn.clicked.connect(self._run_task)
        self.run_task_btn.setVisible(False)
        self.stop_task_btn = QPushButton("停止任务")
        self.stop_task_btn.clicked.connect(self._stop_task)
        self.stop_task_btn.setEnabled(False)
        self.stop_task_btn.setVisible(False)

        conn = QFrame()
        conn.setObjectName("zone")
        self._conn_box = conn
        cv = QVBoxLayout(conn)
        cv.setContentsMargins(PAD, PAD, PAD, PAD)
        cv.setSpacing(GAP_SM)

        conn_title = QLabel("连接")
        conn_title.setObjectName("zoneTitle")
        cv.addWidget(conn_title)

        row1 = QHBoxLayout()
        row1.setSpacing(GAP_SM)
        self.mode = QComboBox()
        self.mode.addItem("电脑端 Win32", "win32")
        self.mode.addItem("安卓端 ADB", "adb")
        self.mode.currentIndexChanged.connect(self._on_mode)
        self.mode.setMinimumWidth(132)
        row1.addWidget(QLabel("控制器"))
        row1.addWidget(self.mode)
        self.win_combo = QComboBox()
        self.win_combo.setMinimumWidth(160)
        self.win_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        refresh = QPushButton("刷新")
        refresh.setObjectName("ghost")
        refresh.clicked.connect(self.refresh_devices)
        row1.addWidget(QLabel("窗口"))
        row1.addWidget(self.win_combo, 1)
        row1.addWidget(refresh)
        cv.addLayout(row1)

        row_filter = QHBoxLayout()
        row_filter.setSpacing(GAP_SM)
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("窗口标题过滤，如 MAA|BrownDust")
        self.filter_edit.returnPressed.connect(self.refresh_devices)
        row_filter.addWidget(QLabel("过滤"))
        row_filter.addWidget(self.filter_edit, 1)
        cv.addLayout(row_filter)

        self._maafw_conn_row = QWidget()
        maafw_l = QHBoxLayout(self._maafw_conn_row)
        maafw_l.setContentsMargins(0, 0, 0, 0)
        maafw_l.setSpacing(GAP_SM)
        self._proj_row = QWidget()
        proj_l = QHBoxLayout(self._proj_row)
        proj_l.setContentsMargins(0, 0, 0, 0)
        proj_l.setSpacing(GAP_SM)
        self.project_path = QLineEdit(str(PROJECTS_DIR / "click_lab"))
        browse = QPushButton("浏览")
        browse.setObjectName("ghost")
        browse.clicked.connect(self._browse_project)
        load_btn = QPushButton("加载")
        load_btn.setObjectName("ghost")
        load_btn.clicked.connect(self._load_project)
        proj_l.addWidget(self.project_path, 1)
        proj_l.addWidget(browse)
        proj_l.addWidget(load_btn)
        maafw_l.addWidget(QLabel("PI 项目"))
        maafw_l.addWidget(self._proj_row, 2)
        self._launch_path_host = QWidget()
        launch_row = QHBoxLayout(self._launch_path_host)
        launch_row.setContentsMargins(0, 0, 0, 0)
        launch_row.setSpacing(GAP_SM)
        self.launch_path = QLineEdit()
        self.launch_path.setPlaceholderText("可选：游戏 exe（maafw 录控用）")
        b_launch_browse = QPushButton("浏览")
        b_launch_browse.setObjectName("ghost")
        b_launch_browse.clicked.connect(self._browse_launch)
        launch_row.addWidget(self.launch_path, 1)
        launch_row.addWidget(b_launch_browse)
        self._launch_path_label = QLabel("启动程序")
        maafw_l.addWidget(self._launch_path_label)
        maafw_l.addWidget(self._launch_path_host, 2)
        cv.addWidget(self._maafw_conn_row)

        self._conn_advanced = QGroupBox("高级（截图 / PI 资源 / 间隔）")
        self._conn_advanced.setCheckable(True)
        self._conn_advanced.setChecked(False)
        adv = QFormLayout(self._conn_advanced)
        adv.setContentsMargins(GAP_SM, GAP_SM, GAP_SM, GAP_SM)
        adv.setSpacing(GAP_SM)
        self.screencap_method = QComboBox()
        for k in WIN32_SCREENCAP:
            self.screencap_method.addItem(k, k)
        self.screencap_method.setCurrentText("PrintWindow")
        self.screencap_method.setToolTip(
            "PrintWindow：后台稳，对齐 MAA PC 常用项（推荐）。\n"
            "Background：兼容优先。\n"
            "FramePool：快，但窗口关闭/重建后易报 Window is no longer valid。"
        )
        adv.addRow("截图方式", self.screencap_method)
        self.mouse_method = QComboBox()
        for k in WIN32_INPUT:
            self.mouse_method.addItem(k, k)
        if self.mouse_method.findText("PostMessageWithWindowPos") >= 0:
            self.mouse_method.setCurrentText("PostMessageWithWindowPos")
        self.mouse_method.setToolTip(
            "PostMessageWithWindowPos：对齐 MAA「PostMsg-WindowPos」，少抢鼠标；"
            "建议与 PrintWindow 同用。"
        )
        adv.addRow("鼠标/键盘", self.mouse_method)
        self.launch_workdir = QLineEdit()
        self.launch_workdir.setPlaceholderText("可选；空则用 exe 所在目录")
        adv.addRow("启动工作目录", self.launch_workdir)
        self.interval = QSpinBox()
        self.interval.setRange(100, 5000)
        self.interval.setValue(500)
        self.interval.setSuffix(" ms")
        self.interval.setToolTip("实时预览轮询间隔；越大越省 CPU")
        adv.addRow("预览间隔", self.interval)
        self.pi_ctrl = QComboBox()
        self.pi_res = QComboBox()
        adv.addRow("PI 控制器定义", self.pi_ctrl)
        adv.addRow("PI 资源", self.pi_res)
        cv.addWidget(self._conn_advanced)
        bind_collapsible_group(self._conn_advanced)

        actions = QFrame()
        actions.setObjectName("toolbarStrip")
        btn = QHBoxLayout(actions)
        btn.setContentsMargins(GAP_SM, GAP_SM, GAP_SM, GAP_SM)
        btn.setSpacing(GAP_SM)
        self.launch_connect_btn = QPushButton("启动并连接")
        self.launch_connect_btn.setObjectName("primary")
        self.launch_connect_btn.setToolTip(
            "启动程序 → 按进程/过滤匹配窗口后连接。"
        )
        self.launch_connect_btn.clicked.connect(self._launch_and_connect)
        self.connect_btn = QPushButton("连接")
        self.connect_btn.setObjectName("secondary")
        self.connect_btn.clicked.connect(self._connect)
        self.play_btn = QPushButton("▶ 实时截图")
        self.play_btn.setObjectName("secondary")
        self.play_btn.clicked.connect(self.toggle_play)
        self.play_btn.setEnabled(False)
        self.snap_btn = QPushButton("保存帧")
        self.snap_btn.setObjectName("ghost")
        self.snap_btn.clicked.connect(self.save_frame)
        self.snap_btn.setEnabled(False)
        self.disconnect_btn = QPushButton("断开")
        self.disconnect_btn.setObjectName("ghost")
        self.disconnect_btn.clicked.connect(self._disconnect)
        btn.addWidget(self.launch_connect_btn)
        btn.addWidget(self.connect_btn)
        btn.addWidget(self.play_btn)
        btn.addWidget(self.snap_btn)
        btn.addWidget(self.disconnect_btn)
        btn.addStretch(1)
        self.status = QLabel(
            "未连接 · 「启动并连接」，或刷新窗口后点连接"
        )
        self.status.setWordWrap(True)
        self.status.setObjectName("muted")
        btn.addWidget(self.status, 1)
        cv.addWidget(actions)
        conn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        root.addWidget(conn)

        self._asst_left = QWidget()
        asst_lay = QVBoxLayout(self._asst_left)
        asst_lay.setContentsMargins(PAD, PAD, PAD, PAD)
        asst_lay.setSpacing(GAP_SM)
        self._build_assistant_steps(asst_lay)

        steps_host = QFrame()
        steps_host.setObjectName("zone")
        steps_outer = QVBoxLayout(steps_host)
        steps_outer.setContentsMargins(0, 0, 0, 0)
        steps_outer.setSpacing(0)
        self._steps_stack = QStackedWidget()
        self._steps_stack.setMinimumWidth(280)
        self._steps_stack.setMaximumWidth(380)
        self._steps_stack.addWidget(self._asst_left)
        self._steps_stack.addWidget(self._left)
        steps_outer.addWidget(self._steps_stack)

        view_box = QFrame()
        view_box.setObjectName("zone")
        self._view_box = view_box
        vl = QVBoxLayout(view_box)
        vl.setContentsMargins(PAD, PAD, PAD, PAD)
        vl.setSpacing(GAP_SM)
        view_head = QHBoxLayout()
        view_title = QLabel("实时截图")
        view_title.setObjectName("zoneTitle")
        view_head.addWidget(view_title)
        view_hint = QLabel("点/拖=操作 · 滚轮=滚动 · 录制中同时记点击")
        view_hint.setObjectName("muted")
        view_head.addWidget(view_hint, 1)
        vl.addLayout(view_head)
        self.canvas = PreviewCanvas()
        self.canvas.setToolTip("左键点/拖=操作游戏 · 滚轮=游戏内滚动 · 录制中同时记点击")
        self.canvas.clicked.connect(self._on_canvas_click)
        self.canvas.scrolled.connect(self._on_canvas_scroll)
        self.canvas.touch_down.connect(self._on_canvas_touch_down)
        self.canvas.touch_move.connect(self._on_canvas_touch_move)
        self.canvas.touch_up.connect(self._on_canvas_touch_up)
        vl.addWidget(self.canvas, 1)

        mid = QSplitter(Qt.Orientation.Horizontal)
        mid.setChildrenCollapsible(False)
        mid.setHandleWidth(GAP)
        mid.setMinimumHeight(320)
        mid.addWidget(steps_host)
        mid.addWidget(view_box)
        mid.setStretchFactor(0, 1)
        mid.setStretchFactor(1, 3)
        mid.setSizes([300, 700])
        root.addWidget(mid, 1)

        log_box = QGroupBox("日志")
        log_box.setCheckable(True)
        log_box.setChecked(False)
        lg = QVBoxLayout(log_box)
        lg.setContentsMargins(GAP_SM, GAP_SM, GAP_SM, GAP_SM)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(72)
        self.log_view.setMaximumHeight(140)
        self.log_view.document().setMaximumBlockCount(400)
        lg.addWidget(self.log_view)
        log_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        root.addWidget(log_box)
        bind_collapsible_group(log_box)

        self._on_mode()
        self.refresh_devices()
        self.set_panel_mode("maafw")

    def _build_maafw_record(self, ll: QVBoxLayout) -> None:
        head = QHBoxLayout()
        title = QLabel("识图步骤")
        title.setObjectName("zoneTitle")
        head.addWidget(title)
        head.addStretch(1)
        self.rec_armed = QCheckBox("录制中")
        self.rec_armed.setToolTip("勾选后，点右侧实时截图追加步骤")
        self.rec_armed.setChecked(True)
        head.addWidget(self.rec_armed)
        ll.addLayout(head)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(GAP_SM)
        mode_row.addWidget(QLabel("记为"))
        self.rec_mode = QComboBox()
        self.rec_mode.addItem("模板裁切（更稳）", "click_template")
        self.rec_mode.addItem("绝对坐标（备选）", "click_xy")
        self.rec_mode.setCurrentIndex(0)
        mode_row.addWidget(self.rec_mode, 1)
        ll.addLayout(mode_row)
        opt = QHBoxLayout()
        opt.setSpacing(GAP_SM)
        self.rec_or = QCheckBox("下一步作 OR")
        self.rec_or.setToolTip("勾选后，下一次记录并入上一步的 next 多候选")
        opt.addWidget(self.rec_or)
        self.rec_half = QSpinBox()
        self.rec_half.setRange(16, 200)
        self.rec_half.setValue(48)
        self.rec_half.setPrefix("半边 ")
        self.rec_half.setSuffix(" px")
        self.rec_half.setToolTip("模板裁切：以点击为中心的半边长（只影响之后新录的步）")
        opt.addWidget(self.rec_half)
        ll.addLayout(opt)
        self.rec_task_name = QLineEdit("录制草稿")
        self.rec_task_name.setPlaceholderText("导出任务名")
        ll.addWidget(self.rec_task_name)
        self.rec_list = QListWidget()
        self.rec_list.setMinimumHeight(80)
        self.rec_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.rec_list.currentRowChanged.connect(self._rec_on_row)
        ll.addWidget(self.rec_list, 1)

        form = QFormLayout()
        form.setSpacing(GAP_SM)
        self.rec_edit_name = QLineEdit()
        self.rec_edit_name.setPlaceholderText("步骤名")
        self.rec_edit_name.editingFinished.connect(self._rec_apply_editor)
        self.rec_edit_x = QSpinBox()
        self.rec_edit_x.setRange(0, 10000)
        self.rec_edit_y = QSpinBox()
        self.rec_edit_y.setRange(0, 10000)
        self.rec_edit_delay = QSpinBox()
        self.rec_edit_delay.setRange(0, 60000)
        self.rec_edit_delay.setSuffix(" ms")
        self.rec_edit_delay.setValue(500)
        self.rec_edit_delay.valueChanged.connect(self._rec_apply_editor)
        self.rec_edit_x.editingFinished.connect(self._rec_apply_editor)
        self.rec_edit_y.editingFinished.connect(self._rec_apply_editor)
        form.addRow("名称", self.rec_edit_name)
        xy = QHBoxLayout()
        xy.setSpacing(GAP_SM)
        xy.addWidget(QLabel("X"))
        xy.addWidget(self.rec_edit_x)
        xy.addWidget(QLabel("Y"))
        xy.addWidget(self.rec_edit_y)
        form.addRow("坐标", xy)
        form.addRow("步延迟", self.rec_edit_delay)
        ll.addLayout(form)

        rb = QHBoxLayout()
        rb.setSpacing(GAP_SM)
        b_up = QPushButton("▲")
        b_up.setObjectName("icon")
        b_up.setToolTip("上移")
        b_up.clicked.connect(lambda: self._rec_move(-1))
        b_dn = QPushButton("▼")
        b_dn.setObjectName("icon")
        b_dn.setToolTip("下移")
        b_dn.clicked.connect(lambda: self._rec_move(1))
        b_wait = QPushButton("+等待")
        b_wait.setObjectName("ghost")
        b_wait.clicked.connect(self._rec_add_wait)
        b_del = QPushButton("删除")
        b_del.setObjectName("danger")
        b_del.clicked.connect(self._rec_delete)
        b_cover = QPushButton("覆盖坐标")
        b_cover.setObjectName("ghost")
        b_cover.setToolTip("用上次点击改坐标；模板步会按当前帧重裁")
        b_cover.clicked.connect(self._rec_cover_last_click)
        b_clear = QPushButton("清空")
        b_clear.setObjectName("ghost")
        b_clear.clicked.connect(self._rec_clear)
        rb.addWidget(b_up)
        rb.addWidget(b_dn)
        rb.addWidget(b_wait)
        rb.addWidget(b_del)
        rb.addWidget(b_cover)
        rb.addWidget(b_clear)
        ll.addLayout(rb)

        self.rec_status = QLabel("尚无步骤")
        self.rec_status.setObjectName("muted")
        self.rec_status.setWordWrap(True)
        ll.addWidget(self.rec_status)

        b_export = QPushButton("导出到项目")
        b_export.setObjectName("primary")
        b_export.clicked.connect(self._rec_export)
        ll.addWidget(b_export)

    def _build_assistant_steps(self, lay: QVBoxLayout) -> None:
        head = QHBoxLayout()
        title = QLabel("点击步骤")
        title.setObjectName("zoneTitle")
        head.addWidget(title)
        head.addStretch(1)
        self._asst_armed = QCheckBox("录制中")
        self._asst_armed.setToolTip("勾选后，点右侧实时截图追加步骤")
        self._asst_armed.setChecked(True)
        head.addWidget(self._asst_armed)
        lay.addLayout(head)

        delay_row = QHBoxLayout()
        delay_row.setSpacing(GAP_SM)
        delay_row.addWidget(QLabel("开窗前"))
        self._asst_open_delay = QSpinBox()
        self._asst_open_delay.setRange(0, 120)
        self._asst_open_delay.setValue(2)
        self._asst_open_delay.setSuffix(" 秒")
        self._asst_open_delay.setToolTip("找到窗口前的总等待（写入 after_launch.delay_sec）")
        delay_row.addWidget(self._asst_open_delay)
        b_test = QPushButton("试运行")
        b_test.setObjectName("secondary")
        b_test.setToolTip("对已打开窗口按当前步骤点击（不启动 exe）")
        b_test.clicked.connect(self.test_after_launch_requested.emit)
        delay_row.addWidget(b_test)
        lay.addLayout(delay_row)

        self._asst_list = QListWidget()
        self._asst_list.setMinimumHeight(80)
        self._asst_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._asst_list.currentRowChanged.connect(self._asst_on_list_row)
        self._asst_list.itemClicked.connect(self._asst_on_item_clicked)
        lay.addWidget(self._asst_list, 1)

        form = QFormLayout()
        form.setSpacing(GAP_SM)
        self._asst_name = QLineEdit()
        self._asst_name.setPlaceholderText("步骤名，如 领取")
        self._asst_name_completer = QCompleter(self)
        self._asst_name_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._asst_name_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._asst_name_model = QStringListModel(self)
        self._asst_name_completer.setModel(self._asst_name_model)
        self._asst_name.setCompleter(self._asst_name_completer)
        self._asst_name.editingFinished.connect(self._asst_apply_editor)
        self._asst_x = QSpinBox()
        self._asst_x.setRange(0, 10000)
        self._asst_y = QSpinBox()
        self._asst_y.setRange(0, 10000)
        self._asst_step_delay = QSpinBox()
        self._asst_step_delay.setRange(0, 120)
        self._asst_step_delay.setSuffix(" 秒")
        self._asst_step_delay.setToolTip("本步点击前等待")
        for w in (self._asst_x, self._asst_y, self._asst_step_delay):
            w.valueChanged.connect(self._asst_apply_editor)
        form.addRow("名称", self._asst_name)
        xy = QHBoxLayout()
        xy.setSpacing(GAP_SM)
        xy.addWidget(QLabel("X"))
        xy.addWidget(self._asst_x)
        xy.addWidget(QLabel("Y"))
        xy.addWidget(self._asst_y)
        form.addRow("坐标", xy)

        wait_row = QHBoxLayout()
        wait_row.setSpacing(GAP_SM)
        wait_row.addWidget(self._asst_step_delay, 1)
        self._asst_delay_lock = QCheckBox("锁定全部")
        self._asst_delay_lock.setToolTip(
            "勾选后改间隔会同步到全部步骤；解锁后可单独改每一步"
        )
        self._asst_delay_lock.toggled.connect(self._asst_on_delay_lock)
        wait_row.addWidget(self._asst_delay_lock)
        form.addRow("步前等待", wait_row)

        self._asst_group = QLineEdit()
        self._asst_group.setPlaceholderText("分组名（空=未分组）")
        self._asst_group.editingFinished.connect(self._asst_apply_editor)
        grp_row = QHBoxLayout()
        grp_row.setSpacing(GAP_SM)
        grp_row.addWidget(self._asst_group, 1)
        b_fold = QPushButton("折叠组")
        b_fold.setObjectName("linkish")
        b_fold.setToolTip("折叠或展开当前步骤所在分组")
        b_fold.clicked.connect(self._asst_toggle_current_group)
        grp_row.addWidget(b_fold)
        form.addRow("分组", grp_row)
        lay.addLayout(form)

        row = QHBoxLayout()
        row.setSpacing(GAP_SM)
        b_up = QPushButton("▲")
        b_up.setObjectName("icon")
        b_up.setToolTip("上移")
        b_up.clicked.connect(lambda: self._asst_move(-1))
        b_dn = QPushButton("▼")
        b_dn.setObjectName("icon")
        b_dn.setToolTip("下移")
        b_dn.clicked.connect(lambda: self._asst_move(1))
        b_del = QPushButton("删除")
        b_del.setObjectName("danger")
        b_del.clicked.connect(self._asst_delete)
        b_cover = QPushButton("覆盖坐标")
        b_cover.setObjectName("ghost")
        b_cover.setToolTip("把选中步骤的坐标改成刚才点的位置")
        b_cover.clicked.connect(self._asst_cover_last_click)
        row.addWidget(b_up)
        row.addWidget(b_dn)
        row.addWidget(b_del)
        row.addWidget(b_cover, 1)
        lay.addLayout(row)

        self._asst_status = QLabel("尚无步骤")
        self._asst_status.setObjectName("muted")
        self._asst_status.setWordWrap(True)
        lay.addWidget(self._asst_status)

        self._asst_save_btn = QPushButton("写入配置")
        self._asst_save_btn.setObjectName("primary")
        self._asst_save_btn.setToolTip("把左侧步骤保存为脚本的启动后点击（after_launch）")
        self._asst_save_btn.clicked.connect(self._asst_emit_save)
        lay.addWidget(self._asst_save_btn)

    def _append_log(self, msg: str) -> None:
        self.log_view.append(msg)

    def _on_boxes_from_session(self, boxes: list[BoxHit]) -> None:
        # may be called from maa callback thread
        QTimer.singleShot(0, lambda: self.canvas.set_boxes(list(boxes)))

    def _on_mode(self) -> None:
        win32 = self.mode.currentData() == "win32"
        self.screencap_method.setEnabled(win32)
        self.mouse_method.setEnabled(win32)
        self.filter_edit.setEnabled(win32)
        self.refresh_devices()

    def refresh_devices(self) -> None:
        def work():
            ensure_library(resolve_bin_dir())
            if self.mode.currentData() == "adb":
                return ("adb", list_adb_devices())
            return ("win32", list_windows(self.filter_edit.text()))

        job = _FnJob(work)
        job.signals.ok.connect(self._fill_devices)
        job.signals.err.connect(self._on_refresh_err)
        QThreadPool.globalInstance().start(job)

    @Slot(str)
    def _on_refresh_err(self, err: str) -> None:
        self.win_combo.clear()
        self.win_combo.addItem("（无法枚举 — 见状态栏 / 日志）", None)
        self.status.setText(f"刷新失败: {err}")
        self._append_log(f"刷新设备失败: {err}")

    @Slot(object)
    def _fill_devices(self, payload) -> None:
        kind, items = payload
        self.win_combo.clear()
        if kind == "adb":
            self._adb = items
            for d in items:
                self.win_combo.addItem(d.label(), d.address)
            if not items:
                self.win_combo.addItem("（未发现 ADB 设备）", None)
            self.status.setText(f"ADB 设备 {len(items)} 个")
        else:
            self._windows = items
            for w in items:
                self.win_combo.addItem(w.label(), w.hwnd)
            if not items:
                self.win_combo.addItem("（无窗口 — 放宽过滤或打开目标程序）", None)
            self.status.setText(f"窗口 {len(items)} 个 · 点下拉可切换")

    def _browse_project(self) -> None:
        p = QFileDialog.getExistingDirectory(self, "选择含 interface.json 的项目目录", str(ROOT))
        if p:
            self.project_path.setText(p)

    def set_panel_mode(self, mode: str) -> None:
        """maafw = PI template record; assistant = after_launch coordinate steps."""
        self._panel_mode = "assistant" if mode == "assistant" else "maafw"
        is_asst = self._panel_mode == "assistant"
        self._steps_stack.setCurrentIndex(0 if is_asst else 1)
        self._maafw_conn_row.setVisible(not is_asst)
        self.pi_ctrl.setEnabled(not is_asst)
        self.pi_res.setEnabled(not is_asst)
        if is_asst:
            self.mode.setCurrentIndex(0)  # Win32
            self._conn_advanced.setChecked(False)
            self._mode_hint.setText(
                "连窗口 → 开实时截图 → 勾选录制中点画面 → 写入配置。路径在①。"
            )
            self._append_log("助手连控：路径用① · ②只连控/录点击")
        else:
            self._conn_advanced.setChecked(False)
            self.rec_mode.setCurrentIndex(0)  # TemplateMatch default
            self._mode_hint.setText(
                "连窗口 → 开实时截图 → 左侧录识图步骤 → 导出到项目。无人值守仍走主台队列。"
            )
            self._append_log("maafw 识图录制：上连接 · 左步骤 · 右截图")

    def use_project(self, path: str) -> None:
        """Called by script editor when switching to the record tab (maafw)."""
        self.set_panel_mode("maafw")
        path = (path or "").strip()
        if not path:
            return
        p = Path(path)
        if not p.is_absolute():
            p = (ROOT / p).resolve()
        self.project_path.setText(str(p))
        self._load_project()

    def use_assistant(
        self,
        *,
        exe_path: str = "",
        window_filter: str = "",
        after_launch: dict | None = None,
    ) -> None:
        """Called for type=exe: connect/click helper + load multi-step list."""
        self.set_panel_mode("assistant")
        stem = ""
        if exe_path.strip():
            self.launch_path.setText(exe_path.strip())
            stem = Path(exe_path).stem
            if not self.launch_workdir.text().strip():
                self.launch_workdir.setText(str(Path(exe_path).parent))
        wf = (window_filter or "").strip()
        if not wf and after_launch:
            wf = str(after_launch.get("window_regex") or after_launch.get("window") or "").strip()
        if wf:
            self.filter_edit.setText(wf)
        elif stem and not self.filter_edit.text().strip():
            self.filter_edit.setText(stem)
            self._append_log(f"过滤已填入程序名: {stem}（可改）")
        self.load_after_launch(after_launch)
        self.refresh_devices()

    def load_after_launch(self, raw: dict | None) -> None:
        """Fill left step list from script after_launch."""
        self._asst_loading = True
        try:
            self._asst_steps = []
            # Prefer raw steps so editor-only fields (group) survive normalize.
            steps_src: list = []
            if isinstance(raw, dict) and isinstance(raw.get("steps"), list):
                steps_src = list(raw["steps"])
            else:
                spec = normalize_after_launch(raw) if raw else None
                if spec:
                    steps_src = list(spec.get("steps") or [])
                    if not self.filter_edit.text().strip():
                        self.filter_edit.setText(str(spec.get("window_regex") or ""))
            if isinstance(raw, dict) and not self.filter_edit.text().strip():
                wf = str(raw.get("window_regex") or raw.get("window") or "").strip()
                if wf:
                    self.filter_edit.setText(wf)
            if isinstance(raw, dict):
                try:
                    self._asst_open_delay.setValue(
                        int(float(raw.get("delay_sec") or 2))
                    )
                except (TypeError, ValueError):
                    self._asst_open_delay.setValue(2)
            for st in steps_src:
                if not isinstance(st, dict):
                    continue
                try:
                    x, y = int(st["x"]), int(st["y"])
                except (KeyError, TypeError, ValueError):
                    continue
                entry = {
                    "name": str(st.get("name") or f"点击 ({x},{y})"),
                    "x": x,
                    "y": y,
                    "delay_sec": float(st.get("delay_sec") or 0),
                    "window_regex": str(st.get("window_regex") or ""),
                    "group": str(st.get("group") or "").strip(),
                }
                self._asst_steps.append(entry)
                self._asst_remember_name(str(entry["name"]))
            self._asst_refresh_name_completer()
            self._asst_refresh_list()
            self._asst_select_step_index(0 if self._asst_steps else -1)
        finally:
            self._asst_loading = False

    def after_launch_fields(self) -> dict | None:
        """Build after_launch dict for config; None if no steps."""
        if not self._asst_steps:
            return None
        filt = self.filter_edit.text().strip()
        hwnd = self.win_combo.currentData()
        if hwnd is not None:
            for w in self._windows:
                if int(w.hwnd) == int(hwnd) and (w.title or "").strip():
                    filt = re.escape(w.title.strip())
                    break
        if not filt:
            filt = str(self._asst_steps[0].get("window_regex") or "").strip() or ".*"
        raw_steps = []
        for st in self._asst_steps:
            item = {
                "name": st.get("name") or f"点击 ({st['x']},{st['y']})",
                "x": int(st["x"]),
                "y": int(st["y"]),
                "delay_sec": float(st.get("delay_sec") or 0),
            }
            g = str(st.get("group") or "").strip()
            if g:
                item["group"] = g
            raw_steps.append(item)
        raw = {
            "window_regex": filt,
            "delay_sec": float(self._asst_open_delay.value()),
            "timeout_sec": 30,
            "steps": raw_steps,
        }
        spec = normalize_after_launch(raw)
        if not spec:
            return None
        stored = after_launch_to_storage(spec)
        # normalize strips group; re-attach from editor state by index
        for i, st in enumerate(self._asst_steps):
            if i < len(stored.get("steps") or []):
                g = str(st.get("group") or "").strip()
                if g:
                    stored["steps"][i]["group"] = g
                else:
                    stored["steps"][i].pop("group", None)
        return stored

    def _asst_group_key(self, st: dict) -> str:
        return str(st.get("group") or "").strip()

    def _asst_remember_name(self, name: str) -> None:
        name = (name or "").strip()
        if not name or name.startswith("步骤 ") or name.startswith("点击 ("):
            return
        if name in self._asst_name_history:
            self._asst_name_history.remove(name)
        self._asst_name_history.insert(0, name)
        del self._asst_name_history[40:]

    def _asst_refresh_name_completer(self) -> None:
        seen: list[str] = []
        for n in self._asst_name_history:
            if n not in seen:
                seen.append(n)
        for st in self._asst_steps:
            n = str(st.get("name") or "").strip()
            if n and n not in seen and not n.startswith("步骤 "):
                seen.append(n)
        self._asst_name_model.setStringList(seen)

    def _asst_current_step_index(self) -> int:
        row = self._asst_list.currentRow()
        if row < 0 or row >= len(self._asst_list_map):
            return -1
        kind, key = self._asst_list_map[row]
        return int(key) if kind == "step" else -1

    def _asst_select_step_index(self, step_idx: int) -> None:
        if step_idx < 0:
            return
        for i, (kind, key) in enumerate(self._asst_list_map):
            if kind == "step" and int(key) == step_idx:
                self._asst_list.setCurrentRow(i)
                return

    def _asst_refresh_list(self) -> None:
        keep = self._asst_current_step_index()
        self._asst_list.clear()
        self._asst_list_map = []
        # Preserve first-seen group order
        order: list[str] = []
        for st in self._asst_steps:
            g = self._asst_group_key(st)
            if g not in order:
                order.append(g)
        for g in order:
            idxs = [i for i, st in enumerate(self._asst_steps) if self._asst_group_key(st) == g]
            label = g if g else "未分组"
            collapsed = g in self._asst_collapsed
            mark = "▶" if collapsed else "▼"
            hdr = QListWidgetItem(f"{mark} {label}（{len(idxs)}）")
            hdr.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self._asst_list.addItem(hdr)
            self._asst_list_map.append(("group", g))
            if collapsed:
                continue
            for i in idxs:
                st = self._asst_steps[i]
                d = float(st.get("delay_sec") or 0)
                delay = f"  +{d:g}s" if d > 0 else ""
                self._asst_list.addItem(
                    f"  {i + 1}. {st.get('name') or '点击'}  ({st['x']},{st['y']}){delay}"
                )
                self._asst_list_map.append(("step", i))
        n = len(self._asst_steps)
        self._asst_status.setText(
            f"共 {n} 步 · 点组名可折叠" if n else "尚无步骤 — 勾选录制中后点右侧实时截图"
        )
        if keep >= 0:
            self._asst_select_step_index(keep)
        elif n:
            self._asst_select_step_index(n - 1)

    def _asst_on_item_clicked(self, item: QListWidgetItem) -> None:
        row = self._asst_list.row(item)
        if row < 0 or row >= len(self._asst_list_map):
            return
        kind, key = self._asst_list_map[row]
        if kind != "group":
            return
        g = str(key)
        if g in self._asst_collapsed:
            self._asst_collapsed.discard(g)
        else:
            self._asst_collapsed.add(g)
        self._asst_refresh_list()

    def _asst_on_list_row(self, row: int) -> None:
        if row < 0 or row >= len(self._asst_list_map):
            return
        kind, key = self._asst_list_map[row]
        if kind != "step":
            return
        self._asst_fill_editor(int(key))

    def _asst_fill_editor(self, step_idx: int) -> None:
        if step_idx < 0 or step_idx >= len(self._asst_steps):
            return
        self._asst_loading = True
        try:
            st = self._asst_steps[step_idx]
            self._asst_name.setText(str(st.get("name") or ""))
            self._asst_x.setValue(int(st["x"]))
            self._asst_y.setValue(int(st["y"]))
            self._asst_step_delay.setValue(int(float(st.get("delay_sec") or 0)))
            self._asst_group.setText(str(st.get("group") or ""))
        finally:
            self._asst_loading = False

    def _asst_on_delay_lock(self, locked: bool) -> None:
        self._asst_delay_locked = bool(locked)
        if locked and not self._asst_loading:
            val = float(self._asst_step_delay.value())
            for st in self._asst_steps:
                st["delay_sec"] = val
            self._asst_refresh_list()
            self._append_log(f"已锁定步前等待：全部 {val:g}s")

    def _asst_toggle_current_group(self) -> None:
        idx = self._asst_current_step_index()
        if idx < 0:
            # try selected group header
            row = self._asst_list.currentRow()
            if 0 <= row < len(self._asst_list_map) and self._asst_list_map[row][0] == "group":
                g = str(self._asst_list_map[row][1])
            else:
                return
        else:
            g = self._asst_group_key(self._asst_steps[idx])
        if g in self._asst_collapsed:
            self._asst_collapsed.discard(g)
        else:
            self._asst_collapsed.add(g)
        self._asst_refresh_list()

    def _asst_apply_editor(self, *_args) -> None:
        if self._asst_loading:
            return
        idx = self._asst_current_step_index()
        if idx < 0 or idx >= len(self._asst_steps):
            return
        st = self._asst_steps[idx]
        name = self._asst_name.text().strip() or f"点击 ({self._asst_x.value()},{self._asst_y.value()})"
        st["name"] = name
        self._asst_remember_name(name)
        self._asst_refresh_name_completer()
        st["x"] = int(self._asst_x.value())
        st["y"] = int(self._asst_y.value())
        delay = float(self._asst_step_delay.value())
        st["group"] = self._asst_group.text().strip()
        if self._asst_delay_locked:
            for s in self._asst_steps:
                s["delay_sec"] = delay
        else:
            st["delay_sec"] = delay
        self._asst_refresh_list()
        self._asst_select_step_index(idx)

    def _asst_move(self, delta: int) -> None:
        idx = self._asst_current_step_index()
        j = idx + delta
        if idx < 0 or j < 0 or j >= len(self._asst_steps):
            return
        self._asst_steps[idx], self._asst_steps[j] = self._asst_steps[j], self._asst_steps[idx]
        self._asst_refresh_list()
        self._asst_select_step_index(j)

    def _asst_delete(self) -> None:
        idx = self._asst_current_step_index()
        if idx < 0 or idx >= len(self._asst_steps):
            return
        self._asst_steps.pop(idx)
        self._asst_refresh_list()
        if self._asst_steps:
            self._asst_select_step_index(min(idx, len(self._asst_steps) - 1))

    def _asst_cover_last_click(self) -> None:
        if not self._last_click:
            QMessageBox.information(self, "提示", "请先在右侧实时截图上点一下")
            return
        idx = self._asst_current_step_index()
        if idx < 0 or idx >= len(self._asst_steps):
            QMessageBox.information(self, "提示", "请先选中左侧一步")
            return
        x, y = self._last_click
        self._asst_steps[idx]["x"] = int(x)
        self._asst_steps[idx]["y"] = int(y)
        self._asst_refresh_list()
        self._asst_select_step_index(idx)
        self._asst_fill_editor(idx)

    def _asst_append_click(self, x: int, y: int) -> None:
        n = len(self._asst_steps) + 1
        if self._asst_delay_locked:
            delay = float(self._asst_step_delay.value())
        else:
            delay = 0.5 if n > 1 else 0
        # Inherit group from current selection when recording
        cur = self._asst_current_step_index()
        group = ""
        if cur >= 0:
            group = self._asst_group_key(self._asst_steps[cur])
        elif self._asst_group.text().strip():
            group = self._asst_group.text().strip()
        self._asst_steps.append(
            {
                "name": f"步骤 {n}",
                "x": int(x),
                "y": int(y),
                "delay_sec": delay,
                "window_regex": "",
                "group": group,
            }
        )
        # Ensure new group's steps are visible
        self._asst_collapsed.discard(group)
        self._asst_refresh_list()
        self._asst_select_step_index(len(self._asst_steps) - 1)
        self._append_log(f"已录步骤 {n}: ({x},{y})")

    def _asst_emit_save(self) -> None:
        if not self._asst_steps:
            QMessageBox.information(self, "提示", "还没有步骤。勾选「录制中」后在右侧实时截图点击。")
            return
        data = self.after_launch_fields()
        if not data:
            QMessageBox.warning(self, "无法保存", "步骤无效")
            return
        self.after_launch_changed.emit(data)
        # Legacy signal for first step (editor may still listen)
        s0 = data["steps"][0]
        self.after_launch_picked.emit(
            str(data.get("window_regex") or ""),
            int(s0["x"]),
            int(s0["y"]),
        )
        self._asst_status.setText(f"已写入配置 · 共 {len(self._asst_steps)} 步")
        self._append_log(f"启动后点击已写入配置（{len(self._asst_steps)} 步）")

    def set_studio_launch(
        self,
        path: str = "",
        workdir: str = "",
        settle_sec: float | None = None,
    ) -> None:
        """Bind optional launch exe from script fields (studio_launch*)."""
        self.launch_path.setText(path or "")
        self.launch_workdir.setText(workdir or "")
        if settle_sec is not None:
            self._launch_settle_sec = max(0.5, float(settle_sec))
        else:
            self._launch_settle_sec = 3.0

    def studio_launch_fields(self) -> dict[str, str | float]:
        """Values to persist on the maafw script when saving the editor."""
        out: dict[str, str | float] = {
            "studio_launch": self.launch_path.text().strip(),
            "studio_launch_workdir": self.launch_workdir.text().strip(),
        }
        if abs(float(self._launch_settle_sec) - 3.0) > 1e-6:
            out["studio_launch_settle_sec"] = float(self._launch_settle_sec)
        return out

    def _browse_launch(self) -> None:
        start = self.launch_path.text().strip() or str(ROOT)
        p, _ = QFileDialog.getOpenFileName(
            self, "选择要启动的程序", start, "Executable (*.exe);;All (*.*)"
        )
        if p:
            self.launch_path.setText(p)
            if not self.launch_workdir.text().strip():
                self.launch_workdir.setText(str(Path(p).parent))

    def _set_launch_controls_enabled(self, enabled: bool) -> None:
        self.launch_connect_btn.setEnabled(enabled)
        self.connect_btn.setEnabled(enabled)

    def _launch_and_connect(self) -> None:
        path = self.launch_path.text().strip()
        if not path:
            QMessageBox.information(
                self,
                "提示",
                "请先填写或浏览「启动程序」（游戏客户端 / 助手 exe）。\n"
                "也可手动打开目标窗口后点「刷新」→「连接」。",
            )
            return
        if self._launch_busy:
            return

        mode = self.mode.currentData()
        title_filter = self.filter_edit.text()
        workdir = self.launch_workdir.text().strip()
        settle = float(self._launch_settle_sec)
        exe_stem = Path(path).stem
        # Extra poll window after settle so slow GUIs can appear.
        poll_budget = max(8.0, settle + 12.0)

        def work():
            ensure_library(resolve_bin_dir())
            proc = launch_detached(path, workdir=workdir or None, root=ROOT)
            wait_settle(settle)
            deadline = time.time() + poll_budget
            last_count = 0
            last_wins: list = []
            while True:
                if mode == "adb":
                    devices = list_adb_devices()
                    last_count = len(devices)
                    if devices:
                        return {
                            "kind": "adb",
                            "pid": proc.pid,
                            "items": devices,
                            "pick": devices[0].address,
                            "auto_connect": True,
                        }
                else:
                    wins = list_windows(title_filter)
                    last_wins = wins
                    last_count = len(wins)
                    picked = pick_window_for_launch(
                        wins,
                        launched_pid=proc.pid,
                        exe_stem=exe_stem,
                        title_filter=title_filter,
                    )
                    if picked is not None:
                        return {
                            "kind": "win32",
                            "pid": proc.pid,
                            "items": wins,
                            "pick": picked.hwnd,
                            "auto_connect": True,
                            "pick_title": picked.title,
                        }
                    # Keep polling: process may own a window that appears later.
                    related = related_pids(proc.pid)
                    owned = [w for w in wins if hwnd_pid(int(w.hwnd)) in related]
                    if owned:
                        # Should have been picked; force first owned window.
                        w0 = owned[0]
                        return {
                            "kind": "win32",
                            "pid": proc.pid,
                            "items": wins,
                            "pick": w0.hwnd,
                            "auto_connect": True,
                            "pick_title": w0.title,
                        }
                if time.time() >= deadline:
                    break
                wait_settle(0.5)
            if mode == "win32" and last_wins:
                return {
                    "kind": "win32",
                    "pid": proc.pid,
                    "items": last_wins,
                    "pick": None,
                    "auto_connect": False,
                    "message": (
                        f"已启动 pid={proc.pid}，未能唯一定位「{exe_stem}」窗口"
                        f"（当前列表 {last_count} 个）。"
                        "请在下拉框选手动目标窗口后点「连接」；"
                        "或在「过滤」填 MAA 等关键字再「启动并连接」。"
                    ),
                }
            raise RuntimeError(
                f"已启动 pid={proc.pid}，但未找到可连接目标"
                f"（{mode}，匹配数={last_count}）。"
                "请放宽「过滤」后点刷新，或手动选择窗口再连接。"
            )

        self._launch_busy = True
        self._set_launch_controls_enabled(False)
        self.status.setText("正在启动程序并等待窗口…")
        self._append_log(f"启动并连接（默认管理员）: {path}")
        job = _FnJob(work)
        job.signals.ok.connect(self._on_launch_ready)
        job.signals.err.connect(self._on_launch_err)
        QThreadPool.globalInstance().start(job)

    @Slot(object)
    def _on_launch_ready(self, payload) -> None:
        self._launch_busy = False
        self._set_launch_controls_enabled(True)
        kind = payload["kind"]
        n = len(payload["items"])
        self._append_log(f"已启动 pid={payload['pid']}，发现 {n} 个目标")
        if kind == "adb":
            self._fill_devices(("adb", payload["items"]))
            idx = self.win_combo.findData(payload["pick"])
            if idx >= 0:
                self.win_combo.setCurrentIndex(idx)
            if payload.get("auto_connect", True):
                self._connect()
            return

        self._fill_devices(("win32", payload["items"]))
        pick = payload.get("pick")
        if pick is not None:
            idx = self.win_combo.findData(pick)
            if idx >= 0:
                self.win_combo.setCurrentIndex(idx)
            title = payload.get("pick_title") or ""
            self._append_log(f"已匹配窗口: {title or pick}")
        if payload.get("auto_connect") and pick is not None:
            self._connect()
            return
        msg = payload.get("message") or "请从下拉选择正确窗口后点「连接」。"
        self.status.setText(msg)
        self._append_log(msg)
        QMessageBox.information(self, "请选择窗口", msg)

    @Slot(str)
    def _on_launch_err(self, err: str) -> None:
        self._launch_busy = False
        self._set_launch_controls_enabled(True)
        self.status.setText(f"启动并连接失败: {err}")
        self._append_log(err)
        QMessageBox.warning(self, "启动并连接失败", err)
        self.refresh_devices()

    def _load_project(self) -> None:
        path = self.project_path.text().strip()
        try:
            proj = load_pi_project(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "加载失败", str(e))
            return
        self._project = proj
        self.pi_ctrl.clear()
        for c in proj.controllers:
            self.pi_ctrl.addItem(f"{c.label} ({c.type})", c.name)
        self.pi_res.clear()
        for name, _ in proj.resources:
            self.pi_res.addItem(name, name)
        self.task_list.clear()
        for t in proj.tasks:
            item = QListWidgetItem(f"{t.label}  [{t.entry}]")
            item.setData(Qt.ItemDataRole.UserRole, t.entry)
            item.setToolTip(t.description)
            self.task_list.addItem(item)
        self._append_log(f"已解析项目 {proj.name} @ {proj.root}")
        try:
            self.pi_ctrl.currentIndexChanged.disconnect(self._on_pi_ctrl_changed)
        except (TypeError, RuntimeError):
            pass
        self.pi_ctrl.currentIndexChanged.connect(self._on_pi_ctrl_changed)
        if proj.controllers:
            self._apply_pi_controller_hint(proj.controllers[0].name)

    def _on_pi_ctrl_changed(self, _index: int = 0) -> None:
        self._apply_pi_controller_hint(self.pi_ctrl.currentData())

    def _apply_pi_controller_hint(self, name: str | None) -> None:
        if not self._project or not name:
            return
        ctrl = next((c for c in self._project.controllers if c.name == name), None)
        if not ctrl:
            return
        ctype = (ctrl.type or "").lower()
        if ctype == "win32":
            self.mode.setCurrentIndex(0)
            win = ctrl.raw.get("win32") or {}
            sc = win.get("screencap")
            if sc and self.screencap_method.findText(str(sc)) >= 0:
                self.screencap_method.setCurrentText(str(sc))
            mouse = win.get("mouse")
            if mouse and self.mouse_method.findText(str(mouse)) >= 0:
                self.mouse_method.setCurrentText(str(mouse))
            wr = win.get("window_regex")
            if wr:
                self.filter_edit.setText(str(wr).replace(".*", "").strip("^$") or str(wr))
                self.refresh_devices()
        elif ctype == "adb":
            self.mode.setCurrentIndex(1)

    def _connect(self) -> None:
        target_label = self.win_combo.currentText()
        self._append_log(f"正在连接: {target_label}")

        def work():
            ensure_library(resolve_bin_dir())
            if self.mode.currentData() == "adb":
                addr = self.win_combo.currentData()
                if addr is None:
                    raise RuntimeError("请先点「刷新」并选择 ADB 设备（需 exe 旁有 maafw\\）")
                dev = next((d for d in self._adb if d.address == addr), None)
                if not dev:
                    raise RuntimeError("请选择 ADB 设备")
                self.session.connect_adb(dev)
            else:
                hwnd = self.win_combo.currentData()
                if hwnd is None:
                    # try PI auto by window_regex
                    if self._project and self.pi_ctrl.currentData():
                        ctrl = next(
                            c
                            for c in self._project.controllers
                            if c.name == self.pi_ctrl.currentData()
                        )
                        self.session.connect_from_pi_controller(ctrl)
                    else:
                        raise RuntimeError(
                            "请先点「刷新」并从下拉选择窗口。"
                            "若列表为空：用 start.bat 从仓库根启动，并确认已运行 tools\\setup_maafw.bat"
                        )
                else:
                    self.session.connect_win32(
                        int(hwnd),
                        screencap=self.screencap_method.currentData(),
                        mouse=self.mouse_method.currentData(),
                        keyboard=self.mouse_method.currentData(),
                    )
            if self._project:
                self.session.load_project(self._project, self.pi_res.currentData())
            return target_label

        self.connect_btn.setEnabled(False)
        job = _FnJob(work)
        job.signals.ok.connect(self._on_connected)
        job.signals.err.connect(self._on_connect_err)
        QThreadPool.globalInstance().start(job)

    @Slot(object)
    def _on_connected(self, label) -> None:
        self.connect_btn.setEnabled(True)
        self.play_btn.setEnabled(True)
        text = str(label) if label and label is not True else self.win_combo.currentText()
        self.status.setText(f"已连接 · {text}")
        self._append_log(f"已连接: {text}")
        if not self._playing:
            self.start_preview()

    @Slot(str)
    def _on_connect_err(self, err: str) -> None:
        self.connect_btn.setEnabled(True)
        QMessageBox.warning(self, "连接失败", err)
        self.status.setText(f"连接失败: {err}")

    def _disconnect(self) -> None:
        self.shutdown(clear_status=True)

    def is_session_active(self) -> bool:
        """True while connected or live preview is running."""
        return bool(self.session.connected or self._playing)

    def shutdown(self, *, clear_status: bool = False) -> None:
        """Stop timers, drop frame buffers, disconnect Maa session (dialog close / 断开)."""
        self.stop_preview()
        self._task_poll.stop()
        try:
            self.session.stop_task()
        except Exception:  # noqa: BLE001
            pass
        self.session.disconnect()
        self._last_image = None
        self._busy = False
        self.canvas.clear_frame()
        self.play_btn.setEnabled(False)
        self.snap_btn.setEnabled(False)
        if clear_status:
            self.status.setText("已断开")

    def toggle_play(self) -> None:
        if self._playing:
            self.stop_preview()
        else:
            self.start_preview()

    def start_preview(self) -> None:
        if not self.session.connected:
            QMessageBox.information(self, "提示", "请先连接")
            return
        self._playing = True
        self._screencap_fail_streak = 0
        self.play_btn.setText("■ 停止预览")
        self._timer.start(self.interval.value())
        self._tick_screencap()

    def stop_preview(self) -> None:
        self._playing = False
        self._timer.stop()
        self.play_btn.setText("▶ 实时截图")

    def _tick_screencap(self) -> None:
        if self._busy or not self._playing:
            return
        self._busy = True

        def work():
            return self.session.screencap()

        job = _FnJob(work)
        job.signals.ok.connect(self._on_frame)
        job.signals.err.connect(self._on_frame_err)
        QThreadPool.globalInstance().start(job)

    @Slot(object)
    def _on_frame(self, arr) -> None:
        self._busy = False
        self._screencap_fail_streak = 0
        if not self._playing:
            return
        try:
            img = numpy_to_qimage(arr)
        except Exception as e:  # noqa: BLE001
            self.status.setText(f"帧转换失败: {e}")
            return
        self._last_image = img
        self.snap_btn.setEnabled(True)
        self.canvas.set_frame(img, self.session.boxes)
        self.status.setText(f"{img.width()}×{img.height()}  ·  MaaFW screencap")

    @staticmethod
    def _is_dead_window_err(err: str) -> bool:
        low = (err or "").lower()
        return any(
            k in low
            for k in (
                "no longer valid",
                "句柄失效",
                "窗口已关闭",
                "invalid hwnd",
                "iswindow",
            )
        )

    @Slot(str)
    def _on_frame_err(self, err: str) -> None:
        self._busy = False
        self._screencap_fail_streak += 1
        self.status.setText(f"截图失败: {err}")
        # Dead HWND: stop immediately. Other flaky failures: stop after a short streak
        # so MaaFw does not spam FramePool "Window is no longer valid" forever.
        fatal = self._is_dead_window_err(err) or self._screencap_fail_streak >= 3
        if not fatal or not self._playing:
            return
        self._recover_after_screencap_fail(err)

    def _recover_after_screencap_fail(self, err: str) -> None:
        """Stop spam, nudge user to re-pick window / safer screencap method."""
        method = str(self.screencap_method.currentData() or "")
        switched = False
        if method == "FramePool":
            self.screencap_method.setCurrentText("Background")
            switched = True
            self._conn_advanced.setChecked(True)
        self._append_log(f"预览已停止（连续截图失败）: {err}")
        if switched:
            self._append_log("已将截图方式改为 Background，请刷新窗口后重新「连接」。")
        self.shutdown(clear_status=False)
        self.connect_btn.setEnabled(True)
        tip = "已断开 · 窗口失效或截图失败。"
        if switched:
            tip += " 截图方式已改为 Background。"
        tip += " 请确认目标仍打开 → 刷新 → 选对窗口 → 再连接。"
        self.status.setText(tip)
        if self.mode.currentData() == "win32":
            self.refresh_devices()

    def _require_connected_input(self) -> bool:
        if self.session.connected:
            return True
        self.status.setText("未连接 — 请先「连接」后再操作游戏")
        self._append_log("输入忽略：尚未连接控制器")
        return False

    def _on_canvas_click(self, x: int, y: int) -> None:
        if not self._require_connected_input():
            return
        self._last_click = (x, y)

        def work():
            self.session.click(x, y)
            return (x, y)

        job = _FnJob(work)
        job.signals.ok.connect(
            lambda _p: self.status.setText(f"已点击游戏 ({x}, {y})")
        )
        job.signals.err.connect(self._on_canvas_input_err)
        QThreadPool.globalInstance().start(job)

        if self._panel_mode == "assistant" and self._asst_armed.isChecked():
            try:
                self._asst_append_click(x, y)
            except Exception as e:  # noqa: BLE001
                self._append_log(f"录制步骤失败: {e}")
        if self.rec_armed.isChecked() and self._panel_mode == "maafw":
            try:
                self._rec_capture_click(x, y)
            except Exception as e:  # noqa: BLE001
                self._append_log(f"录制失败: {e}")
                QMessageBox.warning(self, "录制失败", str(e))

    def _on_canvas_scroll(self, dx: int, dy: int) -> None:
        if not self._require_connected_input():
            return

        def work():
            self.session.scroll(dx, dy)
            return (dx, dy)

        job = _FnJob(work)
        job.signals.err.connect(self._on_canvas_input_err)
        QThreadPool.globalInstance().start(job)

    def _on_canvas_touch_down(self, x: int, y: int) -> None:
        if not self._require_connected_input():
            return
        self._last_click = (x, y)
        try:
            self.session.touch_down(x, y)
            self.status.setText(f"拖拽中… ({x}, {y})")
        except Exception as e:  # noqa: BLE001
            self._on_canvas_input_err(str(e))

    def _on_canvas_touch_move(self, x: int, y: int) -> None:
        if not self.session.connected:
            return
        try:
            self.session.touch_move(x, y)
        except Exception as e:  # noqa: BLE001
            self._append_log(f"拖拽移动失败: {e}")

    def _on_canvas_touch_up(self) -> None:
        if not self.session.connected:
            return
        try:
            self.session.touch_up()
            self.status.setText("拖拽结束")
        except Exception as e:  # noqa: BLE001
            self._on_canvas_input_err(str(e))

    @Slot(str)
    def _on_canvas_input_err(self, err: str) -> None:
        self._append_log(f"游戏输入失败: {err}")
        self.status.setText(f"游戏输入失败: {err}")

    def _rec_refresh_list(self) -> None:
        row = self.rec_list.currentRow()
        self.rec_list.clear()
        for i, st in enumerate(self._recording.steps):
            tag = "OR·" if st.or_with_prev else f"{i + 1}."
            if st.kind == "wait":
                text = f"{tag} 等待 {st.delay_ms}ms"
            elif st.kind == "click_template":
                text = f"{tag} 模板 {st.name} @({st.x},{st.y})"
            else:
                text = f"{tag} 坐标 {st.name} ({st.x},{st.y})"
            self.rec_list.addItem(text)
        n = len(self._recording.steps)
        self.rec_status.setText(
            f"共 {n} 步 · 默认模板裁切" if n else "尚无步骤 — 勾选录制中后点右侧截图"
        )
        if 0 <= row < n:
            self.rec_list.setCurrentRow(row)
        elif n:
            self.rec_list.setCurrentRow(n - 1)

    def _rec_on_row(self, row: int) -> None:
        if row < 0 or row >= len(self._recording.steps):
            return
        st = self._recording.steps[row]
        self._rec_loading = True
        try:
            self.rec_edit_name.setText(st.name or "")
            self.rec_edit_x.setValue(int(st.x))
            self.rec_edit_y.setValue(int(st.y))
            self.rec_edit_delay.setValue(int(st.delay_ms))
        finally:
            self._rec_loading = False

    def _rec_apply_editor(self, *_args) -> None:
        if self._rec_loading:
            return
        row = self.rec_list.currentRow()
        if row < 0 or row >= len(self._recording.steps):
            return
        st = self._recording.steps[row]
        st.name = self.rec_edit_name.text().strip() or st.name
        old_x, old_y = int(st.x), int(st.y)
        st.x = int(self.rec_edit_x.value())
        st.y = int(self.rec_edit_y.value())
        st.delay_ms = int(self.rec_edit_delay.value())
        if st.kind == "click_template" and (st.x != old_x or st.y != old_y):
            try:
                self._rec_recrop_step(st)
            except Exception as e:  # noqa: BLE001
                self._append_log(f"重裁模板失败: {e}")
        self._rec_refresh_list()

    def _rec_move(self, delta: int) -> None:
        row = self.rec_list.currentRow()
        j = row + delta
        steps = self._recording.steps
        if row < 0 or j < 0 or j >= len(steps):
            return
        steps[row], steps[j] = steps[j], steps[row]
        self._rec_refresh_list()
        self.rec_list.setCurrentRow(j)

    def _rec_recrop_step(self, st: RecordStep) -> None:
        if st.kind != "click_template":
            return
        if self._last_image is None:
            raise RuntimeError("请先开实时截图再覆盖/重裁模板")
        root = Path(self.project_path.text().strip() or ".")
        img_dir = root / "resource" / "image"
        fname = st.template or f"rec_{datetime_stamp()}_{st.name}.png"
        dest = img_dir / Path(fname).name
        _, crop_box = crop_template_png(
            self._last_image, int(st.x), int(st.y), int(self.rec_half.value()), dest
        )
        st.template = dest.name
        pad = max(8, int(self.rec_half.value()) // 2)
        iw = self._last_image.width()
        ih = self._last_image.height()
        rx = max(0, crop_box[0] - pad)
        ry = max(0, crop_box[1] - pad)
        rw = min(iw - rx, crop_box[2] + pad * 2)
        rh = min(ih - ry, crop_box[3] + pad * 2)
        st.roi = (rx, ry, rw, rh)
        st.desc = f"录制点击 ({st.x},{st.y})"
        self._append_log(f"已重裁模板 {dest}")

    def _rec_cover_last_click(self) -> None:
        if not self._last_click:
            QMessageBox.information(self, "提示", "请先在右侧实时截图上点一下")
            return
        row = self.rec_list.currentRow()
        if row < 0 or row >= len(self._recording.steps):
            QMessageBox.information(self, "提示", "请先选中左侧一步")
            return
        st = self._recording.steps[row]
        if st.kind == "wait":
            QMessageBox.information(self, "提示", "等待步没有坐标")
            return
        x, y = self._last_click
        st.x, st.y = int(x), int(y)
        if st.kind == "click_template":
            try:
                self._rec_recrop_step(st)
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(self, "重裁失败", str(e))
                return
        self._rec_refresh_list()
        self.rec_list.setCurrentRow(row)
        self._rec_on_row(row)

    def _rec_capture_click(self, x: int, y: int) -> None:
        kind = self.rec_mode.currentData()
        or_flag = self.rec_or.isChecked()
        n = len(self._recording.steps) + 1
        name = f"RecClick{n}"
        template = ""
        if kind == "click_template":
            if self._last_image is None:
                raise RuntimeError("请先开实时截图，再点画面录制模板")
            root = Path(self.project_path.text().strip() or ".")
            img_dir = root / "resource" / "image"
            fname = f"rec_{datetime_stamp()}_{n:02d}.png"
            dest = img_dir / fname
            _, crop_box = crop_template_png(
                self._last_image, x, y, int(self.rec_half.value()), dest
            )
            template = fname
            pad = max(8, int(self.rec_half.value()) // 2)
            iw = self._last_image.width()
            ih = self._last_image.height()
            rx = max(0, crop_box[0] - pad)
            ry = max(0, crop_box[1] - pad)
            rw = min(iw - rx, crop_box[2] + pad * 2)
            rh = min(ih - ry, crop_box[3] + pad * 2)
            roi_box = (rx, ry, rw, rh)
            self._append_log(f"已裁模板 {dest} roi={roi_box}")
        else:
            roi_box = (0, 0, 0, 0)
        step = RecordStep(
            kind=kind if kind in ("click_template", "click_xy") else "click_xy",
            name=name,
            x=int(x),
            y=int(y),
            delay_ms=500,
            or_with_prev=bool(or_flag) and bool(self._recording.steps),
            template=template,
            desc=f"录制点击 ({x},{y})",
            roi=roi_box,
        )
        if kind == "click_template" and template:
            step.kind = "click_template"
        else:
            step.kind = "click_xy"
        self._recording.add(step)
        # one-shot OR flag
        self.rec_or.setChecked(False)
        self._rec_refresh_list()

    def _rec_add_wait(self) -> None:
        ms, ok = 800, True
        from PySide6.QtWidgets import QInputDialog

        ms, ok = QInputDialog.getInt(self, "等待", "毫秒:", 800, 0, 60000, 100)
        if not ok:
            return
        n = len(self._recording.steps) + 1
        self._recording.add(
            RecordStep(
                kind="wait",
                name=f"RecWait{n}",
                delay_ms=int(ms),
                or_with_prev=False,
                desc=f"等待 {ms}ms",
            )
        )
        self._rec_refresh_list()

    def _rec_delete(self) -> None:
        row = self.rec_list.currentRow()
        if row < 0 or row >= len(self._recording.steps):
            return
        self._recording.steps.pop(row)
        self._rec_refresh_list()

    def _rec_clear(self) -> None:
        self._recording.clear()
        self._rec_refresh_list()

    def _rec_export(self) -> None:
        if not self._recording.steps:
            QMessageBox.information(self, "提示", "还没有录制步骤")
            return
        root = Path(self.project_path.text().strip())
        if not (root / "interface.json").is_file():
            QMessageBox.warning(self, "提示", "请先在上方选择并「加载」含 interface.json 的 PI 项目")
            return
        self._recording.task_label = self.rec_task_name.text().strip() or "录制草稿"
        self._recording.entry_name = "RecStart"
        try:
            info = export_pipeline(root, self._recording, register_task=True)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "导出失败", str(e))
            return
        entry = str(info.get("entry") or "")
        self._last_export_entry = entry
        self._append_log(f"已导出 {info['pipeline_path']} entry={entry}")
        try:
            self._load_project()
        except Exception:  # noqa: BLE001
            pass
        # Prefer matching hidden task row for bookkeeping
        for i in range(self.task_list.count()):
            item = self.task_list.item(i)
            if not item:
                continue
            if str(item.data(Qt.ItemDataRole.UserRole) or "") == entry:
                self.task_list.setCurrentRow(i)
                break

        box = QMessageBox(self)
        box.setWindowTitle("已导出")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(
            f"pipeline:\n{info['pipeline_path']}\n\n"
            f"任务「{info['task_name']}」已写入 interface.json\n"
            f"入口节点: {entry}"
        )
        box.setInformativeText(
            "可立刻进程内试跑验证识图；无人值守仍用主台队列 / MaaPiCli。"
            "复杂分支可用 MaaPipelineEditor 精修。"
        )
        trial_btn = box.addButton("试跑刚导出的任务", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("关闭", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() == trial_btn:
            self._run_task_entry(entry)

    def _run_task(self) -> None:
        item = self.task_list.currentItem()
        if not item:
            if self._last_export_entry:
                self._run_task_entry(self._last_export_entry)
                return
            QMessageBox.information(self, "提示", "请先导出任务，或从导出对话框点试跑")
            return
        entry = item.data(Qt.ItemDataRole.UserRole)
        self._run_task_entry(str(entry))

    def _run_task_entry(self, entry: str) -> None:
        entry = (entry or "").strip()
        if not entry:
            QMessageBox.information(self, "提示", "没有可试跑的入口")
            return
        if not self.session.tasker:
            if self._project and self.session.connected:
                try:
                    self.session.load_project(self._project, self.pi_res.currentData())
                except Exception as e:  # noqa: BLE001
                    QMessageBox.warning(self, "加载资源失败", str(e))
                    return
            else:
                QMessageBox.information(self, "提示", "请先加载 PI 项目并连接窗口")
                return
        try:
            self.session.run_task(entry)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "启动失败", str(e))
            return
        self._append_log(f"试跑任务 entry={entry}")
        self._task_poll.start()
        if not self._playing:
            self.start_preview()

    def _stop_task(self) -> None:
        self.session.stop_task()
        self._append_log("已请求停止任务")

    def _poll_task(self) -> None:
        if self.session.task_running:
            return
        self._task_poll.stop()
        self._append_log("任务已结束")

    def save_frame(self) -> None:
        if self._last_image is None:
            return
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            self, "保存截图", str(LOGS_DIR / "preview_shot.png"), "PNG (*.png)"
        )
        if path and self._last_image.save(path, "PNG"):
            self._append_log(f"已保存 {path}")

    def hideEvent(self, event) -> None:  # noqa: N802
        if self._playing:
            self.stop_preview()
        super().hideEvent(event)


def datetime_stamp() -> str:
    from datetime import datetime

    return datetime.now().strftime("%H%M%S")
