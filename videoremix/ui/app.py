"""Modern, responsive desktop GUI for VideoRemix."""

import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, List, Optional

# Ensure package path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pathlib import Path
from videoremix import __version__
from videoremix.core.hardware import HardwareDetector
from videoremix.core.presets import PRESET_DESCRIPTIONS, PresetMode
from videoremix.queue.manager import BatchQueueManager
from videoremix.queue.task import RemediationTask, TaskStatus


def setup_windows_dpi_awareness():
    """Configure Windows high-DPI awareness before creating Tk instance."""
    if sys.platform.startswith("win") or (os.name == "nt"):
        try:
            import ctypes
            # 1. Per-Monitor V2 (Windows 10 Creators Update 1703+)
            try:
                if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
                    return
            except Exception:
                pass

            # 2. System DPI Aware (Windows 8.1+)
            try:
                if ctypes.windll.shcore.SetProcessDpiAwareness(1) == 0:
                    return
            except Exception:
                pass

            # 3. Process DPI Aware (Windows Vista+)
            try:
                if ctypes.windll.user32.SetProcessDPIAware():
                    return
            except Exception:
                pass
        except Exception:
            pass


class VideoRemixApp:
    """Modern, adaptive desktop application for batch video deduplication."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"VideoRemix Pro v{__version__} - 智能多模态音视频去重系统")

        # DPI Awareness & Scaling
        is_win = sys.platform.startswith("win") or (os.name == "nt")
        self.font_family = "Microsoft YaHei UI" if is_win else "Segoe UI"
        try:
            dpi = float(self.root.winfo_fpixels('1i'))
            self.scale = max(1.0, dpi / 96.0)
        except Exception:
            self.scale = 1.0

        # Responsive size scaled by DPI
        win_w = int(1020 * self.scale)
        win_h = int(720 * self.scale)
        min_w = int(860 * self.scale)
        min_h = int(580 * self.scale)
        self.root.geometry(f"{win_w}x{win_h}")
        self.root.minsize(min_w, min_h)
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
        self.custom_color_var = tk.BooleanVar(value=True)
        self.custom_eq_var = tk.BooleanVar(value=True)
        self.custom_noise_var = tk.BooleanVar(value=True)
        self.custom_mask_var = tk.BooleanVar(value=False)
        self.custom_trim_start_var = tk.DoubleVar(value=0.8)
        self.custom_trim_end_var = tk.DoubleVar(value=0.5)

        # Matrix裂变与随机化
        self.variants_var = tk.IntVar(value=1)
        self.randomize_var = tk.BooleanVar(value=True)

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
            rowheight=max(28, int(28 * self.scale)),
            font=(self.font_family, 9),
        )
        style.configure(
            "Treeview.Heading",
            background="#313244",
            foreground="#cdd6f4",
            relief="flat",
            font=(self.font_family, 9, "bold"),
        )
        style.map("Treeview", background=[("selected", "#45475a")])

        # Modern Progressbar
        style.configure("Horizontal.TProgressbar", troughcolor="#313244", background="#89b4fa", thickness=10)

    def _build_layout(self):
        # 1. Top Header Bar
        header = tk.Frame(self.root, bg="#181825", height=int(65 * self.scale))
        header.pack(fill=tk.X, side=tk.TOP)

        title_lbl = tk.Label(
            header,
            text="VideoRemix Engine",
            font=(self.font_family, 16, "bold"),
            fg="#cdd6f4",
            bg="#181825",
        )
        title_lbl.pack(side=tk.LEFT, padx=20, pady=12)

        codec_badge = tk.Label(
            header,
            text=f"加速引擎: {self.encoder_config.name}",
            font=(self.font_family, 9, "bold"),
            fg="#a6e3a1" if self.encoder_config.is_hardware else "#f9e2af",
            bg="#313244",
            padx=10,
            pady=4,
        )
        codec_badge.pack(side=tk.RIGHT, padx=20, pady=16)

        # 2. Main Content Split View
        content = tk.Frame(self.root, bg="#1e1e2e")
        content.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)

        # Left Column: Presets & Controls with Smooth Scrollable Canvas
        left_container = tk.Frame(content, bg="#252538", width=int(330 * self.scale))
        left_container.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 12))
        left_container.pack_propagate(False)

        self.left_canvas = tk.Canvas(left_container, bg="#252538", highlightthickness=0)
        left_scrollbar = ttk.Scrollbar(left_container, orient=tk.VERTICAL, command=self.left_canvas.yview)
        left_panel = tk.Frame(self.left_canvas, bg="#252538", padx=10, pady=10)

        left_panel.bind(
            "<Configure>",
            lambda e: self.left_canvas.configure(scrollregion=self.left_canvas.bbox("all")),
        )

        self._left_win = self.left_canvas.create_window((0, 0), window=left_panel, anchor="nw")

        def _on_canvas_configure(e):
            self.left_canvas.itemconfig(self._left_win, width=e.width)

        self.left_canvas.bind("<Configure>", _on_canvas_configure)
        self.left_canvas.configure(yscrollcommand=left_scrollbar.set)

        self.left_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        def _on_mousewheel(event):
            if event.delta:
                self.left_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            elif getattr(event, "num", None) == 4:
                self.left_canvas.yview_scroll(-1, "units")
            elif getattr(event, "num", None) == 5:
                self.left_canvas.yview_scroll(1, "units")

        self.left_canvas.bind("<Enter>", lambda e: self.left_canvas.bind_all("<MouseWheel>", _on_mousewheel))
        self.left_canvas.bind("<Leave>", lambda e: self.left_canvas.unbind_all("<MouseWheel>"))

        # Right Column: Task Queue Table & Log Output
        right_panel = tk.Frame(content, bg="#1e1e2e")
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self._build_left_controls(left_panel)
        self._build_right_queue(right_panel)

        # 3. Bottom Status Bar
        statusbar = tk.Frame(self.root, bg="#181825", height=int(32 * self.scale), padx=15)
        statusbar.pack(fill=tk.X, side=tk.BOTTOM)

        tk.Label(
            statusbar,
            textvariable=self.global_status_var,
            font=(self.font_family, 9),
            fg="#a6adc8",
            bg="#181825",
        ).pack(side=tk.LEFT, pady=6)

    def _build_left_controls(self, parent: tk.Frame):
        # Section: Preset Selection
        tk.Label(
            parent,
            text="去重模式预设",
            font=(self.font_family, 11, "bold"),
            fg="#cdd6f4",
            bg="#252538",
        ).pack(anchor=tk.W, pady=(0, 8))

        presets = [
            (PresetMode.BALANCED_REMIX.value, "推荐: 强效去重 (自媒体矩阵)"),
            (PresetMode.ECOMMERCE.value, "专版: 电商防查重 (专克京东/拼多多)"),
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
                font=(self.font_family, 9),
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
            font=(self.font_family, 8),
            fg="#a6adc8",
            bg="#1e1e2e",
            wraplength=int(280 * self.scale),
            justify=tk.LEFT,
            padx=8,
            pady=8,
        )
        self.desc_lbl.pack(fill=tk.X, pady=(6, 12))

        # Collapsible Custom Options Panel
        self.custom_panel = tk.LabelFrame(
            parent,
            text=" ⚙️ 自定义参数配置 ",
            font=(self.font_family, 8, "bold"),
            fg="#89b4fa",
            bg="#252538",
            padx=int(8 * self.scale),
            pady=int(6 * self.scale),
        )

        # 1. Zoom Slider
        z_frame = tk.Frame(self.custom_panel, bg="#252538")
        z_frame.pack(fill=tk.X, pady=(2, 0))
        tk.Label(z_frame, text="画幅微缩放:", font=(self.font_family, 8), fg="#cdd6f4", bg="#252538").pack(side=tk.LEFT)
        self.zoom_lbl = tk.Label(z_frame, text=f"{self.custom_zoom_var.get():.2f}x", font=(self.font_family, 8, "bold"), fg="#a6e3a1", bg="#252538")
        self.zoom_lbl.pack(side=tk.RIGHT)
        z_scale = tk.Scale(
            self.custom_panel,
            variable=self.custom_zoom_var,
            from_=1.00,
            to=1.15,
            resolution=0.01,
            orient=tk.HORIZONTAL,
            showvalue=False,
            bg="#181825",
            fg="#cdd6f4",
            troughcolor="#313244",
            highlightthickness=0,
            relief=tk.FLAT,
            command=lambda v: self.zoom_lbl.config(text=f"{float(v):.2f}x"),
        )
        z_scale.pack(fill=tk.X, pady=(0, 4))

        # 2. Speed Slider
        s_frame = tk.Frame(self.custom_panel, bg="#252538")
        s_frame.pack(fill=tk.X, pady=(2, 0))
        tk.Label(s_frame, text="音画变速比:", font=(self.font_family, 8), fg="#cdd6f4", bg="#252538").pack(side=tk.LEFT)
        self.speed_lbl = tk.Label(s_frame, text=f"{self.custom_speed_var.get():.3f}x", font=(self.font_family, 8, "bold"), fg="#a6e3a1", bg="#252538")
        self.speed_lbl.pack(side=tk.RIGHT)
        s_scale = tk.Scale(
            self.custom_panel,
            variable=self.custom_speed_var,
            from_=0.950,
            to=1.100,
            resolution=0.005,
            orient=tk.HORIZONTAL,
            showvalue=False,
            bg="#181825",
            fg="#cdd6f4",
            troughcolor="#313244",
            highlightthickness=0,
            relief=tk.FLAT,
            command=lambda v: self.speed_lbl.config(text=f"{float(v):.3f}x"),
        )
        s_scale.pack(fill=tk.X, pady=(0, 4))

        # 3. Grain & Pitch row
        gp_frame = tk.Frame(self.custom_panel, bg="#252538")
        gp_frame.pack(fill=tk.X, pady=2)

        g_box = tk.Frame(gp_frame, bg="#252538")
        g_box.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(g_box, text="胶片噪点:", font=(self.font_family, 8), fg="#cdd6f4", bg="#252538").pack(anchor=tk.W)
        tk.Spinbox(
            g_box, from_=0, to=10, textvariable=self.custom_grain_var, width=5,
            font=(self.font_family, 8), bg="#181825", fg="#cdd6f4", relief=tk.FLAT
        ).pack(anchor=tk.W, pady=2)

        p_box = tk.Frame(gp_frame, bg="#252538")
        p_box.pack(side=tk.RIGHT, fill=tk.X, expand=True)
        tk.Label(p_box, text="变调(半音):", font=(self.font_family, 8), fg="#cdd6f4", bg="#252538").pack(anchor=tk.W)
        tk.Spinbox(
            p_box, from_=-2.0, to=2.0, increment=0.05, textvariable=self.custom_pitch_var, width=5,
            font=(self.font_family, 8), bg="#181825", fg="#cdd6f4", relief=tk.FLAT
        ).pack(anchor=tk.W, pady=2)

        # 4. Checkbuttons for Effects
        cb_grid = tk.Frame(self.custom_panel, bg="#252538")
        cb_grid.pack(fill=tk.X, pady=(4, 0))

        tk.Checkbutton(
            cb_grid, text="镜像翻转", variable=self.custom_hflip_var,
            font=(self.font_family, 8), fg="#cdd6f4", bg="#252538", selectcolor="#313244", activebackground="#252538"
        ).grid(row=0, column=0, sticky=tk.W, pady=1)

        tk.Checkbutton(
            cb_grid, text="画中画模式", variable=self.custom_pip_var,
            font=(self.font_family, 8), fg="#cdd6f4", bg="#252538", selectcolor="#313244", activebackground="#252538"
        ).grid(row=0, column=1, sticky=tk.W, pady=1)

        tk.Checkbutton(
            cb_grid, text="自然调色", variable=self.custom_color_var,
            font=(self.font_family, 8), fg="#cdd6f4", bg="#252538", selectcolor="#313244", activebackground="#252538"
        ).grid(row=1, column=0, sticky=tk.W, pady=1)

        tk.Checkbutton(
            cb_grid, text="声学重构", variable=self.custom_eq_var,
            font=(self.font_family, 8), fg="#cdd6f4", bg="#252538", selectcolor="#313244", activebackground="#252538"
        ).grid(row=1, column=1, sticky=tk.W, pady=1)

        tk.Checkbutton(
            cb_grid, text="底部字幕遮罩 (阻断OCR)", variable=self.custom_mask_var,
            font=(self.font_family, 8), fg="#cdd6f4", bg="#252538", selectcolor="#313244", activebackground="#252538"
        ).grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=1)

        # 5. Trim Head & Tail row
        trim_frame = tk.Frame(self.custom_panel, bg="#252538")
        trim_frame.pack(fill=tk.X, pady=(4, 2))

        th_box = tk.Frame(trim_frame, bg="#252538")
        th_box.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(th_box, text="片头截断(秒):", font=(self.font_family, 8), fg="#cdd6f4", bg="#252538").pack(anchor=tk.W)
        tk.Spinbox(
            th_box, from_=0.0, to=5.0, increment=0.1, textvariable=self.custom_trim_start_var, width=5,
            font=(self.font_family, 8), bg="#181825", fg="#cdd6f4", relief=tk.FLAT
        ).pack(anchor=tk.W, pady=2)

        te_box = tk.Frame(trim_frame, bg="#252538")
        te_box.pack(side=tk.RIGHT, fill=tk.X, expand=True)
        tk.Label(te_box, text="片尾截断(秒):", font=(self.font_family, 8), fg="#cdd6f4", bg="#252538").pack(anchor=tk.W)
        tk.Spinbox(
            te_box, from_=0.0, to=5.0, increment=0.1, textvariable=self.custom_trim_end_var, width=5,
            font=(self.font_family, 8), bg="#181825", fg="#cdd6f4", relief=tk.FLAT
        ).pack(anchor=tk.W, pady=2)

        # Output Directory Settings
        tk.Label(
            parent,
            text="输出目录 (留空为原目录)",
            font=(self.font_family, 9, "bold"),
            fg="#cdd6f4",
            bg="#252538",
        ).pack(anchor=tk.W, pady=(0, 4))

        out_frame = tk.Frame(parent, bg="#252538")
        out_frame.pack(fill=tk.X, pady=(0, 10))

        out_entry = tk.Entry(
            out_frame,
            textvariable=self.output_dir_var,
            font=(self.font_family, 8),
            bg="#181825",
            fg="#cdd6f4",
            insertbackground="#cdd6f4",
            relief=tk.FLAT,
        )
        out_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4, padx=(0, 4))

        tk.Button(
            out_frame,
            text="选择",
            command=self._browse_output_dir,
            font=(self.font_family, 8, "bold"),
            bg="#45475a",
            fg="#cdd6f4",
            relief=tk.FLAT,
            padx=6,
            cursor="hand2",
        ).pack(side=tk.LEFT, padx=(0, 4))

        tk.Button(
            out_frame,
            text="打开",
            command=self._open_output_dir,
            font=(self.font_family, 8),
            bg="#313244",
            fg="#89b4fa",
            relief=tk.FLAT,
            padx=6,
            cursor="hand2",
        ).pack(side=tk.RIGHT)

        # Matrix Multiplier & Concurrency Card
        matrix_card = tk.LabelFrame(
            parent,
            text=" 🎲 矩阵裂变与并发 ",
            font=(self.font_family, 8, "bold"),
            fg="#cba6f7",
            bg="#252538",
            padx=int(8 * self.scale),
            pady=int(6 * self.scale),
        )
        matrix_card.pack(fill=tk.X, pady=(0, 14))

        mc_row1 = tk.Frame(matrix_card, bg="#252538")
        mc_row1.pack(fill=tk.X, pady=2)
        tk.Label(mc_row1, text="变体裂变数 (1变N):", font=(self.font_family, 8), fg="#cdd6f4", bg="#252538").pack(side=tk.LEFT)
        tk.Spinbox(
            mc_row1, from_=1, to=5, textvariable=self.variants_var, width=4,
            font=(self.font_family, 8, "bold"), bg="#181825", fg="#a6e3a1", relief=tk.FLAT
        ).pack(side=tk.RIGHT)

        mc_row2 = tk.Frame(matrix_card, bg="#252538")
        mc_row2.pack(fill=tk.X, pady=2)
        tk.Label(mc_row2, text="并行处理数 (线程):", font=(self.font_family, 8), fg="#cdd6f4", bg="#252538").pack(side=tk.LEFT)
        tk.Spinbox(
            mc_row2, from_=1, to=8, textvariable=self.workers_var, width=4,
            font=(self.font_family, 8), bg="#181825", fg="#cdd6f4", relief=tk.FLAT
        ).pack(side=tk.RIGHT)

        tk.Checkbutton(
            matrix_card, text="参数区间微扰 (防批量同质化)", variable=self.randomize_var,
            font=(self.font_family, 8), fg="#a6adc8", bg="#252538", selectcolor="#313244", activebackground="#252538"
        ).pack(anchor=tk.W, pady=(2, 0))

        # Primary Action Buttons
        self.start_btn = tk.Button(
            parent,
            text="▶ 开始批量处理",
            command=self._start_processing,
            font=(self.font_family, 11, "bold"),
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
            font=(self.font_family, 10, "bold"),
            bg="#f38ba8",
            fg="#11111b",
            relief=tk.FLAT,
            pady=8,
            cursor="hand2",
        )
        self.stop_btn.pack(fill=tk.X)

        self._on_preset_changed()

    def _build_right_queue(self, parent: tk.Frame):
        # Action Toolbar
        toolbar = tk.Frame(parent, bg="#1e1e2e")
        toolbar.pack(fill=tk.X, pady=(0, 10))

        tk.Button(
            toolbar,
            text="+ 添加视频文件...",
            command=self._add_files,
            font=(self.font_family, 9, "bold"),
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
            font=(self.font_family, 9),
            bg="#313244",
            fg="#cdd6f4",
            relief=tk.FLAT,
            padx=12,
            pady=6,
            cursor="hand2",
        ).pack(side=tk.LEFT, padx=(0, 8))

        tk.Button(
            toolbar,
            text="📂 打开输出目录",
            command=self._open_output_dir,
            font=(self.font_family, 9),
            bg="#313244",
            fg="#89b4fa",
            relief=tk.FLAT,
            padx=10,
            pady=6,
            cursor="hand2",
        ).pack(side=tk.LEFT, padx=(0, 8))

        tk.Button(
            toolbar,
            text="清空已完成",
            command=self._clear_completed,
            font=(self.font_family, 9),
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

        self.tree.column("name", width=int(260 * self.scale), anchor=tk.W)
        self.tree.column("preset", width=int(100 * self.scale), anchor=tk.CENTER)
        self.tree.column("status", width=int(90 * self.scale), anchor=tk.CENTER)
        self.tree.column("progress", width=int(100 * self.scale), anchor=tk.CENTER)
        self.tree.column("speed", width=int(80 * self.scale), anchor=tk.CENTER)
        self.tree.column("eta", width=int(80 * self.scale), anchor=tk.CENTER)

        tree_scroll = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<Double-1>", self._on_tree_double_click)

    # ------------------ Actions ------------------

    def _on_preset_changed(self):
        val = self.preset_var.get()
        try:
            mode = PresetMode(val)
            self.desc_lbl.config(text=PRESET_DESCRIPTIONS.get(mode, ""))
            if mode == PresetMode.CUSTOM:
                self.custom_panel.pack(fill=tk.X, pady=(0, 12), after=self.desc_lbl)
            else:
                self.custom_panel.pack_forget()
            if hasattr(self, "left_canvas"):
                self.left_canvas.update_idletasks()
                self.left_canvas.configure(scrollregion=self.left_canvas.bbox("all"))
        except Exception:
            pass

    def _get_current_custom_opts(self) -> Dict[str, Any]:
        """Collect current values from custom settings controls."""
        return {
            "zoom": round(float(self.custom_zoom_var.get()), 3),
            "speed": round(float(self.custom_speed_var.get()), 3),
            "grain": int(self.custom_grain_var.get()),
            "pitch": round(float(self.custom_pitch_var.get()), 2),
            "hflip": bool(self.custom_hflip_var.get()),
            "pip": bool(self.custom_pip_var.get()),
            "color_grade": bool(self.custom_color_var.get()),
            "equalizer": bool(self.custom_eq_var.get()),
            "noise_floor": bool(self.custom_noise_var.get()),
            "subtitle_mask": bool(self.custom_mask_var.get()),
            "trim_start": round(float(self.custom_trim_start_var.get()), 2),
            "trim_end": round(float(self.custom_trim_end_var.get()), 2),
            "randomize": bool(self.randomize_var.get()),
        }

    def _browse_output_dir(self):
        d = filedialog.askdirectory(title="选择输出保存目录")
        if d:
            self.output_dir_var.set(d)

    def _open_output_dir(self):
        target = self.output_dir_var.get().strip()
        if not target:
            target = os.getcwd()
        if not os.path.exists(target):
            try:
                os.makedirs(target, exist_ok=True)
            except Exception as e:
                messagebox.showwarning("提示", f"无法创建输出目录: {e}")
                return

        try:
            if sys.platform == "win32":
                os.startfile(target)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", target])
            else:
                subprocess.Popen(["xdg-open", target])
        except Exception as e:
            messagebox.showwarning("提示", f"打开输出目录失败: {e}")

    def _add_files(self):
        paths = filedialog.askopenfilenames(
            title="选择视频文件 (支持多选)",
            filetypes=[("视频文件", "*.mp4 *.mov *.mkv *.flv *.avi *.webm"), ("所有文件", "*.*")],
        )
        if not paths:
            return

        out_base = self.output_dir_var.get().strip() or None
        mode = PresetMode(self.preset_var.get())
        custom_opts = self._get_current_custom_opts() if mode == PresetMode.CUSTOM else {}
        if bool(self.randomize_var.get()):
            custom_opts["randomize"] = True

        variants = max(1, min(5, int(self.variants_var.get())))

        for p in paths:
            out_path = None
            if out_base:
                p_in = Path(p)
                target = Path(out_base) / p_in.name
                try:
                    is_same = target.resolve() == p_in.resolve()
                except Exception:
                    is_same = os.path.abspath(str(target)) == os.path.abspath(str(p_in))
                if is_same:
                    target = Path(out_base) / f"{p_in.stem}_remix{p_in.suffix}"
                out_path = str(target)

            res = self.queue_manager.add_task(p, output_path=out_path, preset=mode, variants=variants, **custom_opts)
            if isinstance(res, list):
                for t in res:
                    self._insert_task_to_tree(t)
            else:
                self._insert_task_to_tree(res)

        self.global_status_var.set(f"已就绪: 当前队列共有 {len(self.queue_manager.tasks)} 个任务")

    def _add_folder(self):
        folder = filedialog.askdirectory(title="选择包含视频的文件夹")
        if not folder:
            return

        out_base = self.output_dir_var.get().strip() or None
        mode = PresetMode(self.preset_var.get())
        custom_opts = self._get_current_custom_opts() if mode == PresetMode.CUSTOM else {}
        if bool(self.randomize_var.get()):
            custom_opts["randomize"] = True

        variants = max(1, min(5, int(self.variants_var.get())))

        added = self.queue_manager.add_directory(
            folder, output_dir=out_base, preset=mode, variants=variants, **custom_opts
        )
        for t in added:
            self._insert_task_to_tree(t)

        self.global_status_var.set(f"已就绪: 从目录添加了 {len(added)} 个视频任务")

    def _format_preset(self, task: RemediationTask) -> str:
        if task.preset == PresetMode.CUSTOM:
            opts = task.custom_opts or {}
            z = opts.get("zoom", 1.0)
            s = opts.get("speed", 1.0)
            return f"自定义 ({z:.2f}x/{s:.3f}x)"
        mapping = {
            PresetMode.QUALITY_FIRST: "画质保真",
            PresetMode.BALANCED_REMIX: "强效去重",
            PresetMode.ECOMMERCE: "电商专版",
            PresetMode.SMART_PIP: "智能画中画",
        }
        return mapping.get(task.preset, task.preset.value)

    def _on_tree_double_click(self, event):
        item_id = self.tree.identify_row(event.y)
        if not item_id:
            return

        target_task = None
        for task in self.queue_manager.tasks:
            if self._task_tree_items.get(task.task_id) == item_id:
                target_task = task
                break

        if not target_task:
            return

        if target_task.status == TaskStatus.FAILED:
            err_msg = target_task.error_message or "未知错误信息"
            messagebox.showerror(
                f"任务失败详情 - {target_task.filename}",
                f"文件: {target_task.filename}\n\n错误信息:\n{err_msg}",
            )
        else:
            lines = [
                f"文件名称: {target_task.filename}",
                f"输入路径: {target_task.input_path}",
                f"输出路径: {target_task.output_path}",
                f"预设方案: {self._format_preset(target_task)}",
                f"当前状态: {self._format_status(target_task.status)}",
                f"完成进度: {target_task.progress:.1f}%",
                f"当前转速: {target_task.speed}",
            ]
            if target_task.preset == PresetMode.CUSTOM and target_task.custom_opts:
                lines.append("\n【自定义参数清单】:")
                for k, v in target_task.custom_opts.items():
                    lines.append(f"  • {k}: {v}")
            messagebox.showinfo(f"任务详情 - {target_task.filename}", "\n".join(lines))

    def _insert_task_to_tree(self, task: RemediationTask):
        status_text = self._format_status(task.status)
        iid = self.tree.insert(
            "",
            tk.END,
            values=(
                task.filename,
                self._format_preset(task),
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
                self._format_preset(task),
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
    setup_windows_dpi_awareness()
    root = tk.Tk()
    app = VideoRemixApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
