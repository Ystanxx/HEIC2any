# -*- coding: utf-8 -*-
"""
CancellationToken：每个任务持有的取消令牌。

用于在任务提交到队列后，在真正开始前快速取消；
已进入执行中的任务不强制打断，完成当前图片后即可感知停止。
"""

from __future__ import annotations

import threading


class CancellationToken:
    """简单取消令牌。"""

    def __init__(self) -> None:
        self._evt = threading.Event()

    def cancel(self) -> None:
        self._evt.set()

    @property
    def cancelled(self) -> bool:
        return self._evt.is_set()

