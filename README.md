# VideoRemix Pro (下一代音视频智能去重与再创作引擎)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.9+](https://img.shields.io/badge/Python-3.9+-green.svg)](https://www.python.org/)

**VideoRemix** 是一套现代化、工业级的多模态音视频去重与二次创作系统。针对传统开源去重工具（如 `sdlw7757/Video-Dedup-Tool` 等）在**音频零处理秒被识别**、**抽帧导致音画严重脱节**、**粗暴RGB偏移破坏画质**、**硬编码UI界面破损**等致命缺陷，VideoRemix 进行了全面的底层重构。

---

## 🚀 核心架构革新与对比

| 对比维度 | 原传统去重工具 (`sdlw7757`) | **VideoRemix (本系统)** |
| :--- | :--- | :--- |
| **音频声学去重** | ❌ **完全未处理**（平台音频指纹秒杀） | ✅ **多重声纹重构**（微变调 + 频谱重塑 + 心理声学底噪掩蔽） |
| **音画同步保真** | ❌ 粗暴丢帧导致**音画脱节、口型错位** | ✅ **毫秒级时间戳同步**（严格数学对齐 `setpts + atempo`） |
| **画面观感质量** | ❌ RGB 明显色散毛刺、运动鬼影撕裂 | ✅ **电影级自然质感**（微平移缩放 + 胶片微噪点 + 自然调色） |
| **批量并发处理** | ❌ 仅支持单文件选择 | ✅ **多任务线程池队列**，支持文件夹递归扫描与批量并发 |
| **界面与分辨率适配** | ❌ 硬编码 `1700x1500`（1080p屏按钮掉出屏幕） | ✅ **弹性自适应现代化 UI**，支持暗黑主题，适配 768p 至 4K |
| **硬件加速** | ❌ 仅软解软编 | ✅ **智能硬件探测**（自动启用 NVENC / QSV / VideoToolbox） |
| **系统解耦** | ❌ 单文件 800 行面条代码 | ✅ **分层解耦**（内核 CLI 引擎、批处理服务、表现层完全分离） |

---

## 🛠️ 核心预设模式 (Presets)

1. **`balanced`【推荐：强效去重·自媒体矩阵】**：
   * 微平移缩放（1.02x） + 音画严格同步变速（1.018x） + 微变调（+0.25半音） + 均衡重构 + 胶片微噪点。
   * 适合投放各大主流短视频平台，在保持人眼无感的前提下彻底打乱视觉与音频特征向量。
2. **`quality`【保真：画质优先·高保真原创】**：
   * 胶片微颗粒 + 自然色彩映射 + 微变调 + 底噪混入。
   * 零构图裁剪，适合精剪原创或画质敏感型内容。
3. **`pip`【变体：智能画中画·背景虚化】**：
   * 90% 居中原片 + 动态高斯模糊虚化背景 + 全面声学指纹重构。
   * 彻底颠覆全局空间构图与宽高比。
4. **`custom`【自定义模式】**：
   * 支持自由微调变调半音数、缩放倍率、变速比、胶片颗粒度、镜像翻转等。

---

## 💻 安装与使用指南

### 0. 📦 免配置独立版直接运行（推荐普通用户 / Windows 创作者）
无需安装 Python，也无需配置任何 FFmpeg 环境，直接前往 Releases 页面：
👉 **[下载最新编译版 (GitHub Releases)](https://github.com/ruiworm/VideoRemix/releases)**

* **Windows 用户**：下载 `VideoRemix-windows-x64.zip`，解压后双击 `VideoRemix.exe` 即可启动原生桌面 GUI！
* **WSL / 命令行用户**：亦可在解压目录下运行 `VideoRemix --web` 开启浏览器控制台，或直接调用 CLI。

---

### 1. 源码与开发者安装
```bash
git clone https://github.com/ruiworm/VideoRemix.git
cd VideoRemix

# 推荐使用 uv 或 venv
uv venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
uv pip install -e .
```

### 2. 界面使用方式

#### 方式 A：现代化桌面端 GUI (Tkinter 原生界面)
适用于 Windows / macOS / 安装了中文字体的 Linux 桌面环境：
```bash
python -m videoremix.ui.app
# 或使用全局入口
videoremix-gui
```

#### 方式 B：Web 浏览器控制台 (WSL2 / 无头服务器 / 跨平台免配置推荐)
针对 WSL2 缺少中文字体库或 X11 兼容性问题，提供了极速轻量 Web 控制台，直接在宿主 Windows 浏览器中打开，告别字体渲染与编码困扰：
```bash
python -m videoremix.ui.web
# 或使用全局入口
videoremix-web
```
* 启动后会自动唤起浏览器打开 `http://127.0.0.1:8765`。
* 纯标准库实现，零额外三方 Web 框架依赖。

### 3. 命令行批量自动化处理 (CLI)
适合集成至自动化搬运、混剪矩阵流水线或云端批处理任务：

```bash
# 单文件强效去重
videoremix input.mp4 -o output.mp4 --preset balanced

# 文件夹全量批量去重 (4 线程并行)
videoremix /path/to/videos/ -o /path/to/remixed/ --preset balanced --workers 4

# 画中画模式
videoremix input.mp4 -o output_pip.mp4 --preset pip

# 自定义精细调参
videoremix input.mp4 -o out.mp4 --preset custom --zoom 1.03 --speed 1.02 --pitch 0.3 --grain 4
```

---

## 📂 项目模块结构

```
videoremix/
├── core/                    # 核心处理引擎
│   ├── probe.py             # 媒体探针 (支持 FFprobe 与 FFmpeg 兜底)
│   ├── filtergraph.py       # 声明式音视频协同滤镜链构建器
│   ├── hardware.py          # 硬件加速探测 (NVENC / QSV / AMF / VideoToolbox / CPU)
│   ├── executor.py          # 异步子进程调度与实时百分比解析
│   └── presets.py           # 预设场景库
├── queue/                   # 批处理任务调度
│   ├── task.py              # 任务数据结构与生命周期状态机
│   └── manager.py           # 线程池并发管理器
├── ui/                      # 现代化用户界面
│   ├── app.py               # 响应式自适应桌面客户端 (Tkinter)
│   └── web.py               # 轻量自适应 Web 控制台 (适配 WSL/无头环境)
└── cli.py                   # 命令行主入口
```

---

## ⚖️ 开源协议
本项目基于 [MIT License](LICENSE) 开源。仅供音视频工程技术研究、数字水印对抗测试及学习交流使用。
