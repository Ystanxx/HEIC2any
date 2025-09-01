# -*- coding: utf-8 -*-
"""
缩略图工具：尽量加载真实缩略图，若依赖缺失则生成占位图。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtGui import QPixmap, QImage, QPainter, QColor


def make_placeholder_thumbnail() -> QPixmap:
    """生成占位缩略图。"""
    pix = QPixmap(48, 48)
    pix.fill(QColor(240, 240, 240))
    p = QPainter(pix)
    p.setPen(QColor(160, 160, 160))
    p.drawRect(0, 0, 47, 47)
    p.drawText(pix.rect(), 0x84, "HEIC")  # 居中
    p.end()
    return pix


def load_thumbnail(path: str) -> Optional[QPixmap]:
    """尝试加载真实缩略图；失败则返回None。"""
    try:
        from PIL import Image  # type: ignore
        try:
            import pillow_heif  # type: ignore
            pillow_heif.register_heif_opener()
        except Exception:
            return None
        with Image.open(path) as im:
            im.thumbnail((48, 48))
            img = im.convert('RGB')
            data = img.tobytes('raw', 'RGB')
            qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGB888)
            return QPixmap.fromImage(qimg)
    except Exception:
        return None

