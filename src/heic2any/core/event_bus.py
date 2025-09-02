# -*- coding: utf-8 -*-
"""
线程安全的轻量事件总线。

用于在核心任务控制层与UI层之间解耦：控制层仅发布事件，
UI 层订阅后在自己的线程/信号中转更新界面。
"""

from __future__ import annotations

import threading
from enum import Enum, auto
from typing import Callable, Dict, List, Any


class EventType(Enum):
    """事件类型枚举。"""
    JOB_UPDATED = auto()
    OVERALL_UPDATED = auto()
    ALL_DONE = auto()


Handler = Callable[[Dict[str, Any]], None]


class EventBus:
    """简单的发布-订阅事件总线（线程安全）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: Dict[EventType, List[Handler]] = {}

    def subscribe(self, etype: EventType, handler: Handler) -> None:
        """订阅指定事件类型。"""
        with self._lock:
            self._subs.setdefault(etype, []).append(handler)

    def publish(self, etype: EventType, payload: Dict[str, Any]) -> None:
        """发布事件，逐个调用已订阅的处理器。"""
        handlers: List[Handler]
        with self._lock:
            handlers = list(self._subs.get(etype, []))
        for h in handlers:
            try:
                h(payload)
            except Exception:
                # 事件处理失败不影响主流程
                pass

