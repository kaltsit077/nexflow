"""One window to edit a script: basics + MaaFW record/connect (when type=maafw)."""
from __future__ import annotations

from typing import Any, Callable, Optional

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from runner.after_launch import run_after_launch
from runner.catalog import sync_run_preset
from ui.dialog_chrome import dialog_margins, fit_dialog, footer_bar, scroll_page
from ui.preview_panel import PreviewPanel
from ui.styles import GAP, GAP_SM


class _JobSignals(QObject):
    ok = Signal(object)
    err = Signal(str)


class _FnJob(QRunnable):
    def __init__(self, fn) -> None:
        super().__init__()
        self.fn = fn
        self.signals = _JobSignals()

    @Slot()
    def run(self) -> None:
        try:
            self.signals.ok.emit(self.fn())
        except Exception as e:  # noqa: BLE001
            self.signals.err.emit(str(e))


def _split_csv(text: str) -> list[str]:
    return [x.strip() for x in text.split(",") if x.strip()]


class ScriptEditorDialog(QDialog):
    """Edit script fields and (for maafw) record/connect in one dialog."""

    def __init__(
        self,
        cfg: dict[str, Any],
        save_cfg: Callable[[dict], None],
        parent=None,
        select_id: Optional[str] = None,
        *,
        manage: bool = False,
    ) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self._save_cfg = save_cfg
        self._draft: Optional[dict[str, Any]] = None
        self._manage = manage
        self._select_id = select_id
        self.setWindowTitle("管理脚本库" if manage else "编辑脚本")
        fit_dialog(
            self,
            1180 if not manage else 1280,
            720,
            min_width=720 if not manage else 880,
            min_height=420,
        )

        root = QHBoxLayout(self)
        dialog_margins(root)

        self.list: QListWidget | None = None
        if manage:
            left = QVBoxLayout()
            self.list = QListWidget()
            self.list.currentRowChanged.connect(self._on_row)
            left.addWidget(self.list, 1)
            lb = QHBoxLayout()
            b_new = QPushButton("新建")
            b_new.clicked.connect(self._new)
            lb.addWidget(b_new)
            left.addLayout(lb)
            root.addLayout(left, 1)

        right = QVBoxLayout()
        self.tabs = QTabWidget()
        # Scroll both tabs so dense ② (connect + steps + preview) never crush
        # into a flat strip; footer Save/Close stay outside the scroll.
        self.tabs.addTab(scroll_page(self._build_basic_tab()), "① 基本与调度")
        self.studio = PreviewPanel()
        self.studio.after_launch_changed.connect(self._on_after_launch_changed)
        self.studio.save_script_requested.connect(self._save)
        self.studio.test_after_launch_requested.connect(self._test_after_launch)
        self.tabs.addTab(scroll_page(self.studio), "② 录制 / 连控")
        self.tabs.currentChanged.connect(self._on_tab)
        right.addWidget(self.tabs, 1)

        self.hint = QLabel("")
        self.hint.setObjectName("muted")
        self.hint.setWordWrap(True)
        right.addWidget(self.hint)

        save_btn = QPushButton("保存脚本")
        save_btn.setObjectName("primary")
        save_btn.clicked.connect(self._save)
        self._del_btn = QPushButton("删除")
        self._del_btn.setObjectName("danger")
        self._del_btn.setToolTip("从脚本库移除；若仍被队列引用则无法删除")
        self._del_btn.clicked.connect(self._delete)
        footer_bar(right, [save_btn, self._del_btn], dialog=self, add_close=True)
        root.addLayout(right, 3)

        self.f_type.currentTextChanged.connect(self._sync_record_tab_enabled)

        if manage:
            self._reload_list()
            if select_id:
                self._select_by_id(select_id)
            elif self.cfg.get("scripts"):
                assert self.list is not None
                self.list.setCurrentRow(0)
        elif select_id:
            script = next((s for s in cfg.get("scripts", []) if s["id"] == select_id), None)
            if script:
                self._fill(script)
            else:
                QMessageBox.warning(self, "提示", f"找不到脚本 {select_id}")
        self._sync_record_tab_enabled()
        self._sync_delete_enabled()

    def _build_basic_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(GAP_SM, GAP_SM, GAP_SM, GAP_SM)
        form.setSpacing(GAP)
        form.setHorizontalSpacing(GAP)
        self._basic_form = form
        self.f_id = QLineEdit()
        self.f_name = QLineEdit()
        self.f_type = QComboBox()
        self.f_type.addItems(["maafw", "exe", "python", "bat", "cmd", "powershell", "ahk"])
        self.f_path = QLineEdit()
        self.f_workdir = QLineEdit()
        self.f_args = QLineEdit()
        self.f_maafw_bin = QLineEdit()
        self.f_timeout = QSpinBox()
        self.f_timeout.setRange(1, 86400)
        self.f_timeout.setValue(3600)
        self.f_wait_mode = QComboBox()
        self.f_wait_mode.addItem("等进程退出 wait_exit", "wait_exit")
        self.f_wait_mode.addItem("只启动继续 launch（GUI）", "launch")
        self.f_wait_mode.addItem("启动并等退出 launch_wait（助手日常）", "launch_wait")
        self.f_wait_mode.setToolTip(
            "launch：settle 后放行（模拟器）。"
            "launch_wait：settle→代点开始→等进程退出→再 cleanup（串行游戏 A→B）。"
        )
        self.f_cleanup = QComboBox()
        self.f_cleanup.addItem("成功后关本步 self", "self")
        self.f_cleanup.addItem("成功后关本步+前置 self+pre", "self+pre")
        self.f_cleanup.addItem("不收尾 none", "none")
        self.f_cleanup.setToolTip(
            "仅本步成功时执行；launch 模式跳过。"
            "self 杀助手；self+pre 另杀 pre_launch 的模拟器/游戏。"
        )

        def _browse_row(edit: QLineEdit, browse) -> QWidget:
            host = QWidget()
            hl = QHBoxLayout(host)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.addWidget(edit, 1)
            b = QPushButton("浏览")
            b.clicked.connect(browse)
            hl.addWidget(b)
            return host

        self._path_host = _browse_row(self.f_path, self._browse_path)
        self._workdir_host = _browse_row(
            self.f_workdir, lambda: self._set_dir(self.f_workdir)
        )
        self._maafw_bin_host = _browse_row(
            self.f_maafw_bin, lambda: self._set_dir(self.f_maafw_bin)
        )

        def _section(title: str) -> None:
            lab = QLabel(title)
            lab.setObjectName("zoneTitle")
            form.addRow(lab)

        _section("身份")
        form.addRow("ID", self.f_id)
        form.addRow("名称", self.f_name)
        form.addRow("类型", self.f_type)
        _section("路径")
        form.addRow("路径", self._path_host)
        form.addRow("工作目录", self._workdir_host)
        form.addRow("参数", self.f_args)
        form.addRow("maafw_bin", self._maafw_bin_host)
        _section("调度")
        form.addRow("超时(秒)", self.f_timeout)
        form.addRow("等待模式", self.f_wait_mode)
        form.addRow("成功收尾", self.f_cleanup)
        self.f_lane = QLineEdit()
        self.f_lane.setPlaceholderText("emulator / pc（空=default）")
        self.f_lane.setToolTip("并行队列同名互斥；不同 lane 可同开")
        form.addRow("并行 lane", self.f_lane)
        self.f_launch_settle = QSpinBox()
        self.f_launch_settle.setRange(1, 300)
        self.f_launch_settle.setValue(3)
        self.f_launch_settle.setSuffix(" 秒")
        self.f_launch_settle.setToolTip(
            "launch / launch_wait：起来后等多久再代点开始"
        )
        form.addRow("启动安定", self.f_launch_settle)
        self.f_run_as_admin = QCheckBox("管理员启动（UAC）")
        self.f_run_as_admin.setChecked(True)
        form.addRow("权限", self.f_run_as_admin)
        self.f_pre_launch = QLineEdit()
        self.f_pre_launch.setPlaceholderText("可选：先开模拟器等")
        self._pre_host = _browse_row(self.f_pre_launch, self._browse_pre_launch)
        form.addRow("前置启动", self._pre_host)

        # Hidden extras — kept for round-trip, not shown in the form
        self.f_tags = QLineEdit()
        self.f_pre_launch_workdir = QLineEdit()
        self.f_pre_launch_settle = QSpinBox()
        self.f_pre_launch_settle.setRange(0, 300)
        self.f_pre_launch_settle.setValue(3)
        self._after_launch_cache: Optional[dict[str, Any]] = None

        tip = QLabel("启动后点击 / 窗口过滤 / 试运行 → 只在 ② 录制页。")
        tip.setObjectName("muted")
        tip.setWordWrap(True)
        form.addRow(tip)
        return w

    def _set_basic_row_visible(self, field: QWidget, visible: bool) -> None:
        lab = self._basic_form.labelForField(field)
        if lab is not None:
            lab.setVisible(visible)
        field.setVisible(visible)

    def _sync_basic_fields(self) -> None:
        t = self.f_type.currentText()
        is_maafw = t == "maafw"
        is_asst = t in ("exe", "ahk")
        is_cli = t in ("python", "bat", "cmd", "powershell", "maafw")
        # Focused edit: ID rarely changed — hide; manage list still shows it
        self._set_basic_row_visible(self.f_id, self.list is not None)
        self._set_basic_row_visible(self._maafw_bin_host, is_maafw)
        self._set_basic_row_visible(self.f_args, is_cli)
        self._set_basic_row_visible(self.f_run_as_admin, is_asst or t == "exe")
        self._set_basic_row_visible(self._pre_host, is_asst or is_maafw)
        self._set_basic_row_visible(self.f_cleanup, is_asst or is_maafw)
        self._set_basic_row_visible(self.f_launch_settle, is_asst or is_maafw)

    def _sync_record_tab_enabled(self, _t: str = "") -> None:
        t = self.f_type.currentText()
        can = t in ("maafw", "exe", "ahk")
        self.tabs.setTabEnabled(1, can)
        self._sync_basic_fields()
        if t == "maafw":
            self.hint.setText("① 填 PI 路径与调度 · ② 连窗口并录识图步骤。")
        elif t in ("exe", "ahk"):
            self.hint.setText("① 填 exe 与调度 · ② 连窗口并录点击。")
        else:
            self.hint.setText("当前类型无窗口连控，保存后即可加入队列。")
            if self.tabs.currentIndex() == 1:
                self.tabs.setCurrentIndex(0)

    def _on_tab(self, index: int) -> None:
        if index != 1:
            return
        t = self.f_type.currentText()
        if t == "maafw":
            path = self.f_path.text().strip()
            if not path:
                QMessageBox.information(self, "提示", "请先在「基本」里填好 maafw 项目路径")
                self.tabs.setCurrentIndex(0)
                return
            self.studio.use_project(path)
            return
        if t in ("exe", "ahk"):
            path = self.f_path.text().strip()
            if not path:
                QMessageBox.information(self, "提示", "请先在「基本」里填好 exe 路径")
                self.tabs.setCurrentIndex(0)
                return
            wf = ""
            if isinstance(self._after_launch_cache, dict):
                wf = str(
                    self._after_launch_cache.get("window_regex")
                    or self._after_launch_cache.get("window")
                    or ""
                ).strip()
            self.studio.use_assistant(
                exe_path=path,
                window_filter=wf,
                after_launch=self._after_launch_cache,
            )
            # Keep ② launch fields synced from ① (no second path editor)
            self.studio.set_studio_launch(
                path,
                self.f_workdir.text().strip(),
                float(self.f_launch_settle.value()),
            )
            return
        self.tabs.setCurrentIndex(0)

    def _current_script(self) -> Optional[dict[str, Any]]:
        if self.list is not None:
            row = self.list.currentRow()
            scripts = self.cfg.get("scripts", [])
            if 0 <= row < len(scripts):
                return scripts[row]
        sid = self._select_id or self.f_id.text().strip()
        if sid:
            return next((x for x in self.cfg.get("scripts", []) if x.get("id") == sid), None)
        return None

    def _on_after_launch_changed(self, data: object) -> None:
        if not isinstance(data, dict):
            return
        self._after_launch_cache = dict(data)
        if self.f_wait_mode.currentData() == "wait_exit":
            li = self.f_wait_mode.findData("launch_wait")
            if li >= 0:
                self.f_wait_mode.setCurrentIndex(li)
        script = self._current_script()
        if script is not None:
            self._collect_into(script)
            self._save_cfg(self.cfg)
            n = len((data.get("steps") or []))
            QMessageBox.information(
                self,
                "已写入启动后点击",
                f"已保存 {n} 步。可在②点「试运行」验证。",
            )
        else:
            QMessageBox.information(
                self, "已暂存步骤", "尚未绑定库中脚本，请再点底栏「保存脚本」。"
            )

    def _test_after_launch(self) -> None:
        # Prefer live steps from ② if present
        spec = self.studio.after_launch_fields() if self.studio._panel_mode == "assistant" else None
        if not spec:
            spec = self._after_launch_cache
        if not spec:
            QMessageBox.information(self, "提示", "请先在 ② 录制步骤并「写入配置」。")
            return
        trial = dict(spec)
        trial["delay_sec"] = 0
        trial["timeout_sec"] = 8
        # Zero step delays for quicker trial except keep small gaps
        steps = trial.get("steps")
        if isinstance(steps, list):
            trial["steps"] = [
                {**st, "delay_sec": 0.3 if i else 0}
                for i, st in enumerate(steps)
                if isinstance(st, dict)
            ]
        stem = Path(self.f_path.text().strip()).stem

        def work():
            run_after_launch(trial, exe_stem=stem)
            return True

        job = _FnJob(work)
        job.signals.ok.connect(
            lambda _ok: QMessageBox.information(self, "试运行", "已按步骤发送点击，请查看目标窗口。")
        )
        job.signals.err.connect(lambda e: QMessageBox.warning(self, "试运行失败", e))
        QThreadPool.globalInstance().start(job)

    def _reload_list(self) -> None:
        if not self.list:
            return
        self.list.clear()
        for s in self.cfg.get("scripts", []):
            self.list.addItem(f'{s["id"]}  ·  {s["name"]}  ({s["type"]})')

    def _select_by_id(self, select_id: str) -> None:
        if not self.list:
            return
        for i, s in enumerate(self.cfg.get("scripts", [])):
            if s["id"] == select_id:
                self.list.setCurrentRow(i)
                return

    def _on_row(self, row: int) -> None:
        scripts = self.cfg.get("scripts", [])
        if row < 0 or row >= len(scripts):
            self._sync_delete_enabled()
            return
        # Drop previous Maa session before binding another script's studio fields.
        if self.studio.is_session_active():
            self.studio.shutdown(clear_status=True)
        self._fill(scripts[row])
        self._sync_record_tab_enabled()
        self._sync_delete_enabled()

    def _sync_delete_enabled(self) -> None:
        sid = (self.f_id.text() or "").strip()
        exists = any(s.get("id") == sid for s in self.cfg.get("scripts", []))
        self._del_btn.setEnabled(bool(sid and exists))

    def _fill(self, s: dict[str, Any]) -> None:
        self._draft = None
        self.f_id.setText(s.get("id", ""))
        self.f_name.setText(s.get("name", ""))
        t = s.get("type", "exe")
        idx = self.f_type.findText(t)
        if idx >= 0:
            self.f_type.setCurrentIndex(idx)
        self.f_path.setText(s.get("path", ""))
        self.f_workdir.setText(s.get("workdir", ""))
        self.f_args.setText(", ".join(s.get("args") or []))
        self.f_maafw_bin.setText(s.get("maafw_bin", ""))
        self.f_timeout.setValue(int(s.get("timeout_sec") or 3600))
        wm = s.get("wait_mode") or "wait_exit"
        wi = self.f_wait_mode.findData(wm)
        self.f_wait_mode.setCurrentIndex(wi if wi >= 0 else 0)
        cu = s.get("cleanup") or "self"
        ci = self.f_cleanup.findData(cu)
        self.f_cleanup.setCurrentIndex(ci if ci >= 0 else 0)
        self.f_lane.setText(str(s.get("lane") or ""))
        if "run_as_admin" in s:
            self.f_run_as_admin.setChecked(bool(s.get("run_as_admin")))
        else:
            self.f_run_as_admin.setChecked(True)
        self.f_launch_settle.setValue(int(s.get("launch_settle_sec") or 3))
        self.f_tags.setText(", ".join(s.get("tags") or []))
        pre = s.get("pre_launch")
        if isinstance(pre, list) and pre:
            first = pre[0] if isinstance(pre[0], dict) else {"path": str(pre[0])}
            self.f_pre_launch.setText(str(first.get("path") or ""))
            self.f_pre_launch_workdir.setText(str(first.get("workdir") or ""))
            self.f_pre_launch_settle.setValue(int(first.get("settle_sec") or 3))
        elif isinstance(pre, str):
            self.f_pre_launch.setText(pre)
            self.f_pre_launch_workdir.clear()
            self.f_pre_launch_settle.setValue(3)
        else:
            self.f_pre_launch.clear()
            self.f_pre_launch_workdir.clear()
            self.f_pre_launch_settle.setValue(3)
        after = s.get("after_launch") if isinstance(s.get("after_launch"), dict) else None
        self._after_launch_cache = dict(after) if after else None
        # maafw: studio_launch*; exe/ahk: ② 启动栏跟 path/workdir
        stype = str(s.get("type") or "").lower()
        if stype == "maafw":
            settle = s.get("studio_launch_settle_sec")
            self.studio.set_studio_launch(
                s.get("studio_launch", "") or "",
                s.get("studio_launch_workdir", "") or "",
                float(settle) if settle is not None else None,
            )
        else:
            self.studio.set_studio_launch(
                s.get("path", "") or "",
                s.get("workdir", "") or "",
                float(s.get("launch_settle_sec") or 3),
            )
        self._sync_basic_fields()

    def fill_from_detected(self, script: dict[str, Any]) -> None:
        self._draft = dict(script)
        if self.list:
            self.list.clearSelection()
        self._fill(script)
        self._sync_record_tab_enabled()

    def _set_dir(self, edit: QLineEdit) -> None:
        p = QFileDialog.getExistingDirectory(self, "选择目录")
        if p:
            edit.setText(p)

    def _browse_path(self) -> None:
        t = self.f_type.currentText()
        if t in ("exe", "ahk"):
            p, _ = QFileDialog.getOpenFileName(
                self, "选择文件", "", "Executable (*.exe);;All (*.*)"
            )
        elif t == "python":
            p, _ = QFileDialog.getOpenFileName(
                self, "选择文件", "", "Python (*.py);;All (*.*)"
            )
        elif t in ("bat", "powershell", "cmd"):
            p, _ = QFileDialog.getOpenFileName(
                self, "选择文件", "", "Batch (*.bat *.cmd);;All (*.*)"
            )
        else:
            p = QFileDialog.getExistingDirectory(self, "选择项目目录")
        if p:
            self.f_path.setText(p)

    def _browse_pre_launch(self) -> None:
        start = self.f_pre_launch.text().strip() or ""
        p, _ = QFileDialog.getOpenFileName(
            self, "选择前置启动程序", start, "Executable (*.exe);;All (*.*)"
        )
        if p:
            self.f_pre_launch.setText(p)
            if not self.f_pre_launch_workdir.text().strip():
                from pathlib import Path

                self.f_pre_launch_workdir.setText(str(Path(p).parent))

    def _new(self) -> None:
        n = 1
        while any(s["id"] == f"script_{n}" for s in self.cfg["scripts"]):
            n += 1
        sid = f"script_{n}"
        self.cfg["scripts"].append(
            {
                "id": sid,
                "name": f"新脚本 {n}",
                "type": "maafw",
                "path": "projects/demo_click",
                "args": ["-d"],
                "workdir": "",
                "timeout_sec": 600,
                "tags": ["maafw"],
                "presets": [
                    {
                        "id": "run",
                        "name": "MaaPiCli -d",
                        "args": ["-d"],
                        "timeout_sec": 600,
                    }
                ],
            }
        )
        self._save_cfg(self.cfg)
        self._reload_list()
        if self.list:
            self.list.setCurrentRow(len(self.cfg["scripts"]) - 1)

    def _delete(self) -> None:
        sid = (self.f_id.text() or "").strip()
        if not sid:
            return
        scripts = self.cfg.get("scripts", [])
        row = next((i for i, s in enumerate(scripts) if s.get("id") == sid), -1)
        if row < 0:
            QMessageBox.warning(self, "无法删除", f"脚本库中没有 {sid}")
            return
        used = [
            l["name"]
            for l in self.cfg["lists"]
            if any(
                st.get("script") == sid or st.get("fallback_script") == sid
                for st in l.get("steps", [])
            )
        ]
        if used:
            QMessageBox.warning(self, "无法删除", f"仍被列表引用: {', '.join(used)}")
            return
        if QMessageBox.question(self, "确认", f"删除 {sid}？") != QMessageBox.Yes:
            return
        self.cfg["scripts"].pop(row)
        self._save_cfg(self.cfg)
        if self._manage and self.list is not None:
            self._reload_list()
            if self.cfg.get("scripts"):
                self.list.setCurrentRow(min(row, len(self.cfg["scripts"]) - 1))
            else:
                self.f_id.clear()
                self._sync_delete_enabled()
        else:
            self.accept()

    def _collect_into(self, script: dict[str, Any]) -> None:
        script["name"] = self.f_name.text().strip() or script.get("id", "")
        script["type"] = self.f_type.currentText()
        script["path"] = self.f_path.text().strip()
        script["workdir"] = self.f_workdir.text().strip()
        script["args"] = _split_csv(self.f_args.text())
        mb = self.f_maafw_bin.text().strip()
        if mb:
            script["maafw_bin"] = mb
        else:
            script.pop("maafw_bin", None)
        script["timeout_sec"] = self.f_timeout.value()
        script["wait_mode"] = self.f_wait_mode.currentData() or "wait_exit"
        script["cleanup"] = self.f_cleanup.currentData() or "self"
        lane = self.f_lane.text().strip()
        if lane:
            script["lane"] = lane
        else:
            script.pop("lane", None)
        script["launch_settle_sec"] = int(self.f_launch_settle.value())
        script["run_as_admin"] = bool(self.f_run_as_admin.isChecked())
        script["tags"] = _split_csv(self.f_tags.text())
        pre_path = self.f_pre_launch.text().strip()
        if pre_path:
            entry: dict[str, Any] = {
                "path": pre_path,
                "settle_sec": int(self.f_pre_launch_settle.value()),
            }
            pwd = self.f_pre_launch_workdir.text().strip()
            if pwd:
                entry["workdir"] = pwd
            existing = script.get("pre_launch")
            rest: list[Any] = []
            if isinstance(existing, list) and len(existing) > 1:
                rest = list(existing[1:])
            script["pre_launch"] = [entry, *rest]
        else:
            script.pop("pre_launch", None)
        # after_launch only from ②
        live = None
        if self.f_type.currentText() in ("exe", "ahk"):
            live = self.studio.after_launch_fields()
        al = live if live else self._after_launch_cache
        if al:
            if script["wait_mode"] == "wait_exit":
                li = self.f_wait_mode.findData("launch_wait")
                if li >= 0:
                    self.f_wait_mode.setCurrentIndex(li)
                script["wait_mode"] = "launch_wait"
            script["after_launch"] = dict(al)
            self._after_launch_cache = dict(al)
        else:
            script.pop("after_launch", None)
            self._after_launch_cache = None
        if script["type"] == "maafw":
            launch = self.studio.studio_launch_fields()
            for key in ("studio_launch", "studio_launch_workdir", "studio_launch_settle_sec"):
                val = launch.get(key)
                if val not in (None, ""):
                    script[key] = val
                else:
                    script.pop(key, None)
        else:
            for key in ("studio_launch", "studio_launch_workdir", "studio_launch_settle_sec"):
                script.pop(key, None)
        sync_run_preset(script)

    def _save(self) -> None:
        row = self.list.currentRow() if self.list else -1

        if self._draft is not None and (self.list is None or row < 0):
            script = dict(self._draft)
            existing = {s["id"] for s in self.cfg["scripts"]}
            sid = self.f_id.text().strip() or script.get("id", "imported")
            base = sid
            n = 2
            while sid in existing:
                sid = f"{base}_{n}"
                n += 1
            script["id"] = sid
            self.f_id.setText(sid)
            self._collect_into(script)
            self.cfg["scripts"].append(script)
            self._draft = None
            self._save_cfg(self.cfg)
            if self.list:
                self._reload_list()
                self.list.setCurrentRow(len(self.cfg["scripts"]) - 1)
            QMessageBox.information(self, "已保存", f"脚本 {sid}")
            return

        # focused mode: find by id field / select_id
        if self.list is None:
            sid_key = self._select_id or self.f_id.text().strip()
            s = next((x for x in self.cfg.get("scripts", []) if x["id"] == sid_key), None)
            if not s:
                QMessageBox.warning(self, "提示", "脚本不在库中，请用「管理」新建")
                return
            old_id = s["id"]
            new_id = self.f_id.text().strip() or old_id
            if new_id != old_id and any(x["id"] == new_id for x in self.cfg["scripts"]):
                QMessageBox.warning(self, "错误", f"id 已存在: {new_id}")
                return
            s["id"] = new_id
            self._collect_into(s)
            if new_id != old_id:
                self._rewrite_refs(old_id, new_id)
                self._select_id = new_id
            self._save_cfg(self.cfg)
            QMessageBox.information(self, "已保存", f"脚本 {new_id}")
            return

        if row < 0 or row >= len(self.cfg.get("scripts", [])):
            QMessageBox.warning(self, "提示", "先选中一个脚本")
            return
        s = self.cfg["scripts"][row]
        old_id = s["id"]
        new_id = self.f_id.text().strip() or old_id
        if new_id != old_id and any(x["id"] == new_id for x in self.cfg["scripts"]):
            QMessageBox.warning(self, "错误", f"id 已存在: {new_id}")
            return
        s["id"] = new_id
        self._collect_into(s)
        if new_id != old_id:
            self._rewrite_refs(old_id, new_id)
        self._save_cfg(self.cfg)
        self._reload_list()
        self.list.setCurrentRow(row)
        QMessageBox.information(self, "已保存", f"脚本 {new_id}")

    def _rewrite_refs(self, old_id: str, new_id: str) -> None:
        for lst in self.cfg.get("lists", []):
            for st in lst.get("steps", []):
                if st.get("script") == old_id:
                    st["script"] = new_id
                if st.get("fallback_script") == old_id:
                    st["fallback_script"] = new_id

    def closeEvent(self, event) -> None:
        self.studio.shutdown(clear_status=True)
        super().closeEvent(event)

    def hideEvent(self, event) -> None:
        self.studio.stop_preview()
        super().hideEvent(event)


# Back-compat name used by main_window / import
ScriptDialog = ScriptEditorDialog
