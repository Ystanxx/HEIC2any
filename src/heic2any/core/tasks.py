# -*- coding: utf-8 -*-
"""
任务管理：多线程并发、暂停/恢复/停止、状态回调。
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Callable, Dict, List, Optional, Tuple

from heic2any.core.state import JobItem, JobStatus
from heic2any.core import converter
from heic2any.utils.naming import build_output_path


OnJobUpdate = Callable[[int, JobItem], None]
OnOverallUpdate = Callable[[int, int], None]


class TaskManager:
    """基于线程池的任务管理器。"""

    def __init__(self, threads: int, on_job_update: OnJobUpdate, on_overall_update: OnOverallUpdate) -> None:
        self._lock = threading.Lock()
        self._threads = max(1, threads)
        self._executor: Optional[ThreadPoolExecutor] = None
        self._futures: Dict[int, Future] = {}
        self._paused = threading.Event()
        self._stop = threading.Event()
        self._on_job_update = on_job_update
        self._on_overall_update = on_overall_update

    def set_threads(self, n: int) -> None:
        with self._lock:
            self._threads = max(1, n)

    def start(self, jobs: List[JobItem]) -> None:
        with self._lock:
            if self._executor is not None:
                # 若已有执行器，则视为继续
                self.resume()
                return
            self._paused.clear()
            self._stop.clear()
            self._executor = ThreadPoolExecutor(max_workers=self._threads, thread_name_prefix="heic2any")
            self._futures.clear()

        # 提交任务
        for idx, job in enumerate(jobs):
            if self._stop.is_set():
                break
            if job.status in (JobStatus.COMPLETED, JobStatus.RUNNING, JobStatus.CANCELLED):
                continue
            f = self._executor.submit(self._run_one, idx, job)
            with self._lock:
                self._futures[idx] = f

    def pause(self) -> None:
        # 通过事件阻塞后续任务进入执行关键段
        self._paused.set()
        # 标记任务状态为PAUSED（运行中的任务进入下一步前会感知到）

    def resume(self) -> None:
        self._paused.clear()

    def stop(self) -> None:
        self._stop.set()
        self._paused.clear()
        with self._lock:
            for idx, fut in list(self._futures.items()):
                # 尝试取消未运行任务
                fut.cancel()
            self._futures.clear()
            if self._executor is not None:
                self._executor.shutdown(wait=False, cancel_futures=True)
                self._executor = None

    # ---------- 内部执行 ----------
    def _run_one(self, idx: int, job: JobItem) -> None:
        # 等待继续
        if self._paused.is_set():
            # 更新状态以便UI显示（轻量处理）
            job.status = JobStatus.PAUSED
            self._emit_job(idx, job)
        while self._paused.is_set() and not self._stop.is_set():
            threading.Event().wait(0.1)
        if self._stop.is_set():
            job.status = JobStatus.CANCELLED
            job.progress = 0
            self._emit_job(idx, job)
            self._emit_overall()
            return

        # 真正执行
        job.status = JobStatus.RUNNING
        job.progress = 1
        job.error = None
        self._emit_job(idx, job)
        try:
            out_path = build_output_path(job, idx + 1)
            w, h = converter.convert_one(
                src_path=job.src_path,
                dst_path=out_path,
                fmt=job.export_format,
                quality=job.quality,
                dpi=job.dpi,
                req_size=job.req_size,
                keep_aspect=job.keep_aspect,
                png_compress_level=job.png_compress_level if job.export_format.lower() == 'png' else None,
            )
            job.orig_size = (w, h)
            job.progress = 100
            job.status = JobStatus.COMPLETED
            self._emit_job(idx, job)
        except Exception as e:
            job.status = JobStatus.FAILED
            job.error = str(e)
            job.progress = 100
            self._emit_job(idx, job)
        finally:
            self._emit_overall()

    def _emit_job(self, idx: int, job: JobItem) -> None:
        try:
            self._on_job_update(idx, job)
        except Exception:
            pass

    def _emit_overall(self) -> None:
        # 这里只能估算：交给UI端统计或通过回调收集
        try:
            # 交由调用方传入完整jobs列表管理进度，这里仅回调总进度需上层维护
            # 为了简化，这里只传占位（0,0），上层会重新统计
            self._on_overall_update(0, 0)
        except Exception:
            pass
