#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
主入口：main_heic2any
说明：
- 启动 Qt 应用，装载主窗口
- 保持模块化，便于维护与扩展
"""

import os
import sys

# 将 src 目录加入搜索路径，保证包导入清晰
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(BASE_DIR, 'src')
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from heic2any.app import run_app  # noqa: E402


def main() -> int:
    """程序主入口。"""
    # 在Windows高DPI环境下确保界面清晰
    return run_app()


if __name__ == '__main__':
    sys.exit(main())

