# -*- coding: utf-8 -*-
"""
缩略图工具：尽量加载真实缩略图，若依赖缺失则生成占位图。
"""

from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtGui import QPixmap, QImage, QColor


def make_placeholder_thumbnail() -> QPixmap:
    """生成占位缩略图（无QPainter，避免绘制警告）。"""
    pix = QPixmap(48, 48)
    pix.fill(QColor(230, 230, 230))
    return pix


def load_thumbnail(path: str, max_side: int = 256) -> Optional[QImage]:
    """尝试加载真实缩略图为QImage；失败则返回None。

    参数:
        max_side: 最大边尺寸，默认256。会使用高质量下采样（LANCZOS）。

    说明：QImage可安全跨线程传递，QPixmap需在GUI线程创建。
    """
    try:
        from PIL import Image  # type: ignore
        try:
            import pillow_heif  # type: ignore
            pillow_heif.register_heif_opener()
        except Exception:
            return None
        with Image.open(path) as im:
            # 限制到 max_side，并使用高质量采样
            max_side = max(64, min(1024, int(max_side)))
            im.thumbnail((max_side, max_side), Image.LANCZOS)
            img = im.convert('RGB')
            # 注意：QImage使用外部缓冲区时需拷贝，避免悬空指针
            data = img.tobytes('raw', 'RGB')
            w, h = img.width, img.height
            bytes_per_line = w * 3
            qimg = QImage(data, w, h, bytes_per_line, QImage.Format.Format_RGB888).copy()
            return qimg
    except Exception:
        return None


def get_image_size(path: str) -> Optional[Tuple[int, int]]:
    """快速读取图片像素尺寸，失败返回None。

    使用Pillow打开文件仅读取元数据，避免完整解码，性能友好。
    需要 pillow-heif 支持 HEIC/HEIF；缺失时返回None。
    """
    try:
        from PIL import Image  # type: ignore
        try:
            import pillow_heif  # type: ignore
            pillow_heif.register_heif_opener()
        except Exception:
            return None
        with Image.open(path) as im:
            return tuple(im.size)  # (w, h)
    except Exception:
        return None
