"""Modern dedicated GUI for Douyin watermark-free video parsing, downloading, and benchmark creator monitoring."""

import ctypes
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, Dict, List, Optional
import urllib.request

from videoremix.core.probe import get_ffmpeg_bin
from videoremix.ingest.account_manager import BenchmarkAccountManager
from videoremix.ingest.douyin import DouyinParser, DouyinScraperError
from videoremix.ingest.downloader import VideoDownloader
from videoremix.ingest.models import BenchmarkAccount, DouyinVideoItem

logger = logging.getLogger(__name__)


def setup_windows_dpi_awareness():
    """Enable high-DPI scaling on Windows to ensure razor-sharp text and controls."""
    if sys.platform.startswith("win") or (os.name == "nt"):
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except Exception:
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                try:
                    ctypes.windll.user32.SetProcessDPIAware()
                except Exception:
                    pass


class DouyinParserApp:
    """Dedicated desktop tool for Douyin watermark-free parsing, downloading, and benchmark creator monitoring."""

    def __init__(self, root: Any, on_import_callback: Optional[Callable[[str], None]] = None):
        self.root = root
        self.on_import_callback = on_import_callback
        self.root.title("抖音无水印解析与长期对标监控 - VideoRemix Pro Suite")

        # DPI Calculation
        try:
            dpi = float(self.root.winfo_fpixels('1i'))
            self.scale = max(1.0, dpi / 96.0)
        except Exception:
            self.scale = 1.0

        self.font_family = "Microsoft YaHei UI" if (sys.platform == "win32" or os.name == "nt") else "Segoe UI"

        w = int(980 * self.scale)
        h = int(720 * self.scale)
        self.root.geometry(f"{w}x{h}")
        self.root.minsize(int(840 * self.scale), int(580 * self.scale))
        self.root.configure(bg="#11111b")

        # Core Engines
        self.parser = DouyinParser()
        self.downloader = VideoDownloader()
        self.account_mgr = BenchmarkAccountManager(parser=self.parser)

        # Tab 1: Single Video State
        self.input_url_var = tk.StringVar()
        self.status_var = tk.StringVar(value="就绪: 请输入抖音链接或在对标监控中添加博主")
        self.save_dir_var = tk.StringVar(value=str(self.downloader.default_dir))
        self.current_item: Optional[DouyinVideoItem] = None
        self.download_progress_var = tk.DoubleVar(value=0.0)
        self.cover_img_ref = None

        # Tab 2: Benchmark Accounts State
        self.acc_url_var = tk.StringVar()
        self.acc_category_var = tk.StringVar(value="电商带货")
        self.monitored_videos: List[DouyinVideoItem] = []
        self.selected_aweme_ids: set[str] = set()
        self._account_row_map: Dict[str, BenchmarkAccount] = {}
        self._video_row_map: Dict[str, DouyinVideoItem] = {}

        self._build_ui()
        self._reload_accounts_table()

    # ------------------ UI Construction ------------------

    def _build_ui(self):
        # 1. Header
        header = tk.Frame(self.root, bg="#1e1e2e", padx=20, pady=14)
        header.pack(fill=tk.X)

        title_lbl = tk.Label(
            header,
            text="⚡ 抖音无水印原画解析与长期对标监控",
            font=(self.font_family, 14, "bold"),
            fg="#ffffff",
            bg="#1e1e2e",
        )
        title_lbl.pack(side=tk.LEFT)

        sub_badge = tk.Label(
            header,
            text="无水印原画直链 • 对标博主增量抓取 • 0秒去重流转",
            font=(self.font_family, 9),
            fg="#a6e3a1",
            bg="#252538",
            padx=8,
            pady=3,
        )
        sub_badge.pack(side=tk.RIGHT)

        # Configure TTK styles for dark theme
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TNotebook", background="#11111b", borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background="#1e1e2e",
            foreground="#cdd6f4",
            padding=[16, 7],
            font=(self.font_family, 10, "bold"),
        )
        style.map("TNotebook.Tab", background=[("selected", "#313244")], foreground=[("selected", "#89b4fa")])

        style.configure(
            "Treeview",
            background="#1e1e2e",
            foreground="#cdd6f4",
            fieldbackground="#1e1e2e",
            rowheight=max(26, int(26 * self.scale)),
            font=(self.font_family, 9),
        )
        style.configure(
            "Treeview.Heading",
            background="#313244",
            foreground="#ffffff",
            font=(self.font_family, 9, "bold"),
        )
        style.map("Treeview", background=[("selected", "#45475a")])

        # Notebook Container
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=16, pady=10)

        # Tab 1: Single Parse
        tab1_frame = tk.Frame(self.notebook, bg="#11111b", padx=6, pady=6)
        self.notebook.add(tab1_frame, text=" 🔗 单视频快速解析 ")
        self._build_tab1_single_parser(tab1_frame)

        # Tab 2: Benchmark Monitor
        tab2_frame = tk.Frame(self.notebook, bg="#11111b", padx=6, pady=6)
        self.notebook.add(tab2_frame, text=" 👥 长期对标账号监控 (增量抓取) ")
        self._build_tab2_monitor(tab2_frame)

        # Bottom Status Bar
        self.status_bar = tk.Label(
            self.root,
            textvariable=self.status_var,
            font=(self.font_family, 8),
            fg="#a6adc8",
            bg="#181825",
            anchor=tk.W,
            padx=12,
            pady=6,
        )
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    # ------------------ Tab 1: Single Video Parser ------------------

    def _build_tab1_single_parser(self, parent: tk.Frame):
        # 1. Input Box Card
        input_card = tk.LabelFrame(
            parent,
            text=" 🔗 输入视频分享链接或口令 ",
            font=(self.font_family, 9, "bold"),
            fg="#89b4fa",
            bg="#1e1e2e",
            padx=14,
            pady=10,
        )
        input_card.pack(fill=tk.X, pady=(4, 12))

        input_row = tk.Frame(input_card, bg="#1e1e2e")
        input_row.pack(fill=tk.X)

        self.url_entry = tk.Entry(
            input_row,
            textvariable=self.input_url_var,
            font=(self.font_family, 10),
            bg="#252538",
            fg="#ffffff",
            insertbackground="#ffffff",
            relief=tk.FLAT,
        )
        self.url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6, padx=(0, 8))
        self.url_entry.bind("<Return>", lambda e: self._on_parse_clicked())

        tk.Button(
            input_row,
            text="📋 粘贴",
            command=self._paste_clipboard,
            font=(self.font_family, 9),
            bg="#313244",
            fg="#cdd6f4",
            relief=tk.FLAT,
            padx=10,
            cursor="hand2",
        ).pack(side=tk.LEFT, padx=(0, 6))

        self.parse_btn = tk.Button(
            input_row,
            text="🔍 一键解析",
            command=self._on_parse_clicked,
            font=(self.font_family, 10, "bold"),
            bg="#89b4fa",
            fg="#11111b",
            relief=tk.FLAT,
            padx=14,
            cursor="hand2",
        )
        self.parse_btn.pack(side=tk.RIGHT)

        # 2. Result Preview Card
        self.result_card = tk.LabelFrame(
            parent,
            text=" 🎬 解析结果与视频详情 ",
            font=(self.font_family, 9, "bold"),
            fg="#cba6f7",
            bg="#1e1e2e",
            padx=14,
            pady=12,
        )
        self.result_card.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        res_grid = tk.Frame(self.result_card, bg="#1e1e2e")
        res_grid.pack(fill=tk.BOTH, expand=True)

        self.cover_box = tk.Label(
            res_grid,
            text="封面预览\n(解析后显示)",
            font=(self.font_family, 9),
            fg="#6c7086",
            bg="#252538",
            width=20,
            height=10,
            relief=tk.FLAT,
        )
        self.cover_box.pack(side=tk.LEFT, padx=(0, 16), fill=tk.Y)

        meta_box = tk.Frame(res_grid, bg="#1e1e2e")
        meta_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.title_lbl = tk.Label(
            meta_box,
            text="等待解析输入...",
            font=(self.font_family, 10, "bold"),
            fg="#cdd6f4",
            bg="#1e1e2e",
            justify=tk.LEFT,
            wraplength=int(450 * self.scale),
            anchor=tk.W,
        )
        self.title_lbl.pack(fill=tk.X, pady=(0, 6))

        self.author_lbl = tk.Label(
            meta_box,
            text="博主: -",
            font=(self.font_family, 9),
            fg="#a6adc8",
            bg="#1e1e2e",
            anchor=tk.W,
        )
        self.author_lbl.pack(fill=tk.X, pady=1)

        self.time_lbl = tk.Label(
            meta_box,
            text="发布时间: -    时长: -",
            font=(self.font_family, 9),
            fg="#a6adc8",
            bg="#1e1e2e",
            anchor=tk.W,
        )
        self.time_lbl.pack(fill=tk.X, pady=1)

        self.url_info_lbl = tk.Label(
            meta_box,
            text="视频ID: -",
            font=(self.font_family, 8),
            fg="#6c7086",
            bg="#1e1e2e",
            anchor=tk.W,
        )
        self.url_info_lbl.pack(fill=tk.X, pady=(2, 6))

        self.prog_bar = ttk.Progressbar(
            meta_box,
            variable=self.download_progress_var,
            maximum=100.0,
        )
        self.prog_bar.pack(fill=tk.X, pady=(6, 4))

        # Save Directory Row
        path_row = tk.Frame(parent, bg="#11111b")
        path_row.pack(fill=tk.X, pady=(0, 10))

        tk.Label(
            path_row,
            text="保存路径:",
            font=(self.font_family, 9),
            fg="#a6adc8",
            bg="#11111b",
        ).pack(side=tk.LEFT, padx=(0, 6))

        self.dir_entry = tk.Entry(
            path_row,
            textvariable=self.save_dir_var,
            font=(self.font_family, 8),
            bg="#252538",
            fg="#cdd6f4",
            relief=tk.FLAT,
        )
        self.dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=3, padx=(0, 6))

        tk.Button(
            path_row,
            text="更改目录",
            command=self._browse_dir,
            font=(self.font_family, 8),
            bg="#313244",
            fg="#cdd6f4",
            relief=tk.FLAT,
            padx=8,
            cursor="hand2",
        ).pack(side=tk.LEFT, padx=(0, 6))

        tk.Button(
            path_row,
            text="📂 打开",
            command=self._open_dir,
            font=(self.font_family, 8),
            bg="#313244",
            fg="#89b4fa",
            relief=tk.FLAT,
            padx=8,
            cursor="hand2",
        ).pack(side=tk.RIGHT)

        # Action Buttons
        btn_bar = tk.Frame(parent, bg="#11111b")
        btn_bar.pack(fill=tk.X, pady=(0, 4))

        self.download_btn = tk.Button(
            btn_bar,
            text="⬇️ 一键下载无水印原画视频",
            command=self._on_download_clicked,
            state=tk.DISABLED,
            font=(self.font_family, 10, "bold"),
            bg="#a6e3a1",
            fg="#11111b",
            relief=tk.FLAT,
            pady=8,
            cursor="hand2",
        )
        self.download_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        self.remix_btn = tk.Button(
            btn_bar,
            text="🚀 一键导入 VideoRemix 去重",
            command=self._on_send_to_remix_clicked,
            state=tk.DISABLED,
            font=(self.font_family, 10, "bold"),
            bg="#cba6f7",
            fg="#11111b",
            relief=tk.FLAT,
            pady=8,
            cursor="hand2",
        )
        self.remix_btn.pack(side=tk.RIGHT, fill=tk.X, expand=True)

    # ------------------ Tab 2: Benchmark Creator Monitor ------------------

    def _build_tab2_monitor(self, parent: tk.Frame):
        # 1. Top Add Account Bar
        add_card = tk.LabelFrame(
            parent,
            text=" ➕ 添加长期对标博主主页 ",
            font=(self.font_family, 9, "bold"),
            fg="#a6e3a1",
            bg="#1e1e2e",
            padx=12,
            pady=8,
        )
        add_card.pack(fill=tk.X, pady=(4, 10))

        add_row = tk.Frame(add_card, bg="#1e1e2e")
        add_row.pack(fill=tk.X)

        tk.Label(
            add_row,
            text="博主主页链接:",
            font=(self.font_family, 9),
            fg="#cdd6f4",
            bg="#1e1e2e",
        ).pack(side=tk.LEFT, padx=(0, 6))

        self.acc_url_entry = tk.Entry(
            add_row,
            textvariable=self.acc_url_var,
            font=(self.font_family, 9),
            bg="#252538",
            fg="#ffffff",
            insertbackground="#ffffff",
            relief=tk.FLAT,
        )
        self.acc_url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4, padx=(0, 8))

        tk.Label(
            add_row,
            text="分类:",
            font=(self.font_family, 9),
            fg="#cdd6f4",
            bg="#1e1e2e",
        ).pack(side=tk.LEFT, padx=(0, 4))

        self.acc_cat_entry = tk.Entry(
            add_row,
            textvariable=self.acc_category_var,
            font=(self.font_family, 9),
            bg="#252538",
            fg="#ffffff",
            width=10,
            relief=tk.FLAT,
        )
        self.acc_cat_entry.pack(side=tk.LEFT, ipady=4, padx=(0, 8))

        self.add_acc_btn = tk.Button(
            add_row,
            text="➕ 添加博主",
            command=self._on_add_account_clicked,
            font=(self.font_family, 9, "bold"),
            bg="#a6e3a1",
            fg="#11111b",
            relief=tk.FLAT,
            padx=10,
            cursor="hand2",
        )
        self.add_acc_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.refresh_all_btn = tk.Button(
            add_row,
            text="🔄 刷新全部对标",
            command=self._on_refresh_all_accounts_clicked,
            font=(self.font_family, 9, "bold"),
            bg="#fab387",
            fg="#11111b",
            relief=tk.FLAT,
            padx=10,
            cursor="hand2",
        )
        self.refresh_all_btn.pack(side=tk.RIGHT)

        # 2. Center Paned Split View
        paned = tk.PanedWindow(parent, orient=tk.HORIZONTAL, bg="#11111b", sashrelief=tk.FLAT)
        paned.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # Left Column: Monitored Creators List
        left_box = tk.LabelFrame(
            paned,
            text=" 📌 已保存的对标博主 ",
            font=(self.font_family, 9, "bold"),
            fg="#89b4fa",
            bg="#1e1e2e",
            padx=8,
            pady=8,
        )
        paned.add(left_box, width=int(320 * self.scale))

        acc_cols = ("nickname", "category", "posts")
        self.acc_tree = ttk.Treeview(left_box, columns=acc_cols, show="headings", selectmode="browse")
        self.acc_tree.heading("nickname", text="博主昵称")
        self.acc_tree.heading("category", text="分类")
        self.acc_tree.heading("posts", text="作品数")

        self.acc_tree.column("nickname", width=int(140 * self.scale), anchor=tk.W)
        self.acc_tree.column("category", width=int(80 * self.scale), anchor=tk.CENTER)
        self.acc_tree.column("posts", width=int(70 * self.scale), anchor=tk.CENTER)

        acc_scroll = ttk.Scrollbar(left_box, orient=tk.VERTICAL, command=self.acc_tree.yview)
        self.acc_tree.configure(yscrollcommand=acc_scroll.set)
        self.acc_tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        acc_scroll.pack(side=tk.RIGHT, fill=tk.Y, before=self.acc_tree)

        acc_btn_bar = tk.Frame(left_box, bg="#1e1e2e", pady=6)
        acc_btn_bar.pack(side=tk.BOTTOM, fill=tk.X)

        tk.Button(
            acc_btn_bar,
            text="🔄 刷新选中博主",
            command=self._on_refresh_selected_account_clicked,
            font=(self.font_family, 8, "bold"),
            bg="#89b4fa",
            fg="#11111b",
            relief=tk.FLAT,
            padx=8,
            cursor="hand2",
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))

        tk.Button(
            acc_btn_bar,
            text="🗑️ 删除",
            command=self._on_delete_account_clicked,
            font=(self.font_family, 8),
            bg="#f38ba8",
            fg="#11111b",
            relief=tk.FLAT,
            padx=8,
            cursor="hand2",
        ).pack(side=tk.RIGHT)

        # Right Column: Incremental Posts Table with Checkbox
        right_box = tk.LabelFrame(
            paned,
            text=" 🎬 新发布视频待选列表 (可勾选下载) ",
            font=(self.font_family, 9, "bold"),
            fg="#cba6f7",
            bg="#1e1e2e",
            padx=8,
            pady=8,
        )
        paned.add(right_box, width=int(560 * self.scale))

        vid_cols = ("check", "title", "author", "duration", "date", "status")
        self.video_tree = ttk.Treeview(right_box, columns=vid_cols, show="headings", selectmode="browse")
        self.video_tree.heading("check", text="选择")
        self.video_tree.heading("title", text="视频标题")
        self.video_tree.heading("author", text="博主")
        self.video_tree.heading("duration", text="时长")
        self.video_tree.heading("date", text="发布日期")
        self.video_tree.heading("status", text="状态")

        self.video_tree.column("check", width=int(45 * self.scale), anchor=tk.CENTER)
        self.video_tree.column("title", width=int(220 * self.scale), anchor=tk.W)
        self.video_tree.column("author", width=int(90 * self.scale), anchor=tk.W)
        self.video_tree.column("duration", width=int(55 * self.scale), anchor=tk.CENTER)
        self.video_tree.column("date", width=int(75 * self.scale), anchor=tk.CENTER)
        self.video_tree.column("status", width=int(65 * self.scale), anchor=tk.CENTER)

        vid_scroll = ttk.Scrollbar(right_box, orient=tk.VERTICAL, command=self.video_tree.yview)
        self.video_tree.configure(yscrollcommand=vid_scroll.set)
        self.video_tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        vid_scroll.pack(side=tk.RIGHT, fill=tk.Y, before=self.video_tree)

        self.video_tree.bind("<ButtonRelease-1>", self._on_video_tree_click)

        # Selection Toolbar
        sel_bar = tk.Frame(right_box, bg="#1e1e2e", pady=4)
        sel_bar.pack(fill=tk.X)

        tk.Button(
            sel_bar,
            text="☑️ 全选",
            command=self._select_all_videos,
            font=(self.font_family, 8),
            bg="#313244",
            fg="#cdd6f4",
            relief=tk.FLAT,
            padx=8,
            cursor="hand2",
        ).pack(side=tk.LEFT, padx=(0, 4))

        tk.Button(
            sel_bar,
            text="⬜ 取消全选",
            command=self._deselect_all_videos,
            font=(self.font_family, 8),
            bg="#313244",
            fg="#cdd6f4",
            relief=tk.FLAT,
            padx=8,
            cursor="hand2",
        ).pack(side=tk.LEFT, padx=(0, 10))

        self.selected_count_lbl = tk.Label(
            sel_bar,
            text="已选: 0 个视频",
            font=(self.font_family, 8, "bold"),
            fg="#a6adc8",
            bg="#1e1e2e",
        )
        self.selected_count_lbl.pack(side=tk.LEFT)

        # 3. Bottom Action Bar for Tab 2
        tab2_actions = tk.Frame(parent, bg="#11111b")
        tab2_actions.pack(fill=tk.X, pady=(0, 4))

        self.batch_download_btn = tk.Button(
            tab2_actions,
            text="⬇️ 批量下载选中视频",
            command=self._on_batch_download_clicked,
            font=(self.font_family, 10, "bold"),
            bg="#a6e3a1",
            fg="#11111b",
            relief=tk.FLAT,
            pady=8,
            cursor="hand2",
        )
        self.batch_download_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        self.batch_remix_btn = tk.Button(
            tab2_actions,
            text="🚀 一键批量导入 VideoRemix 去重",
            command=self._on_batch_remix_clicked,
            state=tk.DISABLED,
            font=(self.font_family, 10, "bold"),
            bg="#cba6f7",
            fg="#11111b",
            relief=tk.FLAT,
            pady=8,
            cursor="hand2",
        )
        self.batch_remix_btn.pack(side=tk.RIGHT, fill=tk.X, expand=True)

    # ------------------ Tab 1 Action Handlers ------------------

    def _paste_clipboard(self):
        try:
            cb = self.root.clipboard_get()
            if cb:
                self.input_url_var.set(cb.strip())
        except Exception:
            pass

    def _browse_dir(self):
        d = filedialog.askdirectory(title="选择下载保存目录")
        if d:
            self.save_dir_var.set(d)

    def _open_dir(self):
        target = self.save_dir_var.get().strip() or os.getcwd()
        if not os.path.exists(target):
            os.makedirs(target, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(target)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", target])
            else:
                subprocess.Popen(["xdg-open", target])
        except Exception as e:
            messagebox.showwarning("提示", f"打开目录失败: {e}")

    def _on_parse_clicked(self):
        raw_text = self.input_url_var.get().strip()
        if not raw_text:
            messagebox.showinfo("提示", "请先输入或粘贴抖音分享链接！")
            return

        self.parse_btn.config(state=tk.DISABLED, bg="#45475a")
        self.download_btn.config(state=tk.DISABLED)
        self.remix_btn.config(state=tk.DISABLED)
        self.status_var.set("正在解析抖音视频直链，请稍候...")

        threading.Thread(target=self._async_parse, args=(raw_text,), daemon=True).start()

    def _async_parse(self, raw_text: str):
        try:
            item = self.parser.parse_single_video(raw_text)
            self.root.after(0, self._on_parse_success, item)
        except Exception as e:
            self.root.after(0, self._on_parse_failed, str(e))

    def _on_parse_success(self, item: DouyinVideoItem):
        self.current_item = item
        self.parse_btn.config(state=tk.NORMAL, bg="#89b4fa")
        self.download_btn.config(state=tk.NORMAL)

        self.title_lbl.config(text=item.title)
        self.author_lbl.config(text=f"博主: {item.author_nickname}")
        self.time_lbl.config(text=f"发布时间: {item.formatted_date}    时长: {item.formatted_duration}")
        self.url_info_lbl.config(text=f"视频ID: {item.aweme_id}")
        self.status_var.set(f"解析成功！已提取无水印原画直链 ({item.formatted_duration})")

        if item.cover_url:
            threading.Thread(target=self._async_load_cover, args=(item.cover_url,), daemon=True).start()

    def _async_load_cover(self, cover_url: str):
        try:
            req = urllib.request.Request(cover_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                raw_bytes = resp.read()

            cache_dir = Path.home() / ".videoremix" / "cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            temp_jpg = cache_dir / "temp_cover.jpg"
            temp_png = cache_dir / "temp_cover.png"
            temp_jpg.write_bytes(raw_bytes)

            ffmpeg_bin = get_ffmpeg_bin()
            subprocess.run(
                [ffmpeg_bin, "-y", "-i", str(temp_jpg), "-vf", "scale=140:-1", str(temp_png)],
                capture_output=True,
                check=False,
            )

            if temp_png.exists():
                self.root.after(0, self._display_cover_image, str(temp_png))
        except Exception as e:
            logger.debug(f"Failed to load cover image: {e}")

    def _display_cover_image(self, png_path: str):
        try:
            img = tk.PhotoImage(file=png_path)
            self.cover_img_ref = img
            self.cover_box.config(image=img, text="")
        except Exception:
            pass

    def _on_parse_failed(self, error_msg: str):
        self.parse_btn.config(state=tk.NORMAL, bg="#89b4fa")
        self.status_var.set(f"解析失败: {error_msg}")
        messagebox.showerror("解析失败", f"无法解析该链接:\n{error_msg}\n\n提示: 请确保输入的是公开的抖音视频链接或分享口令。")

    def _on_download_clicked(self):
        if not self.current_item:
            return

        self.download_btn.config(state=tk.DISABLED, bg="#45475a")
        self.status_var.set("正在下载无水印原画视频...")
        target_dir = self.save_dir_var.get().strip() or str(self.downloader.default_dir)

        threading.Thread(target=self._async_download, args=(target_dir,), daemon=True).start()

    def _async_download(self, target_dir: str):
        try:
            def _prog(item, pct, done_b, total_b):
                self.root.after(0, self._sync_download_prog, pct, done_b, total_b)

            saved_path = self.downloader.download_video(
                self.current_item,
                output_dir=target_dir,
                progress_cb=_prog,
            )
            self.root.after(0, self._on_download_success, saved_path)
        except Exception as e:
            self.root.after(0, self._on_download_failed, str(e))

    def _sync_download_prog(self, pct: float, done_b: int, total_b: int):
        self.download_progress_var.set(pct)
        mb_done = done_b / (1024 * 1024)
        mb_total = total_b / (1024 * 1024)
        self.status_var.set(f"下载中: {pct:.1f}% ({mb_done:.1f}MB / {mb_total:.1f}MB)")

    def _on_download_success(self, saved_path: str):
        self.download_btn.config(state=tk.NORMAL, bg="#a6e3a1")
        self.remix_btn.config(state=tk.NORMAL)
        self.download_progress_var.set(100.0)
        self.status_var.set(f"下载成功！已保存到: {os.path.basename(saved_path)}")
        messagebox.showinfo("下载完成", f"视频已成功下载！\n\n保存在:\n{saved_path}\n\n您可以点击『一键导入 VideoRemix 去重』直接进行去重处理！")

    def _on_download_failed(self, err_msg: str):
        self.download_btn.config(state=tk.NORMAL, bg="#a6e3a1")
        self.status_var.set(f"下载失败: {err_msg}")
        messagebox.showerror("下载失败", f"下载视频遇到错误:\n{err_msg}")

    def _on_send_to_remix_clicked(self):
        if not self.current_item or not self.current_item.local_path:
            messagebox.showinfo("提示", "请先下载视频！")
            return

        video_path = self.current_item.local_path
        if self.on_import_callback:
            try:
                self.on_import_callback(video_path)
                self.status_var.set("已成功将视频添加到 VideoRemix 任务列表！")
                messagebox.showinfo(
                    "导入成功",
                    f"视频已成功添加至主界面去重列表：\n{os.path.basename(video_path)}\n\n您可以在主界面设置参数并开始去重。"
                )
                return
            except Exception as e:
                messagebox.showerror("导入失败", f"添加到主界面失败: {e}")
                return

        try:
            from videoremix.ui.app import VideoRemixApp
            subprocess.Popen([sys.executable, "-m", "videoremix.ui.app", video_path])
            self.status_var.set("已调起 VideoRemix 去重流水线！")
        except Exception as e:
            messagebox.showwarning("提示", f"启动 VideoRemix 失败: {e}")

    # ------------------ Tab 2 Benchmark Handlers ------------------

    def _reload_accounts_table(self):
        """Refresh the benchmark accounts treeview from disk."""
        if not hasattr(self, "acc_tree"):
            return
        for row in self.acc_tree.get_children():
            self.acc_tree.delete(row)
        self._account_row_map.clear()

        accounts = self.account_mgr.list_accounts()
        for acc in accounts:
            item_id = self.acc_tree.insert(
                "",
                tk.END,
                values=(acc.nickname, acc.category, acc.total_posts),
            )
            self._account_row_map[item_id] = acc

    def _on_add_account_clicked(self):
        url = self.acc_url_var.get().strip()
        cat = self.acc_category_var.get().strip() or "电商带货"
        if not url:
            messagebox.showinfo("提示", "请先输入对标博主的主页链接或分享短链！")
            return

        self.add_acc_btn.config(state=tk.DISABLED)
        self.status_var.set("正在获取对标博主主页信息及作品列表...")
        threading.Thread(target=self._async_add_account, args=(url, cat), daemon=True).start()

    def _async_add_account(self, url: str, cat: str):
        try:
            account, initial_posts = self.account_mgr.add_account(url, category=cat)
            self.root.after(0, self._on_add_account_success, account, initial_posts)
        except Exception as e:
            self.root.after(0, self._on_add_account_failed, str(e))

    def _on_add_account_success(self, account: BenchmarkAccount, initial_posts: List[DouyinVideoItem]):
        self.add_acc_btn.config(state=tk.NORMAL)
        self.acc_url_var.set("")
        self._reload_accounts_table()
        self.status_var.set(f"成功添加对标博主: {account.nickname} (获取到 {len(initial_posts)} 个近期视频)")
        self._set_video_items(initial_posts)
        messagebox.showinfo(
            "添加成功",
            f"已成功添加并保存对标博主：\n『{account.nickname}』({account.category})\n\n已为您抓取该博主最新的 {len(initial_posts)} 条作品，可在右侧勾选下载。"
        )

    def _on_add_account_failed(self, err_msg: str):
        self.add_acc_btn.config(state=tk.NORMAL)
        self.status_var.set(f"添加对标博主失败: {err_msg}")
        messagebox.showerror("添加博主失败", f"无法添加该博主:\n{err_msg}\n\n提示: 请确保输入的是公开的博主主页链接。")

    def _on_refresh_selected_account_clicked(self):
        sel = self.acc_tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请在左侧列表中先点击选择一个对标博主！")
            return

        item_id = sel[0]
        acc = self._account_row_map.get(item_id)
        if not acc:
            return

        self.status_var.set(f"正在检测博主 [{acc.nickname}] 是否有新作品发布...")
        threading.Thread(target=self._async_refresh_account, args=(acc.sec_user_id,), daemon=True).start()

    def _async_refresh_account(self, sec_user_id: str):
        try:
            acc, new_posts = self.account_mgr.refresh_account(sec_user_id)
            self.root.after(0, self._on_refresh_account_success, acc, new_posts)
        except Exception as e:
            self.root.after(0, self._on_refresh_account_failed, str(e))

    def _on_refresh_account_success(self, acc: BenchmarkAccount, new_posts: List[DouyinVideoItem]):
        self._reload_accounts_table()
        if new_posts:
            self._set_video_items(new_posts)
            self.status_var.set(f"博主 [{acc.nickname}] 发现 {len(new_posts)} 个新发布的增量作品！")
            messagebox.showinfo("发现新作品", f"博主『{acc.nickname}』有 {len(new_posts)} 个新发布的视频！\n已自动列在右侧并全部勾选，可一键批量下载。")
        else:
            self.status_var.set(f"博主 [{acc.nickname}] 暂无新视频发布 (已是最新)")
            messagebox.showinfo("暂无更新", f"博主『{acc.nickname}』自上次抓取后暂未发布新作品，已保持最新状态。")

    def _on_refresh_account_failed(self, err: str):
        self.status_var.set(f"刷新博主失败: {err}")
        messagebox.showerror("刷新失败", f"检测博主更新失败:\n{err}")

    def _on_refresh_all_accounts_clicked(self):
        accounts = self.account_mgr.list_accounts()
        if not accounts:
            messagebox.showinfo("提示", "当前尚未添加任何对标博主，请先添加！")
            return

        self.refresh_all_btn.config(state=tk.DISABLED)
        self.status_var.set("正在一键刷新所有对标博主，比对增量作品...")
        threading.Thread(target=self._async_refresh_all, daemon=True).start()

    def _async_refresh_all(self):
        try:
            results = self.account_mgr.refresh_all()
            all_new_posts = []
            for sec_uid, (acc, posts) in results.items():
                all_new_posts.extend(posts)
            self.root.after(0, self._on_refresh_all_success, all_new_posts)
        except Exception as e:
            self.root.after(0, self._on_refresh_all_failed, str(e))

    def _on_refresh_all_success(self, all_new_posts: List[DouyinVideoItem]):
        self.refresh_all_btn.config(state=tk.NORMAL)
        self._reload_accounts_table()
        if all_new_posts:
            self._set_video_items(all_new_posts)
            self.status_var.set(f"全部刷新完成！共发现 {len(all_new_posts)} 条最新发布的视频！")
            messagebox.showinfo("增量刷新完成", f"所有对标账号已比对完毕！\n\n共检测到 {len(all_new_posts)} 条新视频，已为您自动勾选。")
        else:
            self.status_var.set("全部对标博主已刷新，暂无新视频。")
            messagebox.showinfo("全部最新", "所有对标博主均无新发布的增量视频，已保持最新！")

    def _on_refresh_all_failed(self, err: str):
        self.refresh_all_btn.config(state=tk.NORMAL)
        self.status_var.set(f"批量刷新失败: {err}")
        messagebox.showerror("刷新失败", f"批量刷新遇到错误:\n{err}")

    def _on_delete_account_clicked(self):
        sel = self.acc_tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先在左侧选择要删除的博主！")
            return

        item_id = sel[0]
        acc = self._account_row_map.get(item_id)
        if not acc:
            return

        if messagebox.askyesno("确认删除", f"确定要移除对标博主『{acc.nickname}』吗？"):
            self.account_mgr.remove_account(acc.sec_user_id)
            self._reload_accounts_table()
            self.status_var.set(f"已移除对标博主: {acc.nickname}")

    # ------------------ Video Table Selection & Batching ------------------

    def _set_video_items(self, items: List[DouyinVideoItem]):
        """Populate the incremental video items treeview."""
        self.monitored_videos = items
        self.selected_aweme_ids = {it.aweme_id for it in items}  # Default all checked
        for r in self.video_tree.get_children():
            self.video_tree.delete(r)
        self._video_row_map.clear()

        for it in items:
            check_mark = "☑" if it.aweme_id in self.selected_aweme_ids else "☐"
            stat = "已下载" if it.downloaded else "待下载"
            row_id = self.video_tree.insert(
                "",
                tk.END,
                values=(check_mark, it.title, it.author_nickname, it.formatted_duration, it.formatted_date, stat),
            )
            self._video_row_map[row_id] = it

        self._update_selected_count()

    def _on_video_tree_click(self, event):
        item_id = self.video_tree.identify_row(event.y)
        if not item_id:
            return
        video_item = self._video_row_map.get(item_id)
        if not video_item:
            return

        if video_item.aweme_id in self.selected_aweme_ids:
            self.selected_aweme_ids.remove(video_item.aweme_id)
            check_str = "☐"
        else:
            self.selected_aweme_ids.add(video_item.aweme_id)
            check_str = "☑"

        cur_vals = list(self.video_tree.item(item_id, "values"))
        cur_vals[0] = check_str
        self.video_tree.item(item_id, values=cur_vals)
        self._update_selected_count()

    def _select_all_videos(self):
        self.selected_aweme_ids = {it.aweme_id for it in self.monitored_videos}
        for row_id, it in self._video_row_map.items():
            cur_vals = list(self.video_tree.item(row_id, "values"))
            cur_vals[0] = "☑"
            self.video_tree.item(row_id, values=cur_vals)
        self._update_selected_count()

    def _deselect_all_videos(self):
        self.selected_aweme_ids.clear()
        for row_id, it in self._video_row_map.items():
            cur_vals = list(self.video_tree.item(row_id, "values"))
            cur_vals[0] = "☐"
            self.video_tree.item(row_id, values=cur_vals)
        self._update_selected_count()

    def _update_selected_count(self):
        n = len(self.selected_aweme_ids)
        self.selected_count_lbl.config(text=f"已选: {n} 个视频")

    def _on_batch_download_clicked(self):
        to_download = [it for it in self.monitored_videos if it.aweme_id in self.selected_aweme_ids]
        if not to_download:
            messagebox.showinfo("提示", "请先在列表中勾选要下载的视频！")
            return

        self.batch_download_btn.config(state=tk.DISABLED, bg="#45475a")
        self.status_var.set(f"准备下载选中的 {len(to_download)} 个无水印视频...")
        target_dir = self.save_dir_var.get().strip() or str(self.downloader.default_dir)

        threading.Thread(target=self._async_batch_download, args=(to_download, target_dir), daemon=True).start()

    def _async_batch_download(self, items: List[DouyinVideoItem], target_dir: str):
        total = len(items)
        done_count = 0

        def _item_done(item: DouyinVideoItem, path: str):
            nonlocal done_count
            done_count += 1
            self.root.after(0, self._on_batch_item_completed, item, done_count, total)

        try:
            results = self.downloader.download_batch(
                items,
                output_dir=target_dir,
                max_workers=3,
                item_completed_cb=_item_done,
            )
            self.root.after(0, self._on_batch_all_completed, results)
        except Exception as e:
            self.root.after(0, self._on_batch_failed, str(e))

    def _on_batch_item_completed(self, item: DouyinVideoItem, current: int, total: int):
        self.status_var.set(f"批量下载中: 已完成 {current}/{total} 个 - {item.title[:20]}")
        for row_id, it in self._video_row_map.items():
            if it.aweme_id == item.aweme_id:
                vals = list(self.video_tree.item(row_id, "values"))
                vals[5] = "已下载"
                self.video_tree.item(row_id, values=vals)
                break

    def _on_batch_all_completed(self, results: List[str]):
        self.batch_download_btn.config(state=tk.NORMAL, bg="#a6e3a1")
        self.batch_remix_btn.config(state=tk.NORMAL)
        self.status_var.set(f"批量下载完成！共成功下载 {len(results)} 个原画视频！")
        messagebox.showinfo(
            "批量下载成功",
            f"恭喜！选中的 {len(results)} 个无水印原画视频已全部下载完成！\n\n可直接点击『一键批量导入 VideoRemix 去重』启动去重流水线。"
        )

    def _on_batch_failed(self, err_msg: str):
        self.batch_download_btn.config(state=tk.NORMAL, bg="#a6e3a1")
        self.status_var.set(f"批量下载遇到错误: {err_msg}")
        messagebox.showerror("下载错误", f"批量下载出现异常:\n{err_msg}")

    def _on_batch_remix_clicked(self):
        downloaded = [it.local_path for it in self.monitored_videos if it.downloaded and it.local_path]
        if not downloaded:
            messagebox.showinfo("提示", "当前尚无已下载完成的视频！")
            return

        if self.on_import_callback:
            try:
                for p in downloaded:
                    self.on_import_callback(p)
                self.status_var.set(f"已成功将 {len(downloaded)} 个视频注入 VideoRemix 去重队列！")
                messagebox.showinfo(
                    "导入成功",
                    f"已将 {len(downloaded)} 个无水印视频成功添加到 VideoRemix 主界面任务列表！\n可在主界面查看并直接点击开始去重。"
                )
                return
            except Exception as e:
                messagebox.showerror("导入失败", f"导入主界面失败: {e}")
                return

        messagebox.showinfo("完成", f"视频已保存在本地，可直接在主界面批量导入！")


def main():
    setup_windows_dpi_awareness()
    root = tk.Tk()
    app = DouyinParserApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
