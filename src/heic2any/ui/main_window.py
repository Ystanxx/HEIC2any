# -*- coding: utf-8 -*-
"""
主窗口：四区布局
- 顶部：应用名 + 开始/暂停/继续 + 停止 + 更多…
- 左栏：文件队列（拖拽/添加、缩略图+名称/尺寸/状态+进度）
- 右栏：检查器（导出设置/尺寸/DPI/命名Token、应用到选中/恢复默认）
- 底部：状态栏显示总进度
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, QSize, Signal, QObject
from PySide6.QtGui import QAction, QIcon, QPixmap, QImage
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSplitter, QTreeWidget, QTreeWidgetItem, QFileDialog, QMenu, QToolButton,
    QStatusBar, QProgressBar, QComboBox, QGroupBox, QFormLayout, QSlider,
    QSpinBox, QCheckBox, QLineEdit, QStyle, QMessageBox, QDialog, QListWidget,
    QListWidgetItem, QDialogButtonBox, QSystemTrayIcon
)

from heic2any.core.state import JobItem, JobStatus, ExportFormat, AppSettings
from heic2any.core.tasks import TaskManager
from heic2any.utils.images import make_placeholder_thumbnail, load_thumbnail
from heic2any.utils.naming import render_output_name
from heic2any.utils.conda import CondaEnv, find_conda_envs, test_env_dependencies


class EnvSelectDialog(QDialog):
    """Conda环境选择对话框。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("选择Conda环境")
        self.resize(560, 420)
        lay = QVBoxLayout(self)
        self.listw = QListWidget()
        lay.addWidget(self.listw, 1)
        self.btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        lay.addWidget(self.btns)
        self.btns.accepted.connect(self.accept)
        self.btns.rejected.connect(self.reject)
        # 加载环境
        envs = find_conda_envs()
        for e in envs:
            it = QListWidgetItem(f"{e.name} — {e.prefix}")
            it.setData(Qt.UserRole, e)
            self.listw.addItem(it)

    def selected_env(self) -> CondaEnv | None:
        it = self.listw.currentItem()
        if not it:
            return None
        return it.data(Qt.UserRole)


class SignalBus(QObject):
    """跨线程信号总线：确保UI更新在主线程执行。"""
    job_update = Signal(int, object)  # (index, JobItem)
    overall_update = Signal(int, int)
    thumb_ready = Signal(int, str, object)  # (index, src_path, QImage)


class MainWindow(QMainWindow):
    """应用主窗口。"""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("HEIC2any")
        self.resize(1200, 720)

        # 应用设置（可通过偏好设置修改并持久化）
        self.settings = AppSettings.load()

        # 任务管理器（并发 + 控制）
        # 信号总线
        self.bus = SignalBus(self)
        self.bus.job_update.connect(self._on_job_update)
        self.bus.overall_update.connect(self._on_overall_update)
        self.bus.thumb_ready.connect(self._on_thumb_ready)

        self.task_manager = TaskManager(
            threads=self.settings.default_threads,
            on_job_update=self.bus.job_update.emit,   # 由工作线程发射信号，Qt队列到主线程
            on_overall_update=self.bus.overall_update.emit,
        )

        # 界面
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(6)

        # 顶部工具栏
        topbar = self._build_topbar()
        root_layout.addWidget(topbar)

        # 中部：左右分割
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        left = self._build_queue()
        right = self._build_inspector()
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([700, 500])
        root_layout.addWidget(splitter)

        # 底部状态栏
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.total_progress = QProgressBar()
        self.total_progress.setRange(0, 100)
        self.total_progress.setValue(0)
        self.status.addPermanentWidget(QLabel("总进度"))
        self.status.addPermanentWidget(self.total_progress, 1)
        self._label_remaining = QLabel("剩余：0")
        self.status.addPermanentWidget(self._label_remaining)

        self.setCentralWidget(root)

        # 选择的输出目录
        self.output_dir = self.settings.default_output_dir
        if not os.path.isdir(self.output_dir):
            os.makedirs(self.output_dir, exist_ok=True)

        # 内部数据
        self.jobs: List[JobItem] = []
        self._selected_indices: List[int] = []
        # 缩略图后台线程池（小并发，减少IO阻塞）
        from concurrent.futures import ThreadPoolExecutor
        self._thumb_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="thumbs")
        self._start_button_state = "start"  # start|pause|resume
        self._really_quit = False
        self._notified_all_done = False

        # 系统托盘
        self._init_tray()

        # 初始化UI状态
        self._refresh_topbar_states()
        self._refresh_inspector_preview()

    # ---------- 顶部工具栏 ----------
    def _build_topbar(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        title = QLabel("HEIC2any")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")

        btn_start = QPushButton("开始")
        btn_stop = QPushButton("停止")
        btn_start.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        btn_stop.setIcon(self.style().standardIcon(QStyle.SP_BrowserStop))
        btn_start.clicked.connect(self._on_click_start_pause_resume)
        btn_stop.clicked.connect(self._on_click_stop)
        self._btn_start = btn_start
        self._btn_stop = btn_stop

        # 右侧更多菜单
        more_btn = QToolButton()
        more_btn.setText("更多…")
        more_btn.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu()

        act_clear = QAction("清空队列", self)
        act_clear.triggered.connect(self._action_clear_queue)
        act_reset = QAction("恢复默认", self)
        act_reset.triggered.connect(self._action_reset_defaults)
        act_choose_env = QAction("选择环境", self)
        act_choose_env.triggered.connect(self._action_choose_env)
        act_prefs = QAction("偏好设置", self)
        act_prefs.triggered.connect(self._action_open_prefs)
        menu.addAction(act_clear)
        menu.addAction(act_reset)
        menu.addSeparator()
        menu.addAction(act_choose_env)
        menu.addAction(act_prefs)

        more_btn.setMenu(menu)

        lay.addWidget(title, 0, Qt.AlignLeft)
        lay.addWidget(btn_start, 0, Qt.AlignLeft)
        lay.addWidget(btn_stop, 0, Qt.AlignLeft)
        lay.addStretch(1)
        lay.addWidget(more_btn, 0, Qt.AlignRight)
        return w

    def _refresh_topbar_states(self) -> None:
        if self._start_button_state == "start":
            self._btn_start.setText("开始")
            self._btn_start.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        elif self._start_button_state == "pause":
            self._btn_start.setText("暂停")
            self._btn_start.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        else:
            self._btn_start.setText("继续")
            self._btn_start.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        # 同步托盘菜单文案
        if hasattr(self, '_act_tray_toggle'):
            if self._start_button_state == "start":
                self._act_tray_toggle.setText("开始")
            elif self._start_button_state == "pause":
                self._act_tray_toggle.setText("暂停")
            else:
                self._act_tray_toggle.setText("继续")

    def _on_click_start_pause_resume(self) -> None:
        if self._start_button_state == "start":
            # 提交任务
            self.task_manager.set_threads(self.ins_threads.value())
            self.task_manager.start(self.jobs)
            self._start_button_state = "pause"
            self._notified_all_done = False
        elif self._start_button_state == "pause":
            self.task_manager.pause()
            self._start_button_state = "resume"
        else:
            self.task_manager.resume()
            self._start_button_state = "pause"
        self._refresh_topbar_states()

    def _on_click_stop(self) -> None:
        self.task_manager.stop()
        self._start_button_state = "start"
        self._refresh_topbar_states()

    def _action_clear_queue(self) -> None:
        self.task_manager.stop()
        self.jobs.clear()
        self.queue.clear()
        self._update_total_progress()
        self._notified_all_done = False

    def _action_reset_defaults(self) -> None:
        self.settings = AppSettings()  # 恢复默认
        AppSettings.save(self.settings)
        self._load_settings_into_inspector()
        self._refresh_inspector_preview()

    def _action_open_prefs(self) -> None:
        # 轻量化：直接基于当前 inspector 的设置保存为默认
        self._apply_inspector_to_defaults()
        QMessageBox.information(self, "提示", "已将当前检查器作为偏好设置保存")

    def _action_choose_env(self) -> None:
        dlg = EnvSelectDialog(self)
        if dlg.exec() == QDialog.Accepted:
            env = dlg.selected_env()
            if env is None:
                QMessageBox.information(self, "环境", "未选择环境")
                return
            okdep, msg = test_env_dependencies(env)
            # 保存到设置
            self.settings.selected_env_prefix = env.prefix
            AppSettings.save(self.settings)
            tip = f"已选择环境：{env.name}\n路径：{env.prefix}\n依赖检测：{msg}"
            QMessageBox.information(self, "环境", tip)

    # ---------- 左侧文件队列 ----------
    def _build_queue(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        header = QHBoxLayout()
        btn_add_files = QPushButton("添加文件")
        btn_add_dir = QPushButton("添加文件夹")
        btn_choose_out = QPushButton("选择输出目录")
        btn_add_files.clicked.connect(self._add_files)
        btn_add_dir.clicked.connect(self._add_dir)
        btn_choose_out.clicked.connect(self._choose_output_dir)
        header.addWidget(btn_add_files)
        header.addWidget(btn_add_dir)
        header.addStretch(1)
        header.addWidget(btn_choose_out)

        self.queue = QTreeWidget()
        self.queue.setColumnCount(6)
        self.queue.setHeaderLabels(["缩略图", "名称", "尺寸", "状态", "进度", "错误"])
        self.queue.setRootIsDecorated(False)
        self.queue.setAlternatingRowColors(True)
        self.queue.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.queue.setIconSize(QSize(48, 48))
        self.queue.setAcceptDrops(True)
        self.queue.dragEnterEvent = self._drag_enter
        self.queue.dropEvent = self._drop
        self.queue.itemSelectionChanged.connect(self._on_selection_changed)

        lay.addLayout(header)
        lay.addWidget(self.queue, 1)
        return w

    def _drag_enter(self, e):  # type: ignore
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            e.ignore()

    def _drop(self, e):  # type: ignore
        paths = []
        for url in e.mimeData().urls():
            p = url.toLocalFile()
            if os.path.isdir(p):
                for root, _, files in os.walk(p):
                    for fn in files:
                        if fn.lower().endswith(('.heic', '.heif')):
                            paths.append(os.path.join(root, fn))
            else:
                if p.lower().endswith(('.heic', '.heif')):
                    paths.append(p)
        self._append_jobs(paths)

    def _on_selection_changed(self) -> None:
        sel = self.queue.selectedItems()
        indices: List[int] = []
        for it in sel:
            idx = it.data(0, Qt.UserRole)
            if idx is not None:
                indices.append(int(idx))
        self._selected_indices = sorted(indices)
        self._load_selected_to_inspector()

    def _choose_output_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择输出目录", self.output_dir)
        if d:
            self.output_dir = d
            # 保存到设置并应用到队列中的待处理任务
            self.settings.default_output_dir = d
            AppSettings.save(self.settings)
            self._apply_output_dir_to_jobs()
            self._refresh_inspector_preview()

    def _apply_output_dir_to_jobs(self) -> None:
        """将当前选择的输出目录应用到队列中的未完成任务。"""
        changed = 0
        for j in self.jobs:
            if j.status in (JobStatus.WAITING, JobStatus.PAUSED):
                j.export_dir = self.output_dir
                changed += 1
        if changed:
            QMessageBox.information(self, "输出目录", f"已将输出目录应用到{changed}个未完成任务")

    def _add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择HEIC文件", os.getcwd(), "HEIC 文件 (*.heic *.heif);;所有文件 (*.*)")
        self._append_jobs(files)

    def _add_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择文件夹", os.getcwd())
        if not d:
            return
        paths: List[str] = []
        for root, _, files in os.walk(d):
            for fn in files:
                if fn.lower().endswith(('.heic', '.heif')):
                    paths.append(os.path.join(root, fn))
        self._append_jobs(paths)

    def _append_jobs(self, paths: List[str]) -> None:
        added = 0
        for p in paths:
            if not os.path.isfile(p):
                continue
            item = JobItem.from_source(p)
            item.export_dir = self.output_dir
            self.jobs.append(item)
            row = self._create_row(item, len(self.jobs)-1)
            self.queue.addTopLevelItem(row)
            added += 1
        if added == 0:
            QMessageBox.information(self, "提示", "未添加任何HEIC文件")
        self._update_total_progress()

    def _create_row(self, job: JobItem, index: int) -> QTreeWidgetItem:
        it = QTreeWidgetItem(["", os.path.basename(job.src_path), job.size_text(), job.status_text(), "0%", ""]) 
        it.setData(0, Qt.UserRole, index)
        # 缩略图
        # 先放占位，避免阻塞UI
        placeholder = make_placeholder_thumbnail()
        it.setIcon(0, QIcon(placeholder))
        # 异步加载真实缩略图（QImage），回到主线程设置
        idx = index
        src = job.src_path
        def _load_and_emit():
            img: QImage | None = load_thumbnail(src)
            if img is not None:
                # 通过Qt信号回到UI线程
                self.bus.thumb_ready.emit(idx, src, img)
        self._thumb_pool.submit(_load_and_emit)
        return it

    # ---------- 右侧检查器 ----------
    def _build_inspector(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 0, 0, 0)
        lay.setSpacing(10)

        # 导出设置
        grp_export = QGroupBox("导出设置")
        form1 = QFormLayout(grp_export)
        self.ins_format = QComboBox()
        for fmt in ExportFormat.list_display():
            self.ins_format.addItem(fmt)
        self.ins_quality = QSlider(Qt.Horizontal)
        self.ins_quality.setRange(1, 100)
        self.ins_quality.setValue(90)
        self.ins_quality_lbl = QLabel("90")
        self.ins_quality.valueChanged.connect(lambda v: self.ins_quality_lbl.setText(str(v)))
        qrow = QWidget(); qlay = QHBoxLayout(qrow); qlay.setContentsMargins(0,0,0,0)
        qlay.addWidget(self.ins_quality, 1); qlay.addWidget(self.ins_quality_lbl)

        self.ins_dpi_x = QSpinBox(); self.ins_dpi_x.setRange(50, 600); self.ins_dpi_x.setValue(300)
        self.ins_dpi_y = QSpinBox(); self.ins_dpi_y.setRange(50, 600); self.ins_dpi_y.setValue(300)

        form1.addRow("格式", self.ins_format)
        form1.addRow("质量", qrow)
        form1.addRow("DPI-X", self.ins_dpi_x)
        form1.addRow("DPI-Y", self.ins_dpi_y)

        # 尺寸
        grp_size = QGroupBox("尺寸")
        form2 = QFormLayout(grp_size)
        self.ins_width = QSpinBox(); self.ins_width.setMaximum(20000); self.ins_width.setValue(0)
        self.ins_height = QSpinBox(); self.ins_height.setMaximum(20000); self.ins_height.setValue(0)
        self.ins_keep_aspect = QCheckBox("保持比例")
        self.ins_keep_aspect.setChecked(True)
        form2.addRow("宽(px)", self.ins_width)
        form2.addRow("高(px)", self.ins_height)
        form2.addRow("比例", self.ins_keep_aspect)

        # 输出命名
        grp_name = QGroupBox("输出命名")
        form3 = QFormLayout(grp_name)
        self.ins_template = QLineEdit("{name}_{index}")
        self.ins_token = QComboBox(); self.ins_token.addItems(["{name}", "{index}", "{date}", "{datetime}", "{width}", "{height}"])
        btn_insert = QPushButton("插入Token")
        btn_insert.clicked.connect(lambda: self.ins_template.insert(self.ins_token.currentText()))
        rowt = QWidget(); rt = QHBoxLayout(rowt); rt.setContentsMargins(0,0,0,0)
        rt.addWidget(self.ins_template, 1); rt.addWidget(self.ins_token); rt.addWidget(btn_insert)
        self.ins_preview = QLabel("")
        form3.addRow("模板", rowt)
        form3.addRow("预览", self.ins_preview)

        # 线程与按钮
        grp_misc = QGroupBox("并发与应用")
        form4 = QFormLayout(grp_misc)
        self.ins_threads = QSpinBox(); self.ins_threads.setRange(1, 64); self.ins_threads.setValue(self.settings.default_threads)
        btn_apply_sel = QPushButton("应用到选中")
        btn_apply_sel.clicked.connect(self._apply_to_selected)
        btn_reset = QPushButton("恢复默认")
        btn_reset.clicked.connect(self._action_reset_defaults)
        form4.addRow("线程数", self.ins_threads)
        form4.addRow("", btn_apply_sel)
        form4.addRow("", btn_reset)

        lay.addWidget(grp_export)
        lay.addWidget(grp_size)
        lay.addWidget(grp_name)
        lay.addWidget(grp_misc)
        lay.addStretch(1)
        self._load_settings_into_inspector()
        return w

    def _load_settings_into_inspector(self) -> None:
        # 将当前AppSettings装载进检查器
        self.ins_format.setCurrentText(self.settings.default_format)
        self.ins_quality.setValue(self.settings.default_quality)
        self.ins_dpi_x.setValue(self.settings.default_dpi[0])
        self.ins_dpi_y.setValue(self.settings.default_dpi[1])
        self.ins_width.setValue(self.settings.default_size[0])
        self.ins_height.setValue(self.settings.default_size[1])
        self.ins_keep_aspect.setChecked(self.settings.default_keep_aspect)
        self.ins_threads.setValue(self.settings.default_threads)
        self.ins_template.setText(self.settings.default_template)

    def _apply_inspector_to_defaults(self) -> None:
        # 将检查器值保存为默认设置
        self.settings.default_format = self.ins_format.currentText()
        self.settings.default_quality = self.ins_quality.value()
        self.settings.default_dpi = (self.ins_dpi_x.value(), self.ins_dpi_y.value())
        self.settings.default_size = (self.ins_width.value(), self.ins_height.value())
        self.settings.default_keep_aspect = self.ins_keep_aspect.isChecked()
        self.settings.default_threads = self.ins_threads.value()
        self.settings.default_template = self.ins_template.text()
        AppSettings.save(self.settings)

    def _load_selected_to_inspector(self) -> None:
        # 读取选中项，展示命名预览
        self._refresh_inspector_preview()

    def _refresh_inspector_preview(self) -> None:
        if not self._selected_indices:
            self.ins_preview.setText("(未选择项目)")
            return
        first = self.jobs[self._selected_indices[0]]
        name = render_output_name(self.ins_template.text(), first, index=1)
        self.ins_preview.setText(name)

    def _apply_to_selected(self) -> None:
        if not self._selected_indices:
            QMessageBox.information(self, "提示", "请先选中文件")
            return
        for idx in self._selected_indices:
            job = self.jobs[idx]
            job.export_format = self.ins_format.currentText()
            job.quality = self.ins_quality.value()
            job.dpi = (self.ins_dpi_x.value(), self.ins_dpi_y.value())
            job.req_size = (self.ins_width.value(), self.ins_height.value())
            job.keep_aspect = self.ins_keep_aspect.isChecked()
            job.template = self.ins_template.text()
        QMessageBox.information(self, "提示", "已应用到选中项")

    # ---------- 任务回调、状态更新 ----------
    def _on_job_update(self, job_index: int, job: JobItem) -> None:
        # 保证UI线程安全：Qt回调已在UI线程执行
        it = self.queue.topLevelItem(job_index)
        if not it:
            return
        it.setText(2, job.size_text())
        it.setText(3, job.status_text())
        it.setText(4, f"{job.progress}%")
        it.setText(5, job.error or "")
        # 出错弹出通知（后台可见）
        if job.status == JobStatus.FAILED and job.error:
            base = os.path.basename(job.src_path)
            self._show_notification("转换失败", f"{base}: {job.error}", error=True)

    def _on_overall_update(self, total_progress: int, remaining: int) -> None:
        # 由UI侧统一统计总进度，忽略传入值
        self._update_total_progress()

    def _on_thumb_ready(self, idx: int, src_path: str, img: QImage) -> None:
        # 验证索引与路径，避免因队列变化导致错配
        if idx < 0 or idx >= len(self.jobs):
            return
        if self.jobs[idx].src_path != src_path:
            return
        it = self.queue.topLevelItem(idx)
        if not it:
            return
        pix = QPixmap.fromImage(img)
        it.setIcon(0, QIcon(pix))

    def _update_total_progress(self) -> None:
        total = len(self.jobs)
        if total == 0:
            self.total_progress.setValue(0)
            self._label_remaining.setText("剩余：0")
            return
        done = sum(1 for j in self.jobs if j.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED))
        self.total_progress.setValue(int(100 * done / total))
        self._label_remaining.setText(f"剩余：{total - done}")
        # 全部完成时弹出通知（只弹一次）
        if done == total and total > 0 and not self._notified_all_done:
            succ = sum(1 for j in self.jobs if j.status == JobStatus.COMPLETED)
            fail = sum(1 for j in self.jobs if j.status == JobStatus.FAILED)
            canc = sum(1 for j in self.jobs if j.status == JobStatus.CANCELLED)
            self._show_notification("处理完成", f"共{total}项：成功{succ}，失败{fail}，取消{canc}")
            self._notified_all_done = True

    # ---------- 托盘与后台 ----------
    def _init_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(self)
        icon = self.windowIcon() if not self.windowIcon().isNull() else QIcon()
        self.tray.setIcon(icon)
        menu = QMenu(self)
        act_show = QAction("显示窗口", self)
        act_show.triggered.connect(self._restore_from_tray)
        self._act_tray_toggle = QAction("开始", self)
        self._act_tray_toggle.triggered.connect(self._on_click_start_pause_resume)
        act_stop = QAction("停止", self)
        act_stop.triggered.connect(self._on_click_stop)
        act_exit = QAction("退出", self)
        act_exit.triggered.connect(self._tray_exit)
        menu.addAction(act_show)
        menu.addSeparator()
        menu.addAction(self._act_tray_toggle)
        menu.addAction(act_stop)
        menu.addSeparator()
        menu.addAction(act_exit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()
        # 初始状态同步
        self._refresh_topbar_states()

    def _on_tray_activated(self, reason):  # type: ignore
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._restore_from_tray()

    def _restore_from_tray(self) -> None:
        self.showNormal()
        self.activateWindow()

    def _tray_exit(self) -> None:
        # 托盘菜单退出：真正退出应用
        self._really_quit = True
        try:
            self.task_manager.stop()
        except Exception:
            pass
        try:
            self._thumb_pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        from PySide6.QtWidgets import QApplication
        QApplication.instance().quit()

    def _show_notification(self, title: str, message: str, error: bool = False) -> None:
        try:
            if hasattr(self, 'tray') and self.tray and self.tray.isVisible():
                icon = QSystemTrayIcon.MessageIcon.Critical if error else QSystemTrayIcon.MessageIcon.Information
                # Windows气泡通知自动消失
                self.tray.showMessage(title, message, icon, 4000)
        except Exception:
            pass

    # ---------- 关闭处理 ----------
    def closeEvent(self, event):  # type: ignore
        # 关闭按钮 → 最小化到托盘，继续后台处理
        if not self._really_quit and hasattr(self, 'tray') and self.tray.isVisible():
            event.ignore()
            self.hide()
            # 一次性提示
            self._show_notification("后台运行", "程序已最小化到托盘，继续在后台处理。")
            return
        # 真正退出
        try:
            self.task_manager.stop()
        except Exception:
            pass
        try:
            self._thumb_pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        super().closeEvent(event)
