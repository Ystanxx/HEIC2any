# -*- coding: utf-8 -*-
"""
状态与数据结构定义。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from typing import Optional, Tuple

from heic2any.core.cancellation import CancellationToken


class JobStatus(Enum):
    """任务状态。"""
    WAITING = auto()
    RUNNING = auto()
    PAUSED = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


class JobState(Enum):
    """更清晰的外部状态命名（别名）。

    说明：保持向后兼容，内部仍使用 JobStatus；如需对外表达，可转换：
    QUEUED <-> WAITING；CANCELED <-> CANCELLED
    """
    QUEUED = JobStatus.WAITING.value
    RUNNING = JobStatus.RUNNING.value
    PAUSED = JobStatus.PAUSED.value
    COMPLETED = JobStatus.COMPLETED.value
    FAILED = JobStatus.FAILED.value
    CANCELED = JobStatus.CANCELLED.value


class ExportFormat:
    """导出格式的展示与取值映射。"""
    # 增加主流格式：webp、tiff（保留tif以兼容）
    VALUES = ["jpg", "jpeg", "png", "tif", "tiff", "webp"]

    @classmethod
    def list_display(cls):
        return cls.VALUES


@dataclass
class JobItem:
    """任务条目数据结构。"""
    src_path: str
    export_dir: str
    export_format: str = "jpg"
    quality: int = 90  # 通用质量（JPG/WEBP等）
    png_compress_level: int = 6  # PNG压缩级别 0-9（9最小体积最慢）
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
    src_bytes: int = 0

    # 高级参数（按格式生效）
    # JPEG
    jpeg_progressive: bool = False
    jpeg_optimize: bool = True
    # PNG
    png_optimize: bool = False
    # WEBP
    webp_lossless: bool = False
    webp_method: int = 4  # 0-6
    # TIFF
    tiff_compression: str = "tiff_deflate"  # tiff_deflate/tiff_lzw/tiff_adobe_deflate

    # 取消令牌（每个任务持有）
    token: CancellationToken = field(default_factory=CancellationToken)

    @staticmethod
    def from_source(path: str) -> "JobItem":
        # 初始导出目录设为当前工作目录下的 output
        out = os.path.join(os.getcwd(), 'output')
        try:
            size_b = os.path.getsize(path)
        except Exception:
            size_b = 0
        return JobItem(src_path=path, export_dir=out, src_bytes=size_b)

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
    default_png_compress_level: int = 6
    # 高级默认参数
    default_jpeg_progressive: bool = False
    default_jpeg_optimize: bool = True
    default_png_optimize: bool = False
    default_webp_lossless: bool = False
    default_webp_method: int = 4
    default_tiff_compression: str = "tiff_deflate"
    default_dpi: Tuple[int, int] = (300, 300)
    default_size: Tuple[int, int] = (0, 0)
    default_keep_aspect: bool = True
    default_threads: int = 4
    default_template: str = "{name}_{index}"
    default_output_dir: str = field(default_factory=lambda: os.path.join(os.getcwd(), 'output'))
    selected_env_prefix: str = ""
    selected_python_path: str = ""
    export_convert_log: bool = False
    # 新增：应用设置（通知与关闭行为）
    enable_notifications: bool = True  # 是否启用托盘通知
    on_close_action: str = "ask"       # 关闭行为："ask"/"exit"/"minimize"
    # 新增：记住上次输入目录
    last_input_dir: str = ""
    # 新增：重名文件处理策略："ask"/"replace"/"skip"
    collision_policy: str = "ask"
    # 列显示/计算开关（输入文件信息）
    show_col_dims: bool = True
    show_col_size: bool = True
    show_col_estimate: bool = True

    @staticmethod
    def load() -> "AppSettings":
        """从用户目录读取设置；不存在则使用默认。"""
        try:
            cfg = _settings_path()
            if os.path.isfile(cfg):
                import json
                with open(cfg, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                s = AppSettings()
                for k, v in data.items():
                    if hasattr(s, k):
                        setattr(s, k, v)
                return s
        except Exception:
            pass
        return AppSettings()

    @staticmethod
    def save(s: "AppSettings") -> None:
        """保存到用户目录JSON。"""
        try:
            import json
            cfg = _settings_path()
            os.makedirs(os.path.dirname(cfg), exist_ok=True)
            data = asdict(s)
            with open(cfg, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


def _settings_path() -> str:
    """设置文件路径：~/.heic2any/settings.json"""
    home = os.path.expanduser('~')
    return os.path.join(home, '.heic2any', 'settings.json')
