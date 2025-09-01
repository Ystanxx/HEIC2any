# -*- coding: utf-8 -*-
"""
应用启动模块：创建 QApplication，装载主窗口与样式。
"""

from __future__ import annotations

import os
import sys
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPalette, QColor
from PySide6.QtWidgets import QApplication

from heic2any.ui.main_window import MainWindow


def _load_qss(app: QApplication) -> None:
    """加载应用QSS样式。若样式文件不存在则跳过。

    参数:
        app: QApplication实例
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    qss_path = os.path.join(base_dir, 'heic2any', 'resources', 'qss', 'app.qss')
    if os.path.exists(qss_path):
        try:
            with open(qss_path, 'r', encoding='utf-8') as f:
                app.setStyleSheet(f.read())
        except Exception:
            # 样式加载失败不影响主流程
            pass


def _tune_palette(app: QApplication) -> None:
    """微调调色板，保证浅色主题下的可读性。"""
    pal: QPalette = app.palette()
    pal.setColor(QPalette.Window, QColor(250, 250, 250))
    pal.setColor(QPalette.AlternateBase, QColor(245, 245, 245))
    pal.setColor(QPalette.Base, QColor(255, 255, 255))
    app.setPalette(pal)


def run_app() -> int:
    """启动Qt应用，返回进程退出码。"""
    # 高DPI渲染设置
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("HEIC2any")
    app.setOrganizationName("HEIC2any")
    app.setOrganizationDomain("local")

    _tune_palette(app)
    _load_qss(app)

    win = MainWindow()
    # 尝试设置图标，若无则忽略
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        icon_path = os.path.join(base_dir, 'heic2any', 'resources', 'app.png')
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))
    except Exception:
        pass

    win.show()
    return app.exec()

