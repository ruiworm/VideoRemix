"""Modern, responsive desktop GUI for VideoRemix."""

import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional

# Ensure package path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from videoremix import __version__
from videoremix.core.hardware import HardwareDetector
from videoremix.core.presets import PRESET_DESCRIPTIONS, PresetMode
from videoremix.queue.manager import BatchQueueManager
from videoremix.queue.task import RemediationTask, TaskStatus


class VideoRemixApp:
    """Modern, adaptive desktop application for batch video deduplication."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"VideoRemix Pro v{__version__} - 智能多模态音视频去重系统")

        # Responsive default size (comfortable on 768p, 1080p, and 4K displays)
        self.root.geometry("1020x720")
        self.root.minsize(860, 580)
        self.root.configure(bg="#1e1e2e")

        self.queue_manager = BatchQueueManager(max_workers=2)
        self.queue_manager.on_task_update = self._on_task_updated
        self.queue_manager.on_queue_finished = self._on_queue_finished

        self.encoder_config = HardwareDetector.detect_best_encoder()

        # UI state variables
        self.preset_var = tk.StringVar(value=PresetMode.BALANCED_REMIX.value)
        self.output_dir_var = tk.StringVar(value="")
        self.workers_var = tk.IntVar(value=2)
        self.global_status_var = tk.StringVar(value="就绪：请添加视频文件或目录")
        self.global_progress_var = tk.DoubleVar(value=0.0)

        # Custom options
        self.custom_zoom_var = tk.DoubleVar(value=1.02)
        self.custom_speed_var = tk.DoubleVar(value=1.018)
        self.custom_grain_var = tk.IntVar(value=3)
        self.custom_pitch_var = tk.DoubleVar(value=0.25)
        self.custom_hflip_var = tk.BooleanVar(value=False)
        self.custom_pip_var = tk.BooleanVar(value=False)

        self._task_tree_items: Dict[str, str] = {}  # task_id -> treeview iid

        self._setup_styles()
        self._build_layout()

    def _setup_styles(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")

        # Base Treeview styling
        style.configure(
            "Treeview",
            background="#252538",
            foreground="#cdd6f4",
            fieldbackground="#252538",
            rowheight=28,
            font=("Segoe UI", 9),
        )
        style.configure(
            "Treeview.Heading",
            background="#313244",
            foreground="#cdd6f4",
            relief="flat",
            font=("Segoe UI", 9, "bold"),
        )
        style.map("Treeview", background=[("selected", "#45475a")])

        # Modern Progressbar
        style.configure("Horizontal.TProgressbar", troughcolor="#313244", background="#89b4fa", thickness=10)

    def _build_layout(self):
        # 1. Top Header Bar
        header = tk.Frame(self.root, bg="#181825", height=65)
        header.pack(fill=tk.X, side=tk.TOP)

        title_lbl = tk.Label(
            header,
            text="VideoRemix Engine",
            font=("Segoe UI", 16, "bold"),
            fg="#cdd6f4",
            bg="#181825",
        )
        title_lbl.pack(side=tk.LEFT, padx=20, pady=12)

        codec_badge = tk.Label(
            header,
            text=f"加速引擎: {self.encoder_config.name}",
            font=("Segoe UI", 9, "bold"),
            fg="#a6e3a1" if self.encoder_config.is_hardware else "#f9e2af",
            bg="#313244",
            padx=10,
            pady=4,
        )
        codec_badge.pack(side=tk.RIGHT, padx=20, pady=16)

        # 2. Main Content Split View
        content = tk.Frame(self.root, bg="#1e1e2e")
        content.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)

        # Left Column: Presets & Controls (Width 320)
        left_panel = tk.Frame(content, bg="#252538", width=320, padx=14, pady=14)
        left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 12))
        left_panel.pack_propagate(False)

        # Right Column: Task Queue Table & Log Output
        right_panel = tk.Frame(content, bg="#1e1e2e")
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self._build_left_controls(left_panel)
        self._build_right_queue(right_panel)

        # 3. Bottom Status Bar
        statusbar = tk.Frame(self.root, bg="#181825", height=32, padx=15)
        statusbar.pack(fill=tk.X, side=tk.BOTTOM)

        tk.Label(
            statusbar,
            textvariable=self.global_status_var,
            font=("Segoe UI", 9),
            fg="#a6adc8",
            bg="#181825",
        ).pack(side=tk.LEFT, pady=6)

    def _build_left_controls(self, parent: tk.Frame):
        # Section: Preset Selection
        tk.Label(
            parent,
            text="去重模式预设",
            font=("Segoe UI", 11, "bold"),
            fg="#cdd6f4",
            bg="#252538",
        ).pack(anchor=tk.W, pady=(0, 8))

        presets = [
            (PresetMode.BALANCED_REMIX.value, "推荐: 强效去重 (自媒体矩阵)"),
            (PresetMode.QUALITY_FIRST.value, "保真: 画质优先 (高保真原创)"),
            (PresetMode.SMART_PIP.value, "变体: 智能画中画 (模糊背景)"),
            (PresetMode.CUSTOM.value, "自定义: 详细参数调节"),
        ]

        for val, text in presets:
            rb = tk.Radiobutton(
                parent,
                text=text,
                value=val,
                variable=self.preset_var,
                command=self._on_preset_changed,
                font=("Segoe UI", 9),
                fg="#cdd6f4",
                bg="#252538",
                selectcolor="#313244",
                activebackground="#252538",
                activeforeground="#89b4fa",
            )
            rb.pack(anchor=tk.W, pady=3)

        # Preset Description Box
        self.desc_lbl = tk.Label(
            parent,
            text=PRESET_DESCRIPTIONS[PresetMode.BALANCED_REMIX],
            font=("Segoe UI", 8),
            fg="#a6adc8",
            bg="#1e1e2e",
            wraplength=280,
            justify=tk.LEFT,
            padx=8,
            pady=8,
        )
        self.desc_lbl.pack(fill=tk.X, pady=(6, 15))

        # Output Directory Settings
        tk.Label(
            parent,
            text="输出目录 (留空为原目录)",
            font=("Segoe UI", 9, "bold"),
            fg="#cdd6f4",
            bg="#252538",
        ).pack(anchor=tk.W, pady=(0, 4))

        out_frame = tk.Frame(parent, bg="#252538")
        out_frame.pack(fill=tk.X, pady=(0, 15))

        out_entry = tk.Entry(
            out_frame,
            textvariable=self.output_dir_var,
            font=("Segoe UI", 8),
            bg="#181825",
            fg="#cdd6f4",
            insertbackground="#cdd6f4",
            relief=tk.FLAT,
        )
        out_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4, padx=(0, 6))

        tk.Button(
            out_frame,
            text="选择",
            command=self._browse_output_dir,
            font=("Segoe UI", 8, "bold"),
            bg="#45475a",
            fg="#cdd6f4",
            relief=tk.FLAT,
            padx=8,
            cursor="hand2",
        ).pack(side=tk.RIGHT)

        # Concurrency
        workers_frame = tk.Frame(parent, bg="#252538")
        workers_frame.pack(fill=tk.X, pady=(0, 20))
        tk.Label(
            workers_frame,
            text="并行任务数:",
            font=("Segoe UI", 9),
            fg="#cdd6f4",
            bg="#252538",
        ).pack(side=tk.LEFT)
        spin = tk.Spinbox(
            workers_frame,
            from_=1,
            to=8,
            textvariable=self.workers_var,
            width=5,
            font=("Segoe UI", 9),
            bg="#181825",
            fg="#cdd6f4",
            relief=tk.FLAT,
        )
        spin.pack(side=tk.RIGHT)

        # Primary Action Buttons
        self.start_btn = tk.Button(
            parent,
            text="▶ 开始批量处理",
            command=self._start_processing,
            font=("Segoe UI", 11, "bold"),
            bg="#a6e3a1",
            fg="#11111b",
            relief=tk.FLAT,
            pady=10,
            cursor="hand2",
        )
        self.start_btn.pack(fill=tk.X, pady=(0, 8))

        self.stop_btn = tk.Button(
            parent,
            text="■ 停止全部任务",
            command=self._stop_processing,
            state=tk.DISABLED,
            font=("Segoe UI", 10, "bold"),
            bg="#f38ba8",
            fg="#11111b",
            relief=tk.FLAT,
            pady=8,
            cursor="hand2",
        )
        self.stop_btn.pack(fill=tk.X)

    def _build_right_queue(self, parent: tk.Frame):
        # Action Toolbar
        toolbar = tk.Frame(parent, bg="#1e1e2e")
        toolbar.pack(fill=tk.X, pady=(0, 10))

        tk.Button(
            toolbar,
            text="+ 添加视频文件...",
            command=self._add_files,
            font=("Segoe UI", 9, "bold"),
            bg="#89b4fa",
            fg="#11111b",
            relief=tk.FLAT,
            padx=12,
            pady=6,
            cursor="hand2",
        ).pack(side=tk.LEFT, padx=(0, 8))

        tk.Button(
            toolbar,
            text="+ 导入整文件夹...",
            command=self._add_folder,
            font=("Segoe UI", 9),
            bg="#313244",
            fg="#cdd6f4",
            relief=tk.FLAT,
            padx=12,
            pady=6,
            cursor="hand2",
        ).pack(side=tk.LEFT, padx=(0, 8))

        tk.Button(
            toolbar,
            text="清空已完成",
            command=self._clear_completed,
            font=("Segoe UI", 9),
            bg="#313244",
            fg="#cdd6f4",
            relief=tk.FLAT,
            padx=10,
            pady=6,
            cursor="hand2",
        ).pack(side=tk.LEFT)

        # Global Progress Bar
        self.global_prog_bar = ttk.Progressbar(
            parent,
            variable=self.global_progress_var,
            style="Horizontal.TProgressbar",
            maximum=100.0,
        )
        self.global_prog_bar.pack(fill=tk.X, pady=(0, 10))

        # Task Table (Treeview)
        cols = ("name", "preset", "status", "progress", "speed", "eta")
        self.tree = ttk.Treeview(parent, columns=cols, show="headings", selectmode="browse")

        self.tree.heading("name", text="文件名称")
        self.tree.heading("preset", text="预设")
        self.tree.heading("status", text="状态")
        self.tree.heading("progress", text="处理进度")
        self.tree.heading("speed", text="转码倍速")
        self.tree.heading("eta", text="预计剩余")

        self.tree.column("name", width=260, anchor=tk.W)
        self.tree.column("preset", width=100, anchor=tk.CENTER)
        self.tree.column("status", width=90, anchor=tk.CENTER)
        self.tree.column("progress", width=100, anchor=tk.CENTER)
        self.tree.column("speed", width=80, anchor=tk.CENTER)
        self.tree.column("eta", width=80, anchor=tk.CENTER)

        tree_scroll = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    # ------------------ Actions ------------------

    def _on_preset_changed(self):
        val = self.preset_var.get()
        try:
            mode = PresetMode(val)
            self.desc_lbl.config(text=PRESET_DESCRIPTIONS.get(mode, ""))
        except Exception:
            pass

    def _browse_output_dir(self):
        d = filedialog.askdirectory(title="选择输出保存目录")
        if d:
            self.output_dir_var.set(d)

    def _add_files(self):
        paths = filedialog.askopenfilenames(
            title="选择视频文件 (支持多选)",
            filetypes=[("视频文件", "*.mp4 *.mov *.mkv *.flv *.avi *.webm"), ("所有文件", "*.*")],
        )
        if not paths:
            return

        out_base = self.output_dir_var.get().strip() or None
        mode = PresetMode(self.preset_var.get())

        for p in paths:
            task = self.queue_manager.add_task(p, output_path=None, preset=mode)
            self._insert_task_to_tree(task)

        self.global_status_var.set(f"已就绪: 当前队列共有 {len(self.queue_manager.tasks)} 个任务")

    def _add_folder(self):
        folder = filedialog.askdirectory(title="选择包含视频的文件夹")
        if not folder:
            return

        out_base = self.output_dir_var.get().strip() or None
        mode = PresetMode(self.preset_var.get())

        added = self.queue_manager.add_directory(folder, output_dir=out_base, preset=mode)
        for t in added:
            self._insert_task_to_tree(t)

        self.global_status_var.set(f"已就绪: 从目录添加了 {len(added)} 个视频任务")

    def _insert_task_to_tree(self, task: RemediationTask):
        status_text = self._format_status(task.status)
        iid = self.tree.insert(
            "",
            tk.END,
            values=(
                task.filename,
                task.preset.value,
                status_text,
                f"{task.progress:.1f}%",
                task.speed,
                f"{task.eta:.0f}s" if task.eta > 0 else "-",
            ),
        )
        self._task_tree_items[task.task_id] = iid

    def _start_processing(self):
        if not self.queue_manager.tasks:
            messagebox.showinfo("提示", "队列中暂无任务，请先添加视频文件！")
            return

        self.queue_manager.max_workers = self.workers_var.get()
        self.start_btn.config(state=tk.DISABLED, bg="#45475a")
        self.stop_btn.config(state=tk.NORMAL)
        self.global_status_var.set("正在批量处理任务...")
        self.queue_manager.start()

    def _stop_processing(self):
        self.queue_manager.stop_all()
        self.global_status_var.set("已终止任务处理")
        self.start_btn.config(state=tk.NORMAL, bg="#a6e3a1")
        self.stop_btn.config(state=tk.DISABLED)

    def _clear_completed(self):
        self.queue_manager.clear_completed()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._task_tree_items.clear()
        for t in self.queue_manager.tasks:
            self._insert_task_to_tree(t)
        self.global_status_var.set("已清空完成项")

    # ------------------ Callbacks ------------------

    def _on_task_updated(self, task: RemediationTask):
        self.root.after(0, self._sync_task_ui, task)

    def _sync_task_ui(self, task: RemediationTask):
        iid = self._task_tree_items.get(task.task_id)
        if not iid:
            return

        status_text = self._format_status(task.status)
        self.tree.item(
            iid,
            values=(
                task.filename,
                task.preset.value,
                status_text,
                f"{task.progress:.1f}%",
                task.speed,
                f"{task.eta:.0f}s" if task.eta > 0 else "-",
            ),
        )

        # Update global progress bar
        tasks = self.queue_manager.tasks
        if tasks:
            avg_prog = sum(t.progress for t in tasks) / len(tasks)
            self.global_progress_var.set(avg_prog)

    def _on_queue_finished(self):
        self.root.after(0, self._sync_queue_finished)

    def _sync_queue_finished(self):
        self.start_btn.config(state=tk.NORMAL, bg="#a6e3a1")
        self.stop_btn.config(state=tk.DISABLED)
        self.global_progress_var.set(100.0)
        self.global_status_var.set("所有任务已处理完毕！")
        messagebox.showinfo("完成", "队列中所有视频处理完毕！")

    def _format_status(self, status: TaskStatus) -> str:
        mapping = {
            TaskStatus.PENDING: "待处理",
            TaskStatus.RUNNING: "处理中 ⏳",
            TaskStatus.SUCCESS: "已完成 ✔",
            TaskStatus.FAILED: "失败 ✖",
            TaskStatus.CANCELLED: "已取消",
        }
        return mapping.get(status, status.value)


def main():
    root = tk.Tk()
    app = VideoRemixApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
