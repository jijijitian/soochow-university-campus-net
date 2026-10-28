#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
校园网自动登录 - 统一入口
==========================

同一个可执行文件承担两种角色，靠命令行参数区分：

    （无参数）        打开图形界面
    --daemon         静默后台守护（开机自启、界面“启动守护”都走这里）
    --once           只跑一轮就退出
    --check          只检测网络状态，打印结果
    --force-login    跳过检测直接登录

打包采用「控制台模式 + 运行时隐藏窗口」：
窗口模式下 bootloader 出错会完全静默（用户看到"双击没反应"），
控制台模式至少能把错误暴露出来，启动成功后再隐藏。
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

if getattr(sys, "frozen", False):
    RES_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
else:
    RES_DIR = Path(__file__).resolve().parent

sys.path.insert(0, str(RES_DIR))

CLI_FLAGS = {"--daemon", "--once", "--check", "--force-login", "-v", "--verbose",
             "-c", "--config", "-h", "--help"}


def _is_cli(argv: list[str]) -> bool:
    return any(arg in CLI_FLAGS or arg.startswith("--config=") for arg in argv)


def _fatal(message: str) -> int:
    """把致命错误展示给用户：优先弹窗，其次写日志。"""
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            None, message, "校园网自动登录 - 启动失败", 0x10
        )
    except Exception:
        pass
    try:
        log = Path(sys.executable).parent / "startup-error.log"
        with log.open("a", encoding="utf-8") as fh:
            fh.write(message + "\n")
    except Exception:
        pass
    return 1


def _runtime_root() -> Path:
    """打包后的资源根目录。

    onedir 模式下 sys._MEIPASS 指向 <程序目录>\\_internal，
    onefile 模式指向临时解压目录，两者都是资源所在处。
    """
    return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))


def _check_runtime() -> str | None:
    """检查打包依赖是否齐全，返回错误说明或 None。"""
    if not getattr(sys, "frozen", False):
        return None

    base = _runtime_root()
    tcl = base / "_tcl_data"
    tk = base / "_tk_data"
    if not tcl.is_dir() or not tk.is_dir():
        return (
            "程序文件不完整，缺少界面运行库。\n\n"
            f"资源目录：\n{base}\n\n"
            "请重新解压完整的压缩包，不要只把 exe 拿出来运行。\n\n"
            "也可能是杀毒软件删除了 _internal 里的文件，"
            "请检查杀毒软件的隔离区或恢复区。"
        )
    return None


def main() -> int:
    argv = sys.argv[1:]
    cli_mode = _is_cli(argv)

    problem = _check_runtime()
    if problem:
        return _fatal(problem)

    # 启动即清除「来自网络」标记：只处理 exe 自身，且不阻塞启动
    try:
        import motw

        motw.self_heal_async()
    except Exception:
        pass

    if cli_mode:
        import auto_login as core

        return core.main(argv)

    # 界面模式：先隐藏控制台（如果有），再进 GUI
    try:
        import console

        console.hide_console()
    except Exception:
        pass

    try:
        from gui import main as gui_main

        return gui_main()
    except Exception:
        return _fatal("界面启动失败：\n\n" + traceback.format_exc())


if __name__ == "__main__":
    sys.exit(main())
