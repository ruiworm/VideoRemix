import json
import threading
import time
import urllib.request
from videoremix.ui.web import WebUIServer

def test_web_server_endpoints():
    server = WebUIServer(port=8769)
    t = threading.Thread(target=server.start, kwargs={"open_browser": False}, daemon=True)
    t.start()
    time.sleep(0.3)

    # 1. Test GET /
    req = urllib.request.urlopen("http://127.0.0.1:8769/")
    assert req.status == 200
    html = req.read().decode("utf-8")
    assert "VideoRemix Pro" in html
    assert "智能多模态音视频去重控制台" in html

    # 2. Test GET /api/status
    req_status = urllib.request.urlopen("http://127.0.0.1:8769/api/status")
    assert req_status.status == 200
    data = json.loads(req_status.read().decode("utf-8"))
    assert "codec_name" in data
    assert "tasks" in data
    assert isinstance(data["tasks"], list)
