"""控制台窗口辅助：以控制台模式打包，运行时隐藏窗口。

为什么这么做：
PyInstaller 的窗口模式（runw）在启动期出错时**完全不显示任何信息**，
用户看到的就是"双击没反应"。改成控制台模式后，bootloader 的错误
能正常打印；程序启动成功后再把控制台隐藏，体验与窗口程序一致。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_user32 = ctypes.WinDLL("user32", use_last_error=True)

_kernel32.GetConsoleWindow.restype = wt.HWND
_kernel32.GetConsoleWindow.argtypes = []

SW_HIDE = 0
SW_SHOW = 5


def get_console_hwnd():
    try:
        return _kernel32.GetConsoleWindow()
    except Exception:
        return None


def has_console() -> bool:
    return bool(get_console_hwnd())


def hide_console() -> bool:
    """隐藏当前进程的控制台窗口。"""
    try:
        hwnd = get_console_hwnd()
        if not hwnd:
            return False
        _user32.ShowWindow(hwnd, SW_HIDE)
        return True
    except Exception:
        return False


def show_console() -> bool:
    try:
        hwnd = get_console_hwnd()
        if not hwnd:
            return False
        _user32.ShowWindow(hwnd, SW_SHOW)
        return True
    except Exception:
        return False
