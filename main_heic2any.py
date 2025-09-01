#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
兼容入口：main_HEIC2any
说明：部分环境或脚本可能调用该文件名，此处仅转发到实际入口。
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(BASE_DIR, 'src')
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from heic2any.app import run_app  # noqa: E402


if __name__ == '__main__':
    sys.exit(run_app())

