# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（onedir + 控制台模式）。

为什么用控制台模式：
窗口模式（console=False）使用的 runw bootloader 在启动期出错时
不会显示任何信息，用户看到的就是"双击没反应"。
改成控制台模式后错误可以暴露，程序启动成功再由 console.hide_console()
把窗口隐藏，使用体验不变。
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
    ],
    hiddenimports=["auto_login", "gui", "motw", "console"],
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
    console=True,          # 控制台模式：出错可见，启动后自行隐藏
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
