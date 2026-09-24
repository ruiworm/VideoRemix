"""Douyin media parser and signature resolver."""

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple
import urllib.parse
import urllib.request

from videoremix.ingest.models import BenchmarkAccount, DouyinContentType, DouyinVideoItem

logger = logging.getLogger(__name__)

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
)


class DouyinScraperError(Exception):
    """Raised when parsing or fetching Douyin media fails."""
    pass


class DouyinParser:
    """Core parser for Douyin single videos, shortlinks, and benchmark creator profiles."""

    def __init__(self, default_cookie: Optional[str] = None):
        self.cached_cookie: Optional[str] = default_cookie
        self._cached_ttwid: Optional[str] = None
        self._ttwid_expiry: float = 0.0

    # ------------------ Link Extraction & Redirection ------------------

    @staticmethod
    def extract_url_from_text(text: str) -> Optional[str]:
        """Extract the first valid http/https URL from messy clipboard or share text."""
        if not text:
            return None
        text = text.strip()
        # Direct URL match
        match = re.search(r"https?://[a-zA-Z0-9\.\-_/]+[^\s\u4e00-\u9fa5]*", text)
        if match:
            url = match.group(0).rstrip("，。！？,!?")
            return url
        return None

    def resolve_url(self, raw_input: str) -> Dict[str, Any]:
        """Expand shortlink if needed and detect whether it is a video, photo album, or user profile."""
        url = self.extract_url_from_text(raw_input) or raw_input.strip()
        if not url.startswith("http"):
            raise DouyinScraperError(f"无效的链接格式: {raw_input}")

        # Follow redirects for shortlink like v.douyin.com
        final_url = self._follow_redirects(url)

        parsed = urllib.parse.urlparse(final_url)
        path = parsed.path

        # 1. Video match
        video_match = re.search(r"/(?:video|note)/(\d+)", path)
        if video_match:
            return {
                "type": "video",
                "aweme_id": video_match.group(1),
                "original_url": url,
                "resolved_url": final_url,
            }

        # 2. Check query param sec_uid / sec_user_id first
        qs = urllib.parse.parse_qs(parsed.query)
        if "sec_uid" in qs:
            return {
                "type": "user",
                "sec_user_id": qs["sec_uid"][0],
                "original_url": url,
                "resolved_url": final_url,
            }
        if "sec_user_id" in qs:
            return {
                "type": "user",
                "sec_user_id": qs["sec_user_id"][0],
                "original_url": url,
                "resolved_url": final_url,
            }

        # 3. User profile match in path
        user_match = re.search(r"/user/([a-zA-Z0-9_\-]+)", path)
        if user_match:
            return {
                "type": "user",
                "sec_user_id": user_match.group(1),
                "original_url": url,
                "resolved_url": final_url,
            }

        raise DouyinScraperError(f"未能从链接中识别出视频ID或博主主页ID: {final_url}")

    def _follow_redirects(self, url: str) -> str:
        """Resolve shortlink redirects using HTTP HEAD/GET."""
        if "v.douyin.com" not in url:
            return url
        headers = {"User-Agent": MOBILE_UA}
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as resp:
                return resp.geturl()
        except Exception as e:
            logger.warning(f"Error following redirect for {url}: {e}")
            return url

    # ------------------ Dynamic TTWID Token ------------------

    def get_dynamic_ttwid(self) -> str:
        """Dynamically obtain valid guest device ttwid from ByteDance union registration endpoint."""
        now = time.time()
        if self._cached_ttwid and now < self._ttwid_expiry:
            return self._cached_ttwid

        reg_url = "https://ttwid.bytedance.com/ttwid/union/register/"
        data = json.dumps({
            "region": "cn",
            "aid": 1768,
            "needFid": False,
            "service": "www.ixigua.com",
            "migrate_info": {"ticket": "", "source": "node"},
            "cbUrlProtocol": "https",
            "union": True
        }).encode("utf-8")

        req = urllib.request.Request(
            reg_url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": DEFAULT_UA,
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                sc = resp.headers.get("Set-Cookie", "")
                match = re.search(r"ttwid=([^;]+)", sc)
                if match:
                    self._cached_ttwid = match.group(1)
                    self._ttwid_expiry = now + 86400  # valid for 24h
                    return self._cached_ttwid
        except Exception as e:
            logger.warning(f"Failed to dynamically fetch ttwid: {e}")

        return ""

    def _build_headers(self, user_cookie: Optional[str] = None) -> Dict[str, str]:
        """Build request headers with active or dynamic cookie."""
        cookie_parts = []
        custom_cookie = user_cookie or self.cached_cookie
        if custom_cookie:
            cookie_parts.append(custom_cookie.strip())

        # If custom cookie lacks ttwid, inject dynamic ttwid
        if not custom_cookie or "ttwid=" not in custom_cookie:
            ttwid = self.get_dynamic_ttwid()
            if ttwid:
                cookie_parts.append(f"ttwid={ttwid}")

        headers = {
            "User-Agent": DEFAULT_UA,
            "Referer": "https://www.douyin.com/",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        if cookie_parts:
            headers["Cookie"] = "; ".join(cookie_parts)

        return headers

    # ------------------ Single Video Parsing ------------------

    def parse_single_video(
        self,
        video_input: str,
        user_cookie: Optional[str] = None,
    ) -> DouyinVideoItem:
        """Parse a single video URL or aweme_id and return a DouyinVideoItem with watermark-free stream."""
        aweme_id = video_input.strip()
        if not aweme_id.isdigit():
            info = self.resolve_url(video_input)
            if info["type"] != "video":
                raise DouyinScraperError(f"输入的是博主主页，非单个视频链接: {video_input}")
            aweme_id = info["aweme_id"]

        detail_url = (
            f"https://www.douyin.com/aweme/v1/web/aweme/detail/"
            f"?aweme_id={aweme_id}&device_platform=webapp&aid=6383&channel=channel_pc_web"
        )
        headers = self._build_headers(user_cookie)

        req = urllib.request.Request(detail_url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw_json = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            raise DouyinScraperError(f"请求抖音详情接口失败: {e}")

        item_detail = raw_json.get("aweme_detail")
        if not item_detail:
            filter_msg = raw_json.get("filter_detail", {}).get("notice", "")
            raise DouyinScraperError(
                f"抖音未能返回视频详情 (可能是私密作品或已被删除{f': {filter_msg}' if filter_msg else ''})"
            )

        return self._extract_video_item(item_detail)

    # ------------------ Benchmark User Profile & Posts ------------------

    def parse_user_profile(
        self,
        user_input: str,
        count: int = 20,
        user_cookie: Optional[str] = None,
    ) -> Tuple[BenchmarkAccount, List[DouyinVideoItem]]:
        """Fetch user profile metadata and the newest post list for incremental monitoring."""
        sec_uid = user_input.strip()
        homepage_url = f"https://www.douyin.com/user/{sec_uid}"
        if "/" in user_input or "http" in user_input:
            info = self.resolve_url(user_input)
            if info["type"] != "user":
                raise DouyinScraperError(f"输入的是单个视频，非博主主页链接: {user_input}")
            sec_uid = info["sec_user_id"]
            homepage_url = info.get("resolved_url", homepage_url)

        headers = self._build_headers(user_cookie)

        # 1. Fetch user metadata
        profile_url = (
            f"https://www.douyin.com/aweme/v1/web/user/profile/other/"
            f"?sec_user_id={sec_uid}&device_platform=webapp&aid=6383&channel=channel_pc_web"
        )
        nickname = "未知博主"
        avatar_url = ""
        total_posts = 0

        try:
            req_prof = urllib.request.Request(profile_url, headers=headers)
            with urllib.request.urlopen(req_prof, timeout=10) as resp_p:
                prof_json = json.loads(resp_p.read().decode("utf-8"))
                user_info = prof_json.get("user", {})
                if user_info:
                    nickname = user_info.get("nickname", nickname)
                    avatar_list = user_info.get("avatar_larger", {}).get("url_list", []) or \
                                  user_info.get("avatar_thumb", {}).get("url_list", [])
                    if avatar_list:
                        avatar_url = avatar_list[0]
                    total_posts = user_info.get("aweme_count", 0)
        except Exception as e:
            logger.warning(f"Failed to fetch detailed profile for {sec_uid}: {e}")

        # 2. Fetch posts list
        posts_url = (
            f"https://www.douyin.com/aweme/v1/web/aweme/post/"
            f"?sec_user_id={sec_uid}&count={count}&max_cursor=0&device_platform=webapp&aid=6383&channel=channel_pc_web"
        )
        posts: List[DouyinVideoItem] = []
        try:
            req_posts = urllib.request.Request(posts_url, headers=headers)
            with urllib.request.urlopen(req_posts, timeout=10) as resp_posts:
                posts_json = json.loads(resp_posts.read().decode("utf-8"))
                raw_list = posts_json.get("aweme_list", [])
                for raw_item in raw_list:
                    try:
                        v_item = self._extract_video_item(raw_item)
                        posts.append(v_item)
                    except Exception as e:
                        logger.debug(f"Skipping malformed post item: {e}")
        except Exception as e:
            logger.warning(f"Failed to fetch posts for {sec_uid}: {e}")

        account = BenchmarkAccount(
            sec_user_id=sec_uid,
            nickname=nickname,
            avatar_url=avatar_url,
            homepage_url=homepage_url,
            total_posts=total_posts,
            last_checked_time=time.time(),
        )

        return account, posts

    # ------------------ Helpers ------------------

    def _extract_video_item(self, item: Dict[str, Any]) -> DouyinVideoItem:
        """Parse raw Douyin item JSON into a clean, normalized DouyinVideoItem."""
        aweme_id = str(item.get("aweme_id", ""))
        desc = item.get("desc", "").strip() or "无标题作品"
        create_time = int(item.get("create_time", 0))

        # Author
        author_dict = item.get("author", {})
        author_nickname = author_dict.get("nickname", "")
        author_sec_uid = author_dict.get("sec_uid", "")
        author_avatar = ""
        avatars = author_dict.get("avatar_thumb", {}).get("url_list", [])
        if avatars:
            author_avatar = avatars[0]

        # Video / Images
        video_dict = item.get("video", {})
        duration = float(video_dict.get("duration", 0)) / 1000.0  # ms to seconds

        # Thumbnail cover
        cover_url = ""
        covers = video_dict.get("cover", {}).get("url_list", []) or \
                 video_dict.get("origin_cover", {}).get("url_list", [])
        if covers:
            cover_url = covers[0]

        # Extract highest quality watermark-free video play URL
        play_urls = video_dict.get("play_addr", {}).get("url_list", [])
        play_url = ""
        if play_urls:
            raw_play = play_urls[0]
            # Replace playwm with play to bypass Douyin watermark
            play_url = raw_play.replace("playwm", "play")

        # Check if photo album (images)
        images = item.get("images")
        content_type = DouyinContentType.VIDEO
        if images and not play_url:
            content_type = DouyinContentType.IMAGE_ALBUM

        return DouyinVideoItem(
            aweme_id=aweme_id,
            title=desc,
            cover_url=cover_url,
            play_url=play_url,
            duration=duration,
            create_time=create_time,
            author_nickname=author_nickname,
            author_avatar=author_avatar,
            author_sec_uid=author_sec_uid,
            content_type=content_type,
        )
