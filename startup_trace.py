"""启动过程追踪：把每个启动步骤写进文件，便于事后排查。

为什么需要它：
窗口模式（console=False）下没有控制台，任何启动期异常用户都看不到。
把关键步骤和异常写进 startup-trace.log，出问题时能直接拿到现场。

注意：写入必须极轻量（只追加一行），不能拖慢启动。
"""

from __future__ import annotations

import datetime
import os
import sys
import threading
import traceback
from pathlib import Path

_LOCK = threading.Lock()
_TRACE_NAME = "startup-trace.log"
_MAX_BYTES = 256 * 1024


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def trace_path() -> Path:
    return _app_dir() / _TRACE_NAME


def _rotate() -> None:
    """超过上限就滚动一次，避免无限增长。"""
    try:
        path = trace_path()
        if path.is_file() and path.stat().st_size > _MAX_BYTES:
            backup = path.with_suffix(".log.old")
            backup.unlink(missing_ok=True)
            os.replace(path, backup)
    except Exception:
        pass


def trace(message: str) -> None:
    """追加一条追踪记录。任何异常都吞掉，绝不影响启动。"""
    try:
        with _LOCK:
            _rotate()
            stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            with trace_path().open("a", encoding="utf-8") as fh:
                fh.write(f"{stamp}  {message}\n")
    except Exception:
        pass


def trace_exception(title: str) -> None:
    """记录当前异常堆栈。"""
    try:
        trace(f"{title}\n{traceback.format_exc()}")
    except Exception:
        pass


def reset() -> None:
    """开始一次新启动：记录分隔线与环境信息。"""
    try:
        trace("=" * 60)
        trace("程序启动")
        trace(f"  frozen      = {getattr(sys, 'frozen', False)}")
        trace(f"  executable  = {sys.executable}")
        trace(f"  _MEIPASS    = {getattr(sys, '_MEIPASS', '(无)')}")
        trace(f"  python      = {sys.version.split()[0]}")
        trace(f"  argv        = {sys.argv[1:]}")
        trace(f"  cwd         = {os.getcwd()}")
        trace(f"  pid         = {os.getpid()}")
    except Exception:
        pass
