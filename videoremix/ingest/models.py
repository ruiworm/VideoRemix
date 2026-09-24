"""Data models for benchmark accounts and media ingestion."""

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
import os
import time
from typing import Any, Dict, List, Optional


class DouyinContentType(str, Enum):
    VIDEO = "video"
    IMAGE_ALBUM = "image_album"
    UNKNOWN = "unknown"


@dataclass
class DouyinVideoItem:
    """Represents a single parsed video/post item from Douyin."""
    aweme_id: str
    title: str
    cover_url: str
    play_url: str
    duration: float = 0.0  # seconds
    create_time: int = 0   # unix timestamp
    author_nickname: str = ""
    author_avatar: str = ""
    author_sec_uid: str = ""
    content_type: DouyinContentType = DouyinContentType.VIDEO
    downloaded: bool = False
    local_path: Optional[str] = None

    @property
    def formatted_duration(self) -> str:
        """Format duration into MM:SS."""
        d = int(self.duration)
        mins = d // 60
        secs = d % 60
        return f"{mins:02d}:{secs:02d}"

    @property
    def formatted_date(self) -> str:
        """Format create timestamp into YYYY-MM-DD HH:MM."""
        if not self.create_time:
            return "-"
        try:
            return datetime.fromtimestamp(self.create_time).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return str(self.create_time)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["content_type"] = self.content_type.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DouyinVideoItem":
        ctype = DouyinContentType(data.get("content_type", DouyinContentType.VIDEO.value))
        return cls(
            aweme_id=str(data.get("aweme_id", "")),
            title=data.get("title", ""),
            cover_url=data.get("cover_url", ""),
            play_url=data.get("play_url", ""),
            duration=float(data.get("duration", 0.0)),
            create_time=int(data.get("create_time", 0)),
            author_nickname=data.get("author_nickname", ""),
            author_avatar=data.get("author_avatar", ""),
            author_sec_uid=data.get("author_sec_uid", ""),
            content_type=ctype,
            downloaded=bool(data.get("downloaded", False)),
            local_path=data.get("local_path"),
        )


@dataclass
class BenchmarkAccount:
    """Represents a long-term monitored benchmark creator account."""
    sec_user_id: str
    nickname: str
    avatar_url: str = ""
    homepage_url: str = ""
    category: str = "默认"
    last_aweme_id: str = ""
    last_checked_time: float = field(default_factory=time.time)
    total_posts: int = 0
    note: str = ""

    @property
    def formatted_last_checked(self) -> str:
        if not self.last_checked_time:
            return "从未更新"
        try:
            return datetime.fromtimestamp(self.last_checked_time).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return "-"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BenchmarkAccount":
        return cls(
            sec_user_id=data.get("sec_user_id", ""),
            nickname=data.get("nickname", "未知博主"),
            avatar_url=data.get("avatar_url", ""),
            homepage_url=data.get("homepage_url", ""),
            category=data.get("category", "默认"),
            last_aweme_id=data.get("last_aweme_id", ""),
            last_checked_time=float(data.get("last_checked_time", 0.0)),
            total_posts=int(data.get("total_posts", 0)),
            note=data.get("note", ""),
        )
