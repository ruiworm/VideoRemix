"""Video file downloader with chunk streaming and progress callbacks."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import os
from pathlib import Path
import re
from typing import Callable, List, Optional
import urllib.request

from videoremix.ingest.douyin import DEFAULT_UA
from videoremix.ingest.models import DouyinVideoItem

logger = logging.getLogger(__name__)

DownloadProgressCallback = Callable[[DouyinVideoItem, float, int, int], None]  # item, percent, downloaded_bytes, total_bytes


class VideoDownloader:
    """Handles reliable, chunked downloading of watermark-free videos with progress reporting."""

    def __init__(self, default_dir: Optional[str] = None):
        if default_dir:
            self.default_dir = Path(default_dir)
        else:
            self.default_dir = Path.home() / "Downloads" / "VideoRemix_Ingest"
        self.default_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def sanitize_filename(name: str, max_length: int = 60) -> str:
        """Sanitize title into safe filename characters for Windows / Linux / macOS."""
        cleaned = re.sub(r'[\\/*?:"<>|#\r\n\t]+', '_', name).strip()
        cleaned = re.sub(r'\s+', ' ', cleaned)
        if len(cleaned) > max_length:
            cleaned = cleaned[:max_length].rstrip()
        return cleaned or "video"

    def download_video(
        self,
        item: DouyinVideoItem,
        output_dir: Optional[str] = None,
        progress_cb: Optional[DownloadProgressCallback] = None,
    ) -> str:
        """Download a single video item to the target directory."""
        if not item.play_url:
            raise ValueError(f"视频无有效播放/下载直链: {item.aweme_id}")

        dest_dir = Path(output_dir) if output_dir else self.default_dir
        dest_dir.mkdir(parents=True, exist_ok=True)

        safe_title = self.sanitize_filename(item.title)
        safe_author = self.sanitize_filename(item.author_nickname or "douyin", max_length=20)
        filename = f"{safe_author}_{item.aweme_id}_{safe_title}.mp4"
        target_path = dest_dir / filename

        headers = {
            "User-Agent": DEFAULT_UA,
            "Referer": "https://www.douyin.com/",
        }

        req = urllib.request.Request(item.play_url, headers=headers)
        temp_path = target_path.with_suffix(".tmp")

        try:
            with urllib.request.urlopen(req, timeout=30) as resp, open(temp_path, "wb") as f_out:
                total_bytes = int(resp.headers.get("Content-Length", 0))
                downloaded_bytes = 0
                chunk_size = 64 * 1024  # 64 KB

                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f_out.write(chunk)
                    downloaded_bytes += len(chunk)
                    if progress_cb:
                        pct = (downloaded_bytes / total_bytes * 100.0) if total_bytes > 0 else 0.0
                        progress_cb(item, pct, downloaded_bytes, total_bytes)

            temp_path.replace(target_path)
            item.downloaded = True
            item.local_path = str(target_path)
            return str(target_path)

        except Exception as e:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            logger.error(f"Download failed for {item.aweme_id}: {e}")
            raise

    def download_batch(
        self,
        items: List[DouyinVideoItem],
        output_dir: Optional[str] = None,
        max_workers: int = 3,
        item_completed_cb: Optional[Callable[[DouyinVideoItem, str], None]] = None,
    ) -> List[str]:
        """Download multiple video items concurrently."""
        dest_dir = output_dir or str(self.default_dir)
        results: List[str] = []

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_to_item = {
                pool.submit(self.download_video, item, dest_dir): item
                for item in items
            }
            for fut in as_completed(future_to_item):
                item = future_to_item[fut]
                try:
                    path = fut.result()
                    results.append(path)
                    if item_completed_cb:
                        item_completed_cb(item, path)
                except Exception as e:
                    logger.warning(f"Batch item failed {item.aweme_id}: {e}")

        return results
