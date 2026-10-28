#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
校园网自动登录 - 统一入口
==========================

同一个可执行文件承担两种角色，靠命令行参数区分：

    （无参数）        打开图形界面
    --daemon         静默后台守护（开机自启、界面「启动守护」都走这里）
    --once           只跑一轮就退出
    --check          只检测网络状态，打印结果
    --force-login    跳过检测直接登录

打包为窗口程序（console=False）：双击不会出现黑色控制台窗口。
启动失败时会弹出原生对话框说明原因，不再静默退出。
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

CLI_FLAGS = {"--daemon", "--once", "--check", "--force-login",
             "-v", "--verbose", "-c", "--config", "-h", "--help"}


def _is_cli(argv: list[str]) -> bool:
    return any(arg in CLI_FLAGS or arg.startswith("--config=") for arg in argv)


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _message_box(title: str, text: str) -> None:
    """弹一个系统原生对话框。不依赖 tkinter，最早期也能用。"""
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)
    except Exception:
        pass


def _fatal(title: str, message: str) -> int:
    """把致命错误展示给用户：弹窗 + 写文件。"""
    _message_box(f"校园网自动登录 - {title}", message)
    try:
        log = _app_dir() / "startup-error.log"
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"[{title}]\n{message}\n")
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
    missing = [name for name in ("_tcl_data", "_tk_data") if not (base / name).is_dir()]
    if not missing:
        return None
    return (
        "程序文件不完整，缺少界面运行库：\n"
        + "、".join(missing)
        + "\n\n"
        + f"资源目录：\n{base}\n\n"
        + "可能的原因：\n"
        + "  1. 只把 exe 单独拿出来运行，没有解压整个文件夹\n"
        + "  2. 杀毒软件删除了 _internal 里的文件\n\n"
        + "解决办法：\n"
        + "  · 重新解压完整的压缩包（要解压整个文件夹）\n"
        + "  · 检查杀毒软件的隔离区 / 恢复区，把文件恢复回来"
    )


def _version() -> str:
    try:
        import auto_login

        return auto_login.APP_VERSION
    except Exception:
        return "未知"


def main() -> int:
    argv = sys.argv[1:]
    cli_mode = _is_cli(argv)

    problem = _check_runtime()
    if problem:
        return _fatal("启动失败", problem)

    # 清除「来自网络」标记：只处理 exe 自身，后台执行，不阻塞
    try:
        import motw

        motw.self_heal_async()
    except Exception:
        pass

    if cli_mode:
        import auto_login as core

        try:
            return core.main(argv)
        except SystemExit as exc:
            # argparse 的 --help / 参数错误会走这里，属于正常流程
            return exc.code if isinstance(exc.code, int) else 0
        except Exception:
            raise

    # 界面模式
    try:
        from gui import main as gui_main

        return gui_main()
    except SystemExit as exc:
        # 兜底：任何模块调用 sys.exit() 都不该让窗口静默消失
        code = exc.code if isinstance(exc.code, int) else 1
        detail = str(exc) or f"（退出码 {code}）"
        if code != 0:
            return _fatal(
                "启动失败",
                f"程序在启动过程中主动退出。\n\n{detail}\n\n"
                "如果提示缺少配置文件，请重新解压完整压缩包。",
            )
        return 0
    except Exception:
        detail = traceback.format_exc()
        return _fatal(
            "界面启动失败",
            "程序在启动界面时出错。\n\n"
            "请把下面的信息发给开发者。\n\n"
            + detail[-1500:],
        )


if __name__ == "__main__":
    sys.exit(main())
