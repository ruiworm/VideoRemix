"""Modern dedicated GUI for Douyin watermark-free video parsing and downloading."""

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
from typing import Any, Callable, Optional
import urllib.request

from videoremix.core.probe import get_ffmpeg_bin
from videoremix.ingest.douyin import DouyinParser, DouyinScraperError
from videoremix.ingest.downloader import VideoDownloader
from videoremix.ingest.models import DouyinVideoItem

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
    """Dedicated standalone desktop tool for Douyin watermark-free parsing and downloading."""

    def __init__(self, root: Any, on_import_callback: Optional[Callable[[str], None]] = None):
        self.root = root
        self.on_import_callback = on_import_callback
        self.root.title("抖音无水印视频快速解析器 - VideoRemix Pro Suite")

        # DPI Calculation
        try:
            dpi = float(self.root.winfo_fpixels('1i'))
            self.scale = max(1.0, dpi / 96.0)
        except Exception:
            self.scale = 1.0

        self.font_family = "Microsoft YaHei UI" if (sys.platform == "win32" or os.name == "nt") else "Segoe UI"

        w = int(720 * self.scale)
        h = int(620 * self.scale)
        self.root.geometry(f"{w}x{h}")
        self.root.minsize(int(600 * self.scale), int(520 * self.scale))
        self.root.configure(bg="#11111b")

        # Core Engines
        self.parser = DouyinParser()
        self.downloader = VideoDownloader()

        # State Variables
        self.input_url_var = tk.StringVar()
        self.status_var = tk.StringVar(value="就绪: 请粘贴抖音分享链接或短链 (如 v.douyin.com)")
        self.save_dir_var = tk.StringVar(value=str(self.downloader.default_dir))
        self.current_item: Optional[DouyinVideoItem] = None
        self.download_progress_var = tk.DoubleVar(value=0.0)
        self.cover_img_ref = None  # Prevent GC for PhotoImage

        self._build_ui()

    def _build_ui(self):
        # 1. Header
        header = tk.Frame(self.root, bg="#1e1e2e", padx=20, pady=16)
        header.pack(fill=tk.X)

        title_lbl = tk.Label(
            header,
            text="⚡ 抖音无水印原画解析与下载",
            font=(self.font_family, 14, "bold"),
            fg="#ffffff",
            bg="#1e1e2e",
        )
        title_lbl.pack(side=tk.LEFT)

        sub_badge = tk.Label(
            header,
            text="无水印原画直链 • 0秒去重流转",
            font=(self.font_family, 9),
            fg="#a6e3a1",
            bg="#252538",
            padx=8,
            pady=3,
        )
        sub_badge.pack(side=tk.RIGHT)

        # Main Container
        main_box = tk.Frame(self.root, bg="#11111b", padx=20, pady=16)
        main_box.pack(fill=tk.BOTH, expand=True)

        # 2. Input Box Card
        input_card = tk.LabelFrame(
            main_box,
            text=" 🔗 输入视频分享链接或口令 ",
            font=(self.font_family, 9, "bold"),
            fg="#89b4fa",
            bg="#1e1e2e",
            padx=14,
            pady=12,
        )
        input_card.pack(fill=tk.X, pady=(0, 14))

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

        # 3. Result Preview Card
        self.result_card = tk.LabelFrame(
            main_box,
            text=" 🎬 解析结果与视频详情 ",
            font=(self.font_family, 9, "bold"),
            fg="#cba6f7",
            bg="#1e1e2e",
            padx=14,
            pady=12,
        )
        self.result_card.pack(fill=tk.BOTH, expand=True, pady=(0, 14))

        # Result inner layout
        res_grid = tk.Frame(self.result_card, bg="#1e1e2e")
        res_grid.pack(fill=tk.BOTH, expand=True)

        # Left Cover Image Box
        self.cover_box = tk.Label(
            res_grid,
            text="封面预览\n(解析后显示)",
            font=(self.font_family, 9),
            fg="#6c7086",
            bg="#252538",
            width=18,
            height=9,
            relief=tk.FLAT,
        )
        self.cover_box.pack(side=tk.LEFT, padx=(0, 14), fill=tk.Y)

        # Right Metadata
        meta_box = tk.Frame(res_grid, bg="#1e1e2e")
        meta_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.title_lbl = tk.Label(
            meta_box,
            text="等待解析输入...",
            font=(self.font_family, 10, "bold"),
            fg="#cdd6f4",
            bg="#1e1e2e",
            justify=tk.LEFT,
            wraplength=int(380 * self.scale),
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

        # Progress bar
        self.prog_bar = ttk.Progressbar(
            meta_box,
            variable=self.download_progress_var,
            maximum=100.0,
        )
        self.prog_bar.pack(fill=tk.X, pady=(6, 4))

        # Download path setting row
        path_row = tk.Frame(main_box, bg="#11111b")
        path_row.pack(fill=tk.X, pady=(0, 12))

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

        # 4. Action Buttons
        btn_bar = tk.Frame(main_box, bg="#11111b")
        btn_bar.pack(fill=tk.X)

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

    # ------------------ Action Handlers ------------------

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

        # Update metadata display
        self.title_lbl.config(text=item.title)
        self.author_lbl.config(text=f"博主: {item.author_nickname}")
        self.time_lbl.config(text=f"发布时间: {item.formatted_date}    时长: {item.formatted_duration}")
        self.url_info_lbl.config(text=f"视频ID: {item.aweme_id}")
        self.status_var.set(f"解析成功！已提取无水印原画直链 ({item.formatted_duration})")

        # Asynchronously fetch and render thumbnail
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

            # Convert to PNG using bundled ffmpeg for Tkinter PhotoImage compatibility
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

    # ------------------ Download Handlers ------------------

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

        # Standalone mode: launch VideoRemix main GUI or process
        try:
            from videoremix.ui.app import VideoRemixApp
            subprocess.Popen([sys.executable, "-m", "videoremix.ui.app", video_path])
            self.status_var.set("已调起 VideoRemix 去重流水线！")
        except Exception as e:
            messagebox.showwarning("提示", f"启动 VideoRemix 失败: {e}")


def main():
    setup_windows_dpi_awareness()
    root = tk.Tk()
    app = DouyinParserApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
