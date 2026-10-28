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
    --diag           打印运行环境诊断信息（排查启动问题用）

打包为窗口程序（console=False）：双击不会出现黑色控制台窗口。
启动期异常写入 startup-trace.log，并在必要时弹出对话框说明。
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

CLI_FLAGS = {"--daemon", "--once", "--check", "--force-login", "--diag",
             "--quiet", "-v", "--verbose", "-c", "--config", "-h", "--help"}


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
    try:
        import startup_trace

        startup_trace.trace(f"致命错误：{title}\n{message}")
    except Exception:
        pass
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


def _diag() -> int:
    """打印运行环境诊断信息，写入 startup-trace.log 并输出到控制台。"""
    lines = [
        "校园网自动登录 - 环境诊断",
        "=" * 56,
        f"版本          : {_version()}",
        f"打包模式      : {'exe' if getattr(sys, 'frozen', False) else '源码'}",
        f"可执行文件    : {sys.executable}",
        f"_MEIPASS      : {getattr(sys, '_MEIPASS', '(无)')}",
        f"数据目录      : {_app_dir()}",
        f"Python        : {sys.version.split()[0]}",
        f"系统          : {sys.getwindowsversion()}",
        f"当前目录      : {Path.cwd()}",
        "",
        f"资源目录      : {_runtime_root()}",
    ]

    base = _runtime_root()
    for name in ("_tcl_data", "_tk_data", "assets"):
        target = base / name
        lines.append(f"  {name:12}: {'存在' if target.is_dir() else '缺失'}")

    internal = base
    dlls = list(internal.glob("python3*.dll")) if internal.is_dir() else []
    lines.append(f"  python dll  : {'存在 ' + dlls[0].name if dlls else '缺失'}")

    try:
        import tkinter

        lines.append(f"  tkinter     : 可用 (Tk {tkinter.TkVersion})")
    except Exception as exc:
        lines.append(f"  tkinter     : 不可用 ({exc})")

    for name in ("auto_login", "gui", "motw", "console"):
        try:
            __import__(name)
            lines.append(f"  模块 {name:12}: 正常")
        except Exception as exc:
            lines.append(f"  模块 {name:12}: 导入失败 ({exc})")

    report = "\n".join(lines)
    try:
        out = _app_dir() / "diagnose.txt"
        out.write_text(report + "\n", encoding="utf-8")
    except Exception:
        pass

    try:
        print(report)
    except Exception:
        pass

    # --quiet：只写文件不弹窗，方便另一台机器用脚本调用时不被对话框卡住
    if "--quiet" not in sys.argv:
        _message_box(
            "环境诊断完成",
            report + "\n\n已写入 diagnose.txt，可把这个文件发给开发者。",
        )
    return 0


def _version() -> str:
    try:
        import auto_login

        return auto_login.APP_VERSION
    except Exception:
        return "未知"


def main() -> int:
    argv = sys.argv[1:]
    cli_mode = _is_cli(argv)

    # 最早的追踪点：此时还没导入任何项目模块
    try:
        import startup_trace

        startup_trace.reset()
        startup_trace.trace("入口开始")
    except Exception:
        startup_trace = None  # type: ignore

    if "--diag" in argv:
        return _diag()

    problem = _check_runtime()
    if problem:
        return _fatal("启动失败", problem)

    if startup_trace:
        startup_trace.trace("依赖检查通过")

    # 清除「来自网络」标记：只处理 exe 自身，后台执行，不阻塞
    try:
        import motw

        motw.self_heal_async()
        if startup_trace:
            startup_trace.trace("MOTW 自愈已排入后台")
    except Exception:
        if startup_trace:
            startup_trace.trace_exception("MOTW 自愈失败（忽略）")

    if cli_mode:
        if startup_trace:
            startup_trace.trace(f"进入命令行模式 argv={argv}")
        import auto_login as core

        try:
            return core.main(argv)
        except SystemExit as exc:
            # argparse 的 --help / 参数错误会走这里，属于正常流程
            code = exc.code if isinstance(exc.code, int) else 0
            if startup_trace:
                startup_trace.trace(f"命令行退出，返回 {code}")
            return code
        except BaseException:
            if startup_trace:
                startup_trace.trace_exception("命令行模式异常")
            raise

    # 界面模式
    if startup_trace:
        startup_trace.trace("进入界面模式")
    try:
        from gui import main as gui_main

        code = gui_main()
        if startup_trace:
            startup_trace.trace(f"界面退出，返回 {code}")
        return code
    except SystemExit as exc:
        # 兜底：任何模块调用 sys.exit() 都不该让窗口静默消失
        code = exc.code if isinstance(exc.code, int) else 1
        detail = str(exc) or f"（退出码 {code}）"
        if startup_trace:
            startup_trace.trace(f"界面内触发 SystemExit：{detail}")
        if code != 0:
            return _fatal(
                "启动失败",
                f"程序在启动过程中主动退出。\n\n{detail}\n\n"
                "如果提示缺少配置文件，请重新解压完整压缩包，"
                "或在目录里放一份 config.ini。",
            )
        return 0
    except BaseException:
        detail = traceback.format_exc()
        if startup_trace:
            startup_trace.trace(f"界面异常\n{detail}")
        return _fatal(
            "界面启动失败",
            "程序在启动界面时出错。\n\n"
            "详细信息已写入 startup-trace.log，请把这个文件发给开发者。\n\n"
            + detail[-1500:],
        )


if __name__ == "__main__":
    sys.exit(main())
