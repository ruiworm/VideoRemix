"""Task definition and state management."""

from dataclasses import dataclass, field
from enum import Enum
import os
import time
from typing import Any, Dict, Optional
import uuid
from videoremix.core.executor import FFmpegExecutor
from videoremix.core.presets import PresetMode


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class RemediationTask:
    input_path: str
    output_path: str
    preset: PresetMode = PresetMode.BALANCED_REMIX
    custom_opts: Dict[str, Any] = field(default_factory=dict)
    task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    status: TaskStatus = TaskStatus.PENDING
    progress: float = 0.0
    speed: str = "0.0x"
    eta: float = 0.0
    error_message: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    executor: Optional[FFmpegExecutor] = None

    @property
    def filename(self) -> str:
        base = os.path.basename(self.input_path)
        if self.custom_opts and self.custom_opts.get("variant_index"):
            return f"{base} [v{self.custom_opts['variant_index']}]"
        return base

    @property
    def output_filename(self) -> str:
        return os.path.basename(self.output_path)

    @property
    def duration_elapsed(self) -> float:
        end = self.completed_at or time.time()
        return round(end - self.created_at, 1)
