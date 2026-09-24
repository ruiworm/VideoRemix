"""Benchmark account persistence and incremental video diff engine."""

import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from videoremix.ingest.douyin import DouyinParser, DouyinScraperError
from videoremix.ingest.models import BenchmarkAccount, DouyinVideoItem

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_DIR = Path.home() / ".videoremix"
DEFAULT_ACCOUNTS_FILE = DEFAULT_CONFIG_DIR / "benchmark_accounts.json"
DEFAULT_INGEST_CONFIG_FILE = DEFAULT_CONFIG_DIR / "ingest_config.json"


class BenchmarkAccountManager:
    """Manages long-term monitored creator accounts, persistent storage, and incremental post diffing."""

    def __init__(
        self,
        accounts_file: Optional[Path] = None,
        config_file: Optional[Path] = None,
        parser: Optional[DouyinParser] = None,
    ):
        self.accounts_file = Path(accounts_file) if accounts_file else DEFAULT_ACCOUNTS_FILE
        self.config_file = Path(config_file) if config_file else DEFAULT_INGEST_CONFIG_FILE
        self._lock = threading.RLock()

        self.accounts: Dict[str, BenchmarkAccount] = {}  # sec_user_id -> BenchmarkAccount
        self.config: Dict[str, Any] = {}
        self.parser = parser or DouyinParser()

        self._ensure_storage()
        self.load()

    def _ensure_storage(self):
        """Create parent directory if not present."""
        self.accounts_file.parent.mkdir(parents=True, exist_ok=True)

    # ------------------ Persistence ------------------

    def load(self):
        """Load benchmark accounts and ingest configuration from disk."""
        with self._lock:
            # 1. Load config (e.g. cookie)
            if self.config_file.exists():
                try:
                    with open(self.config_file, "r", encoding="utf-8") as f:
                        self.config = json.load(f)
                    user_cookie = self.config.get("cookie")
                    if user_cookie:
                        self.parser.cached_cookie = user_cookie
                except Exception as e:
                    logger.warning(f"Error loading ingest config: {e}")

            # 2. Load accounts
            if self.accounts_file.exists():
                try:
                    with open(self.accounts_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    acc_list = data.get("accounts", [])
                    self.accounts = {
                        item["sec_user_id"]: BenchmarkAccount.from_dict(item)
                        for item in acc_list
                        if "sec_user_id" in item
                    }
                except Exception as e:
                    logger.warning(f"Error loading benchmark accounts: {e}")
                    self.accounts = {}

    def save(self):
        """Save benchmark accounts and config atomically to disk."""
        with self._lock:
            self._ensure_storage()
            # Save accounts
            acc_list = [acc.to_dict() for acc in self.accounts.values()]
            tmp_accounts = self.accounts_file.with_suffix(".tmp")
            with open(tmp_accounts, "w", encoding="utf-8") as f:
                json.dump({"accounts": acc_list, "updated_at": time.time()}, f, ensure_ascii=False, indent=2)
            tmp_accounts.replace(self.accounts_file)

            # Save config
            tmp_config = self.config_file.with_suffix(".tmp")
            with open(tmp_config, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            tmp_config.replace(self.config_file)

    # ------------------ Config Management ------------------

    def get_cookie(self) -> str:
        """Get currently configured Douyin cookie."""
        return self.config.get("cookie", "")

    def set_cookie(self, cookie: str):
        """Update Douyin cookie and persist."""
        with self._lock:
            self.config["cookie"] = cookie.strip()
            self.parser.cached_cookie = cookie.strip()
            self.save()

    # ------------------ Account Management ------------------

    def list_accounts(self) -> List[BenchmarkAccount]:
        """Return all saved benchmark accounts."""
        with self._lock:
            return list(self.accounts.values())

    def get_account(self, sec_user_id: str) -> Optional[BenchmarkAccount]:
        """Get an account by sec_user_id."""
        with self._lock:
            return self.accounts.get(sec_user_id)

    def add_account(
        self,
        url_or_sec_uid: str,
        category: str = "默认",
        note: str = "",
    ) -> Tuple[BenchmarkAccount, List[DouyinVideoItem]]:
        """Add a new benchmark creator account by URL or sec_user_id.

        Fetches initial profile and initial posts list, then saves to storage.
        """
        account, initial_posts = self.parser.parse_user_profile(
            url_or_sec_uid,
            count=15,
            user_cookie=self.get_cookie(),
        )

        account.category = category or "默认"
        account.note = note
        if initial_posts:
            account.last_aweme_id = initial_posts[0].aweme_id

        with self._lock:
            self.accounts[account.sec_user_id] = account
            self.save()

        return account, initial_posts

    def remove_account(self, sec_user_id: str) -> bool:
        """Remove a benchmark creator account."""
        with self._lock:
            if sec_user_id in self.accounts:
                del self.accounts[sec_user_id]
                self.save()
                return True
            return False

    def update_account(
        self,
        sec_user_id: str,
        nickname: Optional[str] = None,
        category: Optional[str] = None,
        note: Optional[str] = None,
    ) -> Optional[BenchmarkAccount]:
        """Update metadata notes or category for an account."""
        with self._lock:
            acc = self.accounts.get(sec_user_id)
            if not acc:
                return None
            if nickname:
                acc.nickname = nickname
            if category:
                acc.category = category
            if note is not None:
                acc.note = note
            self.save()
            return acc

    # ------------------ Incremental Diff Engine ------------------

    def refresh_account(
        self,
        sec_user_id: str,
        count: int = 20,
    ) -> Tuple[BenchmarkAccount, List[DouyinVideoItem]]:
        """Query creator's latest posts and extract incremental new videos since last check.

        Returns (updated_account, new_videos_list).
        """
        with self._lock:
            account = self.accounts.get(sec_user_id)
            if not account:
                raise DouyinScraperError(f"未找到指定的对标账号: {sec_user_id}")

        # Fetch current latest posts
        fresh_acc, fresh_posts = self.parser.parse_user_profile(
            account.homepage_url or sec_user_id,
            count=count,
            user_cookie=self.get_cookie(),
        )

        with self._lock:
            # Update basic info if available
            if fresh_acc.nickname and fresh_acc.nickname != "未知博主":
                account.nickname = fresh_acc.nickname
            if fresh_acc.avatar_url:
                account.avatar_url = fresh_acc.avatar_url
            if fresh_acc.total_posts:
                account.total_posts = fresh_acc.total_posts

            last_id = account.last_aweme_id
            incremental_new: List[DouyinVideoItem] = []

            if not last_id:
                # First time: all fetched posts are considered candidates
                incremental_new = fresh_posts
            else:
                for post in fresh_posts:
                    if post.aweme_id == last_id:
                        # Reached the boundary of previously seen video
                        break
                    incremental_new.append(post)

            # Advance the benchmark pointer to the latest video
            if fresh_posts:
                account.last_aweme_id = fresh_posts[0].aweme_id

            account.last_checked_time = time.time()
            self.save()

        return account, incremental_new

    def refresh_all(self) -> Dict[str, List[DouyinVideoItem]]:
        """Refresh all saved benchmark accounts and return a mapping of new videos per account."""
        results: Dict[str, List[DouyinVideoItem]] = {}
        with self._lock:
            uids = list(self.accounts.keys())

        for uid in uids:
            try:
                _, new_videos = self.refresh_account(uid)
                results[uid] = new_videos
            except Exception as e:
                logger.warning(f"Error refreshing account {uid}: {e}")
                results[uid] = []

        return results
