"""Unit tests for ingestion data models, URL resolver, Douyin parser, manager, and downloader."""

from pathlib import Path
import time
from unittest.mock import MagicMock, patch
import pytest

from videoremix.ingest.account_manager import BenchmarkAccountManager
from videoremix.ingest.douyin import DouyinParser, DouyinScraperError
from videoremix.ingest.downloader import VideoDownloader
from videoremix.ingest.models import BenchmarkAccount, DouyinContentType, DouyinVideoItem


def test_douyin_video_item_model():
    item = DouyinVideoItem(
        aweme_id="7123456789012345678",
        title="好物开箱推荐",
        cover_url="https://p3.douyinpic.com/cover.jpg",
        play_url="https://aweme.snssdk.com/play/video.mp4",
        duration=45.5,
        create_time=1700000000,
        author_nickname="创作者小李",
        author_sec_uid="MS4wLjABAAAA_test",
    )

    assert item.formatted_duration == "00:45"
    assert item.formatted_date.startswith("2023-")
    d = item.to_dict()
    assert d["aweme_id"] == "7123456789012345678"
    assert d["content_type"] == "video"

    restored = DouyinVideoItem.from_dict(d)
    assert restored.title == "好物开箱推荐"
    assert restored.duration == 45.5


def test_benchmark_account_model():
    account = BenchmarkAccount(
        sec_user_id="MS4wLjABAAAA_creator1",
        nickname="金牌带货博主",
        homepage_url="https://www.douyin.com/user/MS4wLjABAAAA_creator1",
        category="电商好物",
        last_aweme_id="7412345678",
        last_checked_time=1700000000,
        total_posts=88,
    )

    assert account.nickname == "金牌带货博主"
    assert account.formatted_last_checked.startswith("2023-")
    data = account.to_dict()
    assert data["sec_user_id"] == "MS4wLjABAAAA_creator1"

    restored = BenchmarkAccount.from_dict(data)
    assert restored.category == "电商好物"
    assert restored.total_posts == 88


def test_extract_url_from_text():
    # 1. Bare short link
    url1 = "https://v.douyin.com/iABCxyz/"
    assert DouyinParser.extract_url_from_text(url1) == url1

    # 2. Chinese share text with punctuation
    text2 = "7.12 复制打开抖音，看看【老张的个人主页】... https://v.douyin.com/iABCxyz/，长按复制"
    assert DouyinParser.extract_url_from_text(text2) == "https://v.douyin.com/iABCxyz/"

    # 3. Direct web URL in text
    text3 = "快来看这个视频：https://www.douyin.com/video/7412345678901234567 ！太搞笑了"
    assert DouyinParser.extract_url_from_text(text3) == "https://www.douyin.com/video/7412345678901234567"

    # 4. Empty or invalid
    assert DouyinParser.extract_url_from_text("") is None
    assert DouyinParser.extract_url_from_text("没有链接的普通文字") is None


def test_resolve_url_types():
    parser = DouyinParser()

    # 1. Video URL
    res_v = parser.resolve_url("https://www.douyin.com/video/7234567890123456789")
    assert res_v["type"] == "video"
    assert res_v["aweme_id"] == "7234567890123456789"

    # 2. Note / photo album URL
    res_n = parser.resolve_url("https://www.douyin.com/note/7345678901234567890")
    assert res_n["type"] == "video"
    assert res_n["aweme_id"] == "7345678901234567890"

    # 3. User profile URL
    res_u = parser.resolve_url("https://www.douyin.com/user/MS4wLjABAAAA-sample_sec_id_123")
    assert res_u["type"] == "user"
    assert res_u["sec_user_id"] == "MS4wLjABAAAA-sample_sec_id_123"

    # 4. User profile with query param sec_uid
    res_q = parser.resolve_url("https://www.douyin.com/share/user/1000?sec_uid=MS4wLjABAAAA_query_uid")
    assert res_q["type"] == "user"
    assert res_q["sec_user_id"] == "MS4wLjABAAAA_query_uid"

    # 5. Invalid URL throws DouyinScraperError
    with pytest.raises(DouyinScraperError):
        parser.resolve_url("https://www.douyin.com/random/unknown/path")


def test_extract_video_item_watermark_bypass():
    parser = DouyinParser()

    # Mock raw API item response
    raw_item = {
        "aweme_id": "7400112233445566778",
        "desc": "最新测评好物分享 #生活技巧",
        "create_time": 1720000000,
        "author": {
            "nickname": "科技小达人",
            "sec_uid": "MS4wLjABAAAA_author_xyz",
            "avatar_thumb": {"url_list": ["https://p3.douyinpic.com/avatar.jpg"]},
        },
        "video": {
            "duration": 58200,  # 58.2s in ms
            "cover": {"url_list": ["https://p3.douyinpic.com/cover.jpg"]},
            "play_addr": {
                "url_list": [
                    "https://aweme.snssdk.com/aweme/v1/playwm/?video_id=v0200fg10000xxxx"
                ]
            },
        },
    }

    item = parser._extract_video_item(raw_item)
    assert item.aweme_id == "7400112233445566778"
    assert item.title == "最新测评好物分享 #生活技巧"
    assert item.duration == 58.2
    assert item.formatted_duration == "00:58"
    assert item.author_nickname == "科技小达人"
    # Ensure playwm was stripped to play for watermark-free URL
    assert "playwm" not in item.play_url
    assert "play/?video_id=" in item.play_url


def test_dynamic_ttwid_generator():
    parser = DouyinParser()
    ttwid = parser.get_dynamic_ttwid()
    # It should successfully obtain a real ttwid string from ByteDance register API
    assert isinstance(ttwid, str)
    assert len(ttwid) > 10
    # Second call should use cache
    cached_ttwid = parser.get_dynamic_ttwid()
    assert cached_ttwid == ttwid


def test_benchmark_account_manager_crud_and_incremental_diff(tmp_path):
    accounts_file = tmp_path / "accounts.json"
    config_file = tmp_path / "config.json"

    # Create mock parser
    mock_parser = MagicMock(spec=DouyinParser)

    # Initial profile and 3 posts
    v1 = DouyinVideoItem(aweme_id="101", title="V1", cover_url="", play_url="")
    v2 = DouyinVideoItem(aweme_id="102", title="V2", cover_url="", play_url="")
    v3 = DouyinVideoItem(aweme_id="103", title="V3", cover_url="", play_url="")

    init_acc = BenchmarkAccount(sec_user_id="sec_1", nickname="测试达人")
    mock_parser.parse_user_profile.return_value = (init_acc, [v3, v2, v1])

    mgr = BenchmarkAccountManager(accounts_file=accounts_file, config_file=config_file, parser=mock_parser)

    # 1. Add account
    acc, posts = mgr.add_account("https://www.douyin.com/user/sec_1", category="母婴")
    assert acc.sec_user_id == "sec_1"
    assert acc.category == "母婴"
    assert acc.last_aweme_id == "103"
    assert len(mgr.list_accounts()) == 1

    # Verify persistence
    assert accounts_file.exists()
    mgr2 = BenchmarkAccountManager(accounts_file=accounts_file, config_file=config_file, parser=mock_parser)
    assert len(mgr2.list_accounts()) == 1
    assert mgr2.get_account("sec_1").nickname == "测试达人"

    # 2. Test Incremental Diff when 2 new videos appear: V5 and V4
    v4 = DouyinVideoItem(aweme_id="104", title="V4", cover_url="", play_url="")
    v5 = DouyinVideoItem(aweme_id="105", title="V5", cover_url="", play_url="")
    # Latest post feed has [V5, V4, V3, V2, V1]
    mock_parser.parse_user_profile.return_value = (init_acc, [v5, v4, v3, v2, v1])

    refreshed_acc, new_posts = mgr.refresh_account("sec_1")
    # Must only return V5 and V4!
    assert len(new_posts) == 2
    assert new_posts[0].aweme_id == "105"
    assert new_posts[1].aweme_id == "104"
    assert refreshed_acc.last_aweme_id == "105"

    # 3. Test Refresh All
    all_res = mgr.refresh_all()
    assert "sec_1" in all_res

    # 4. Remove account
    assert mgr.remove_account("sec_1") is True
    assert len(mgr.list_accounts()) == 0


def test_video_downloader_filename_sanitization():
    downloader = VideoDownloader()
    raw_title = "好物开箱! / 大揭秘: 价值 999* 的神器? | <必看>"
    safe = downloader.sanitize_filename(raw_title)
    assert "/" not in safe
    assert "*" not in safe
    assert "?" not in safe
    assert "|" not in safe
    assert "<" not in safe
    assert ">" not in safe


def test_douyin_parser_gui_callback(tmp_path):
    from unittest.mock import MagicMock, patch
    from videoremix.ingest.gui import DouyinParserApp
    from videoremix.ingest.models import DouyinVideoItem

    mock_cb = MagicMock()
    mock_root = MagicMock()

    with patch.object(DouyinParserApp, "_build_ui"), \
         patch("tkinter.StringVar"), \
         patch("tkinter.DoubleVar"):
        app = DouyinParserApp(mock_root, on_import_callback=mock_cb)

        test_file = tmp_path / "downloaded_douyin.mp4"
        test_file.write_text("dummy")

        app.current_item = DouyinVideoItem(
            aweme_id="12345",
            title="Test Video",
            cover_url="",
            play_url="",
            local_path=str(test_file),
        )
        app.status_var = MagicMock()

        with patch("tkinter.messagebox.showinfo"):
            app._on_send_to_remix_clicked()

        mock_cb.assert_called_once_with(str(test_file))


