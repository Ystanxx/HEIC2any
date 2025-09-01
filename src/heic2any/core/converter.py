# -*- coding: utf-8 -*-
"""
图片转换核心：基于 Pillow + pillow-heif 读取 HEIC，转换为目标格式。

注意：
- 若缺少 pillow-heif，将抛出异常提示用户安装依赖。
- 支持质量(质量对JPG/JPEG生效；PNG映射到压缩级别)、DPI、尺寸调整。
"""

from __future__ import annotations

import os
from typing import Tuple


def _import_image_libs():
    """导入图像库，缺少依赖时报错。"""
    try:
        from PIL import Image  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("未安装 Pillow，请先安装: pip install Pillow") from e
    # HEIC 支持
    try:
        import pillow_heif  # type: ignore
        pillow_heif.register_heif_opener()
    except Exception as e:
        # 允许用户之后再安装；此时HEIC无法打开
        raise RuntimeError("未安装 pillow-heif，请先安装: pip install pillow-heif") from e
    return Image


def _ensure_output_dir(path: str) -> None:
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)


def _map_png_quality_to_compress_level(q: int) -> int:
    """将0-100质量映射到PNG压缩级别(0-9，数值越大压缩越高速度越慢)。"""
    q = max(1, min(100, q))
    # 粗略映射：100 -> 1, 1 -> 9
    level = int(round(9 - (q / 100.0) * 8))
    return max(0, min(9, level))


def convert_one(
    src_path: str,
    dst_path: str,
    fmt: str,
    quality: int,
    dpi: Tuple[int, int],
    req_size: Tuple[int, int],
    keep_aspect: bool,
) -> Tuple[int, int]:
    """执行单张图片转换。

    返回：输出尺寸(width, height)
    抛出：RuntimeError（依赖缺失或读取失败）
    """
    Image = _import_image_libs()
    with Image.open(src_path) as im:
        # 原始尺寸
        ow, oh = im.size
        tw, th = req_size
        # 处理目标尺寸
        if tw > 0 or th > 0:
            if keep_aspect:
                # 仅指定一个边时等比缩放
                if tw > 0 and th == 0:
                    scale = tw / float(ow)
                    th = int(round(oh * scale))
                elif th > 0 and tw == 0:
                    scale = th / float(oh)
                    tw = int(round(ow * scale))
                else:
                    # 同时指定，仍强制等比，以宽度优先
                    scale = tw / float(ow)
                    th = int(round(oh * scale))
            else:
                # 任意拉伸
                if tw == 0:
                    tw = ow
                if th == 0:
                    th = oh
            if (tw, th) != im.size:
                im = im.resize((tw, th))
        else:
            tw, th = ow, oh

        # RGB 确保
        if im.mode in ("RGBA", "LA"):
            background = Image.new("RGB", im.size, (255, 255, 255))
            background.paste(im, mask=im.split()[3])
            im = background
        elif im.mode != "RGB":
            im = im.convert("RGB")

        # 输出
        _ensure_output_dir(dst_path)
        save_kwargs = {"dpi": dpi}
        f = fmt.lower()
        if f in ("jpg", "jpeg"):
            save_kwargs.update({"quality": max(1, min(100, quality)), "optimize": True})
        elif f == "png":
            save_kwargs.update({"compress_level": _map_png_quality_to_compress_level(quality)})
        elif f in ("tif", "tiff"):
            save_kwargs.update({"compression": "tiff_deflate"})

        # 让Pillow按扩展名自动识别格式，可避免'JPG'等大小写映射问题
        im.save(dst_path, **save_kwargs)
        return (tw, th)
