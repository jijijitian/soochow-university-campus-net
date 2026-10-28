"""MOTW（Mark of the Web）处理：检测并清除「来自网络」标记。

从网络下载的 zip 解压后，Windows 会给文件打上 Zone.Identifier 流，
智能控制（Smart App Control）与 SmartScreen 会据此拦截未签名程序。

重要：只处理 exe 自身，不做目录递归扫描。
早期版本每次启动都递归检查近千个文件，在装了实时防护的机器上
每次文件打开都可能被拦截扫描，累计几十秒，表现为"启动卡死"。
现在只查 exe 自己（一次系统调用），并且放在后台线程里做。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
import threading
from pathlib import Path

GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x80
_ACCESS_READ = 0x80000000
_SHARE_ALL = 0x00000001 | 0x00000002

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateFileW.restype = wt.HANDLE
kernel32.CreateFileW.argtypes = [
    wt.LPCWSTR, wt.DWORD, wt.DWORD, wt.LPVOID, wt.DWORD, wt.DWORD, wt.HANDLE
]
_INVALID = ctypes.c_void_p(-1).value


def _open_stream(stream: str, access: int, creation: int):
    handle = kernel32.CreateFileW(
        stream, access, _SHARE_ALL, None, creation, FILE_ATTRIBUTE_NORMAL, None
    )
    if not handle or handle == _INVALID:
        return None
    return handle


def has_motw(path: Path) -> bool:
    """文件是否带 Zone.Identifier 流。"""
    try:
        handle = _open_stream(f"{path}:Zone.Identifier", _ACCESS_READ, OPEN_EXISTING)
        if handle is None:
            return False
        kernel32.CloseHandle(handle)
        return True
    except Exception:
        return False


def clear_motw(path: Path) -> bool:
    """删除单个文件的 Zone.Identifier。"""
    try:
        if not has_motw(path):
            return True
        stream = f"{path}:Zone.Identifier"
        handle = _open_stream(stream, GENERIC_WRITE, OPEN_EXISTING)
        if handle is not None:
            kernel32.CloseHandle(handle)
        kernel32.DeleteFileW(stream)
        return not has_motw(path)
    except Exception:
        return False


def _self_exe() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    try:
        return Path(sys.executable).resolve()
    except Exception:
        return None


def self_heal(timeout: float = 3.0) -> int:
    """清除 exe 自身的 MOTW。

    只处理 exe 一个文件，并设超时保护——绝不阻塞界面显示。
    返回清除数量（0 或 1）。
    """
    exe = _self_exe()
    if exe is None:
        return 0

    result = {"count": 0}

    def worker() -> None:
        try:
            if has_motw(exe) and clear_motw(exe):
                result["count"] = 1
        except Exception:
            pass

    thread = threading.Thread(target=worker, daemon=True, name="motw-selfheal")
    thread.start()
    thread.join(timeout)
    return result["count"]


def self_heal_async() -> None:
    """后台清除 exe 的 MOTW，完全不等待。"""
    exe = _self_exe()
    if exe is None:
        return

    def worker() -> None:
        try:
            if has_motw(exe):
                clear_motw(exe)
        except Exception:
            pass

    threading.Thread(target=worker, daemon=True, name="motw-async").start()
