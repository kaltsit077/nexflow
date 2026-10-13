"""Single queue-step card for the main dashboard."""
from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)


class StepCard(QFrame):
    configure = Signal(int)
    edit_script = Signal(int)
    remove = Signal(int)
    run_one = Signal(int)
    move_up = Signal(int)
    move_down = Signal(int)

    def __init__(
        self,
        index: int,
        step: dict[str, Any],
        script: Optional[dict[str, Any]] = None,
        *,
        can_up: bool = True,
        can_down: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.index = index
        self.setObjectName("stepCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 10, 10, 10)
        root.setSpacing(8)

        order = QVBoxLayout()
        order.setSpacing(2)
        btn_up = QPushButton("▲")
        btn_up.setObjectName("chevron")
        btn_up.setFixedWidth(28)
        btn_up.setEnabled(can_up)
        btn_up.setToolTip("上移")
        btn_up.clicked.connect(lambda: self.move_up.emit(self.index))
        btn_dn = QPushButton("▼")
        btn_dn.setObjectName("chevron")
        btn_dn.setFixedWidth(28)
        btn_dn.setEnabled(can_down)
        btn_dn.setToolTip("下移")
        btn_dn.clicked.connect(lambda: self.move_down.emit(self.index))
        order.addWidget(btn_up)
        order.addWidget(btn_dn)
        root.addLayout(order)

        num = QLabel(str(index + 1))
        num.setObjectName("stepNum")
        num.setFixedWidth(22)
        root.addWidget(num)

        mid = QVBoxLayout()
        mid.setSpacing(4)
        name = (script or {}).get("name") or step.get("script", "?")
        title = QLabel(name)
        title.setObjectName("stepTitle")
        mid.addWidget(title)

        stype = (script or {}).get("type", "")
        sid = step.get("script", "")
        meta_parts = [sid]
        if stype:
            meta_parts.append(stype)
        if step.get("preset"):
            meta_parts.append(f"preset={step['preset']}")
        meta_parts.append(f"on_fail={step.get('on_fail', 'stop')}")
        if step.get("retry"):
            meta_parts.append(f"retry={step['retry']}")
        if step.get("fallback_script"):
            meta_parts.append(f"fallback={step['fallback_script']}")
        summary = QLabel(" · ".join(meta_parts))
        summary.setObjectName("muted")
        summary.setWordWrap(True)
        mid.addWidget(summary)
        root.addLayout(mid, 1)

        if stype:
            badge = QLabel(stype)
            badge.setObjectName("badge")
            root.addWidget(badge)

        btn_run = QPushButton("跑")
        btn_run.setObjectName("ghost")
        btn_run.setToolTip("只运行这一脚本（不经整队）")
        btn_run.clicked.connect(lambda: self.run_one.emit(self.index))
        root.addWidget(btn_run)

        btn_edit = QPushButton("编辑")
        btn_edit.setObjectName("linkish")
        btn_edit.setToolTip("改路径 / 录制 / 连控（与脚本库「编辑」同一窗）")
        btn_edit.clicked.connect(lambda: self.edit_script.emit(self.index))
        root.addWidget(btn_edit)

        btn_cfg = QPushButton("队列参数")
        btn_cfg.setObjectName("linkish")
        btn_cfg.setToolTip("本步失败重试 / 备用 / preset（不改脚本本体）")
        btn_cfg.clicked.connect(lambda: self.configure.emit(self.index))
        root.addWidget(btn_cfg)

        btn_del = QPushButton("删除")
        btn_del.setObjectName("danger")
        btn_del.clicked.connect(lambda: self.remove.emit(self.index))
        root.addWidget(btn_del)
