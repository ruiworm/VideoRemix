# -*- mode: python ; coding: utf-8 -*-
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = []
binaries = []
hiddenimports = [
    "videoremix",
    "videoremix.core",
    "videoremix.core.probe",
    "videoremix.core.filtergraph",
    "videoremix.core.executor",
    "videoremix.core.presets",
    "videoremix.core.hardware",
    "videoremix.queue",
    "videoremix.queue.task",
    "videoremix.queue.manager",
    "videoremix.ui",
    "videoremix.ui.app",
    "videoremix.ui.web",
    "videoremix.cli",
    "videoremix.launcher",
    "tkinter",
    "tkinter.ttk",
    "tkinter.filedialog",
    "tkinter.messagebox",
]

# Collect imageio_ffmpeg binaries and metadata
img_datas, img_binaries, img_hidden = collect_all("imageio_ffmpeg")
datas += img_datas
binaries += img_binaries
hiddenimports += img_hidden

a = Analysis(
    ["../videoremix/launcher.py"],
    pathex=[".."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VideoRemix",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="VideoRemix",
)
