"""游戏目录：全部项目 library/ 一键安装与扫描导入。"""
from __future__ import annotations

import webbrowser
from typing import Callable, Optional

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
)

from runner.github_auth import (
    CREATE_FINE_GRAINED_URL,
    CREATE_TOKEN_URL,
    clear_github_token,
    probe_rate_limit,
    set_github_token,
    token_status,
)
from runner.library import (
    LIBRARY_DIR,
    LIBRARY_LABEL,
    app_dir,
    ensure_library_root,
    list_projects,
    scan_roots_for_project,
)
from runner.tool_catalog import list_tools
from runner.tool_installer import install_tool, installed_status, scan_and_register
from ui import styles
from ui.dialog_chrome import dialog_margins, fit_dialog, footer_bar


class GithubTokenDialog(QDialog):
    """Create / paste GitHub PAT to raise API rate limits for catalog install."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("GitHub Token")
        fit_dialog(self, 520, 340, min_width=420, min_height=280)

        root = QVBoxLayout(self)
        dialog_margins(root)

        tip = QLabel(
            "未登录访问 GitHub API 限额很低（约 60 次/小时），国内也易被拒。\n"
            "创建 Personal Access Token 并保存后，安装「游戏目录」会带 Token 请求，"
            "限额可升到约 5000 次/小时。\n"
            "公开仓库安装一般无需勾选特殊权限；Token 只存在本机 .github_token，勿分享。"
        )
        tip.setWordWrap(True)
        tip.setObjectName("muted")
        root.addWidget(tip)

        link_row = QHBoxLayout()
        b_classic = QPushButton("打开：创建经典 Token")
        b_classic.setObjectName("primary")
        b_classic.clicked.connect(lambda: webbrowser.open(CREATE_TOKEN_URL))
        b_fine = QPushButton("打开：细粒度 Token")
        b_fine.clicked.connect(lambda: webbrowser.open(CREATE_FINE_GRAINED_URL))
        link_row.addWidget(b_classic)
        link_row.addWidget(b_fine)
        link_row.addStretch(1)
        root.addLayout(link_row)

        form = QFormLayout()
        self.status = QLabel("")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        form.addRow("当前状态", self.status)

        self.token_edit = QLineEdit()
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_edit.setPlaceholderText("粘贴 ghp_… / github_pat_… 后点保存")
        form.addRow("Token", self.token_edit)
        root.addLayout(form)

        save_btn = QPushButton("保存 Token")
        save_btn.setObjectName("primary")
        save_btn.clicked.connect(self._save)
        test_btn = QPushButton("测试连接")
        test_btn.setToolTip("请求 api.github.com/rate_limit，查看限额")
        test_btn.clicked.connect(self._test)
        clear_btn = QPushButton("清除")
        clear_btn.clicked.connect(self._clear)
        footer_bar(root, [save_btn, test_btn, clear_btn], dialog=self, add_close=True)

        self._refresh_status()

    def _refresh_status(self) -> None:
        st = token_status()
        if st.get("configured"):
            self.status.setText(
                f"已配置 · 来源 {st.get('source')} · {st.get('masked')}"
            )
            if not st.get("editable"):
                self.token_edit.setPlaceholderText(
                    "当前由环境变量提供，改环境变量或清除后可改用文件"
                )
                self.token_edit.setEnabled(False)
            else:
                self.token_edit.setEnabled(True)
                self.token_edit.clear()
        else:
            self.status.setText("未配置（安装易触发限流）")
            self.token_edit.setEnabled(True)

    def _save(self) -> None:
        text = self.token_edit.text().strip()
        if not text:
            QMessageBox.information(self, "提示", "请先粘贴 Token，或点「清除」删除已有 Token。")
            return
        path = set_github_token(text)
        self.token_edit.clear()
        self._refresh_status()
        QMessageBox.information(
            self,
            "已保存",
            f"Token 已写入本机文件：\n{path}\n\n请回到游戏目录重试「安装 / 更新」。",
        )

    def _clear(self) -> None:
        st = token_status()
        if st.get("configured") and not st.get("editable"):
            QMessageBox.information(
                self,
                "提示",
                "当前 Token 来自环境变量，请在系统/启动脚本中取消 "
                "GAME_RUNNER_GITHUB_TOKEN / GITHUB_TOKEN。",
            )
            return
        if QMessageBox.question(self, "确认", "清除本机保存的 GitHub Token？") != QMessageBox.Yes:
            return
        clear_github_token()
        self.token_edit.clear()
        self._refresh_status()

    def _test(self) -> None:
        typed = self.token_edit.text().strip()
        result = probe_rate_limit(token=typed or None)
        if not result.get("ok"):
            QMessageBox.warning(
                self,
                "测试失败",
                f"无法访问 GitHub API：\n{result.get('error')}\n\n"
                "可设 GAME_RUNNER_GH_PROXY，或检查网络 / Token。",
            )
            return
        auth = "已认证" if result.get("authenticated") else "未认证（限额很低）"
        note = ""
        if typed:
            note = "\n\n框内 Token 仅用于本次测试，请点「保存 Token」才会写入本机。"
        QMessageBox.information(
            self,
            "测试成功",
            f"{auth}\n"
            f"core 限额：{result.get('remaining')} / {result.get('limit')}\n"
            f"Token：{result.get('masked') or '（无）'}"
            f"{note}",
        )


class _JobSignals(QObject):
    log = Signal(str)
    done = Signal(object)


class _InstallJob(QRunnable):
    def __init__(self, tool_id: str):
        super().__init__()
        self.tool_id = tool_id
        self.signals = _JobSignals()

    @Slot()
    def run(self) -> None:
        def log(msg: str) -> None:
            self.signals.log.emit(msg)

        try:
            result = install_tool(self.tool_id, log=log)
        except Exception as e:  # noqa: BLE001
            result = {"ok": False, "error": str(e)}
        self.signals.done.emit(result)


class CatalogDialog(QDialog):
    def __init__(self, on_changed: Optional[Callable[[], None]] = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"游戏目录 · {LIBRARY_LABEL}")
        fit_dialog(self, 980, 580, min_width=720, min_height=360)
        self._on_changed = on_changed
        self._busy = False

        root = QVBoxLayout(self)
        dialog_margins(root)
        self.tip = QLabel("")
        self.tip.setWordWrap(True)
        self.tip.setObjectName("muted")
        root.addWidget(self.tip)
        self._refresh_tip()

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["游戏", "助手", "状态", "说明", "安装", "目录", "主页"]
        )
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        root.addWidget(self.table, 2)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(140)
        root.addWidget(self.log)

        b_refresh = QPushButton("刷新状态")
        b_refresh.clicked.connect(self.reload)
        b_scan = QPushButton("扫描全部项目并导入")
        b_scan.clicked.connect(self._scan_all)
        b_open = QPushButton(f"打开{LIBRARY_LABEL}文件夹")
        b_open.clicked.connect(self._open_library)
        b_token = QPushButton("GitHub Token…")
        b_token.setToolTip("创建/保存 Token，缓解 API 限流")
        b_token.clicked.connect(self._open_token_dialog)
        footer_bar(
            root,
            [b_refresh, b_scan, b_open, b_token],
            dialog=self,
            add_close=True,
        )

        ensure_library_root()
        self.reload()

    def _refresh_tip(self) -> None:
        st = token_status()
        tok = (
            f"GitHub Token：已配置（{st.get('masked')}）"
            if st.get("configured")
            else "GitHub Token：未配置 → 点「GitHub Token…」"
        )
        self.tip.setText(
            f"统一目录（类似 mod 管理器）：{LIBRARY_LABEL}/分项目/项目本体(app) + 项目脚本(scripts)\n"
            f"路径：{LIBRARY_DIR}　｜　国内慢可设 GAME_RUNNER_GH_PROXY=https://ghproxy.net\n"
            f"{tok}"
        )

    def _open_token_dialog(self) -> None:
        GithubTokenDialog(self).exec()
        self._refresh_tip()

    def _append(self, msg: str) -> None:
        self.log.append(msg)

    def reload(self) -> None:
        tools = list_tools()
        self.table.setRowCount(0)
        for t in tools:
            st = installed_status(t.id)
            row = self.table.rowCount()
            self.table.insertRow(row)
            status = "已安装/已登记" if st.get("installed") else "未安装"
            vals = [t.game, t.name, status, t.description]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setData(Qt.ItemDataRole.UserRole, t.id)
                if c == 2 and st.get("installed"):
                    item.setForeground(QColor(styles.ACCENT))
                self.table.setItem(row, c, item)

            btn_install = QPushButton("安装 / 更新" if t.kind != "open_url" else "打开说明")
            if t.kind == "open_url":
                btn_install.clicked.connect(lambda _=False, tid=t.id: self._open_home(tid))
            else:
                btn_install.clicked.connect(lambda _=False, tid=t.id: self._start_install(tid))
            self.table.setCellWidget(row, 4, btn_install)

            btn_dir = QPushButton("目录")
            installed = bool(st.get("installed"))
            btn_dir.setEnabled(installed and t.kind != "open_url")
            btn_dir.setToolTip(f"打开 library\\{t.id}\\app")
            btn_dir.clicked.connect(lambda _=False, tid=t.id: self._open_project(tid))
            self.table.setCellWidget(row, 5, btn_dir)

            btn_home = QPushButton("主页")
            btn_home.setEnabled(bool(t.homepage))
            btn_home.clicked.connect(
                lambda _=False, url=t.homepage: webbrowser.open(url) if url else None
            )
            self.table.setCellWidget(row, 6, btn_home)

    def _open_home(self, tool_id: str) -> None:
        from runner.tool_catalog import get_tool

        t = get_tool(tool_id)
        if t and t.homepage:
            webbrowser.open(t.homepage)
            if t.notes:
                self._append(t.notes)

    def _start_install(self, tool_id: str) -> None:
        if self._busy:
            QMessageBox.information(self, "提示", "已有安装任务在进行")
            return
        self._busy = True
        self._append(f"—— 开始安装 {tool_id} → library\\{tool_id}\\app\\ ——")
        job = _InstallJob(tool_id)
        job.signals.log.connect(self._append)
        job.signals.done.connect(self._on_install_done)
        QThreadPool.globalInstance().start(job)

    @Slot(object)
    def _on_install_done(self, result: object) -> None:
        self._busy = False
        r = result if isinstance(result, dict) else {"ok": False, "error": "unknown"}
        if r.get("open_url"):
            webbrowser.open(str(r["open_url"]))
        if r.get("ok"):
            self._append(r.get("message") or "完成")
            if r.get("script"):
                self._append(f"脚本: {r['script'].get('id')} → {r['script'].get('path')}")
            if self._on_changed:
                self._on_changed()
            QMessageBox.information(self, "完成", r.get("message") or "安装完成")
        else:
            err = r.get("error") or "失败"
            self._append(f"失败: {err}")
            if r.get("hint"):
                self._append(str(r["hint"]))
            home = r.get("homepage")
            if home and QMessageBox.question(
                self, "安装失败", f"{err}\n\n是否打开发布页手动下载？"
            ) == QMessageBox.Yes:
                webbrowser.open(str(home))
            else:
                QMessageBox.warning(self, "安装失败", err)
        self.reload()

    def _scan_all(self) -> None:
        ensure_library_root()
        ok_n = 0
        ids = list_projects()
        if not ids:
            QMessageBox.information(self, "提示", f"尚无分项目，先点「安装」或手动建文件夹。\n{LIBRARY_DIR}")
            return
        for name in ids:
            hit = False
            for folder in scan_roots_for_project(name):
                reg = scan_and_register(folder, log=self._append)
                if reg.get("ok"):
                    ok_n += 1
                    sid = (reg.get("script") or {}).get("id")
                    self._append(f"导入 {name} ← {folder} → {sid}")
                    hit = True
                    break
            if not hit:
                self._append(
                    f"未识别: {name}（请把本体放进 library\\{name}\\app\\，"
                    "或该分项目根下直接放解压包）"
                )
        if self._on_changed:
            self._on_changed()
        self.reload()
        QMessageBox.information(self, "扫描完成", f"成功登记 {ok_n} 项")

    def _open_library(self) -> None:
        ensure_library_root()
        try:
            import os

            os.startfile(str(LIBRARY_DIR))  # type: ignore[attr-defined]
        except Exception:
            self._append(str(LIBRARY_DIR))

    def _open_project(self, tool_id: str) -> None:
        folder = app_dir(tool_id)
        if not folder.is_dir():
            QMessageBox.information(
                self, "提示", f"尚未安装到：\n{folder}\n\n先点「安装 / 更新」。"
            )
            return
        try:
            import os

            os.startfile(str(folder))  # type: ignore[attr-defined]
        except OSError as e:
            QMessageBox.warning(self, "无法打开", f"{folder}\n{e}")
