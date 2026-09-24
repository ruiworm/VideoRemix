"""Zero-dependency local Web UI for VideoRemix (perfect for WSL and browser-based usage)."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, Dict
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from videoremix import __version__
from videoremix.core.hardware import HardwareDetector
from videoremix.core.presets import PRESET_DESCRIPTIONS, PresetMode
from videoremix.queue.manager import BatchQueueManager
from videoremix.queue.task import TaskStatus

logger = logging.getLogger(__name__)

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VideoRemix Pro - 智能多模态音视频去重控制台</title>
    <style>
        :root {
            --bg-base: #11111b;
            --bg-surface: #1e1e2e;
            --bg-card: #252538;
            --border: #313244;
            --text-main: #cdd6f4;
            --text-muted: #a6adc8;
            --accent: #89b4fa;
            --accent-green: #a6e3a1;
            --accent-red: #f38ba8;
            --accent-yellow: #f9e2af;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif; }
        body { background-color: var(--bg-base); color: var(--text-main); min-height: 100vh; padding: 24px; }
        .container { max-width: 1200px; margin: 0 auto; display: flex; flex-direction: column; gap: 20px; }
        .header { display: flex; justify-content: space-between; align-items: center; padding-bottom: 16px; border-bottom: 1px solid var(--border); }
        .logo { font-size: 24px; font-weight: 700; color: #fff; display: flex; align-items: center; gap: 10px; }
        .logo span { font-size: 13px; color: var(--accent); background: rgba(137,180,250,0.15); padding: 2px 8px; border-radius: 12px; }
        .codec-badge { font-size: 13px; font-weight: 600; padding: 6px 14px; border-radius: 20px; background: var(--bg-card); border: 1px solid var(--border); color: var(--accent-green); }
        
        .main-grid { display: grid; grid-template-columns: 360px 1fr; gap: 20px; }
        .card { background: var(--bg-surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px; display: flex; flex-direction: column; gap: 16px; }
        .card-title { font-size: 16px; font-weight: 600; color: #fff; margin-bottom: 4px; }

        .form-group { display: flex; flex-direction: column; gap: 6px; }
        .form-group label { font-size: 13px; color: var(--text-muted); font-weight: 500; }
        .input-text, select { background: var(--bg-card); border: 1px solid var(--border); color: #fff; padding: 10px 12px; border-radius: 8px; font-size: 13px; outline: none; transition: 0.2s; }
        .input-text:focus, select:focus { border-color: var(--accent); }
        
        .preset-desc { font-size: 12px; color: var(--text-muted); background: var(--bg-card); padding: 10px; border-radius: 6px; line-height: 1.5; }
        
        .btn-row { display: flex; gap: 10px; margin-top: 8px; }
        .btn { padding: 10px 16px; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; border: none; transition: 0.2s; display: inline-flex; align-items: center; justify-content: center; gap: 6px; }
        .btn-primary { background: var(--accent); color: #11111b; flex: 1; }
        .btn-primary:hover { filter: brightness(1.1); }
        .btn-success { background: var(--accent-green); color: #11111b; font-size: 14px; padding: 12px 18px; }
        .btn-danger { background: var(--accent-red); color: #11111b; }
        .btn-secondary { background: var(--bg-card); color: var(--text-main); border: 1px solid var(--border); }
        .btn:disabled { opacity: 0.4; cursor: not-allowed; }

        .table-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: 8px; }
        table { width: 100%; border-collapse: collapse; font-size: 13px; text-align: left; }
        th { background: var(--bg-card); color: var(--text-muted); padding: 12px 14px; font-weight: 600; }
        td { padding: 12px 14px; border-top: 1px solid var(--border); }
        tr:hover td { background: rgba(255,255,255,0.02); }

        .progress-bar-bg { width: 100px; height: 8px; background: var(--bg-card); border-radius: 4px; overflow: hidden; display: inline-block; vertical-align: middle; margin-right: 8px; }
        .progress-bar-fill { height: 100%; background: var(--accent); width: 0%; transition: width 0.3s; }

        .status-badge { font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 6px; display: inline-block; }
        .status-PENDING { background: rgba(249,226,175,0.15); color: var(--accent-yellow); }
        .status-RUNNING { background: rgba(137,180,250,0.2); color: var(--accent); }
        .status-SUCCESS { background: rgba(166,227,161,0.2); color: var(--accent-green); }
        .status-FAILED { background: rgba(243,139,168,0.2); color: var(--accent-red); }
        .status-CANCELLED { background: var(--border); color: var(--text-muted); }

        .empty-state { text-align: center; padding: 48px; color: var(--text-muted); font-size: 14px; }
    </style>
</head>
<body>
    <div class="container">
        <header class="header">
            <div class="logo">
                VideoRemix Pro
                <span>v__VERSION__</span>
            </div>
            <div class="codec-badge" id="codecBadge">加速引擎检测中...</div>
        </header>

        <div class="main-grid">
            <!-- Left Config Panel -->
            <div class="card">
                <div class="card-title">添加任务与去重策略</div>
                
                <div class="form-group">
                    <label>输入路径 (支持单视频文件或整文件夹)</label>
                    <input type="text" id="inputPath" class="input-text" placeholder="/path/to/video.mp4 或目录">
                </div>

                <div class="form-group">
                    <label>输出路径 (可选，留空默认在原目录输出)</label>
                    <div style="display:flex; gap:6px;">
                        <input type="text" id="outputPath" class="input-text" style="flex:1;" placeholder="/path/to/output.mp4 或目录">
                        <button class="btn btn-secondary" style="padding:0 12px; white-space:nowrap;" onclick="openOutputDir()">📂 打开</button>
                    </div>
                </div>

                <!-- Matrix Multiplier & Randomization Card -->
                <div style="background: rgba(203, 166, 247, 0.08); border: 1px solid rgba(203, 166, 247, 0.3); border-radius: 8px; padding: 12px; display: flex; flex-direction: column; gap: 10px;">
                    <div style="font-size: 13px; font-weight: 600; color: #cba6f7; display: flex; align-items: center; justify-content: space-between;">
                        <span>🎲 矩阵裂变与微扰防重</span>
                        <span style="font-size: 11px; background: rgba(203, 166, 247, 0.2); color: #cba6f7; padding: 2px 6px; border-radius: 4px;">v1.1.0 核心</span>
                    </div>
                    
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <label style="font-size: 12px; color: var(--text-muted);">变体裂变数 (1变N):</label>
                        <select id="variantsSelect" style="padding: 4px 8px; font-size: 12px; font-weight: bold; color: var(--accent-green); background: var(--bg-base); border: 1px solid var(--border); border-radius: 6px;">
                            <option value="1" selected>1 变 1 (标准)</option>
                            <option value="2">1 变 2 (双重变体)</option>
                            <option value="3">1 变 3 (三重变体)</option>
                            <option value="4">1 变 4 (四重变体)</option>
                            <option value="5">1 变 5 (五重裂变)</option>
                        </select>
                    </div>

                    <label style="display: flex; align-items: center; gap: 8px; font-size: 12px; cursor: pointer; color: var(--text-main);">
                        <input type="checkbox" id="randomizeCheck" checked>
                        <span>参数区间微扰 (防批量同质化，每次生成数学指纹独一无二)</span>
                    </label>
                </div>

                <div class="form-group">
                    <label>去重方案预设</label>
                    <select id="presetSelect" onchange="updatePresetDesc()">
                        <option value="balanced" selected>强效去重 (自媒体矩阵推荐)</option>
                        <option value="ecommerce">电商专版 (专克京东/拼多多机器拦截)</option>
                        <option value="quality">画质保真 (高保真原创推荐)</option>
                        <option value="pip">智能画中画 (高斯模糊背景)</option>
                        <option value="custom">自定义: 详细参数调节</option>
                    </select>
                </div>

                <div class="preset-desc" id="presetDesc">加载中...</div>

                <!-- Custom Options Subpanel -->
                <div id="customSettings" style="display: none; background: var(--bg-card); padding: 12px; border-radius: 8px; border: 1px solid var(--border); flex-direction: column; gap: 10px;">
                    <div style="font-size: 13px; font-weight: 600; color: var(--accent);">⚙️ 自定义参数配置</div>
                    
                    <div class="form-group">
                        <div style="display:flex; justify-content:space-between; font-size:12px;">
                            <label>画幅微缩放 (Zoom)</label>
                            <span id="zoomVal" style="color:var(--accent-green); font-weight:bold;">1.02x</span>
                        </div>
                        <input type="range" id="customZoom" min="1.00" max="1.15" step="0.01" value="1.02" oninput="document.getElementById('zoomVal').innerText = parseFloat(this.value).toFixed(2) + 'x'">
                    </div>

                    <div class="form-group">
                        <div style="display:flex; justify-content:space-between; font-size:12px;">
                            <label>音画变速比 (Speed)</label>
                            <span id="speedVal" style="color:var(--accent-green); font-weight:bold;">1.018x</span>
                        </div>
                        <input type="range" id="customSpeed" min="0.950" max="1.100" step="0.005" value="1.018" oninput="document.getElementById('speedVal').innerText = parseFloat(this.value).toFixed(3) + 'x'">
                    </div>

                    <div style="display:flex; gap:10px;">
                        <div class="form-group" style="flex:1;">
                            <label style="font-size:12px;">片头截断 (秒)</label>
                            <input type="number" id="customTrimStart" min="0" max="5.0" step="0.1" value="0.8" class="input-text" style="padding:6px 10px;">
                        </div>
                        <div class="form-group" style="flex:1;">
                            <label style="font-size:12px;">片尾截断 (秒)</label>
                            <input type="number" id="customTrimEnd" min="0" max="5.0" step="0.1" value="0.5" class="input-text" style="padding:6px 10px;">
                        </div>
                    </div>

                    <div style="display:flex; gap:10px;">
                        <div class="form-group" style="flex:1;">
                            <label style="font-size:12px;">胶片噪点 (0-10)</label>
                            <input type="number" id="customGrain" min="0" max="10" value="3" class="input-text" style="padding:6px 10px;">
                        </div>
                        <div class="form-group" style="flex:1;">
                            <label style="font-size:12px;">音频微变调 (半音)</label>
                            <input type="number" id="customPitch" min="-2.0" max="2.0" step="0.05" value="0.25" class="input-text" style="padding:6px 10px;">
                        </div>
                    </div>

                    <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 8px; font-size: 12px; margin-top: 4px;">
                        <label style="display:flex; align-items:center; gap:6px; cursor:pointer;"><input type="checkbox" id="customHflip"> 镜像翻转</label>
                        <label style="display:flex; align-items:center; gap:6px; cursor:pointer;"><input type="checkbox" id="customPip"> 画中画模式</label>
                        <label style="display:flex; align-items:center; gap:6px; cursor:pointer;"><input type="checkbox" id="customColor" checked> 自然调色</label>
                        <label style="display:flex; align-items:center; gap:6px; cursor:pointer;"><input type="checkbox" id="customEq" checked> 声学重构</label>
                        <label style="display:flex; align-items:center; gap:6px; cursor:pointer;"><input type="checkbox" id="customMask"> 底部字幕遮罩</label>
                    </div>
                </div>

                <div class="form-group">
                    <label>并行处理线程数</label>
                    <select id="workersSelect">
                        <option value="1">1 线程 (省资源)</option>
                        <option value="2" selected>2 线程 (均衡推荐)</option>
                        <option value="4">4 线程 (高速并发)</option>
                    </select>
                </div>

                <div class="btn-row">
                    <button class="btn btn-primary" onclick="addTask()">+ 添加到队列</button>
                </div>

                <hr style="border:0; border-top:1px solid var(--border); margin:4px 0;">

                <div class="btn-row" style="flex-direction:column; gap:8px;">
                    <button class="btn btn-success" id="startBtn" onclick="startQueue()">▶ 开始批量执行</button>
                    <button class="btn btn-danger" id="stopBtn" onclick="stopQueue()" disabled>■ 终止运行</button>
                </div>
            </div>

            <!-- Right Queue Panel -->
            <div class="card">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div class="card-title">任务队列与实时进度 (<span id="taskCount">0</span>)</div>
                    <button class="btn btn-secondary" style="padding:6px 12px; font-size:12px;" onclick="clearCompleted()">清空已完成</button>
                </div>

                <div class="table-wrap">
                    <table>
                        <thead>
                            <tr>
                                <th>视频文件</th>
                                <th>预设</th>
                                <th>状态</th>
                                <th style="width:160px;">转码进度</th>
                                <th>倍速</th>
                                <th>预计剩余</th>
                            </tr>
                        </thead>
                        <tbody id="taskBody">
                            <tr><td colspan="6" class="empty-state">队列为空，请在左侧输入路径添加视频任务</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>

    <script>
        const PRESETS = {
            "balanced": "【强效去重】微平移缩放 (1.02x) + 同步变速 (1.018x) + 音高微调 + 均衡重构 + 胶片微噪点（音画严格对齐）",
            "ecommerce": "【电商专版】专克京东/拼多多初审 (底部字幕遮罩阻断OCR + 口播抗ASR变速微变调 + 4.5%边缘净空)",
            "quality": "【画质保真】轻量色彩调优 + 微变调 + 底噪混入 + 胶片微噪点（零观感破坏）",
            "pip": "【智能画中画】90% 居中原画 + 动态高斯模糊背景 + 全面声学指纹重塑（强力变体）",
            "custom": "【自定义模式】自由配置缩放比例、变速比率、胶片噪点、变调以及滤镜开关"
        };

        function updatePresetDesc() {
            const val = document.getElementById('presetSelect').value;
            document.getElementById('presetDesc').innerText = PRESETS[val] || '';
            const customDiv = document.getElementById('customSettings');
            if (val === 'custom') {
                customDiv.style.display = 'flex';
            } else {
                customDiv.style.display = 'none';
            }
        }
        updatePresetDesc();

        async function fetchStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                document.getElementById('codecBadge').innerText = '加速引擎: ' + data.codec_name;
                document.getElementById('taskCount').innerText = data.tasks.length;
                
                const isRunning = data.is_running;
                document.getElementById('startBtn').disabled = isRunning || data.tasks.length === 0;
                document.getElementById('stopBtn').disabled = !isRunning;

                const tbody = document.getElementById('taskBody');
                if (data.tasks.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="6" class="empty-state">队列为空，请在左侧输入路径添加视频任务</td></tr>';
                    return;
                }

                let html = '';
                for (const t of data.tasks) {
                    const statusClass = 'status-' + t.status;
                    const statusText = {
                        'PENDING': '等待中',
                        'RUNNING': '处理中 ⏳',
                        'SUCCESS': '完成 ✔',
                        'FAILED': '失败 ✖',
                        'CANCELLED': '已取消'
                    }[t.status] || t.status;

                    html += `<tr>
                        <td title="${t.input_path}"><strong>${t.filename}</strong></td>
                        <td>${t.preset}</td>
                        <td><span class="status-badge ${statusClass}">${statusText}</span></td>
                        <td>
                            <div class="progress-bar-bg"><div class="progress-bar-fill" style="width:${t.progress}%"></div></div>
                            ${t.progress.toFixed(1)}%
                        </td>
                        <td>${t.speed || '-'}</td>
                        <td>${t.eta > 0 ? t.eta.toFixed(0) + 's' : '-'}</td>
                    </tr>`;
                }
                tbody.innerHTML = html;
            } catch (err) {
                console.error(err);
            }
        }

        async function openOutputDir() {
            const output = document.getElementById('outputPath').value.trim();
            const res = await fetch('/api/open_folder', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ folder: output })
            });
            const data = await res.json();
            if (data.error) {
                alert('打开目录失败: ' + data.error);
            }
        }

        async function addTask() {
            const input = document.getElementById('inputPath').value.trim();
            const output = document.getElementById('outputPath').value.trim();
            const preset = document.getElementById('presetSelect').value;
            const workers = parseInt(document.getElementById('workersSelect').value, 10);
            const variants = parseInt(document.getElementById('variantsSelect').value, 10) || 1;
            const randomize = document.getElementById('randomizeCheck').checked;

            if (!input) {
                alert('请输入视频文件或目录路径！');
                return;
            }

            let custom_opts = {};
            if (preset === 'custom') {
                custom_opts = {
                    zoom: parseFloat(document.getElementById('customZoom').value) || 1.0,
                    speed: parseFloat(document.getElementById('customSpeed').value) || 1.0,
                    grain: parseInt(document.getElementById('customGrain').value, 10) || 0,
                    pitch: parseFloat(document.getElementById('customPitch').value) || 0.0,
                    hflip: document.getElementById('customHflip').checked,
                    pip: document.getElementById('customPip').checked,
                    color_grade: document.getElementById('customColor').checked,
                    equalizer: document.getElementById('customEq').checked,
                    subtitle_mask: document.getElementById('customMask').checked,
                    trim_start: parseFloat(document.getElementById('customTrimStart').value) || 0.0,
                    trim_end: parseFloat(document.getElementById('customTrimEnd').value) || 0.0,
                    randomize: randomize,
                    noise_floor: true
                };
            } else {
                if (randomize) {
                    custom_opts.randomize = true;
                }
            }

            const res = await fetch('/api/tasks/add', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ input, output, preset, workers, variants, randomize, custom_opts })
            });
            const data = await res.json();
            if (data.error) {
                alert('添加失败: ' + data.error);
            } else {
                document.getElementById('inputPath').value = '';
                fetchStatus();
            }
        }

        async function startQueue() {
            const workers = parseInt(document.getElementById('workersSelect').value, 10);
            await fetch('/api/tasks/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ workers })
            });
            fetchStatus();
        }

        async function stopQueue() {
            await fetch('/api/tasks/stop', { method: 'POST' });
            fetchStatus();
        }

        async function clearCompleted() {
            await fetch('/api/tasks/clear', { method: 'POST' });
            fetchStatus();
        }

        setInterval(fetchStatus, 600);
        fetchStatus();
    </script>
</body>
</html>
""".replace("__VERSION__", __version__)


class WebUIServer:
    """Embedded HTTP server handling Web UI requests and API endpoints."""

    def __init__(self, port: int = 8765):
        self.port = port
        self.queue_manager = BatchQueueManager(max_workers=2)
        self.encoder = HardwareDetector.detect_best_encoder()

    def create_handler(self):
        parent = self

        class RequestHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # Silence routine request logging

            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path == "/" or parsed.path == "/index.html":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(HTML_TEMPLATE.encode("utf-8"))
                elif parsed.path == "/api/status":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()

                    tasks_data = []
                    for t in parent.queue_manager.tasks:
                        if t.preset == PresetMode.CUSTOM:
                            opts = t.custom_opts or {}
                            z = opts.get("zoom", 1.0)
                            s = opts.get("speed", 1.0)
                            preset_name = f"自定义 ({z:.2f}x/{s:.3f}x)"
                        elif t.preset == PresetMode.BALANCED_REMIX:
                            preset_name = "强效去重"
                        elif t.preset == PresetMode.ECOMMERCE:
                            preset_name = "电商专版"
                        elif t.preset == PresetMode.QUALITY_FIRST:
                            preset_name = "画质保真"
                        elif t.preset == PresetMode.SMART_PIP:
                            preset_name = "智能画中画"
                        else:
                            preset_name = t.preset.value

                        tasks_data.append({
                            "id": t.task_id,
                            "filename": t.filename,
                            "input_path": t.input_path,
                            "preset": preset_name,
                            "custom_opts": t.custom_opts,
                            "status": t.status.value,
                            "progress": t.progress,
                            "speed": t.speed,
                            "eta": t.eta,
                            "error": t.error_message,
                        })

                    data = {
                        "version": __version__,
                        "codec_name": parent.encoder.name,
                        "is_running": parent.queue_manager._is_running,
                        "tasks": tasks_data,
                    }
                    self.wfile.write(json.dumps(data).encode("utf-8"))
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):
                parsed = urllib.parse.urlparse(self.path)
                content_len = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
                req = json.loads(body) if body else {}

                if parsed.path == "/api/tasks/add":
                    inp = req.get("input", "").strip()
                    out = req.get("output", "").strip() or None
                    preset_val = req.get("preset", "balanced")
                    workers = int(req.get("workers", 2))
                    parent.queue_manager.max_workers = workers

                    preset_map = {
                        "quality": PresetMode.QUALITY_FIRST,
                        "balanced": PresetMode.BALANCED_REMIX,
                        "ecommerce": PresetMode.ECOMMERCE,
                        "pip": PresetMode.SMART_PIP,
                        "custom": PresetMode.CUSTOM,
                    }
                    p_mode = preset_map.get(preset_val, PresetMode.BALANCED_REMIX)
                    custom_opts = req.get("custom_opts", {}) if p_mode == PresetMode.CUSTOM else {}
                    variants = max(1, min(5, int(req.get("variants", 1))))
                    if bool(req.get("randomize", True)):
                        custom_opts["randomize"] = True

                    if not os.path.exists(inp):
                        self._json_res({"error": f"路径不存在: {inp}"}, status=400)
                        return

                    if os.path.isdir(inp):
                        added = parent.queue_manager.add_directory(
                            inp, output_dir=out, preset=p_mode, variants=variants, **custom_opts
                        )
                        self._json_res({"success": True, "added": len(added)})
                    else:
                        res = parent.queue_manager.add_task(
                            inp, output_path=out, preset=p_mode, variants=variants, **custom_opts
                        )
                        if isinstance(res, list):
                            self._json_res({"success": True, "added": len(res)})
                        else:
                            self._json_res({"success": True, "task_id": res.task_id})

                elif parsed.path == "/api/open_folder":
                    folder = req.get("folder", "").strip() or os.getcwd()
                    if not os.path.exists(folder):
                        try:
                            os.makedirs(folder, exist_ok=True)
                        except Exception as e:
                            self._json_res({"error": f"无法创建目录: {e}"}, status=400)
                            return

                    opened = False
                    if "microsoft" in platform.uname().release.lower() or os.path.exists("/proc/sys/fs/binfmt_misc/WSLInterop"):
                        try:
                            wpath = subprocess.check_output(["wslpath", "-w", folder], text=True).strip()
                            subprocess.run(["explorer.exe", wpath], check=False)
                            opened = True
                        except Exception:
                            pass

                    if not opened:
                        try:
                            if sys.platform == "win32":
                                os.startfile(folder)
                            elif sys.platform == "darwin":
                                subprocess.Popen(["open", folder])
                            else:
                                subprocess.Popen(["xdg-open", folder])
                            opened = True
                        except Exception as e:
                            self._json_res({"error": f"打开失败: {e}"}, status=500)
                            return

                    self._json_res({"success": True})

                elif parsed.path == "/api/tasks/start":
                    workers = int(req.get("workers", parent.queue_manager.max_workers))
                    parent.queue_manager.max_workers = workers
                    parent.queue_manager.start()
                    self._json_res({"success": True})

                elif parsed.path == "/api/tasks/stop":
                    parent.queue_manager.stop_all()
                    self._json_res({"success": True})

                elif parsed.path == "/api/tasks/clear":
                    parent.queue_manager.clear_completed()
                    self._json_res({"success": True})

                else:
                    self.send_response(404)
                    self.end_headers()

            def _json_res(self, data: Dict[str, Any], status: int = 200):
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps(data).encode("utf-8"))

        return RequestHandler

    def start(self, open_browser: bool = True):
        server = ThreadingHTTPServer(("127.0.0.1", self.port), self.create_handler())
        url = f"http://127.0.0.1:{self.port}"
        print("=" * 60)
        print(f"VideoRemix Web 控制台已启动: {url}")
        print("提示: 适用于 WSL、Windows、Linux 及无桌面环境。字体由浏览器原生排版，绝不丢字。")
        print("=" * 60)

        if open_browser:
            threading.Thread(target=self._open_browser, args=(url,), daemon=True).start()

        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\n正在停止 Web 服务器...")
            server.server_close()

    def _open_browser(self, url: str):
        time.sleep(0.5)
        # 1. WSL 特殊探测：优先调用 Windows 宿主机的默认浏览器打开（彻底解决 WSL 字体问题）
        if "microsoft" in platform.uname().release.lower() or os.path.exists("/proc/sys/fs/binfmt_misc/WSLInterop"):
            try:
                subprocess.run(["cmd.exe", "/c", "start", url], capture_output=True, check=False)
                return
            except Exception:
                pass

        # 2. 通用 Python webbrowser
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass


import platform

def main():
    port = 8765
    server = WebUIServer(port=port)
    server.start(open_browser=True)


if __name__ == "__main__":
    main()
