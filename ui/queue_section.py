"""Collapsible queue block: header + step cards (+ drop target)."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QMouseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ui.script_library_panel import SCRIPT_MIME
from ui.step_card import StepCard


class _Header(QFrame):
    clicked = Signal()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class QueueSection(QFrame):
    """One foldable queue with its steps."""

    toggled = Signal(str, bool)
    activated = Signal(str)
    delete_queue = Signal(str)
    rename_queue = Signal(str)
    configure_step = Signal(str, int)
    edit_step_script = Signal(str, int)
    remove_step = Signal(str, int)
    run_step = Signal(str, int)
    move_step = Signal(str, int, int)  # list_name, index, delta (+1/-1)
    script_dropped = Signal(str, str)  # script_id, list_name
    # list_name, mode, max_parallel
    settings_changed = Signal(str, str, int)

    def __init__(
        self,
        list_name: str,
        steps: list[dict[str, Any]],
        scripts_by_id: dict[str, dict[str, Any]],
        *,
        expanded: bool = True,
        active: bool = False,
        mode: str = "sequential",
        max_parallel: int = 2,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.list_name = list_name
        self._expanded = expanded
        self._syncing = False
        self.setObjectName("queueSection")
        self.setProperty("activeQueue", "true" if active else "false")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.setAcceptDrops(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = _Header()
        header.setObjectName("queueHeader")
        header.setCursor(Qt.PointingHandCursor)
        header.clicked.connect(lambda: self.activated.emit(self.list_name))
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 8, 8, 8)
        hl.setSpacing(6)

        self.chevron = QPushButton("▼" if expanded else "▶")
        self.chevron.setObjectName("chevron")
        self.chevron.setFixedWidth(28)
        self.chevron.clicked.connect(self._toggle)
        hl.addWidget(self.chevron)

        self.title = QLabel(list_name)
        self.title.setObjectName("queueTitle")
        hl.addWidget(self.title, 1)

        count = QLabel(f"{len(steps)} 步")
        count.setObjectName("badge")
        hl.addWidget(count)

        btn_rename = QPushButton("改名")
        btn_rename.setObjectName("linkish")
        btn_rename.clicked.connect(lambda: self.rename_queue.emit(self.list_name))
        hl.addWidget(btn_rename)

        btn_del = QPushButton("删除")
        btn_del.setObjectName("danger")
        btn_del.clicked.connect(lambda: self.delete_queue.emit(self.list_name))
        hl.addWidget(btn_del)

        root.addWidget(header)

        self.body = QWidget()
        self.body.setObjectName("queueBody")
        bl = QVBoxLayout(self.body)
        bl.setContentsMargins(8, 4, 8, 10)
        bl.setSpacing(6)

        opts = QHBoxLayout()
        opts.setSpacing(6)
        opts.addWidget(QLabel("模式"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("顺序", "sequential")
        self.mode_combo.addItem("并行", "parallel")
        mi = self.mode_combo.findData(
            "parallel" if str(mode).lower() == "parallel" else "sequential"
        )
        self.mode_combo.setCurrentIndex(mi if mi >= 0 else 0)
        self.mode_combo.setToolTip("并行：不同 lane 可同开；同名 lane 互斥")
        self.mode_combo.currentIndexChanged.connect(self._emit_settings)
        opts.addWidget(self.mode_combo)

        self.max_label = QLabel("最多")
        opts.addWidget(self.max_label)
        self.max_spin = QSpinBox()
        self.max_spin.setRange(1, 8)
        self.max_spin.setValue(max(1, min(8, int(max_parallel or 2))))
        self.max_spin.setToolTip("并行时最多同时跑几路（默认 2）")
        self.max_spin.valueChanged.connect(self._emit_settings)
        opts.addWidget(self.max_spin)
        opts.addStretch(1)
        bl.addLayout(opts)
        self._sync_parallel_widgets()

        if not steps:
            tip = QLabel("空 · 从右侧加入或拖入脚本")
            tip.setObjectName("muted")
            bl.addWidget(tip)
        else:
            n = len(steps)
            for i, step in enumerate(steps):
                card = StepCard(
                    i,
                    step,
                    scripts_by_id.get(step.get("script", "")),
                    can_up=i > 0,
                    can_down=i < n - 1,
                )
                card.configure.connect(
                    lambda idx, nm=list_name: self.configure_step.emit(nm, idx)
                )
                card.edit_script.connect(
                    lambda idx, nm=list_name: self.edit_step_script.emit(nm, idx)
                )
                card.remove.connect(
                    lambda idx, nm=list_name: self.remove_step.emit(nm, idx)
                )
                card.run_one.connect(
                    lambda idx, nm=list_name: self.run_step.emit(nm, idx)
                )
                card.move_up.connect(
                    lambda idx, nm=list_name: self.move_step.emit(nm, idx, -1)
                )
                card.move_down.connect(
                    lambda idx, nm=list_name: self.move_step.emit(nm, idx, 1)
                )
                bl.addWidget(card)

        root.addWidget(self.body)
        self.body.setVisible(expanded)

    def _sync_parallel_widgets(self) -> None:
        parallel = self.mode_combo.currentData() == "parallel"
        self.max_label.setVisible(parallel)
        self.max_spin.setVisible(parallel)

    def _emit_settings(self, *_args: Any) -> None:
        if self._syncing:
            return
        self._sync_parallel_widgets()
        mode = str(self.mode_combo.currentData() or "sequential")
        self.settings_changed.emit(self.list_name, mode, int(self.max_spin.value()))

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        self.chevron.setText("▼" if self._expanded else "▶")
        self.body.setVisible(self._expanded)
        self.toggled.emit(self.list_name, self._expanded)

    def set_active(self, active: bool) -> None:
        self.setProperty("activeQueue", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasFormat(SCRIPT_MIME) or event.mimeData().hasText():
            event.acceptProposedAction()
            self.setProperty("dropHover", "true")
            self.style().unpolish(self)
            self.style().polish(self)
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self.setProperty("dropHover", "false")
        self.style().unpolish(self)
        self.style().polish(self)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self.setProperty("dropHover", "false")
        self.style().unpolish(self)
        self.style().polish(self)
        mime = event.mimeData()
        sid = ""
        if mime.hasFormat(SCRIPT_MIME):
            sid = bytes(mime.data(SCRIPT_MIME)).decode("utf-8").strip()
        elif mime.hasText():
            sid = mime.text().strip()
        if sid:
            self.activated.emit(self.list_name)
            self.script_dropped.emit(sid, self.list_name)
            event.acceptProposedAction()
        else:
            event.ignore()
