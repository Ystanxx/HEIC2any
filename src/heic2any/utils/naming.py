# -*- coding: utf-8 -*-
"""
输出命名工具：支持Token模板渲染与路径生成。
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Tuple

from heic2any.core.state import JobItem


def render_output_name(template: str, job: JobItem, index: int) -> str:
    """根据模板渲染输出文件名（不含扩展名）。

    支持Token：{name}（原文件名不含扩展）；{index}；{date}；{datetime}；{width}；{height}
    """
    stem = os.path.splitext(os.path.basename(job.src_path))[0]
    now = datetime.now()
    w, h = job.req_size if any(job.req_size) else job.orig_size
    w = w or 0
    h = h or 0
    name = template
    name = name.replace("{name}", stem)
    name = name.replace("{index}", str(index))
    name = name.replace("{date}", now.strftime("%Y%m%d"))
    name = name.replace("{datetime}", now.strftime("%Y%m%d_%H%M%S"))
    name = name.replace("{width}", str(w))
    name = name.replace("{height}", str(h))
    return name


def build_output_path(job: JobItem, index: int) -> str:
    """构建完整输出路径（含扩展名）。"""
    fname = render_output_name(job.template, job, index)
    ext = job.export_format.lower().replace('jpeg', 'jpg')
    return os.path.join(job.export_dir, f"{fname}.{ext}")

