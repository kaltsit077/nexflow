"""Shared dialog sizing so content scrolls and footers stay on screen."""
from __future__ import annotations

from typing import Iterable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLayout,
    QPushButton,
    QScrollArea,
    QWidget,
)

from ui.styles import GAP, PAD

# Title-row height when a checkable QGroupBox is collapsed (QSS padding otherwise
# leaves a tall empty SURFACE card — see Advanced / 日志 in ②).
_COLLAPSED_GROUP_H = 40


def fit_dialog(
    dialog: QDialog,
    width: int,
    height: int,
    *,
    margin: int = 48,
    min_width: int = 480,
    min_height: int = 320,
) -> None:
    """Resize within the screen availableGeometry; enable size grip."""
    screen = dialog.screen()
    if screen is None:
        app = QApplication.instance()
        screen = app.primaryScreen() if app is not None else None
    max_w, max_h = width, height
    if screen is not None:
        ag = screen.availableGeometry()
        max_w = max(min_width, ag.width() - margin)
        max_h = max(min_height, ag.height() - margin)
        dialog.setMaximumSize(max_w, max_h)
    dialog.setMinimumSize(min(min_width, max_w), min(min_height, max_h))
    dialog.resize(min(width, max_w), min(height, max_h))
    dialog.setSizeGripEnabled(True)


def scroll_page(inner: QWidget) -> QScrollArea:
    """Wrap dense dialog body so a sibling footer bar can remain visible.

    ``setWidgetResizable(True)`` lets the page use viewport width, but the
    inner widget must declare a real ``minimumSize`` / ``sizeHint`` taller than
    the viewport — otherwise Qt shrinks content (e.g. preview) into a flat strip
    and there is nothing useful to scroll.
    """
    sc = QScrollArea()
    sc.setWidgetResizable(True)
    sc.setFrameShape(QFrame.Shape.NoFrame)
    sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    sc.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    sc.setContentsMargins(0, 0, 0, 0)
    inner.setContentsMargins(0, 0, 0, 0)
    sc.setWidget(inner)
    sc.setMinimumHeight(0)
    return sc


def bind_collapsible_group(
    box: QGroupBox,
    *,
    collapsed_height: int = _COLLAPSED_GROUP_H,
) -> None:
    """Clamp checkable QGroupBox to a title row when unchecked.

    Qt hides children on uncheck, but QSS padding/margin still paints a large
    empty card and steals vertical space from the preview workspace.
    """
    if not box.isCheckable():
        return

    def _apply(checked: bool) -> None:
        if checked:
            box.setMaximumHeight(16777215)
        else:
            box.setMaximumHeight(max(24, collapsed_height))
        box.updateGeometry()

    box.toggled.connect(_apply)
    _apply(box.isChecked())


def dialog_margins(layout: QLayout) -> None:
    layout.setContentsMargins(PAD, PAD, PAD, PAD)
    layout.setSpacing(GAP)


def footer_bar(
    parent_layout: QLayout,
    buttons: Iterable[QPushButton],
    *,
    dialog: Optional[QDialog] = None,
    add_close: bool = False,
) -> QHBoxLayout:
    """Bottom action row: primary actions first, optional 关闭, then stretch."""
    bar = QHBoxLayout()
    for btn in buttons:
        bar.addWidget(btn)
    if add_close:
        if dialog is None:
            raise ValueError("add_close requires dialog=")
        close_btn = QPushButton("关闭")
        close_btn.setObjectName("ghost")
        close_btn.clicked.connect(dialog.accept)
        bar.addWidget(close_btn)
    bar.addStretch(1)
    parent_layout.addLayout(bar)
    return bar
