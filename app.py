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

打包成 exe 后仍然只需这一个文件。
"""

from __future__ import annotations

import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    RES_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
else:
    RES_DIR = Path(__file__).resolve().parent

sys.path.insert(0, str(RES_DIR))

# 守护模式相关参数：出现任意一个就走命令行逻辑，不启动界面
CLI_FLAGS = {"--daemon", "--once", "--check", "--force-login", "-v", "--verbose",
             "-c", "--config", "-h", "--help"}


def _is_cli(argv: list[str]) -> bool:
    return any(arg in CLI_FLAGS or arg.startswith("--config=") for arg in argv)


def main() -> int:
    argv = sys.argv[1:]

    if _is_cli(argv):
        import auto_login as core

        return core.main(argv)

    # 界面模式：--daemon 以外的情况才到这里
    from gui import main as gui_main

    return gui_main()


if __name__ == "__main__":
    sys.exit(main())
