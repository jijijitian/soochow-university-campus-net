# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（onefile 单文件版）。

单文件的优势：不存在 _internal 目录，用户不可能"只解压了 exe"，
也不会出现依赖文件被杀毒软件批量隔离的问题。

注意：onefile 启动时会把依赖解压到临时目录，首次启动比 onedir 慢几秒。
"""

from pathlib import Path

ROOT = Path(SPECPATH)

a = Analysis(
    [str(ROOT / "app.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "assets" / "app.ico"), "assets"),
        (str(ROOT / "assets" / "app.png"), "assets"),
        (str(ROOT / "assets" / "app_64.png"), "assets"),
        (str(ROOT / "config.example.ini"), "."),
        (str(ROOT / "auto_login.py"), "."),
        (str(ROOT / "gui.py"), "."),
        (str(ROOT / "motw.py"), "."),
        (str(ROOT / "console.py"), "."),
        (str(ROOT / "tray.py"), "."),
    ],
    hiddenimports=["auto_login", "gui", "motw", "console", "tray"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "numpy", "pandas", "matplotlib", "scipy", "PIL", "pytest",
        "setuptools", "pip", "wheel", "tests",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="校园网自动登录",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ROOT / "assets" / "app.ico"),
    version=str(ROOT / "assets" / "version_info.txt"),
)
