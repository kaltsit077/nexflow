"""Popup dialogs: import, step (queue params), history. Script edit → script_editor."""
from __future__ import annotations

from typing import Any, Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from runner.catalog import detect_tool
from runner.config import load_history
from ui.dialog_chrome import dialog_margins, fit_dialog, footer_bar
from ui.script_editor import ScriptDialog, ScriptEditorDialog
from ui import styles

__all__ = [
    "ScriptDialog",
    "ScriptEditorDialog",
    "ImportDialog",
    "StepDialog",
    "HistoryDialog",
]


class ImportDialog(QDialog):
    def __init__(
        self,
        cfg: dict[str, Any],
        save_cfg: Callable[[dict], None],
        open_script_editor: Optional[Callable[[dict], None]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("导入工具 / MaaFW 项目")
        fit_dialog(self, 560, 240, min_width=420, min_height=200)
        self.cfg = cfg
        self._save_cfg = save_cfg
        self._open_script_editor = open_script_editor
        self._last: Optional[dict[str, Any]] = None

        root = QVBoxLayout(self)
        dialog_margins(root)
        form = QFormLayout()
        path_row = QHBoxLayout()
        self.path = QLineEdit()
        self.path.setPlaceholderText("选择工具目录、exe 或 interface.json")
        b_folder = QPushButton("选文件夹")
        b_folder.clicked.connect(self._browse_folder)
        b_file = QPushButton("选文件")
        b_file.clicked.connect(self._browse_file)
        path_row.addWidget(self.path, 1)
        path_row.addWidget(b_folder)
        path_row.addWidget(b_file)
        form.addRow("路径", path_row)
        root.addLayout(form)

        self.hint = QLabel(
            "支持 MAA / BetterGI / 三月七 / ok-ww / LCBA / Alas / interface.json"
        )
        self.hint.setWordWrap(True)
        self.hint.setObjectName("muted")
        root.addWidget(self.hint)

        detect_btn = QPushButton("识别")
        detect_btn.clicked.connect(lambda: self._run(False))
        add_btn = QPushButton("导入并保存")
        add_btn.setObjectName("primary")
        add_btn.clicked.connect(lambda: self._run(True))
        footer_bar(root, [detect_btn, add_btn], dialog=self, add_close=True)

    def _browse_folder(self) -> None:
        p = QFileDialog.getExistingDirectory(self, "选择工具目录")
        if p:
            self.path.setText(p)

    def _browse_file(self) -> None:
        p, _ = QFileDialog.getOpenFileName(
            self, "选择文件", "", "All (*.*);;Executable (*.exe);;JSON (*.json)"
        )
        if p:
            self.path.setText(p)

    def _run(self, add: bool) -> None:
        path = self.path.text().strip()
        if not path:
            QMessageBox.warning(self, "提示", "先选择路径")
            return
        result = detect_tool(path)
        if not result.get("ok"):
            QMessageBox.critical(self, "识别失败", result.get("error") or "unknown")
            return
        script = dict(result["script"])
        notes = "; ".join(result.get("notes") or [])
        hint = f'{result["label"]} → id={script["id"]}' + (f" | {notes}" if notes else "")
        self._last = script
        if not add:
            self.hint.setText(hint + " | 可继续「导入并保存」，或打开编辑微调（含录制）")
            if self._open_script_editor:
                self._open_script_editor(script)
            return
        existing = {s["id"] for s in self.cfg["scripts"]}
        sid = script["id"]
        base = sid
        n = 2
        while sid in existing:
            sid = f"{base}_{n}"
            n += 1
        script["id"] = sid
        self.cfg["scripts"].append(script)
        self._save_cfg(self.cfg)
        self.hint.setText(hint + f" | 已导入为 {sid}")
        QMessageBox.information(self, "已导入", f"脚本 id = {sid}")
        self.accept()


class StepDialog(QDialog):
    """Queue-step params only (retry / on_fail / …). Script body → 编辑脚本."""

    def __init__(
        self,
        cfg: dict[str, Any],
        step: Optional[dict[str, Any]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("队列参数" if step else "添加步骤")
        fit_dialog(self, 440, 360, min_width=360, min_height=280)
        self.cfg = cfg
        step = step or {}

        form = QFormLayout(self)
        form.setContentsMargins(12, 12, 12, 12)
        form.setSpacing(12)
        self.script = QComboBox()
        for s in cfg.get("scripts", []):
            self.script.addItem(f'{s["name"]} ({s["id"]})', s["id"])
        cur = step.get("script")
        if cur:
            idx = self.script.findData(cur)
            if idx >= 0:
                self.script.setCurrentIndex(idx)

        self.on_fail = QComboBox()
        self.on_fail.addItems(["stop", "continue"])
        of = step.get("on_fail", "stop")
        i = self.on_fail.findText(of)
        if i >= 0:
            self.on_fail.setCurrentIndex(i)

        self.retry = QSpinBox()
        self.retry.setRange(0, 20)
        self.retry.setValue(int(step.get("retry") or 0))

        self.preset = QComboBox()
        self.preset.setEditable(True)
        self._refresh_presets()
        self.script.currentIndexChanged.connect(self._refresh_presets)
        if step.get("preset"):
            self.preset.setCurrentText(step["preset"])

        self.fallback = QComboBox()
        self.fallback.addItem("（无）", "")
        for s in cfg.get("scripts", []):
            self.fallback.addItem(f'{s["name"]} ({s["id"]})', s["id"])
        fb = step.get("fallback_script", "")
        if fb:
            i = self.fallback.findData(fb)
            if i >= 0:
                self.fallback.setCurrentIndex(i)

        self.wait_mode = QComboBox()
        self.wait_mode.addItem("跟随脚本", "")
        self.wait_mode.addItem("等进程退出 wait_exit", "wait_exit")
        self.wait_mode.addItem("只启动继续 launch", "launch")
        wcur = step.get("wait_mode", "")
        wi = self.wait_mode.findData(wcur)
        if wi >= 0:
            self.wait_mode.setCurrentIndex(wi)

        tip = QLabel("改路径/录制请回脚本库点「编辑」。此处只调本步在队列里的行为。")
        tip.setObjectName("muted")
        tip.setWordWrap(True)
        form.addRow(tip)
        form.addRow("脚本", self.script)
        form.addRow("失败时", self.on_fail)
        form.addRow("重试", self.retry)
        form.addRow("预设", self.preset)
        form.addRow("等待模式", self.wait_mode)
        form.addRow("备用脚本", self.fallback)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok_btn = buttons.button(QDialogButtonBox.Ok)
        cancel_btn = buttons.button(QDialogButtonBox.Cancel)
        if ok_btn:
            ok_btn.setText("确定")
        if cancel_btn:
            cancel_btn.setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _refresh_presets(self) -> None:
        sid = self.script.currentData()
        self.preset.blockSignals(True)
        cur = self.preset.currentText()
        self.preset.clear()
        self.preset.addItem("")
        for s in self.cfg.get("scripts", []):
            if s["id"] == sid:
                for p in s.get("presets") or []:
                    pid = p.get("id", "")
                    name = p.get("name") or pid
                    self.preset.addItem(f"{pid} — {name}" if name != pid else pid, pid)
                break
        if cur:
            found = False
            for i in range(self.preset.count()):
                if self.preset.itemData(i) == cur or self.preset.itemText(i).startswith(cur):
                    self.preset.setCurrentIndex(i)
                    found = True
                    break
            if not found:
                self.preset.setEditText(cur)
        self.preset.blockSignals(False)

    def result_step(self) -> dict[str, Any]:
        sid = self.script.currentData()
        out: dict[str, Any] = {
            "script": sid,
            "on_fail": self.on_fail.currentText(),
            "retry": self.retry.value(),
        }
        preset = self.preset.currentData()
        if not preset:
            text = self.preset.currentText().strip()
            if " — " in text:
                preset = text.split(" — ", 1)[0].strip()
            else:
                preset = text
        if preset:
            out["preset"] = preset
        wm = self.wait_mode.currentData()
        if wm:
            out["wait_mode"] = wm
        fb = self.fallback.currentData()
        if fb:
            out["fallback_script"] = fb
        return out


class HistoryDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("运行历史")
        fit_dialog(self, 800, 420, min_width=560, min_height=280)
        root = QVBoxLayout(self)
        dialog_margins(root)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["时间", "脚本", "结果", "退出码", "耗时", "错误"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        root.addWidget(self.table, 1)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.reload)
        footer_bar(root, [refresh], dialog=self, add_close=True)
        self.reload()

    def reload(self) -> None:
        rows = list(reversed(load_history()))[:100]
        self.table.setRowCount(0)
        for h in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            ok = bool(h.get("success"))
            vals = [
                str(h.get("when", "")),
                str(h.get("name", "")),
                "成功" if ok else "失败",
                str(h.get("exit_code", "")),
                str(h.get("duration_sec", "")),
                str(h.get("error", "")),
            ]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if c == 2:
                    item.setForeground(QColor(styles.ACCENT if ok else styles.DANGER))
                self.table.setItem(r, c, item)
