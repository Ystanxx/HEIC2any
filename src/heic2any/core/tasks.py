# -*- coding: utf-8 -*-
"""
任务管理：多线程并发、暂停/恢复/停止、状态回调。
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Callable, Dict, List, Optional, Tuple
import queue

from heic2any.core.state import JobItem, JobStatus
from heic2any.core import converter
from heic2any.utils.naming import build_output_path
from heic2any.core.event_bus import EventBus, EventType


OnJobUpdate = Callable[[int, JobItem], None]
OnOverallUpdate = Callable[[int, int], None]


class TaskManager:
    """基于线程池 + 有界队列的任务管理器。

    特性：
    - 明确状态：Queued/Running/Paused/Completed/Failed/Canceled（内部对应 JobStatus）
    - 事件发布：支持 EventBus（可选）
    - 暂停：将队列中未开始的任务切为 Paused 并移出队列，释放线程；恢复时回填到队列
    - 背压：使用 queue.Queue(maxsize) 限制待处理任务数
    """

    def __init__(self, threads: int, on_job_update: OnJobUpdate, on_overall_update: OnOverallUpdate, *, event_bus: Optional[EventBus] = None, queue_capacity: Optional[int] = None) -> None:
        self._lock = threading.Lock()
        self._threads = max(1, threads)
        self._executor: Optional[ThreadPoolExecutor] = None
        self._futures: List[Future] = []
        self._paused = threading.Event()  # set 表示暂停
        self._stop = threading.Event()
        self._on_job_update = on_job_update
        self._on_overall_update = on_overall_update
        self._bus = event_bus
        self._queue_capacity = max(1, int(queue_capacity or (self._threads * 2)))
        self._queue: Optional[queue.Queue[int]] = None
        self._paused_buffer: List[int] = []  # 暂停时暂存的队列元素
        self._jobs_ref: Optional[List[JobItem]] = None

    def set_threads(self, n: int) -> None:
        with self._lock:
            self._threads = max(1, n)
            # 下次 start 时生效（避免运行时强制重建池带来的抖动）

    def start(self, jobs: List[JobItem]) -> None:
        """开始或继续处理队列。"""
        with self._lock:
            self._jobs_ref = jobs
            if self._executor is None:
                self._paused.clear(); self._stop.clear()
                self._executor = ThreadPoolExecutor(max_workers=self._threads, thread_name_prefix="heic2any")
                self._queue = queue.Queue(maxsize=self._queue_capacity)
                self._futures = [self._executor.submit(self._worker_loop, i) for i in range(self._threads)]
            else:
                # 已存在则视为继续
                self._paused.clear()

        # 首次/继续：将可运行任务填充到有界队列（阻塞式put确保背压）
        assert self._queue is not None
        for idx, job in enumerate(jobs):
            if self._stop.is_set():
                break
            if job.status in (JobStatus.COMPLETED, JobStatus.RUNNING, JobStatus.CANCELLED):
                continue
            # 标记为排队
            if job.status != JobStatus.PAUSED:
                job.status = JobStatus.WAITING
                self._emit_job(idx, job)
            try:
                self._queue.put(idx, timeout=0.1)
            except Exception:
                # 若被停止/暂停则退出投放循环
                if self._stop.is_set() or self._paused.is_set():
                    break

    def pause(self) -> None:
        """暂停：将队列中未开始的任务转为PAUSED并暂存，释放线程。"""
        self._paused.set()
        # 将队列中剩余索引转存到缓冲并标记为PAUSED
        q = self._queue
        jobs = self._jobs_ref
        if q is None or jobs is None:
            return
        drained: List[int] = []
        while True:
            try:
                idx = q.get_nowait()
                drained.append(idx)
            except queue.Empty:
                break
        with self._lock:
            self._paused_buffer.extend(drained)
        for idx in drained:
            if 0 <= idx < len(jobs):
                jb = jobs[idx]
                jb.status = JobStatus.PAUSED
                self._emit_job(idx, jb)

    def resume(self) -> None:
        self._paused.clear()
        # 回填缓冲中的任务到队列
        q = self._queue
        if q is None:
            return
        while True:
            idx = None
            with self._lock:
                if self._paused_buffer:
                    idx = self._paused_buffer.pop(0)
            if idx is None:
                break
            try:
                q.put(idx, timeout=0.1)
            except Exception:
                break

    def stop(self) -> None:
        self._stop.set(); self._paused.clear()
        # 取消未开始任务
        jobs = self._jobs_ref or []
        for i, j in enumerate(jobs):
            try:
                j.token.cancel()
            except Exception:
                pass
        # 清空队列
        q = self._queue
        if q is not None:
            while True:
                try:
                    q.get_nowait()
                except Exception:
                    break
        with self._lock:
            if self._executor is not None:
                try:
                    self._executor.shutdown(wait=False, cancel_futures=True)
                except Exception:
                    pass
                self._executor = None
            self._futures = []
            self._queue = None
            self._paused_buffer.clear()

    # ---------- 内部执行 ----------
    def _worker_loop(self, worker_id: int) -> None:
        """工作线程循环：从有界队列取任务并执行。"""
        while not self._stop.is_set():
            # 暂停：不取新任务，阻塞在空队列即可
            try:
                q = self._queue
                jobs = self._jobs_ref
                if q is None or jobs is None:
                    return
                idx = q.get(timeout=0.2)
            except queue.Empty:
                # 可能是暂停或暂时无任务
                continue

            if self._stop.is_set():
                return

            # 取得任务对象
            jobs = self._jobs_ref or []
            if idx < 0 or idx >= len(jobs):
                continue
            job = jobs[idx]

            # 被取消则快速跳过
            if getattr(job, 'token', None) and job.token.cancelled:
                job.status = JobStatus.CANCELLED
                job.progress = 100
                self._emit_job(idx, job)
                self._emit_overall()
                continue

            # 设置运行态
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
                    jpeg_progressive=job.jpeg_progressive if job.export_format.lower() in ('jpg','jpeg') else None,
                    jpeg_optimize=job.jpeg_optimize if job.export_format.lower() in ('jpg','jpeg') else None,
                    png_optimize=job.png_optimize if job.export_format.lower() == 'png' else None,
                    webp_lossless=job.webp_lossless if job.export_format.lower() == 'webp' else None,
                    webp_method=job.webp_method if job.export_format.lower() == 'webp' else None,
                    tiff_compression=job.tiff_compression if job.export_format.lower() in ('tif','tiff') else None,
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
        # 回调
        try:
            if self._on_job_update:
                self._on_job_update(idx, job)
        except Exception:
            pass
        # 事件总线（可选）
        try:
            if self._bus:
                self._bus.publish(EventType.JOB_UPDATED, {"index": idx, "job": job})
        except Exception:
            pass

    def _emit_overall(self) -> None:
        # 这里只能估算：交由UI端统计
        try:
            if self._on_overall_update:
                self._on_overall_update(0, 0)
        except Exception:
            pass
        try:
            if self._bus:
                self._bus.publish(EventType.OVERALL_UPDATED, {})
        except Exception:
            pass
