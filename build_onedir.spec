# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（onedir + 窗口模式）。

console=False：双击不会弹出黑色控制台窗口。
启动期异常由 app.py 写入 startup-trace.log，并用原生 MessageBox 提示，
不依赖控制台输出。
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
        (str(ROOT / "startup_trace.py"), "."),
    ],
    hiddenimports=["auto_login", "gui", "motw", "console", "startup_trace"],
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
    [],
    exclude_binaries=True,
    name="校园网自动登录",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,         # 窗口模式：不弹黑色控制台
    disable_windowed_traceback=False,
    icon=str(ROOT / "assets" / "app.ico"),
    version=str(ROOT / "assets" / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="校园网自动登录",
)
