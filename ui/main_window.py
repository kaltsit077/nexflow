"""Native PySide6 scheduler: left = foldable queues, right = script library."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from runner import (
    RunnerCallbacks,
    append_history,
    load_config,
    run_list,
    run_single_script,
    save_config,
)
from runner.config import ensure_runtime_files, resolve_script_dir
from ui.catalog_dialog import CatalogDialog
from ui.dialogs import (
    HistoryDialog,
    ImportDialog,
    ScriptDialog,
    StepDialog,
)
from ui.queue_section import QueueSection
from ui.script_library_panel import ScriptLibraryPanel
from ui.styles import (
    GAP,
    GAP_SM,
    PAD,
    apply_theme,
    list_themes,
    resolve_theme,
)


class WorkerSignals(QObject):
    status = Signal(str, str)
    output = Signal(str, str)
    step_done = Signal(object)
    finished = Signal(bool, list)


class RunnerWorker(QRunnable):
    def __init__(self, cfg: dict, target: str, mode: str):
        super().__init__()
        from runner.executor import make_stop_flag

        self.cfg = cfg
        self.target = target
        self.mode = mode
        self.signals = WorkerSignals()
        self._stop = make_stop_flag()

    def stop(self) -> None:
        self._stop.request()

    @Slot()
    def run(self) -> None:
        cb = RunnerCallbacks(
            on_status=lambda s, st: self.signals.status.emit(s, st),
            on_output=lambda s, line: self.signals.output.emit(s, line),
            on_step_done=lambda r: self.signals.step_done.emit(r),
        )
        try:
            if self.mode == "list":
                ok, results = run_list(self.cfg, self.target, cb, self._stop)
            else:
                scripts = {s["id"]: s for s in self.cfg["scripts"]}
                r = run_single_script(scripts[self.target], cb, self._stop)
                ok = r.success
                results = [r]
            self.signals.finished.emit(ok, results)
        except Exception as e:  # noqa: BLE001
            self.signals.status.emit("__error__", f"failed: {e}")
            self.signals.finished.emit(False, [])


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        ensure_runtime_files()
        self.setWindowTitle("Game Runner")
        self.resize(1320, 820)
        self.cfg = load_config()
        self.worker: RunnerWorker | None = None
        self._active_queue = ""
        self._expanded: set[str] = set()
        self._sections: dict[str, QueueSection] = {}
        self._build_ui()
        self._refresh_all()

    def _build_ui(self) -> None:
        """TOOLS → COMPOSE|LIBRARY → RUN. Fixed GAP; one run entry."""
        shell = QWidget()
        shell.setObjectName("shell")
        root = QVBoxLayout(shell)
        root.setContentsMargins(GAP, GAP, GAP, GAP)
        root.setSpacing(GAP)

        # ----- TOOLS: acquire only -----
        tools = QFrame()
        tools.setObjectName("zone")
        tl = QHBoxLayout(tools)
        tl.setContentsMargins(PAD, GAP, PAD, GAP)
        tl.setSpacing(GAP)
        brand = QLabel("Game Runner")
        brand.setObjectName("title")
        tl.addWidget(brand)
        self.queue_count = QLabel("0 队列")
        self.queue_count.setObjectName("badge")
        tl.addWidget(self.queue_count)
        tl.addStretch(1)
        theme_lbl = QLabel("主题")
        theme_lbl.setObjectName("muted")
        tl.addWidget(theme_lbl)
        self.theme_combo = QComboBox()
        self.theme_combo.setMinimumWidth(140)
        for tid, label in list_themes():
            self.theme_combo.addItem(label, tid)
        tid = resolve_theme((self.cfg.get("ui") or {}).get("theme"))
        idx = self.theme_combo.findData(tid)
        self.theme_combo.blockSignals(True)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        self.theme_combo.blockSignals(False)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        tl.addWidget(self.theme_combo)
        for text, slot, primary in (
            ("导入", self._open_import, False),
            ("游戏目录", self._open_catalog, False),
            ("历史", self._open_history, False),
        ):
            b = QPushButton(text)
            if primary:
                b.setObjectName("primary")
            b.clicked.connect(slot)
            tl.addWidget(b)
        root.addWidget(tools)

        # ----- COMPOSE | LIBRARY -----
        mid = QSplitter()
        mid.setChildrenCollapsible(False)

        compose = QFrame()
        compose.setObjectName("zone")
        cl = QVBoxLayout(compose)
        cl.setContentsMargins(PAD, PAD, PAD, PAD)
        cl.setSpacing(GAP)

        ch = QHBoxLayout()
        ch.setSpacing(GAP)
        ct = QLabel("编排 · 队列")
        ct.setObjectName("zoneTitle")
        ch.addWidget(ct)
        self.active_hint = QLabel("")
        self.active_hint.setObjectName("muted")
        ch.addWidget(self.active_hint, 1)
        btn_new_q = QPushButton("+ 队列")
        btn_new_q.clicked.connect(self._add_list)
        ch.addWidget(btn_new_q)
        btn_exp = QPushButton("全开")
        btn_exp.setObjectName("linkish")
        btn_exp.clicked.connect(self._expand_all)
        ch.addWidget(btn_exp)
        btn_col = QPushButton("全收")
        btn_col.setObjectName("linkish")
        btn_col.clicked.connect(self._collapse_all)
        ch.addWidget(btn_col)
        cl.addLayout(ch)

        self.queue_scroll = QScrollArea()
        self.queue_scroll.setWidgetResizable(True)
        self.queue_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.queues_host = QWidget()
        self.queues_host.setObjectName("cardsHost")
        self.queues_layout = QVBoxLayout(self.queues_host)
        self.queues_layout.setContentsMargins(0, 0, 0, 0)
        self.queues_layout.setSpacing(GAP)
        self.queues_layout.addStretch(1)
        self.queue_scroll.setWidget(self.queues_host)
        cl.addWidget(self.queue_scroll, 1)
        mid.addWidget(compose)

        lib_wrap = QFrame()
        lib_wrap.setObjectName("zone")
        ll = QVBoxLayout(lib_wrap)
        ll.setContentsMargins(PAD, PAD, PAD, PAD)
        ll.setSpacing(GAP)
        self.script_panel = ScriptLibraryPanel()
        self.script_panel.add_script.connect(self._add_script_to_active)
        self.script_panel.add_script_to.connect(self._add_script_to_named)
        self.script_panel.edit_script.connect(self._edit_script_by_id)
        self.script_panel.open_script_dir.connect(self._open_script_dir)
        self.script_panel.launch_script.connect(self._launch_script)
        self.script_panel.manage_scripts.connect(lambda: self._open_scripts())
        self.script_panel.new_script.connect(self._new_script_quick)
        ll.addWidget(self.script_panel, 1)
        mid.addWidget(lib_wrap)

        mid.setSizes([640, 560])
        root.addWidget(mid, 1)

        # ----- RUN: single execute chain -----
        run_zone = QFrame()
        run_zone.setObjectName("zone")
        rl = QHBoxLayout(run_zone)
        rl.setContentsMargins(PAD, PAD, PAD, PAD)
        rl.setSpacing(GAP)

        log_col = QVBoxLayout()
        log_col.setSpacing(GAP_SM)
        rh = QHBoxLayout()
        rt = QLabel("执行")
        rt.setObjectName("zoneTitle")
        rh.addWidget(rt)
        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("muted")
        rh.addWidget(self.status_label, 1)
        log_col.addLayout(rh)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(100)
        self.log_view.setMaximumHeight(160)
        self.log_view.document().setMaximumBlockCount(500)
        log_col.addWidget(self.log_view, 1)
        rl.addLayout(log_col, 1)

        btns = QVBoxLayout()
        btns.setSpacing(GAP)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.clicked.connect(self._on_stop)
        self.stop_btn.setEnabled(False)
        btns.addWidget(self.stop_btn)
        self.run_btn = QPushButton("运行选中队列")
        self.run_btn.setObjectName("primary")
        self.run_btn.clicked.connect(self._on_run)
        btns.addWidget(self.run_btn)
        btns.addStretch(1)
        rl.addLayout(btns)

        root.addWidget(run_zone)
        self.setCentralWidget(shell)
        self.statusBar().showMessage("顶栏获取 · 中栏把脚本加入队列 · 底栏运行选中队列")

    # ----- config helpers -----
    def _persist(self) -> None:
        self._write_ui_prefs()
        try:
            save_config(self.cfg)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "保存失败", str(e))

    def _write_ui_prefs(self) -> None:
        ui = self.cfg.setdefault("ui", {})
        ui["active_queue"] = self._active_queue
        ui["expanded"] = sorted(self._expanded)
        ui["theme"] = resolve_theme(self.theme_combo.currentData())

    def _load_ui_prefs(self) -> None:
        ui = self.cfg.get("ui") or {}
        aq = str(ui.get("active_queue") or "")
        exp = ui.get("expanded")
        if aq:
            self._active_queue = aq
        if isinstance(exp, list):
            self._expanded = {str(x) for x in exp}

    def _on_theme_changed(self, _index: int) -> None:
        app = QApplication.instance()
        if app is None:
            return
        tid = apply_theme(app, self.theme_combo.currentData())
        self.cfg.setdefault("ui", {})["theme"] = tid
        self._persist()

    def _scripts_by_id(self) -> dict[str, dict[str, Any]]:
        return {s["id"]: s for s in self.cfg.get("scripts", [])}

    def _list_by_name(self, name: str) -> Optional[dict[str, Any]]:
        for lst in self.cfg.get("lists", []):
            if lst["name"] == name:
                return lst
        return None

    def _apply_active_queue(self, name: str, *, persist: bool = False) -> None:
        self._active_queue = name
        self.active_hint.setText(f"目标：{name}" if name else "")
        self.script_panel.set_active_queue(name)
        for n, sec in self._sections.items():
            sec.set_active(n == name)
        if persist:
            self._persist()

    def _set_active_queue(self, name: str) -> None:
        self._apply_active_queue(name, persist=True)

    def _refresh_all(self, *, reload_disk: bool = False, scripts: bool = True) -> None:
        """Rebuild UI from in-memory cfg; set reload_disk after external writes."""
        if reload_disk:
            self.cfg = load_config()
            self._load_ui_prefs()
        lists = self.cfg.get("lists", [])
        names = [l["name"] for l in lists]
        self.queue_count.setText(f"{len(lists)} 队列")

        if self._active_queue not in names:
            self._active_queue = names[0] if names else ""
        self._expanded = {n for n in self._expanded if n in names}
        if not self._expanded and names:
            self._expanded = {self._active_queue or names[0]}

        self._rebuild_queues()
        if scripts:
            self.script_panel.reload(self.cfg.get("scripts", []), names)
        self._apply_active_queue(self._active_queue, persist=False)

    def _refresh_queues(self) -> None:
        """Queue steps changed; skip disk I/O and script-library rebuild."""
        self._refresh_all(reload_disk=False, scripts=False)

    def _rebuild_queues(self) -> None:
        while self.queues_layout.count():
            item = self.queues_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._sections.clear()

        by_id = self._scripts_by_id()
        lists = self.cfg.get("lists", [])
        if not lists:
            tip = QLabel("还没有队列 · 点顶栏「+ 新建队列」")
            tip.setObjectName("muted")
            self.queues_layout.addWidget(tip)
            self.queues_layout.addStretch(1)
            return

        # First paint: expand active (or first) queue
        if not self._expanded:
            self._expanded.add(self._active_queue or lists[0]["name"])

        for lst in lists:
            name = lst["name"]
            expanded = name in self._expanded
            sec = QueueSection(
                name,
                lst.get("steps") or [],
                by_id,
                expanded=expanded,
                active=(name == self._active_queue),
                mode=str(lst.get("mode") or "sequential"),
                max_parallel=max(1, min(8, int(lst.get("max_parallel") or 2))),
            )
            sec.toggled.connect(self._on_queue_toggled)
            sec.activated.connect(self._set_active_queue)
            sec.delete_queue.connect(self._del_list_named)
            sec.rename_queue.connect(self._rename_list)
            sec.configure_step.connect(self._edit_step)
            sec.edit_step_script.connect(self._edit_step_script)
            sec.remove_step.connect(self._remove_step)
            sec.run_step.connect(self._run_step_script)
            sec.move_step.connect(self._move_step)
            sec.script_dropped.connect(self._add_script_to_named)
            sec.settings_changed.connect(self._on_queue_settings)
            self._sections[name] = sec
            self.queues_layout.addWidget(sec)
            if expanded:
                self._expanded.add(name)
        self.queues_layout.addStretch(1)

    def _on_queue_toggled(self, name: str, expanded: bool) -> None:
        if expanded:
            self._expanded.add(name)
        else:
            self._expanded.discard(name)
        self._write_ui_prefs()
        try:
            save_config(self.cfg)
        except Exception:
            pass

    def _expand_all(self) -> None:
        self._expanded = {l["name"] for l in self.cfg.get("lists", [])}
        self._rebuild_queues()
        self._apply_active_queue(self._active_queue, persist=True)

    def _collapse_all(self) -> None:
        self._expanded.clear()
        self._rebuild_queues()
        self._apply_active_queue(self._active_queue, persist=True)

    # ----- queue CRUD -----
    def _add_list(self) -> None:
        name, ok = QInputDialog.getText(self, "新建队列", "队列名称:")
        if not ok or not name.strip():
            return
        name = name.strip()
        if any(l["name"] == name for l in self.cfg["lists"]):
            QMessageBox.warning(self, "错误", "名称已存在")
            return
        self.cfg["lists"].append(
            {"name": name, "mode": "sequential", "max_parallel": 2, "steps": []}
        )
        self._persist()
        self._active_queue = name
        self._expanded.add(name)
        self._refresh_all()

    def _on_queue_settings(self, name: str, mode: str, max_parallel: int) -> None:
        lst = self._list_by_name(name)
        if not lst:
            return
        lst["mode"] = "parallel" if mode == "parallel" else "sequential"
        lst["max_parallel"] = max(1, min(8, int(max_parallel)))
        self._persist()

    def _del_list_named(self, name: str) -> None:
        lst = self._list_by_name(name)
        if not lst:
            return
        if QMessageBox.question(self, "确认", f"删除队列 {name}？") != QMessageBox.Yes:
            return
        self.cfg["lists"] = [l for l in self.cfg["lists"] if l["name"] != name]
        self._expanded.discard(name)
        if self._active_queue == name:
            self._active_queue = ""
        self._persist()
        self._refresh_all()

    def _rename_list(self, name: str) -> None:
        lst = self._list_by_name(name)
        if not lst:
            return
        new_name, ok = QInputDialog.getText(self, "重命名队列", "新名称:", text=name)
        if not ok:
            return
        new_name = new_name.strip()
        if not new_name or new_name == name:
            return
        if any(l["name"] == new_name for l in self.cfg["lists"]):
            QMessageBox.warning(self, "错误", "名称已存在")
            return
        lst["name"] = new_name
        if name in self._expanded:
            self._expanded.discard(name)
            self._expanded.add(new_name)
        if self._active_queue == name:
            self._active_queue = new_name
        self._persist()
        self._refresh_all()

    def _default_step(self, script_id: str) -> dict[str, Any]:
        step: dict[str, Any] = {"script": script_id, "on_fail": "stop", "retry": 0}
        script = self._scripts_by_id().get(script_id) or {}
        presets = script.get("presets") or []
        if presets:
            step["preset"] = presets[0].get("id") or "run"
        return step

    def _add_script_to_active(self, script_id: str) -> None:
        if not self._active_queue:
            QMessageBox.information(self, "提示", "先在左侧点一下要加入的队列标题")
            return
        self._add_script_to_named(script_id, self._active_queue)

    def _add_script_to_named(self, script_id: str, list_name: str) -> None:
        lst = self._list_by_name(list_name)
        if not lst:
            QMessageBox.warning(self, "提示", f"队列不存在：{list_name}")
            return
        if script_id not in self._scripts_by_id():
            QMessageBox.warning(self, "提示", f"脚本不存在：{script_id}")
            return
        lst.setdefault("steps", []).append(self._default_step(script_id))
        self._expanded.add(list_name)
        self._active_queue = list_name
        self._persist()
        self._refresh_queues()
        self.statusBar().showMessage(f"已将 {script_id} 加入「{list_name}」", 4000)

    def _move_step(self, list_name: str, index: int, delta: int) -> None:
        lst = self._list_by_name(list_name)
        if not lst:
            return
        steps = lst.get("steps") or []
        j = index + delta
        if index < 0 or index >= len(steps) or j < 0 or j >= len(steps):
            return
        steps[index], steps[j] = steps[j], steps[index]
        self._expanded.add(list_name)
        self._persist()
        self._refresh_queues()

    def _edit_step(self, list_name: str, index: int) -> None:
        lst = self._list_by_name(list_name)
        if not lst or index < 0 or index >= len(lst.get("steps", [])):
            return
        self._set_active_queue(list_name)
        dlg = StepDialog(self.cfg, lst["steps"][index], parent=self)
        if dlg.exec() != StepDialog.Accepted:
            return
        lst["steps"][index] = dlg.result_step()
        self._persist()
        self._refresh_queues()

    def _edit_step_script(self, list_name: str, index: int) -> None:
        lst = self._list_by_name(list_name)
        if not lst or index < 0 or index >= len(lst.get("steps", [])):
            return
        sid = lst["steps"][index].get("script")
        if not sid:
            return
        self._set_active_queue(list_name)
        self._edit_script_by_id(sid)

    def _remove_step(self, list_name: str, index: int) -> None:
        lst = self._list_by_name(list_name)
        if not lst or index < 0 or index >= len(lst.get("steps", [])):
            return
        lst["steps"].pop(index)
        self._persist()
        self._refresh_queues()

    def _run_step_script(self, list_name: str, index: int) -> None:
        lst = self._list_by_name(list_name)
        if not lst or index < 0 or index >= len(lst.get("steps", [])):
            return
        sid = lst["steps"][index].get("script")
        if not sid:
            return
        self._set_active_queue(list_name)
        self._start_worker(sid, "script")

    # ----- scripts（编辑 = 基本 + 录制一窗；管理 = 带左侧列表）-----
    def _open_scripts(self, draft: Optional[dict] = None) -> None:
        dlg = ScriptDialog(self.cfg, self._on_cfg_saved, parent=self, manage=True)
        if isinstance(draft, dict):
            dlg.fill_from_detected(draft)
        dlg.exec()
        self._refresh_all()

    def _new_script_quick(self) -> None:
        self._open_scripts()

    def _edit_script_by_id(self, script_id: str) -> None:
        dlg = ScriptDialog(
            self.cfg, self._on_cfg_saved, parent=self, select_id=script_id, manage=False
        )
        dlg.exec()
        self._refresh_all()

    def _open_script_dir(self, script_id: str) -> None:
        script = self._scripts_by_id().get(script_id)
        if not script:
            QMessageBox.warning(self, "提示", f"脚本不存在：{script_id}")
            return
        try:
            folder = resolve_script_dir(script)
        except FileNotFoundError as e:
            QMessageBox.warning(self, "无法打开目录", str(e))
            return
        try:
            import os

            os.startfile(str(folder))  # type: ignore[attr-defined]
        except OSError as e:
            QMessageBox.warning(self, "无法打开目录", f"{folder}\n{e}")

    def _launch_script(self, script_id: str) -> None:
        if script_id not in self._scripts_by_id():
            QMessageBox.warning(self, "提示", f"脚本不存在：{script_id}")
            return
        self._start_worker(script_id, "script")

    def _on_cfg_saved(self, cfg: dict) -> None:
        self.cfg = cfg
        try:
            save_config(cfg)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "保存失败", str(e))

    def _open_import(self) -> None:
        def open_editor(script: dict) -> None:
            self._open_scripts(script)

        dlg = ImportDialog(self.cfg, self._on_cfg_saved, open_editor, parent=self)
        dlg.exec()
        self._refresh_all()

    def _open_catalog(self) -> None:
        def changed() -> None:
            self.cfg = load_config()

        CatalogDialog(on_changed=changed, parent=self).exec()
        self._refresh_all()

    def _open_history(self) -> None:
        HistoryDialog(self).exec()

    # ----- run -----
    def _on_run(self) -> None:
        name = self._active_queue
        if not name:
            QMessageBox.warning(self, "提示", "请先点选左侧某个队列")
            return
        self._start_worker(name, "list")

    def _start_worker(self, target: str, mode: str) -> None:
        if self.worker is not None:
            QMessageBox.information(self, "提示", "已有任务在跑")
            return
        self.cfg = load_config()
        self.log_view.clear()
        self.status_label.setText(f"运行中 · {mode} · {target}")
        self.worker = RunnerWorker(self.cfg, target, mode)
        self.worker.signals.status.connect(self._on_status)
        self.worker.signals.output.connect(self._on_output)
        self.worker.signals.step_done.connect(self._on_step_done)
        self.worker.signals.finished.connect(self._on_finished)
        QThreadPool.globalInstance().start(self.worker)
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

    def _on_stop(self) -> None:
        if self.worker is not None:
            self.worker.stop()
            self.statusBar().showMessage("已请求停止…")
            self.status_label.setText("停止中…")

    @Slot(str, str)
    def _on_status(self, sid: str, status: str) -> None:
        msg = f"{sid}: {status}"
        self.statusBar().showMessage(msg)
        self.status_label.setText(msg)

    @Slot(str, str)
    def _on_output(self, sid: str, line: str) -> None:
        self.log_view.append(f"[{sid}] {line}")

    @Slot(object)
    def _on_step_done(self, r) -> None:
        append_history({
            "when": datetime.now().isoformat(timespec="seconds"),
            "name": r.script_id,
            "success": r.success,
            "exit_code": r.exit_code,
            "duration_sec": r.duration_sec,
            "log": r.log_path,
            "error": r.error,
        })
        self.log_view.append(
            f"--- {r.script_id} done: exit={r.exit_code} {r.duration_sec}s err={r.error} ---"
        )

    @Slot(bool, list)
    def _on_finished(self, ok: bool, _results: list) -> None:
        self.worker = None
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        msg = "全部成功" if ok else "有失败步骤"
        self.statusBar().showMessage(msg)
        self.status_label.setText(msg)


def main() -> None:
    ensure_runtime_files()
    app = QApplication([])
    cfg = load_config()
    apply_theme(app, (cfg.get("ui") or {}).get("theme"))
    w = MainWindow()
    w.show()
    app.exec()


if __name__ == "__main__":
    main()
