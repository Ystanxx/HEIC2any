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

from PySide6.QtCore import Qt, QSize, Signal, QObject, QEvent
from PySide6.QtGui import QAction, QIcon, QPixmap, QImage, QCursor
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSplitter, QTreeWidget, QTreeWidgetItem, QFileDialog, QMenu, QToolButton,
    QStatusBar, QProgressBar, QComboBox, QGroupBox, QFormLayout, QSlider,
    QSpinBox, QCheckBox, QLineEdit, QStyle, QMessageBox, QDialog, QListWidget,
    QListWidgetItem, QDialogButtonBox, QSystemTrayIcon, QRadioButton, QStackedWidget, QSizePolicy, QGridLayout
)
from PySide6.QtWidgets import QAbstractSpinBox

from heic2any.core.state import JobItem, JobStatus, ExportFormat, AppSettings
from heic2any.core.tasks import TaskManager
from heic2any.utils.images import make_placeholder_thumbnail, load_thumbnail, get_image_size
from heic2any.utils.naming import render_output_name, build_output_path
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


class AppSettingsDialog(QDialog):
    """应用设置对话框：通知开关与关闭行为选项。"""

    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.resize(420, 220)
        lay = QVBoxLayout(self)

        # 通知
        grp_notify = QGroupBox("通知")
        fl1 = QFormLayout(grp_notify)
        self.chk_notify = QCheckBox("是否打开通知？")  # 左侧勾选框 + 文案
        self.chk_notify.setChecked(bool(getattr(settings, 'enable_notifications', True)))
        fl1.addRow(self.chk_notify)

        # 关闭行为
        grp_close = QGroupBox("关闭程序行为")
        fl2 = QFormLayout(grp_close)
        self.radio_exit = QRadioButton("直接退出")
        self.radio_min = QRadioButton("最小化后台运行")
        act = getattr(settings, 'on_close_action', 'ask')
        if act == 'exit':
            self.radio_exit.setChecked(True)
        elif act == 'minimize':
            self.radio_min.setChecked(True)
        else:
            # 默认倾向最小化
            self.radio_min.setChecked(True)
        fl2.addRow(self.radio_exit)
        fl2.addRow(self.radio_min)

        # 输入文件信息选择
        grp_info = QGroupBox("输入文件信息")
        fl_info = QFormLayout(grp_info)
        self.chk_show_dims = QCheckBox("显示尺寸")
        self.chk_show_size = QCheckBox("显示文件大小")
        self.chk_show_est = QCheckBox("显示预估大小")
        self.chk_show_dims.setChecked(bool(getattr(settings, 'show_col_dims', True)))
        self.chk_show_size.setChecked(bool(getattr(settings, 'show_col_size', True)))
        self.chk_show_est.setChecked(bool(getattr(settings, 'show_col_estimate', True)))
        fl_info.addRow(self.chk_show_dims)
        fl_info.addRow(self.chk_show_size)
        fl_info.addRow(self.chk_show_est)

        # 重名处理
        grp_dup = QGroupBox("重名文件处理")
        fl3 = QFormLayout(grp_dup)
        self.radio_dup_replace = QRadioButton("替换已存在的同名文件")
        self.radio_dup_skip = QRadioButton("跳过已存在的同名文件")
        self.radio_dup_ask = QRadioButton("让我决定每个文件")
        pol = getattr(settings, 'collision_policy', 'ask')
        if pol == 'replace':
            self.radio_dup_replace.setChecked(True)
        elif pol == 'skip':
            self.radio_dup_skip.setChecked(True)
        else:
            self.radio_dup_ask.setChecked(True)
        fl3.addRow(self.radio_dup_replace)
        fl3.addRow(self.radio_dup_skip)
        fl3.addRow(self.radio_dup_ask)

        # 按钮
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        # 统一OK/Cancel按钮宽度
        try:
            okb = btns.button(QDialogButtonBox.Ok)
            cb = btns.button(QDialogButtonBox.Cancel)
            for b in (okb, cb):
                if b is not None:
                    b.setMinimumWidth(96)
        except Exception:
            pass

        lay.addWidget(grp_notify)
        lay.addWidget(grp_close)
        lay.addWidget(grp_info)
        lay.addWidget(grp_dup)
        lay.addStretch(1)
        lay.addWidget(btns)

    def values(self) -> tuple[bool, str, str, dict]:
        """返回(启用通知, 关闭行为, 重名策略, 列显示设置)。"""
        enable = self.chk_notify.isChecked()
        action = 'minimize' if self.radio_min.isChecked() else 'exit'
        if self.radio_dup_replace.isChecked():
            dup = 'replace'
        elif self.radio_dup_skip.isChecked():
            dup = 'skip'
        else:
            dup = 'ask'
        cols = {
            'show_col_dims': self.chk_show_dims.isChecked(),
            'show_col_size': self.chk_show_size.isChecked(),
            'show_col_estimate': self.chk_show_est.isChecked(),
        }
        return enable, action, dup, cols


class FormatSettingsDialog(QDialog):
    """格式相关的高级设置对话框。"""

    def __init__(self, fmt: str, parent: QWidget | None, mw: 'MainWindow') -> None:
        super().__init__(parent)
        self.setWindowTitle("更多设置")
        self.resize(420, 320)
        self._fmt = (fmt or '').lower()
        self._mw = mw
        lay = QVBoxLayout(self)

        form = QFormLayout()
        # 通用：DPI
        self.sp_dpi_x = QSpinBox(); self.sp_dpi_x.setRange(50, 1200); self.sp_dpi_x.setValue(mw._adv_dpi_x)
        self.sp_dpi_y = QSpinBox(); self.sp_dpi_y.setRange(50, 1200); self.sp_dpi_y.setValue(mw._adv_dpi_y)
        form.addRow("DPI-X", self.sp_dpi_x)
        form.addRow("DPI-Y", self.sp_dpi_y)

        if self._fmt in ('jpg','jpeg'):
            self.chk_jpg_prog = QCheckBox("渐进式(Progressive)")
            self.chk_jpg_prog.setChecked(mw._adv_jpeg_progressive)
            self.chk_jpg_opt = QCheckBox("优化(Optimize)")
            self.chk_jpg_opt.setChecked(mw._adv_jpeg_optimize)
            form.addRow(self.chk_jpg_prog)
            form.addRow(self.chk_jpg_opt)
        elif self._fmt == 'png':
            self.chk_png_opt = QCheckBox("优化(Optimize)")
            self.chk_png_opt.setChecked(mw._adv_png_optimize)
            form.addRow(self.chk_png_opt)
        elif self._fmt == 'webp':
            self.chk_webp_lossless = QCheckBox("无损(Lossless)")
            self.chk_webp_lossless.setChecked(mw._adv_webp_lossless)
            self.sl_webp_method = QSlider(Qt.Horizontal); self.sl_webp_method.setRange(0, 6); self.sl_webp_method.setValue(int(mw._adv_webp_method))
            self.lbl_webp_method = QLabel(str(mw._adv_webp_method))
            self.sl_webp_method.valueChanged.connect(lambda v: self.lbl_webp_method.setText(str(v)))
            row = QWidget(); rlay = QHBoxLayout(row); rlay.setContentsMargins(0,0,0,0)
            rlay.addWidget(self.sl_webp_method, 1); rlay.addWidget(self.lbl_webp_method)
            form.addRow(self.chk_webp_lossless)
            form.addRow("方法(method)", row)
        elif self._fmt in ('tif','tiff'):
            self.cmb_tiff_comp = QComboBox(); self.cmb_tiff_comp.addItems(["tiff_deflate","tiff_lzw","tiff_adobe_deflate"])
            try:
                idx = ["tiff_deflate","tiff_lzw","tiff_adobe_deflate"].index(mw._adv_tiff_compression)
            except ValueError:
                idx = 0
            self.cmb_tiff_comp.setCurrentIndex(idx)
            form.addRow("压缩方式", self.cmb_tiff_comp)

        lay.addLayout(form)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        try:
            okb = btns.button(QDialogButtonBox.Ok)
            cb = btns.button(QDialogButtonBox.Cancel)
            for b in (okb, cb):
                if b is not None:
                    b.setMinimumWidth(96)
        except Exception:
            pass
        lay.addStretch(1)
        lay.addWidget(btns)

    def apply_to_main(self) -> None:
        """将对话框选择应用回主窗口缓存与设置。"""
        mw = self._mw
        # DPI
        mw._adv_dpi_x = self.sp_dpi_x.value()
        mw._adv_dpi_y = self.sp_dpi_y.value()
        # 格式相关
        if self._fmt in ('jpg','jpeg'):
            mw._adv_jpeg_progressive = bool(self.chk_jpg_prog.isChecked())
            mw._adv_jpeg_optimize = bool(self.chk_jpg_opt.isChecked())
            mw.settings.default_jpeg_progressive = mw._adv_jpeg_progressive
            mw.settings.default_jpeg_optimize = mw._adv_jpeg_optimize
        elif self._fmt == 'png':
            mw._adv_png_optimize = bool(self.chk_png_opt.isChecked())
            mw.settings.default_png_optimize = mw._adv_png_optimize
        elif self._fmt == 'webp':
            mw._adv_webp_lossless = bool(self.chk_webp_lossless.isChecked())
            mw._adv_webp_method = int(self.sl_webp_method.value())
            mw.settings.default_webp_lossless = mw._adv_webp_lossless
            mw.settings.default_webp_method = mw._adv_webp_method
        elif self._fmt in ('tif','tiff'):
            mw._adv_tiff_compression = self.cmb_tiff_comp.currentText()
            mw.settings.default_tiff_compression = mw._adv_tiff_compression
        # 通用默认写回
        mw.settings.default_dpi = (mw._adv_dpi_x, mw._adv_dpi_y)
        AppSettings.save(mw.settings)


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
        splitter.setHandleWidth(6)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        # 右栏达到最小宽度前不再压缩，左栏最小宽度与右栏一致作为压缩下限
        right_min = 480
        left.setMinimumWidth(right_min)
        right.setMinimumWidth(right_min)
        splitter.setSizes([900, right_min])
        root_layout.addWidget(splitter)

        # 底部状态栏
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.total_progress = QProgressBar()
        self.total_progress.setRange(0, 100)
        self.total_progress.setValue(0)
        self.status.addPermanentWidget(QLabel("总进度"))
        self._label_done = QLabel("已完成 0/0")
        self.status.addPermanentWidget(self._label_done)
        self.status.addPermanentWidget(self.total_progress, 1)
        self._label_remaining = QLabel("剩余：0")
        self.status.addPermanentWidget(self._label_remaining)

        self.setCentralWidget(root)

        # 选择的输出目录
        self.output_dir = self.settings.default_output_dir
        # 启动时不主动创建/弹窗，仅记录路径；在开始转换或用户主动修改时再校验

        # 内部数据
        self.jobs: List[JobItem] = []
        self._selected_indices: List[int] = []
        # 缩略图后台线程池（小并发，减少IO阻塞）
        from concurrent.futures import ThreadPoolExecutor
        self._thumb_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="thumbs")
        self._start_button_state = "start"  # start|pause|resume
        self._really_quit = False
        self._notified_all_done = False
        # 缩略图缓存
        self._thumb_cache: dict[int, QImage] = {}

        # 高级设置缓存（从AppSettings装载）
        self._adv_jpeg_progressive = bool(getattr(self.settings, 'default_jpeg_progressive', False))
        self._adv_jpeg_optimize = bool(getattr(self.settings, 'default_jpeg_optimize', True))
        self._adv_png_optimize = bool(getattr(self.settings, 'default_png_optimize', False))
        self._adv_webp_lossless = bool(getattr(self.settings, 'default_webp_lossless', False))
        self._adv_webp_method = int(getattr(self.settings, 'default_webp_method', 4))
        self._adv_tiff_compression = str(getattr(self.settings, 'default_tiff_compression', 'tiff_deflate'))
        self._adv_dpi_x, self._adv_dpi_y = self.settings.default_dpi

        # 系统托盘
        self._init_tray()

        # 初始化UI状态
        self._refresh_topbar_states()
        self._refresh_inspector_preview()
        
    def _make_card(self, title: str, link_text: str | None = None, link_cb=None) -> tuple[QWidget, QFormLayout]:
        """构建卡片样式分区，返回(卡片Widget, 内容FormLayout)。"""
        card = QWidget(); card.setObjectName('card')
        v = QVBoxLayout(card); v.setContentsMargins(12, 12, 12, 12); v.setSpacing(8)
        head = QWidget(); hl = QHBoxLayout(head); hl.setContentsMargins(0,0,0,0); hl.setSpacing(8)
        title_lbl = QLabel(title); title_lbl.setProperty('class', 'card-title')
        hl.addWidget(title_lbl)
        hl.addStretch(1)
        if link_text:
            link = QPushButton(link_text); link.setCursor(Qt.PointingHandCursor); link.setProperty('class','link')
            if link_cb:
                link.clicked.connect(link_cb)
            hl.addWidget(link)
        v.addWidget(head)
        body = QWidget(); form = QFormLayout(body); form.setFormAlignment(Qt.AlignLeft|Qt.AlignVCenter); form.setLabelAlignment(Qt.AlignLeft)
        form.setHorizontalSpacing(12); form.setVerticalSpacing(8)
        v.addWidget(body)
        return card, form

    # ---------- 顶部工具栏 ----------
    def _build_topbar(self) -> QWidget:
        """精简顶部，仅保留产品名；开始/停止按钮下移到左侧列表头部。"""
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        title = QLabel("HEIC2any")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        lay.addWidget(title, 0, Qt.AlignLeft)
        lay.addStretch(1)
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
            # 空队列防护：无文件或无待处理项时提示且不改变按钮状态
            pending = [j for j in self.jobs if j.status in (JobStatus.WAITING, JobStatus.PAUSED)]
            if len(pending) == 0:
                self._show_info("队列为空，请先添加文件")
                return
            # 解析并发设置（Auto/手动）
            if hasattr(self, 'rb_auto') and self.rb_auto.isChecked():
                self.ins_threads.setValue(self._auto_threads)
            # 在开始前，将当前检查器参数应用到所有未完成任务，避免仅更改下拉未点击“应用到选中”导致始终导出JPG
            self._apply_current_settings_to_pending_jobs()
            # 提交任务前进行重名检测与处理
            if not self._preflight_conflicts():
                return
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
        self._update_empty_placeholder()

    def _action_reset_defaults(self) -> None:
        self.settings = AppSettings()  # 恢复默认
        AppSettings.save(self.settings)
        self._load_settings_into_inspector()
        self._refresh_inspector_preview()
        # 同步高级设置缓存
        self._adv_jpeg_progressive = self.settings.default_jpeg_progressive
        self._adv_jpeg_optimize = self.settings.default_jpeg_optimize
        self._adv_png_optimize = self.settings.default_png_optimize
        self._adv_webp_lossless = self.settings.default_webp_lossless
        self._adv_webp_method = self.settings.default_webp_method
        self._adv_tiff_compression = self.settings.default_tiff_compression
        self._adv_dpi_x, self._adv_dpi_y = self.settings.default_dpi

    def _action_open_prefs(self) -> None:
        # 轻量化：直接基于当前 inspector 的设置保存为默认
        self._apply_inspector_to_defaults()
        self._show_info("已将当前检查器作为偏好设置保存")

    def _action_choose_env(self) -> None:
        dlg = EnvSelectDialog(self)
        if dlg.exec() == QDialog.Accepted:
            env = dlg.selected_env()
            if env is None:
                self._show_info("未选择环境","环境")
                return
            okdep, msg = test_env_dependencies(env)
            # 保存到设置
            self.settings.selected_env_prefix = env.prefix
            AppSettings.save(self.settings)
            tip = f"已选择环境：{env.name}\n路径：{env.prefix}\n依赖检测：{msg}"
            self._show_info(tip,"环境")

    # ---------- 左侧文件队列 ----------
    def _build_queue(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(8)
        # 开始/停止按钮下移到此处
        btn_start = QPushButton("开始"); btn_start.setObjectName("btnStart"); btn_start.setFixedHeight(48); btn_start.setMinimumWidth(120)
        btn_stop = QPushButton("停止"); btn_stop.setObjectName("btnStop"); btn_stop.setFixedHeight(48); btn_stop.setMinimumWidth(120)
        btn_start.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        btn_stop.setIcon(self.style().standardIcon(QStyle.SP_BrowserStop))
        btn_start.clicked.connect(self._on_click_start_pause_resume)
        btn_stop.clicked.connect(self._on_click_stop)
        self._btn_start = btn_start
        self._btn_stop = btn_stop

        btn_choose_out = QToolButton(); btn_choose_out.setText("选择输出目录"); btn_choose_out.setToolButtonStyle(Qt.ToolButtonTextOnly); btn_choose_out.setAutoRaise(False); btn_choose_out.setFixedHeight(32)
        btn_settings = QToolButton(); btn_settings.setText("设置"); btn_settings.setToolButtonStyle(Qt.ToolButtonTextOnly); btn_settings.setAutoRaise(False); btn_settings.setFixedHeight(32)
        btn_choose_out.clicked.connect(self._choose_output_dir)
        btn_settings.clicked.connect(self._open_settings)

        header.addWidget(btn_start)
        header.addWidget(btn_stop)
        header.addStretch(1)
        header.addWidget(btn_choose_out)
        header.addWidget(btn_settings)

        self.queue = QTreeWidget()
        self.queue.setColumnCount(8)
        self.queue.setHeaderLabels(["缩略图", "名称", "尺寸", "大小", "预估", "状态", "进度", "错误"])
        self.queue.setRootIsDecorated(False)
        self.queue.setAlternatingRowColors(True)
        self.queue.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.queue.setIconSize(QSize(48, 48))
        self.queue.setAcceptDrops(True)
        self.queue.dragEnterEvent = self._drag_enter
        self.queue.dragMoveEvent = self._drag_move
        self.queue.dropEvent = self._drop
        self.queue.itemSelectionChanged.connect(self._on_selection_changed)
        try:
            self.queue.header().sectionResized.connect(self._on_queue_section_resized)
            self._update_row_height_for_thumb()
        except Exception:
            pass
        # 空状态提示覆盖到列表内部，允许拖拽到列表
        self._empty = QLabel("拖拽或点击添加文件", self.queue.viewport())
        self._empty.setAlignment(Qt.AlignCenter)
        self._empty.setStyleSheet("color:#9CA3AF; font-size:14px;")
        self._empty.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._empty.show()
        # 设置初始几何并跟随列表 viewport 尺寸
        try:
            self._empty.setGeometry(self.queue.viewport().rect())
        except Exception:
            pass
        _orig_resize = self.queue.resizeEvent
        def _resize(ev):
            try:
                self._empty.setGeometry(self.queue.viewport().rect())
            except Exception:
                pass
            _orig_resize(ev)
        self.queue.resizeEvent = _resize  # type: ignore

        # 允许点击列表空白区域弹出选择菜单（添加文件/文件夹）
        self.queue.viewport().installEventFilter(self)

        lay.addLayout(header)
        lay.addWidget(self.queue, 1)
        self._update_empty_placeholder()
        return w

    def _drag_enter(self, e):  # type: ignore
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            e.ignore()

    def _drag_move(self, e):  # type: ignore
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

    def eventFilter(self, obj, event):  # type: ignore
        # 点击左侧空白区域：左键→直接选择文件；右键→弹出菜单（文件/文件夹）
        try:
            if obj is self.queue.viewport() and event.type() == QEvent.MouseButtonRelease and event.buttons() == Qt.NoButton:
                pos = event.pos()
                # 若点击位置没有条目，则展示菜单
                if self.queue.itemAt(pos) is None:
                    if event.button() == Qt.RightButton:
                        menu = QMenu(self)
                        act_files = QAction("添加文件", self)
                        act_files.triggered.connect(self._add_files)
                        act_dir = QAction("添加文件夹", self)
                        act_dir.triggered.connect(self._add_dir)
                        menu.addAction(act_files)
                        menu.addAction(act_dir)
                        gp = self.queue.viewport().mapToGlobal(pos)
                        menu.exec(gp)
                    else:
                        self._add_files()
                    return True
        except Exception:
            pass
        return super().eventFilter(obj, event)

    def _update_empty_placeholder(self) -> None:
        """根据队列是否为空显示/隐藏内置提示。"""
        try:
            if hasattr(self, 'queue') and hasattr(self, '_empty'):
                self._empty.setGeometry(self.queue.viewport().rect())
                self._empty.setVisible(self.queue.topLevelItemCount() == 0)
        except Exception:
            pass

    def _apply_column_visibility(self) -> None:
        """根据设置隐藏或显示输入信息列，避免不必要的计算。"""
        try:
            # 列索引：2=尺寸, 3=大小, 4=预估
            self.queue.setColumnHidden(2, not getattr(self.settings, 'show_col_dims', True))
            self.queue.setColumnHidden(3, not getattr(self.settings, 'show_col_size', True))
            self.queue.setColumnHidden(4, not getattr(self.settings, 'show_col_estimate', True))
        except Exception:
            pass

    # ---------- 统一弹窗 ----------
    def _show_info(self, text: str, title: str = "提示") -> None:
        try:
            m = QMessageBox(self)
            m.setIcon(QMessageBox.Information)
            m.setWindowTitle(title)
            m.setText(text)
            m.setMinimumWidth(420)
            m.setStandardButtons(QMessageBox.Ok)
            okb = m.button(QMessageBox.Ok)
            if okb:
                okb.setMinimumWidth(96)
            m.exec()
        except Exception:
            QMessageBox.information(self, title, text)

    def _show_warning(self, text: str, title: str = "提示") -> None:
        try:
            m = QMessageBox(self)
            m.setIcon(QMessageBox.Warning)
            m.setWindowTitle(title)
            m.setText(text)
            m.setMinimumWidth(420)
            m.setStandardButtons(QMessageBox.Ok)
            okb = m.button(QMessageBox.Ok)
            if okb:
                okb.setMinimumWidth(96)
            m.exec()
        except Exception:
            QMessageBox.warning(self, title, text)

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
            self._show_info(f"已将输出目录应用到{changed}个未完成任务","输出目录")

    def _add_files(self) -> None:
        start_dir = self._ensure_valid_input_dir()
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择HEIC文件", start_dir, "HEIC 文件 (*.heic *.heif);;所有文件 (*.*)")
        self._append_jobs(files)
        # 记录最近输入目录
        if files:
            base = os.path.dirname(files[0])
            if os.path.isdir(base):
                self.settings.last_input_dir = base
                AppSettings.save(self.settings)

    def _add_dir(self) -> None:
        start_dir = self._ensure_valid_input_dir()
        d = QFileDialog.getExistingDirectory(self, "选择文件夹", start_dir)
        if not d:
            return
        # 记录最近输入目录
        if os.path.isdir(d):
            self.settings.last_input_dir = d
            AppSettings.save(self.settings)
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
            # 新增：按当前检查器设置初始化新任务的导出格式与关键参数
            fmt = self.ins_format.currentText().lower()
            item.export_format = fmt
            if fmt in ("jpg", "jpeg"):
                item.quality = self.jpeg_quality.value()
                item.jpeg_progressive = self._adv_jpeg_progressive
                item.jpeg_optimize = self._adv_jpeg_optimize
            elif fmt == "png":
                item.png_compress_level = self.png_level.value()
                item.png_optimize = self._adv_png_optimize
            else:
                item.quality = self.other_quality.value()
                if fmt == 'webp':
                    item.webp_lossless = self._adv_webp_lossless
                    item.webp_method = self._adv_webp_method
                elif fmt in ('tif','tiff'):
                    item.tiff_compression = self._adv_tiff_compression
            # 尺寸与比例
            wv, hv = self.ins_width.value(), self.ins_height.value()
            item.req_size = (wv, hv)
            item.keep_aspect = bool(self.btn_lock.isChecked())
            self.jobs.append(item)
            row = self._create_row(item, len(self.jobs)-1)
            self.queue.addTopLevelItem(row)
            added += 1
        if added > 0:
            self._update_empty_placeholder()
        if added == 0:
            self._show_info("未添加任何HEIC文件")
        self._update_total_progress()

    def _create_row(self, job: JobItem, index: int) -> QTreeWidgetItem:
        it = QTreeWidgetItem(["", os.path.basename(job.src_path), job.size_text(), self._human_bytes(job.src_bytes), self._estimate_output_text(job), job.status_text(), "0%", ""]) 
        it.setData(0, Qt.UserRole, index)
        it.setTextAlignment(6, Qt.AlignHCenter | Qt.AlignVCenter)
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
            # 异步读取尺寸（轻量元数据），回到UI线程更新
            sz = get_image_size(src)
            if sz is not None:
                job.orig_size = sz
                try:
                    self.bus.job_update.emit(idx, job)
                except Exception:
                    pass
        self._thumb_pool.submit(_load_and_emit)
        return it

    # ---------- 右侧检查器 ----------
    def _build_inspector(self) -> QWidget:
        w = QWidget(); w.setObjectName('rightPanel')
        lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(16)
        # 限位：防止右栏被压缩到按钮与文本不可读
        w.setMinimumWidth(480)

        # 导出设置卡片
        export_card, export_form = self._make_card('导出设置', link_text='更多设置', link_cb=self._open_format_settings_dialog)
        self.ins_format = QComboBox()
        for fmt in ExportFormat.list_display():
            self.ins_format.addItem(fmt)
        export_form.addRow('格式', self.ins_format)

        self.ins_param_stack = QStackedWidget(); self.ins_param_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # JPEG
        page_jpeg = QWidget(); pjlay = QFormLayout(page_jpeg)
        self.jpeg_quality = QSlider(Qt.Horizontal); self.jpeg_quality.setRange(1,95); self.jpeg_quality.setValue(90)
        self.jpeg_quality_lbl = QLabel('90')
        self.jpeg_quality.valueChanged.connect(lambda v: self.jpeg_quality_lbl.setText(str(v)))
        row_jq = QWidget(); rjql = QHBoxLayout(row_jq); rjql.setContentsMargins(0,0,0,0)
        rjql.addWidget(self.jpeg_quality, 1); rjql.addWidget(self.jpeg_quality_lbl)
        pjlay.addRow('质量', row_jq)
        # PNG
        page_png = QWidget(); pplay = QFormLayout(page_png)
        self.png_level = QSlider(Qt.Horizontal); self.png_level.setRange(0,9); self.png_level.setValue(6)
        self.png_level_lbl = QLabel('6')
        self.png_level.valueChanged.connect(lambda v: self.png_level_lbl.setText(str(v)))
        row_pl = QWidget(); rpll = QHBoxLayout(row_pl); rpll.setContentsMargins(0,0,0,0)
        rpll.addWidget(self.png_level, 1); rpll.addWidget(self.png_level_lbl)
        pplay.addRow('压缩等级', row_pl)
        # TIFF
        page_tiff = QWidget(); ptlay = QFormLayout(page_tiff)
        self.tiff_comp = QComboBox(); self.tiff_comp.addItems(['tiff_deflate','tiff_lzw','tiff_adobe_deflate'])
        ptlay.addRow('压缩方式', self.tiff_comp)
        # 其他（WEBP等）
        page_other = QWidget(); polay = QFormLayout(page_other)
        self.other_quality = QSlider(Qt.Horizontal); self.other_quality.setRange(1,100); self.other_quality.setValue(90)
        self.other_quality_lbl = QLabel('90')
        self.other_quality.valueChanged.connect(lambda v: self.other_quality_lbl.setText(str(v)))
        row_oq = QWidget(); roql = QHBoxLayout(row_oq); roql.setContentsMargins(0,0,0,0)
        roql.addWidget(self.other_quality, 1); roql.addWidget(self.other_quality_lbl)
        polay.addRow('质量', row_oq)
        self.ins_param_stack.addWidget(page_jpeg)
        self.ins_param_stack.addWidget(page_png)
        self.ins_param_stack.addWidget(page_tiff)
        self.ins_param_stack.addWidget(page_other)
        h = max(page_jpeg.sizeHint().height(), page_png.sizeHint().height(), page_tiff.sizeHint().height(), page_other.sizeHint().height())
        self.ins_param_stack.setFixedHeight(h)
        self._param_title = QLabel('参数')
        export_form.addRow(self._param_title, self.ins_param_stack)

        # 尺寸卡片
        size_card, size_form = self._make_card('尺寸')
        # 提示语（相对像素）
        self._hint_rel = QLabel('提示：按钮为相对像素调整')
        self._hint_rel.setStyleSheet('color:#9CA3AF;')
        size_form.addRow('', self._hint_rel)
        self.ins_width = QSpinBox(); self.ins_width.setMaximum(20000); self.ins_width.setMinimum(0); self.ins_width.setSpecialValueText('留空＝保持原尺寸'); self.ins_width.setSuffix(' px'); self.ins_width.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.ins_height = QSpinBox(); self.ins_height.setMaximum(20000); self.ins_height.setMinimum(0); self.ins_height.setSpecialValueText('留空＝保持原尺寸'); self.ins_height.setSuffix(' px'); self.ins_height.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self._keep_aspect = True
        self.btn_lock = QToolButton(); self.btn_lock.setCheckable(True); self.btn_lock.setChecked(True); self.btn_lock.setText('🔒')
        self._height_step_buttons: list[QToolButton] = []
        def _on_lock_toggled(b: bool):
            self._keep_aspect = bool(b)
            self.btn_lock.setText('🔒' if b else '🔓')
            # 锁定时禁用“高”输入与其步进按钮
            self.ins_height.setEnabled(not b)
            for bt in self._height_step_buttons:
                bt.setEnabled(not b)
        self.btn_lock.toggled.connect(_on_lock_toggled)
        # 使用网格布局：锁在左侧垂直占两行；宽在上，高在下
        grid = QGridLayout(); grid.setContentsMargins(0,0,0,0); grid.setHorizontalSpacing(8); grid.setVerticalSpacing(8)
        grid.addWidget(self.btn_lock, 0, 0, 2, 1, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        # 宽行
        grid.addWidget(QLabel('宽'), 0, 1)
        grid.addWidget(self.ins_width, 0, 2)
        # 宽步进按钮
        col = 3
        for t, dv in (("-10", -10), ("-1", -1), ("+1", 1), ("+10", 10)):
            b = QToolButton(); b.setObjectName('stepBtn'); b.setText(t); b.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            b.clicked.connect(lambda _, d=dv, sp=self.ins_width: sp.setValue(max(sp.minimum(), min(sp.maximum(), sp.value()+d))))
            grid.addWidget(b, 0, col)
            col += 1
        # 高行
        grid.addWidget(QLabel('高'), 1, 1)
        grid.addWidget(self.ins_height, 1, 2)
        col = 3
        for t, dv in (("-10", -10), ("-1", -1), ("+1", 1), ("+10", 10)):
            b = QToolButton(); b.setObjectName('stepBtn'); b.setText(t); b.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            b.clicked.connect(lambda _, d=dv, sp=self.ins_height: sp.setValue(max(sp.minimum(), min(sp.maximum(), sp.value()+d))))
            grid.addWidget(b, 1, col)
            self._height_step_buttons.append(b)
            col += 1
        row_wh = QWidget(); row_wh.setLayout(grid)
        size_form.addRow('', row_wh)
        # 删除“最长边”设置，保持界面简洁

        # 输出命名卡片
        name_card, name_form = self._make_card('输出命名')
        self.ins_template = QLineEdit('{name}_{index}')
        self.ins_token = QComboBox(); self.ins_token.addItems(['{name}','{index}','{date}','{datetime}','{width}','{height}','{w}','{h}','{fmt}','{q}'])
        btn_insert = QPushButton('插入Token'); btn_insert.clicked.connect(lambda: self.ins_template.insert(self.ins_token.currentText()))
        rowt = QWidget(); rt = QHBoxLayout(rowt); rt.setContentsMargins(0,0,0,0); rt.setSpacing(8)
        rt.addWidget(self.ins_template, 1)
        rt.addWidget(btn_insert)
        rt.addWidget(self.ins_token)
        self.ins_preview = QLabel('(未选择项目)'); self.ins_preview.setStyleSheet('color:#6B7280;')
        # 复制按钮
        btn_copy = QToolButton(); btn_copy.setText('复制'); btn_copy.setObjectName('stepBtn')
        def _copy_preview():
            from PySide6.QtWidgets import QApplication as QApp
            QApp.clipboard().setText(self.ins_preview.text())
        btn_copy.clicked.connect(_copy_preview)
        name_form.addRow('模板', rowt)
        prev_row = QWidget(); prl = QHBoxLayout(prev_row); prl.setContentsMargins(0,0,0,0); prl.setSpacing(8)
        prl.addWidget(self.ins_preview, 1)
        prl.addWidget(btn_copy)
        name_form.addRow('预览', prev_row)

        # 并发与应用卡片
        misc_card, misc_form = self._make_card('并发与应用')
        from os import cpu_count
        self._auto_threads = max(1, min(8, (cpu_count() or 4)))
        self.rb_auto = QRadioButton(f"Auto（当前={self._auto_threads} 线程）")
        self.rb_manual = QRadioButton("手动")
        self.rb_auto.setChecked(True)
        self.ins_threads = QSpinBox(); self.ins_threads.setRange(1, 64); self.ins_threads.setValue(self.settings.default_threads); self.ins_threads.setEnabled(False); self.ins_threads.setButtonSymbols(QAbstractSpinBox.NoButtons)
        # 简洁的 - / + 步进
        self.btn_thr_minus = QToolButton(); self.btn_thr_minus.setObjectName('stepBtn'); self.btn_thr_minus.setText('-'); self.btn_thr_minus.setEnabled(False)
        self.btn_thr_plus = QToolButton(); self.btn_thr_plus.setObjectName('stepBtn'); self.btn_thr_plus.setText('+'); self.btn_thr_plus.setEnabled(False)
        self.btn_thr_minus.clicked.connect(lambda: self.ins_threads.setValue(max(self.ins_threads.minimum(), self.ins_threads.value()-1)))
        self.btn_thr_plus.clicked.connect(lambda: self.ins_threads.setValue(min(self.ins_threads.maximum(), self.ins_threads.value()+1)))
        # 行排布
        thr_row = QWidget(); trl = QHBoxLayout(thr_row); trl.setContentsMargins(0,0,0,0); trl.setSpacing(8)
        trl.addWidget(self.rb_auto)
        trl.addWidget(self.rb_manual)
        trl.addWidget(self.btn_thr_minus)
        trl.addWidget(self.ins_threads)
        trl.addWidget(self.btn_thr_plus)
        trl.addStretch(1)
        misc_form.addRow('并发', thr_row)
        self.rb_auto.toggled.connect(lambda _: self._update_thread_controls())
        self.rb_manual.toggled.connect(lambda _: self._update_thread_controls())
        btn_apply_sel = QPushButton('应用到选中'); btn_apply_sel.clicked.connect(self._apply_to_selected)
        btn_reset = QPushButton('恢复默认'); btn_reset.clicked.connect(self._action_reset_defaults)
        misc_form.addRow('', btn_apply_sel)
        misc_form.addRow('', btn_reset)

        lay.addWidget(export_card)
        lay.addWidget(size_card)
        lay.addWidget(name_card)
        lay.addWidget(misc_card)
        lay.addStretch(1)
        self._load_settings_into_inspector()
        self.ins_format.currentTextChanged.connect(self._on_format_changed)
        self._on_format_changed(self.ins_format.currentText())
        # 预览实时更新
        try:
            self.ins_template.textChanged.connect(lambda _: self._refresh_inspector_preview())
            self.jpeg_quality.valueChanged.connect(lambda _: self._refresh_inspector_preview())
            self.png_level.valueChanged.connect(lambda _: self._refresh_inspector_preview())
            self.other_quality.valueChanged.connect(lambda _: self._refresh_inspector_preview())
            self.ins_width.valueChanged.connect(lambda _: self._refresh_inspector_preview())
            self.ins_height.valueChanged.connect(lambda _: self._refresh_inspector_preview())
            # 估算实时更新（轻量，基于文件大小与格式参数）
            self.ins_format.currentTextChanged.connect(lambda _: self._refresh_estimates_throttled())
            self.jpeg_quality.valueChanged.connect(lambda _: self._refresh_estimates_throttled())
            self.png_level.valueChanged.connect(lambda _: self._refresh_estimates_throttled())
            self.other_quality.valueChanged.connect(lambda _: self._refresh_estimates_throttled())
        except Exception:
            pass
        self._update_thread_controls()
        return w

    def _load_settings_into_inspector(self) -> None:
        # 将当前AppSettings装载进检查器
        self.ins_format.setCurrentText(self.settings.default_format)
        # 三页的默认值
        self.jpeg_quality.setValue(min(95, max(1, self.settings.default_quality)))
        self.png_level.setValue(max(0, min(9, getattr(self.settings, 'default_png_compress_level', 6))))
        self.other_quality.setValue(min(100, max(1, self.settings.default_quality)))
        # TIFF 默认压缩
        try:
            idx = ['tiff_deflate','tiff_lzw','tiff_adobe_deflate'].index(getattr(self.settings, 'default_tiff_compression', 'tiff_deflate'))
        except ValueError:
            idx = 0
        self.tiff_comp.setCurrentIndex(idx)
        self.ins_width.setValue(self.settings.default_size[0])
        self.ins_height.setValue(self.settings.default_size[1])
        if hasattr(self, 'btn_lock'):
            self.btn_lock.setChecked(self.settings.default_keep_aspect)
            # 触发一次以同步禁用状态
            try:
                self.btn_lock.toggled.emit(self.btn_lock.isChecked())
            except Exception:
                pass
        self.ins_threads.setValue(self.settings.default_threads)
        self.ins_template.setText(self.settings.default_template)

    def _apply_inspector_to_defaults(self) -> None:
        # 将检查器值保存为默认设置
        self.settings.default_format = self.ins_format.currentText()
        # 当前格式对应的默认值写回
        fmt = self.ins_format.currentText().lower()
        if fmt in ("jpg", "jpeg"):
            self.settings.default_quality = self.jpeg_quality.value()
        elif fmt == "png":
            self.settings.default_png_compress_level = self.png_level.value()
        elif fmt in ("tif","tiff"):
            self.settings.default_tiff_compression = self.tiff_comp.currentText()
        else:
            self.settings.default_quality = self.other_quality.value()
        self.settings.default_dpi = (self._adv_dpi_x, self._adv_dpi_y)
        self.settings.default_size = (self.ins_width.value(), self.ins_height.value())
        self.settings.default_keep_aspect = bool(getattr(self, 'btn_lock', None) and self.btn_lock.isChecked())
        self.settings.default_threads = self.ins_threads.value()
        self.settings.default_template = self.ins_template.text()
        AppSettings.save(self.settings)

    def _load_selected_to_inspector(self) -> None:
        # 读取选中项，展示命名预览
        self._refresh_inspector_preview()

    def _human_bytes(self, n: int) -> str:
        """将字节数格式化为可读字符串。"""
        try:
            n = int(n)
        except Exception:
            return "-"
        units = ['B','KB','MB','GB','TB']
        x = float(n)
        for u in units:
            if x < 1024 or u == units[-1]:
                return f"{x:.1f}{u}" if u != 'B' else f"{int(x)}B"
            x /= 1024.0

    def _estimate_output_text(self, job: JobItem) -> str:
        """基于源文件大小与当前导出设置的粗略估算，不解码图片，避免卡顿。"""
        if not getattr(job, 'src_bytes', 0):
            return "-"
        fmt = (job.export_format or '').lower()
        size = job.src_bytes
        ratio = 1.0
        try:
            if fmt in ('jpg','jpeg'):
                q = max(1, min(100, job.quality))
                ratio = 0.6 + 1.2*(q/100.0)  # 0.6 .. 1.8
            elif fmt == 'png':
                lvl = getattr(job, 'png_compress_level', 6)
                ratio = 1.6 - 0.1*max(0, min(9, int(lvl)))  # ~1.6 .. 0.7
            elif fmt == 'webp':
                q = max(1, min(100, job.quality))
                ratio = 0.5 + 1.0*(q/100.0)  # 0.5 .. 1.5
            elif fmt in ('tif','tiff'):
                c = (job.tiff_compression or 'tiff_deflate')
                ratio = 1.4 if c != 'tiff_lzw' else 1.3
            est = int(size * ratio)
            return self._human_bytes(est)
        except Exception:
            return "-"

    def _refresh_estimates(self) -> None:
        # 若设置中关闭预估显示，则不计算
        if not getattr(self.settings, 'show_col_estimate', True):
            return
        # 当前检查器设置作为覆盖（仅对待处理项生效）
        fmt = (self.ins_format.currentText() or '').lower() if hasattr(self, 'ins_format') else ''
        # 质量/等级
        jpeg_q = getattr(self, 'jpeg_quality', None).value() if hasattr(self, 'jpeg_quality') else None
        png_lvl = getattr(self, 'png_level', None).value() if hasattr(self, 'png_level') else None
        other_q = getattr(self, 'other_quality', None).value() if hasattr(self, 'other_quality') else None
        for i, job in enumerate(self.jobs):
            try:
                it = self.queue.topLevelItem(i)
                if not it:
                    continue
                # 构造一个轻量覆盖副本，仅覆盖导出参数，不修改原job，避免提前写入
                class OV: pass
                o = job
                if job.status in (JobStatus.WAITING, JobStatus.PAUSED) and fmt:
                    ov = OV()
                    ov.src_bytes = job.src_bytes
                    ov.tiff_compression = getattr(job, 'tiff_compression', 'tiff_deflate')
                    if fmt in ('jpg','jpeg'):
                        ov.export_format = fmt
                        ov.quality = int(jpeg_q or job.quality)
                    elif fmt == 'png':
                        ov.export_format = fmt
                        ov.png_compress_level = int(png_lvl if png_lvl is not None else getattr(job, 'png_compress_level', 6))
                        ov.quality = getattr(job, 'quality', 90)
                    elif fmt == 'webp':
                        ov.export_format = fmt
                        ov.quality = int(other_q or job.quality)
                    elif fmt in ('tif','tiff'):
                        ov.export_format = fmt
                        ov.quality = int(other_q or job.quality)
                    o = ov
                it.setText(4, self._estimate_output_text(o))
            except Exception:
                pass

    def _refresh_estimates_throttled(self) -> None:
        # 简单节流，避免频繁刷新引起卡顿
        try:
            from PySide6.QtCore import QTimer
            if getattr(self, '_est_timer', None) is None:
                self._est_timer = QTimer(self)
                self._est_timer.setSingleShot(True)
                self._est_timer.timeout.connect(self._refresh_estimates)
            self._est_timer.start(120)
        except Exception:
            self._refresh_estimates()
    def _refresh_inspector_preview(self) -> None:
        if not self._selected_indices:
            self.ins_preview.setText("(未选择项目)")
            return
        first = self.jobs[self._selected_indices[0]]
        name = render_output_name(self.ins_template.text(), first, index=1)
        self.ins_preview.setText(name)

    def _apply_to_selected(self) -> None:
        if not self._selected_indices:
            self._show_info("请先选中文件")
            return
        for idx in self._selected_indices:
            job = self.jobs[idx]
            fmt = self.ins_format.currentText().lower()
            job.export_format = fmt
            if fmt in ("jpg", "jpeg"):
                job.quality = self.jpeg_quality.value()
                job.jpeg_progressive = self._adv_jpeg_progressive
                job.jpeg_optimize = self._adv_jpeg_optimize
            elif fmt == "png":
                job.png_compress_level = self.png_level.value()
                # 保留质量用于其他用途，但不影响PNG保存
                job.quality = self.other_quality.value()
                job.png_optimize = self._adv_png_optimize
            else:
                job.quality = self.other_quality.value()
                if fmt == 'webp':
                    job.webp_lossless = self._adv_webp_lossless
                    job.webp_method = self._adv_webp_method
                elif fmt in ('tif','tiff'):
                    job.tiff_compression = self._adv_tiff_compression
            job.dpi = (self._adv_dpi_x, self._adv_dpi_y)
            wv, hv = self.ins_width.value(), self.ins_height.value()
            job.req_size = (wv, hv)
            job.keep_aspect = bool(self.btn_lock.isChecked())
            job.template = self.ins_template.text()
        self._show_info("已应用到选中项")
        self._refresh_estimates_throttled()

    def _on_format_changed(self, fmt: str) -> None:
        f = (fmt or "").lower()
        # 切换堆叠页
        if f in ("jpg", "jpeg"):
            self.ins_param_stack.setCurrentIndex(0)
        elif f == "png":
            self.ins_param_stack.setCurrentIndex(1)
        elif f in ("tif","tiff"):
            self.ins_param_stack.setCurrentIndex(2)
        else:
            self.ins_param_stack.setCurrentIndex(3)
        if hasattr(self, '_param_title'):
            self._param_title.setText('参数')

    # ---------- 任务回调、状态更新 ----------
    def _on_job_update(self, job_index: int, job: JobItem) -> None:
        # 保证UI线程安全：Qt回调已在UI线程执行
        it = self.queue.topLevelItem(job_index)
        if not it:
            return
        it.setText(2, job.size_text())
        # 大小与预估更新
        try:
            it.setText(3, self._human_bytes(job.src_bytes))
            it.setText(4, self._estimate_output_text(job))
        except Exception:
            pass
        # 状态着色徽标化
        txt = job.status_text()
        it.setText(5, txt)
        from PySide6.QtGui import QBrush, QColor
        color_map = {
            JobStatus.WAITING: QColor('#6B7280'),
            JobStatus.RUNNING: QColor('#2563EB'),
            JobStatus.PAUSED: QColor('#F59E0B'),
            JobStatus.COMPLETED: QColor('#16A34A'),
            JobStatus.FAILED: QColor('#DC2626'),
            JobStatus.CANCELLED: QColor('#9CA3AF'),
        }
        it.setForeground(5, QBrush(color_map.get(job.status, QColor('#374151'))))
        it.setText(6, f"{job.progress}%")
        it.setText(7, job.error or "")
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
            if hasattr(self, '_label_done'):
                self._label_done.setText("已完成 0/0")
            # 空列表时显示提示
            self._update_empty_placeholder()
            return
        done = sum(1 for j in self.jobs if j.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED))
        self.total_progress.setValue(int(100 * done / total))
        self._label_remaining.setText(f"剩余：{total - done}")
        if hasattr(self, '_label_done'):
            self._label_done.setText(f"已完成 {done}/{total}")
        # 全部完成时弹出通知（只弹一次）
        if done == total and total > 0 and not self._notified_all_done:
            succ = sum(1 for j in self.jobs if j.status == JobStatus.COMPLETED)
            fail = sum(1 for j in self.jobs if j.status == JobStatus.FAILED)
            canc = sum(1 for j in self.jobs if j.status == JobStatus.CANCELLED)
            self._show_notification("处理完成", f"共{total}项：成功{succ}，失败{fail}，取消{canc}")
            self._notified_all_done = True
            # 重置开始按钮并释放执行器，允许重新开始
            try:
                self.task_manager.stop()
            except Exception:
                pass
            self._start_button_state = "start"
            self._refresh_topbar_states()

    # ---------- 重名预检 ----------
    def _preflight_conflicts(self) -> bool:
        """启动前检查输出目录同名文件，并按设置处理。

        返回：是否继续开始任务。
        """
        # 启动前先校验输出目录是否存在
        if not os.path.isdir(self.output_dir):
            self._show_warning("当前输出目录不存在，请选择新的输出目录。","输出目录")
            newd = QFileDialog.getExistingDirectory(self, "选择输出目录", os.getcwd())
            if not newd:
                return False
            self.output_dir = newd
            self.settings.default_output_dir = newd
            AppSettings.save(self.settings)
            self._apply_output_dir_to_jobs()
        # 收集冲突列表（仅检测磁盘已存在的文件）
        conflicts: list[tuple[int, str]] = []  # (job_index, out_path)
        for idx, job in enumerate(self.jobs):
            if job.status in (JobStatus.COMPLETED, JobStatus.RUNNING, JobStatus.CANCELLED):
                continue
            out_path = build_output_path(job, idx + 1)
            try:
                if os.path.exists(out_path):
                    conflicts.append((idx, out_path))
            except Exception:
                pass

        if not conflicts:
            return True

        policy = getattr(self.settings, 'collision_policy', 'ask')
        if policy == 'replace':
            return True
        if policy == 'skip':
            self._apply_skip_for_conflicts(conflicts, reason="同名文件已存在，按设置跳过")
            return True

        # 询问用户如何处理：替换/跳过/逐个决定
        msg = QMessageBox(self)
        msg.setWindowTitle("重名文件处理")
        msg.setText(f"检测到{len(conflicts)}个输出文件已存在，选择处理方式：")
        btn_replace = msg.addButton("替换全部", QMessageBox.AcceptRole)
        btn_skip = msg.addButton("跳过全部", QMessageBox.ActionRole)
        btn_each = msg.addButton("逐个决定", QMessageBox.ActionRole)
        btn_cancel = msg.addButton("取消开始", QMessageBox.RejectRole)
        msg.setIcon(QMessageBox.Warning)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked == btn_cancel:
            return False
        elif clicked == btn_replace:
            return True
        elif clicked == btn_skip:
            self._apply_skip_for_conflicts(conflicts, reason="同名文件已存在，已跳过")
            return True
        else:
            # 逐个确认
            for idx, path in conflicts:
                base = os.path.basename(path)
                q = QMessageBox(self)
                q.setWindowTitle("重名文件")
                q.setText(f"输出文件已存在：\n{base}\n是否替换？")
                b1 = q.addButton("替换", QMessageBox.AcceptRole)
                b2 = q.addButton("跳过", QMessageBox.DestructiveRole)
                b3 = q.addButton("停止开始", QMessageBox.RejectRole)
                q.setIcon(QMessageBox.Question)
                q.exec()
                c = q.clickedButton()
                if c == b3:
                    return False
                elif c == b2:
                    self._apply_skip_for_conflicts([(idx, path)], reason="同名文件已存在，已跳过")
            return True

    def _apply_skip_for_conflicts(self, conflicts: list[tuple[int, str]], reason: str) -> None:
        """将冲突条目标记为取消并更新队列显示。"""
        for idx, _ in conflicts:
            if 0 <= idx < len(self.jobs):
                job = self.jobs[idx]
                job.status = JobStatus.CANCELLED
                job.progress = 100
                job.error = reason
                # 更新UI行
                self._on_job_update(idx, job)

    def _apply_current_settings_to_pending_jobs(self) -> None:
        """将当前检查器设置应用到所有未完成任务，避免用户未点击“应用到选中”。"""
        fmt = self.ins_format.currentText().lower()
        for job in self.jobs:
            if job.status not in (JobStatus.WAITING, JobStatus.PAUSED):
                continue
            job.export_format = fmt
            if fmt in ("jpg", "jpeg"):
                job.quality = self.jpeg_quality.value()
                job.jpeg_progressive = self._adv_jpeg_progressive
                job.jpeg_optimize = self._adv_jpeg_optimize
            elif fmt == "png":
                job.png_compress_level = self.png_level.value()
                job.png_optimize = self._adv_png_optimize
                # 质量保留为其他用途
                job.quality = self.other_quality.value()
            else:
                job.quality = self.other_quality.value()
                if fmt == 'webp':
                    job.webp_lossless = self._adv_webp_lossless
                    job.webp_method = self._adv_webp_method
                elif fmt in ('tif','tiff'):
                    job.tiff_compression = self._adv_tiff_compression
            # 尺寸与比例
            wv, hv = self.ins_width.value(), self.ins_height.value()
            job.req_size = (wv, hv)
            job.keep_aspect = bool(self.btn_lock.isChecked())
        self._refresh_estimates_throttled()

    # ---------- 托盘与后台 ----------
    def _init_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(self)
        # 托盘图标后备：若应用未设置窗口图标，则使用系统标准图标，避免托盘看不见
        icon = self.windowIcon()
        if icon.isNull():
            from PySide6.QtWidgets import QStyle
            icon = self.style().standardIcon(QStyle.SP_ComputerIcon)
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
            # 未启用通知则直接返回
            if not getattr(self.settings, 'enable_notifications', True):
                return
            if hasattr(self, 'tray') and self.tray and self.tray.isVisible():
                icon = QSystemTrayIcon.MessageIcon.Critical if error else QSystemTrayIcon.MessageIcon.Information
                # Windows气泡通知自动消失
                self.tray.showMessage(title, message, icon, 4000)
        except Exception:
            pass

    # ---------- 关闭处理 ----------
    def closeEvent(self, event):  # type: ignore
        # 首次关闭时询问关闭行为
        action = getattr(self.settings, 'on_close_action', 'ask')
        if action == 'ask':
            # 弹窗让用户选择后记录
            msg = QMessageBox(self)
            msg.setWindowTitle("关闭行为")
            msg.setText("选择关闭程序时的行为：")
            btn_min = msg.addButton("最小化后台运行", QMessageBox.AcceptRole)
            btn_exit = msg.addButton("直接退出", QMessageBox.DestructiveRole)
            msg.setIcon(QMessageBox.Question)
            msg.exec()
            clicked = msg.clickedButton()
            action = 'minimize' if clicked == btn_min else 'exit'
            self.settings.on_close_action = action
            AppSettings.save(self.settings)

        # 如果托盘可用且设置为最小化，则隐藏到托盘
        if not self._really_quit and action == 'minimize' and hasattr(self, 'tray') and self.tray.isVisible():
            event.ignore()
            self.hide()
            self._show_notification("后台运行", "程序已最小化到托盘，继续在后台处理。")
            return

        # 否则直接退出
        try:
            self.task_manager.stop()
        except Exception:
            pass
        try:
            self._thumb_pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        super().closeEvent(event)

    # ---------- 应用设置与目录校验 ----------
    def _open_settings(self) -> None:
        """打开应用设置对话框。"""
        dlg = AppSettingsDialog(self.settings, self)
        if dlg.exec() == QDialog.Accepted:
            enable, action, dup, cols = dlg.values()
            self.settings.enable_notifications = enable
            self.settings.on_close_action = action
            self.settings.collision_policy = dup
            # 列显示设置
            self.settings.show_col_dims = bool(cols.get('show_col_dims', True))
            self.settings.show_col_size = bool(cols.get('show_col_size', True))
            self.settings.show_col_estimate = bool(cols.get('show_col_estimate', True))
            AppSettings.save(self.settings)
            self._apply_column_visibility()
            self._refresh_estimates_throttled()

    def _open_format_settings_dialog(self) -> None:
        """打开‘更多设置’对话框，依当前格式显示高级参数。"""
        fmt = self.ins_format.currentText().lower()
        dlg = FormatSettingsDialog(fmt, self, self)
        if dlg.exec() == QDialog.Accepted:
            dlg.apply_to_main()

    def _update_thread_controls(self) -> None:
        """根据Auto/手动选择启用/禁用线程数控件。"""
        auto = hasattr(self, 'rb_auto') and self.rb_auto.isChecked()
        en = not auto
        self.ins_threads.setEnabled(en)
        if hasattr(self, 'btn_thr_minus'):
            self.btn_thr_minus.setEnabled(en)
        if hasattr(self, 'btn_thr_plus'):
            self.btn_thr_plus.setEnabled(en)
        if hasattr(self, 'rb_auto'):
            self.rb_auto.setText(f"Auto（当前={self._auto_threads} 线程）")

    def _ensure_valid_output_dir(self) -> None:
        """保留占位以兼容旧调用（已不在启动时强制创建）。"""
        return

    def _ensure_valid_input_dir(self) -> str:
        """返回用于文件/文件夹选择对话框的起始目录，若上次目录不存在则提示并让用户选择。"""
        d = self.settings.last_input_dir or os.getcwd()
        if not os.path.isdir(d):
            self._show_info("之前的输入目录不存在，请选择新的输入目录。","输入目录")
            nd = QFileDialog.getExistingDirectory(self, "选择输入目录", os.getcwd())
            if nd:
                self.settings.last_input_dir = nd
                AppSettings.save(self.settings)
                d = nd
            else:
                d = os.getcwd()
        return d
