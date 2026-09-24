"""Batch execution queue and worker management."""

from concurrent.futures import ThreadPoolExecutor
import logging
import os
from pathlib import Path
import threading
import time
from typing import Callable, Dict, List, Optional
from videoremix.core.executor import ExecutionCancelledError, FFmpegExecutor
from videoremix.core.filtergraph import FilterGraphBuilder
from videoremix.core.hardware import HardwareDetector
from videoremix.core.presets import PresetMode, apply_preset
from videoremix.core.probe import probe_media
from videoremix.queue.task import RemediationTask, TaskStatus

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".flv", ".avi", ".webm", ".ts"}

TaskUpdateCallback = Callable[[RemediationTask], None]
QueueFinishedCallback = Callable[[], None]


class BatchQueueManager:
    """Coordinates concurrent video remediation tasks with live status updates."""

    def __init__(self, max_workers: int = 2):
        self.max_workers = max_workers
        self.tasks: List[RemediationTask] = []
        self._task_map: Dict[str, RemediationTask] = {}
        self._executor_pool: Optional[ThreadPoolExecutor] = None
        self._is_running = False
        self._lock = threading.Lock()
        self.on_task_update: Optional[TaskUpdateCallback] = None
        self.on_queue_finished: Optional[QueueFinishedCallback] = None

    def add_task(
        self,
        input_path: str,
        output_path: Optional[str] = None,
        preset: PresetMode = PresetMode.BALANCED_REMIX,
        **custom_opts,
    ) -> RemediationTask:
        """Add a single file task to the queue."""
        if not output_path:
            p = Path(input_path)
            output_path = str(p.parent / f"{p.stem}_remix{p.suffix}")
        else:
            p_in = Path(input_path)
            p_out = Path(output_path)
            try:
                is_same = p_in.resolve() == p_out.resolve()
            except Exception:
                is_same = os.path.abspath(str(p_in)) == os.path.abspath(str(p_out))
            if is_same:
                output_path = str(p_out.parent / f"{p_in.stem}_remix{p_in.suffix}")

        task = RemediationTask(
            input_path=os.path.abspath(input_path),
            output_path=os.path.abspath(output_path),
            preset=preset,
            custom_opts=custom_opts,
        )
        with self._lock:
            self.tasks.append(task)
            self._task_map[task.task_id] = task

        self._notify_update(task)
        return task

    def add_directory(
        self,
        input_dir: str,
        output_dir: Optional[str] = None,
        preset: PresetMode = PresetMode.BALANCED_REMIX,
        recursive: bool = False,
        **custom_opts,
    ) -> List[RemediationTask]:
        """Scan a directory and enqueue all supported media files."""
        input_path = Path(input_dir)
        if not input_path.is_dir():
            raise NotADirectoryError(f"Directory not found: {input_dir}")

        out_base = Path(output_dir) if output_dir else input_path / "remixed"
        pattern = "**/*" if recursive else "*"
        added: List[RemediationTask] = []

        for p in input_path.glob(pattern):
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS:
                if out_base.resolve() in p.resolve().parents:
                    continue  # Skip files in the output directory
                rel = p.relative_to(input_path)
                target = out_base / rel
                task = self.add_task(str(p), str(target), preset=preset, **custom_opts)
                added.append(task)

        return added

    def start(self):
        """Start background queue processing."""
        with self._lock:
            if self._is_running:
                return
            self._is_running = True
            self._executor_pool = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="VideoRemixWorker")

        threading.Thread(target=self._worker_loop, daemon=True).start()

    def stop_all(self):
        """Cancel all pending and running tasks."""
        with self._lock:
            self._is_running = False
            for task in self.tasks:
                if task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                    task.status = TaskStatus.CANCELLED
                    if task.executor:
                        task.executor.cancel()
                    self._notify_update(task)

            if self._executor_pool:
                self._executor_pool.shutdown(wait=False)

    def cancel_task(self, task_id: str):
        """Cancel an individual task."""
        with self._lock:
            task = self._task_map.get(task_id)
            if task and task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                task.status = TaskStatus.CANCELLED
                if task.executor:
                    task.executor.cancel()
                self._notify_update(task)

    def clear_completed(self):
        """Remove finished or cancelled tasks from queue."""
        with self._lock:
            self.tasks = [t for t in self.tasks if t.status in (TaskStatus.PENDING, TaskStatus.RUNNING)]
            self._task_map = {t.task_id: t for t in self.tasks}

    def _worker_loop(self):
        """Main dispatcher loop."""
        futures = []
        best_encoder = HardwareDetector.detect_best_encoder()

        pending_tasks = [t for t in self.tasks if t.status == TaskStatus.PENDING]
        for task in pending_tasks:
            if not self._is_running:
                break
            fut = self._executor_pool.submit(self._execute_single_task, task, best_encoder)
            futures.append(fut)

        # Wait for all submitted futures
        for fut in futures:
            try:
                fut.result()
            except Exception:
                pass

        with self._lock:
            self._is_running = False
            if self._executor_pool:
                self._executor_pool.shutdown(wait=False)

        if self.on_queue_finished:
            self.on_queue_finished()

    def _execute_single_task(self, task: RemediationTask, encoder):
        if task.status == TaskStatus.CANCELLED or not self._is_running:
            return

        task.status = TaskStatus.RUNNING
        self._notify_update(task)

        try:
            info = probe_media(task.input_path)
            builder = FilterGraphBuilder(info)
            apply_preset(builder, task.preset, **task.custom_opts)

            def on_progress(percent: float, speed: str, eta: float):
                task.progress = percent
                task.speed = speed
                task.eta = eta
                self._notify_update(task)

            executor = FFmpegExecutor()
            task.executor = executor

            current_encoder = encoder
            try:
                executor.run_remediation(
                    media_info=info,
                    builder=builder,
                    output_path=task.output_path,
                    encoder_config=current_encoder,
                    on_progress=on_progress,
                )
            except ExecutionCancelledError:
                raise
            except Exception as hw_exc:
                if (
                    getattr(current_encoder, "is_hardware", False)
                    and task.status != TaskStatus.CANCELLED
                    and self._is_running
                ):
                    logger.warning(
                        f"Task {task.task_id} hardware encoder ({getattr(current_encoder, 'name', 'GPU')}) failed: {hw_exc}. "
                        "Retrying with CPU encoding fallback..."
                    )
                    cpu_encoder = HardwareDetector.detect_best_encoder(force_cpu=True)
                    task.progress = 0.0
                    task.speed = "0.0x"
                    task.eta = 0.0
                    self._notify_update(task)

                    executor = FFmpegExecutor()
                    task.executor = executor
                    executor.run_remediation(
                        media_info=info,
                        builder=builder,
                        output_path=task.output_path,
                        encoder_config=cpu_encoder,
                        on_progress=on_progress,
                    )
                else:
                    raise

            task.status = TaskStatus.SUCCESS
            task.progress = 100.0
            task.completed_at = time.time()
            logger.info(f"Task {task.task_id} completed successfully.")

        except ExecutionCancelledError:
            task.status = TaskStatus.CANCELLED
            task.completed_at = time.time()
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error_message = str(e)
            task.completed_at = time.time()
            logger.error(f"Task {task.task_id} failed: {e}", exc_info=True)
        finally:
            self._notify_update(task)

    def _notify_update(self, task: RemediationTask):
        if self.on_task_update:
            try:
                self.on_task_update(task)
            except Exception:
                pass
