# -*- coding: utf-8 -*-
"""
状态与数据结构定义。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Tuple


class JobStatus(Enum):
    """任务状态。"""
    WAITING = auto()
    RUNNING = auto()
    PAUSED = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


class ExportFormat:
    """导出格式的展示与取值映射。"""
    VALUES = ["jpg", "jpeg", "png", "tif"]

    @classmethod
    def list_display(cls):
        return cls.VALUES


@dataclass
class JobItem:
    """任务条目数据结构。"""
    src_path: str
    export_dir: str
    export_format: str = "jpg"
    quality: int = 90
    dpi: Tuple[int, int] = (300, 300)
    req_size: Tuple[int, int] = (0, 0)  # 0 表示不指定
    keep_aspect: bool = True
    template: str = "{name}_{index}"

    # 运行时信息
    status: JobStatus = JobStatus.WAITING
    progress: int = 0
    error: Optional[str] = None

    # 元数据（尺寸）
    orig_size: Tuple[int, int] = (0, 0)

    @staticmethod
    def from_source(path: str) -> "JobItem":
        # 初始导出目录设为当前工作目录下的 output
        out = os.path.join(os.getcwd(), 'output')
        os.makedirs(out, exist_ok=True)
        return JobItem(src_path=path, export_dir=out)

    def size_text(self) -> str:
        w, h = self.orig_size
        if w and h:
            return f"{w}×{h}"
        return "-"

    def status_text(self) -> str:
        m = {
            JobStatus.WAITING: "等待",
            JobStatus.RUNNING: "进行中",
            JobStatus.PAUSED: "已暂停",
            JobStatus.COMPLETED: "已完成",
            JobStatus.FAILED: "失败",
            JobStatus.CANCELLED: "已取消",
        }
        return m.get(self.status, "-")


@dataclass
class AppSettings:
    """应用全局设置（可持久化）。"""
    default_format: str = "jpg"
    default_quality: int = 90
    default_dpi: Tuple[int, int] = (300, 300)
    default_size: Tuple[int, int] = (0, 0)
    default_keep_aspect: bool = True
    default_threads: int = 4
    default_template: str = "{name}_{index}"
    default_output_dir: str = field(default_factory=lambda: os.path.join(os.getcwd(), 'output'))

    @staticmethod
    def load() -> "AppSettings":
        # 简化：当前版本用默认，后续可接入 QSettings
        os.makedirs(os.path.join(os.getcwd(), 'output'), exist_ok=True)
        return AppSettings()

    @staticmethod
    def save(s: "AppSettings") -> None:
        # 简化：当前版本不落盘，后续可接入 QSettings
        pass

