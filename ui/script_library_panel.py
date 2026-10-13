"""Right-hand script library: list scripts and add into a target queue."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QDrag, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

SCRIPT_MIME = "application/x-gamerunner-script"


class ScriptRow(QFrame):
    add_to = Signal(str)
    edit = Signal(str)
    open_dir = Signal(str)
    launch = Signal(str)

    def __init__(
        self,
        script: dict[str, Any],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.script_id = script["id"]
        self._drag_start = None
        self.setObjectName("scriptRow")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setToolTip("拖到左侧队列可加入；目录=资源管理器；启动=单跑此脚本")

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 8, 8, 8)
        root.setSpacing(6)

        mid = QVBoxLayout()
        mid.setSpacing(2)
        title = QLabel(script.get("name") or self.script_id)
        title.setObjectName("scriptName")
        mid.addWidget(title)
        meta = QLabel(f"{self.script_id} · {script.get('type', '?')}")
        meta.setObjectName("muted")
        meta.setWordWrap(True)
        mid.addWidget(meta)
        root.addLayout(mid, 1)

        stype = script.get("type") or ""
        if stype:
            badge = QLabel(stype)
            badge.setObjectName("badge")
            root.addWidget(badge)

        btn_dir = QPushButton("目录")
        btn_dir.setObjectName("linkish")
        btn_dir.setToolTip("在资源管理器中打开项目/工作目录")
        btn_dir.clicked.connect(lambda: self.open_dir.emit(self.script_id))
        root.addWidget(btn_dir)

        btn_run = QPushButton("启动")
        btn_run.setObjectName("linkish")
        btn_run.setToolTip("立即运行此脚本（不经队列）")
        btn_run.clicked.connect(lambda: self.launch.emit(self.script_id))
        root.addWidget(btn_run)

        btn_edit = QPushButton("编辑")
        btn_edit.setToolTip("一窗：基本字段 + maafw 录制/连控")
        btn_edit.setObjectName("linkish")
        btn_edit.clicked.connect(lambda: self.edit.emit(self.script_id))
        root.addWidget(btn_edit)

        btn_add = QPushButton("加入")
        btn_add.setObjectName("primary")
        btn_add.setToolTip("加入左侧当前选中的队列（也可拖拽到队列）")
        btn_add.clicked.connect(lambda: self.add_to.emit(self.script_id))
        root.addWidget(btn_add)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_start = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._drag_start is not None
            and event.buttons() & Qt.LeftButton
            and (event.position().toPoint() - self._drag_start).manhattanLength() >= 8
        ):
            drag = QDrag(self)
            mime = QMimeData()
            mime.setData(SCRIPT_MIME, self.script_id.encode("utf-8"))
            mime.setText(self.script_id)
            drag.setMimeData(mime)
            drag.exec(Qt.CopyAction)
            self._drag_start = None
            return
        super().mouseMoveEvent(event)


class ScriptLibraryPanel(QWidget):
    add_script = Signal(str)
    add_script_to = Signal(str, str)
    edit_script = Signal(str)
    open_script_dir = Signal(str)
    launch_script = Signal(str)
    manage_scripts = Signal()
    new_script = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel("素材 · 脚本库")
        title.setObjectName("zoneTitle")
        head.addWidget(title)
        self.count_label = QLabel("0")
        self.count_label.setObjectName("badge")
        head.addWidget(self.count_label)
        head.addStretch(1)
        btn_new = QPushButton("+ 新建")
        btn_new.clicked.connect(self.new_script.emit)
        head.addWidget(btn_new)
        btn_mgr = QPushButton("管理…")
        btn_mgr.clicked.connect(self.manage_scripts.emit)
        head.addWidget(btn_mgr)
        root.addLayout(head)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("筛选名称 / id / 类型…")
        self.filter_edit.textChanged.connect(self._apply_filter)
        root.addWidget(self.filter_edit)

        self.target_hint = QLabel("目标：—")
        self.target_hint.setObjectName("muted")
        root.addWidget(self.target_hint)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.host = QWidget()
        self.host.setObjectName("cardsHost")
        self.host_l = QVBoxLayout(self.host)
        self.host_l.setContentsMargins(2, 2, 2, 2)
        self.host_l.setSpacing(6)
        self.host_l.addStretch(1)
        self.scroll.setWidget(self.host)
        root.addWidget(self.scroll, 1)

        self._scripts: list[dict[str, Any]] = []
        self._queue_names: list[str] = []
        self._active_queue = ""

    def set_active_queue(self, name: str) -> None:
        self._active_queue = name or ""
        self.target_hint.setText(
            f"加入目标：{self._active_queue}"
            if self._active_queue
            else "点左侧队列标题设为加入目标"
        )

    def reload(self, scripts: list[dict[str, Any]], queue_names: list[str]) -> None:
        self._scripts = list(scripts)
        self._queue_names = list(queue_names)
        self.count_label.setText(str(len(self._scripts)))
        self._rebuild_rows()

    def _apply_filter(self, _text: str = "") -> None:
        self._rebuild_rows()

    def _rebuild_rows(self) -> None:
        while self.host_l.count():
            item = self.host_l.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        needle = self.filter_edit.text().strip().lower()
        shown = 0
        for s in self._scripts:
            blob = f"{s.get('name','')} {s.get('id','')} {s.get('type','')}".lower()
            if needle and needle not in blob:
                continue
            row = ScriptRow(s)
            row.add_to.connect(self.add_script.emit)
            row.edit.connect(self.edit_script.emit)
            row.open_dir.connect(self.open_script_dir.emit)
            row.launch.connect(self.launch_script.emit)
            self.host_l.addWidget(row)
            shown += 1

        if shown == 0:
            tip = QLabel("暂无脚本 · 用顶栏「导入」或「+ 新建」")
            tip.setObjectName("muted")
            self.host_l.addWidget(tip)
        self.host_l.addStretch(1)
