"""MOTW（Mark of the Web）处理：检测并自动清除「来自网络」标记。

从网络下载的 zip 解压后，Windows 会给每个文件打上 Zone.Identifier 流，
智能控制（Smart App Control）与 SmartScreen 会据此拦截未签名的程序。

程序每次启动时顺手清掉自身及同目录文件的标记，可以避免后续启动
再次被拦（第一次仍需用户放行一次）。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
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


def clear_tree(root: Path, max_files: int = 3000) -> int:
    """递归清除目录下所有文件的 MOTW，返回清除数量。"""
    count = 0
    try:
        checked = 0
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            checked += 1
            if checked > max_files:
                break
            if has_motw(path) and clear_motw(path):
                count += 1
    except Exception:
        pass
    return count


def self_heal() -> int:
    """程序启动时调用：清掉自身所在目录的 MOTW。

    只在冻结（exe）模式下做，源码模式没必要也不该动开发目录。
    """
    if not getattr(sys, "frozen", False):
        return 0
    try:
        exe = Path(sys.executable).resolve()
        root = exe.parent
        # 先处理 exe 自己，再处理 _internal 里的依赖
        count = 0
        if has_motw(exe) and clear_motw(exe):
            count += 1
        count += clear_tree(root)
        return count
    except Exception:
        return 0
