#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
校园网自动登录 - 现代界面
==========================

纯 tkinter 自绘实现的现代 UI（无第三方依赖）：
- 侧边栏导航 + 主区卡片布局
- 自绘圆角卡片、渐变主按钮、开关（Switch）控件
- 深色 / 浅色双主题，可在界面上切换
- 状态环 + 实时指标 + 日志流

底层逻辑全部复用 auto_login.py。
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

# 打包成 exe 后 sys._MEIPASS 才是资源目录；源码运行时是脚本目录
if getattr(sys, "frozen", False):
    RES_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
else:
    RES_DIR = Path(__file__).resolve().parent


def _fix_tcl_env() -> None:
    """打包后 Tcl/Tk 的库路径需要显式指定，否则窗口初始化会崩。"""
    if not getattr(sys, "frozen", False):
        return
    base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    candidates = [
        (base / "tcl", base / "tk"),
        (base / "tcl8.6", base / "tk8.6"),
        (base / "_tcl_data", base / "_tk_data"),
        (base / "lib" / "tcl8.6", base / "lib" / "tk8.6"),
    ]
    for tcl_dir, tk_dir in candidates:
        if (tcl_dir / "init.tcl").is_file():
            os.environ["TCL_LIBRARY"] = str(tcl_dir)
            os.environ["TK_LIBRARY"] = str(tk_dir)
            return


_fix_tcl_env()

sys.path.insert(0, str(RES_DIR))

import auto_login as core  # noqa: E402

APP_TITLE = "校园网自动登录"
APP_VERSION = core.APP_VERSION

CONFIG_PATH = core.DEFAULT_CONFIG
LOG_PATH = core.LOG_FILE

OPERATORS = [
    ("校园网", ""),
    ("中国联通", "@cucc"),
    ("中国电信", "@ctc"),
    ("中国移动", "@zgyd"),
]

INTERVAL_PRESETS = [60, 120, 300, 600, 1800, 3600]


# --------------------------------------------------------------------------- #
# 主题
# --------------------------------------------------------------------------- #
class Theme:
    LIGHT = {
        "bg": "#F5F7FA",
        "sidebar": "#FFFFFF",
        "card": "#FFFFFF",
        "card_border": "#E8ECF2",
        "text": "#1A1D24",
        "text_sub": "#6B7280",
        "text_muted": "#9CA3AF",
        "accent": "#2563EB",
        "accent_hover": "#1D4ED8",
        "accent_soft": "#EFF4FF",
        "ok": "#16A34A",
        "ok_soft": "#EAF7EE",
        "warn": "#F59E0B",
        "warn_soft": "#FFF7E6",
        "bad": "#DC2626",
        "bad_soft": "#FEF0F0",
        "field": "#F7F9FC",
        "field_border": "#DDE3EC",
        "switch_off": "#D5DBE5",
        "log_bg": "#0F172A",
        "log_fg": "#D7E0EE",
        "log_time": "#64748B",
        "log_info": "#7DD3FC",
        "log_warn": "#FCD34D",
        "log_err": "#FCA5A5",
        "shadow": "#E4E9F1",
        "hover": "#F0F3F8",
    }
    DARK = {
        "bg": "#0F1419",
        "sidebar": "#151B22",
        "card": "#1A222B",
        "card_border": "#253040",
        "text": "#E8EDF4",
        "text_sub": "#94A3B8",
        "text_muted": "#64748B",
        "accent": "#3B82F6",
        "accent_hover": "#60A5FA",
        "accent_soft": "#1E2C45",
        "ok": "#22C55E",
        "ok_soft": "#14291C",
        "warn": "#FBBF24",
        "warn_soft": "#2A2312",
        "bad": "#F87171",
        "bad_soft": "#2C1719",
        "field": "#141B23",
        "field_border": "#2A3646",
        "switch_off": "#39465A",
        "log_bg": "#0B1016",
        "log_fg": "#CBD5E1",
        "log_time": "#64748B",
        "log_info": "#7DD3FC",
        "log_warn": "#FCD34D",
        "log_err": "#FCA5A5",
        "shadow": "#0B1016",
        "hover": "#212B37",
    }


FONT_FAMILY = "Microsoft YaHei UI"


def font(size: int, weight: str = "normal") -> tuple:
    return (FONT_FAMILY, size, weight)


# --------------------------------------------------------------------------- #
# 自绘基础控件
# --------------------------------------------------------------------------- #
class Card(tk.Frame):
    """圆角卡片：背景 Canvas 用 place 铺满，内容体用 grid 自适应尺寸。"""

    def __init__(self, master, theme: Theme, padding: int = 18, radius: int = 14, **kw):
        self.t = theme
        self.radius = radius
        self.padding = padding
        super().__init__(master, bg=theme["bg"], **kw)
        self._bg = tk.Canvas(self, bg=theme["bg"], highlightthickness=0, bd=0)
        self.body = tk.Frame(self, bg=theme["card"])
        self.body.grid(row=0, column=0, padx=padding, pady=padding, sticky="nsew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.bind("<Configure>", self._redraw)

    def set_theme(self, theme: Theme) -> None:
        self.t = theme
        self.configure(bg=theme["bg"])
        self._bg.configure(bg=theme["bg"])
        self.body.configure(bg=theme["card"])
        self._redraw()

    def _redraw(self, _event=None) -> None:
        cv = self._bg
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4 or h < 4:
            return
        cv.place(x=0, y=0, width=w, height=h)
        cv.delete("all")
        r = self.radius
        t = self.t
        cv.create_rectangle(0, 0, w, h, fill=t["bg"], outline="")
        _rounded(cv, 0, 0, w, h, r, t["card_border"])
        _rounded(cv, 1, 1, w - 1, h - 1, r - 1, t["card"])
        cv.tag_lower("all")


def _rounded(cv, x1, y1, x2, y2, r, fill, width=1, outline=False) -> None:
    """在 Canvas 上画圆角矩形（填充矩形 + 四角扇形）。"""
    r = max(0, r)
    if outline:
        cv.create_line(x1 + r, y1, x2 - r, y1, fill=fill, width=width)
        cv.create_line(x1 + r, y2, x2 - r, y2, fill=fill, width=width)
        cv.create_line(x1, y1 + r, x1, y2 - r, fill=fill, width=width)
        cv.create_line(x2, y1 + r, x2, y2 - r, fill=fill, width=width)
        for cx, cy, start in (
            (x1, y1, 90), (x2 - 2 * r, y1, 0),
            (x1, y2 - 2 * r, 180), (x2 - 2 * r, y2 - 2 * r, 270),
        ):
            cv.create_arc(cx, cy, cx + 2 * r, cy + 2 * r, start=start, extent=90,
                          style="arc", outline=fill, width=width)
        return
    cv.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline="")
    cv.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, outline="")
    for cx, cy in (
        (x1, y1), (x2 - 2 * r, y1), (x1, y2 - 2 * r), (x2 - 2 * r, y2 - 2 * r),
    ):
        cv.create_oval(cx, cy, cx + 2 * r, cy + 2 * r, fill=fill, outline="")


class RoundedButton(tk.Canvas):
    """圆角按钮，支持 primary / ghost / danger 三种风格。"""

    STYLES = ("primary", "ghost", "danger", "subtle")

    def __init__(
        self,
        master,
        text: str,
        command=None,
        theme: Theme = None,
        style: str = "ghost",
        width: int = 108,
        height: int = 38,
        radius: int = 9,
        font_size: int = 10,
        **kw,
    ):
        self.t = theme
        self.text = text
        self.command = command
        self.style = style if style in self.STYLES else "ghost"
        self.radius = radius
        self._enabled = True
        self._hover = False
        super().__init__(
            master, width=width, height=height, highlightthickness=0, bd=0,
            bg=theme["card"], **kw
        )
        self._font = font(font_size, "bold" if style == "primary" else "normal")
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Configure>", lambda e: self._redraw())
        self._redraw()

    def set_theme(self, theme: Theme, parent_bg: str | None = None) -> None:
        self.t = theme
        self.configure(bg=parent_bg or theme["card"])
        self._redraw()

    def set_text(self, text: str) -> None:
        self.text = text
        self._redraw()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.configure(cursor="hand2" if enabled else "arrow")
        self._redraw()

    def _colors(self):
        t = self.t
        if not self._enabled:
            return (t["field"], t["text_muted"])
        if self.style == "primary":
            return (t["accent_hover"] if self._hover else t["accent"], "#FFFFFF")
        if self.style == "danger":
            return (t["bad_soft"] if self._hover else t["card"], t["bad"])
        if self.style == "subtle":
            return (t["hover"] if self._hover else t["accent_soft"], t["accent"])
        return (t["hover"] if self._hover else t["card"], t["text"])

    def _redraw(self) -> None:
        self.delete("all")
        w = self.winfo_width() or int(self["width"])
        h = self.winfo_height() or int(self["height"])
        if w < 4 or h < 4:
            return
        bg, fg = self._colors()
        t = self.t
        r = self.radius
        if self.style == "ghost":
            self._round_rect(0.5, 0.5, w - 0.5, h - 0.5, r, t["card_border"], "outline")
            self._round_rect(1.5, 1.5, w - 1.5, h - 1.5, r - 1, bg, "fill")
        else:
            self._round_rect(0, 0, w, h, r, bg, "fill")
        self.create_text(w / 2, h / 2, text=self.text, fill=fg, font=self._font)

    def _round_rect(self, x1, y1, x2, y2, r, fill, tag) -> None:
        r = max(0, r)
        self.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline="", tags=tag)
        self.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, outline="", tags=tag)
        for cx, cy in ((x1, y1), (x2 - 2 * r, y1), (x1, y2 - 2 * r), (x2 - 2 * r, y2 - 2 * r)):
            self.create_oval(cx, cy, cx + 2 * r, cy + 2 * r, fill=fill, outline="", tags=tag)

    def _on_enter(self, _e):
        if not self._enabled:
            return
        self._hover = True
        self.configure(cursor="hand2")
        self._redraw()

    def _on_leave(self, _e):
        self._hover = False
        self._redraw()

    def _on_press(self, _e):
        if self._enabled:
            self._pressed = True

    def _on_release(self, _e):
        if not self._enabled or not getattr(self, "_pressed", False):
            return
        self._pressed = False
        if self.command:
            self.command()


class Switch(tk.Canvas):
    """现代开关控件。"""

    def __init__(self, master, theme: Theme, variable: tk.BooleanVar, command=None, width=46, height=26):
        self.t = theme
        self.var = variable
        self.command = command
        self.w = width
        self.h = height
        super().__init__(master, width=width, height=height, highlightthickness=0, bd=0, bg=theme["card"])
        self.bind("<Button-1>", self._toggle)
        self.bind("<Configure>", lambda e: self._redraw())
        self.configure(cursor="hand2")
        self._redraw()

    def set_theme(self, theme: Theme, parent_bg: str | None = None) -> None:
        self.t = theme
        self.configure(bg=parent_bg or theme["card"])
        self._redraw()

    def _toggle(self, _e=None):
        self.var.set(not self.var.get())
        self._redraw()
        if self.command:
            self.command()

    def _redraw(self):
        self.delete("all")
        t = self.t
        w, h = self.w, self.h
        r = h / 2
        on = bool(self.var.get())
        track = t["accent"] if on else t["switch_off"]
        self._pill(0, 0, w, h, r, track)
        knob_r = r - 3
        cx = (w - r) if on else r
        self.create_oval(
            cx - knob_r, h / 2 - knob_r, cx + knob_r, h / 2 + knob_r,
            fill="#FFFFFF", outline=""
        )

    def _pill(self, x1, y1, x2, y2, r, fill):
        self.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline="")
        self.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, outline="")
        for cx, cy in ((x1, y1), (x2 - 2 * r, y1), (x1, y2 - 2 * r), (x2 - 2 * r, y2 - 2 * r)):
            self.create_oval(cx, cy, cx + 2 * r, cy + 2 * r, fill=fill, outline="")


class RoundEntry(tk.Frame):
    """带圆角背景的输入框容器（Entry 本身仍是原生控件，保证可编辑）。"""

    def __init__(self, master, theme: Theme, show: str = "", width: int = 260):
        self.t = theme
        super().__init__(master, bg=theme["card"])
        self.canvas = tk.Canvas(self, height=40, width=width, highlightthickness=0, bd=0, bg=theme["card"])
        self.canvas.pack(fill="x")
        self.entry = tk.Entry(
            self.canvas,
            bd=0,
            relief="flat",
            bg=theme["field"],
            fg=theme["text"],
            insertbackground=theme["text"],
            font=font(10),
            show=show,
        )
        self._win = self.canvas.create_window(14, 20, window=self.entry, anchor="w", width=width - 28)
        self.bind("<Configure>", self._redraw)
        self._redraw()

    def set_theme(self, theme: Theme) -> None:
        self.t = theme
        self.configure(bg=theme["card"])
        self.canvas.configure(bg=theme["card"])
        self.entry.configure(
            bg=theme["field"], fg=theme["text"], insertbackground=theme["text"]
        )
        self._redraw()

    def _redraw(self, _e=None):
        self.canvas.delete("bg")
        w = self.canvas.winfo_width()
        if w < 8:
            return
        h = 40
        r = 9
        t = self.t
        self._round(self.canvas, 0, 0, w, h, r, t["field"], "bg")
        self._round(self.canvas, 0.5, 0.5, w - 0.5, h - 0.5, r, t["field_border"], "bg", outline=True)
        self.canvas.tag_lower("bg")

    @staticmethod
    def _round(cv, x1, y1, x2, y2, r, fill, tag, outline=False):
        if outline:
            cv.create_line(x1 + r, y1, x2 - r, y1, fill=fill, width=1, tags=tag)
            cv.create_line(x1 + r, y2, x2 - r, y2, fill=fill, width=1, tags=tag)
            cv.create_line(x1, y1 + r, x1, y2 - r, fill=fill, width=1, tags=tag)
            cv.create_line(x2, y1 + r, x2, y2 - r, fill=fill, width=1, tags=tag)
            for cx, cy, s in ((x1, y1, 90), (x2 - 2 * r, y1, 0), (x1, y2 - 2 * r, 180), (x2 - 2 * r, y2 - 2 * r, 270)):
                cv.create_arc(cx, cy, cx + 2 * r, cy + 2 * r, start=s, extent=90, style="arc", outline=fill, tags=tag)
            return
        cv.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline="", tags=tag)
        cv.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, outline="", tags=tag)
        for cx, cy in ((x1, y1), (x2 - 2 * r, y1), (x1, y2 - 2 * r), (x2 - 2 * r, y2 - 2 * r)):
            cv.create_oval(cx, cy, cx + 2 * r, cy + 2 * r, fill=fill, outline="", tags=tag)


class StatusRing(tk.Canvas):
    """状态环：外圈进度动效 + 中心状态图标。"""

    def __init__(self, master, theme: Theme, size: int = 132):
        self.t = theme
        self.size = size
        self.state = "idle"   # idle | ok | bad | busy
        self._angle = 0
        self._animating = False
        super().__init__(master, width=size, height=size, highlightthickness=0, bd=0, bg=theme["card"])
        self._redraw()
        self._animate()

    def set_theme(self, theme: Theme, parent_bg: str | None = None):
        self.t = theme
        self.configure(bg=parent_bg or theme["card"])
        self._redraw()

    def set_state(self, state: str):
        if state != self.state:
            self.state = state
            self._redraw()

    def _colors(self):
        t = self.t
        if self.state == "ok":
            return t["ok"], t["ok_soft"]
        if self.state == "bad":
            return t["bad"], t["bad_soft"]
        if self.state == "busy":
            return t["accent"], t["accent_soft"]
        return t["text_muted"], t["field"]

    def _redraw(self):
        self.delete("static")
        s = self.size
        pad = 10
        color, soft = self._colors()
        self.create_oval(pad, pad, s - pad, s - pad, fill=soft, outline="", tags="static")
        # 中心图标
        cx = cy = s / 2
        if self.state == "ok":
            self._check(cx, cy, color)
        elif self.state == "bad":
            self._cross(cx, cy, color)
        elif self.state == "busy":
            self._dots(cx, cy, color)
        else:
            self.create_oval(cx - 9, cy - 9, cx + 9, cy + 9, outline=color, width=3, tags="static")

    def _check(self, cx, cy, color):
        self.create_line(cx - 17, cy + 1, cx - 5, cy + 13, fill=color, width=5,
                         capstyle="round", joinstyle="round", tags="static")
        self.create_line(cx - 5, cy + 13, cx + 18, cy - 12, fill=color, width=5,
                         capstyle="round", joinstyle="round", tags="static")

    def _cross(self, cx, cy, color):
        for dx in (-1, 1):
            self.create_line(cx - 14 * dx, cy - 14, cx + 14 * dx, cy + 14,
                             fill=color, width=5, capstyle="round", tags="static")

    def _dots(self, cx, cy, color):
        for i in range(3):
            x = cx - 16 + i * 16
            self.create_oval(x - 4, cy - 4, x + 4, cy + 4, fill=color, outline="", tags="static")

    def _animate(self):
        if self.state == "busy":
            self.delete("spin")
            s = self.size
            pad = 6
            self.create_arc(pad, pad, s - pad, s - pad, start=self._angle, extent=70,
                            style="arc", outline=self.t["accent"], width=3, tags="spin")
            self._angle = (self._angle + 12) % 360
        else:
            self.delete("spin")
        self.after(50, self._animate)


class Toast(tk.Toplevel):
    """轻量提示条。"""

    def __init__(self, master, text: str, theme: Theme, kind: str = "info", duration: int = 2600):
        super().__init__(master)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        t = theme
        fg = {"info": t["accent"], "ok": t["ok"], "warn": t["warn"], "bad": t["bad"]}.get(kind, t["accent"])
        bg = {"info": t["accent_soft"], "ok": t["ok_soft"], "warn": t["warn_soft"], "bad": t["bad_soft"]}.get(kind, t["accent_soft"])

        frame = tk.Frame(self, bg=bg, padx=18, pady=11)
        frame.pack()
        tk.Label(frame, text=text, bg=bg, fg=fg, font=font(10), wraplength=360, justify="left").pack()

        self.update_idletasks()
        w = self.winfo_reqwidth()
        h = self.winfo_reqheight()
        mx = master.winfo_rootx() + (master.winfo_width() - w) // 2
        my = master.winfo_rooty() + master.winfo_height() - h - 48
        self.geometry(f"{w}x{h}+{max(mx, 0)}+{max(my, 0)}")
        self.after(duration, self.destroy)


# --------------------------------------------------------------------------- #
# 主窗口
# --------------------------------------------------------------------------- #
class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1080x720")
        self.minsize(960, 660)
        # 界面自身也要写日志：手动检测 / 登录都必须落盘
        self._ensure_logging()
        self.dark = core.read_json(Path(core.APP_DIR) / "ui_state.json").get("dark", False)
        self.t = Theme.DARK if self.dark else Theme.LIGHT

        self._apply_window_icon()
        self.configure(bg=self.t["bg"])

        self._busy = False
        self._ui_queue: queue.Queue = queue.Queue()
        self._log_pos = 0
        self._last_log_size = 0
        self._page = "dashboard"
        self._nav_items: dict[str, tk.Frame] = {}

        # 变量
        self.var_username = tk.StringVar()
        self.var_password = tk.StringVar()
        self.var_operator = tk.StringVar(value="校园网")
        self.var_interval = tk.StringVar(value="300")
        self.var_autostart = tk.BooleanVar(value=False)
        self.var_show_pw = tk.BooleanVar(value=False)

        self.var_status = tk.StringVar(value="正在读取状态…")
        self.var_detail = tk.StringVar(value="")
        self.var_action = tk.StringVar(value="")
        self.var_account = tk.StringVar(value="")
        self.var_ip = tk.StringVar(value="—")
        self.var_mac = tk.StringVar(value="—")
        self.var_checks = tk.StringVar(value="0")
        self.var_logins = tk.StringVar(value="0")
        self.var_next = tk.StringVar(value="—")

        self._build()
        self._load_config()
        self._refresh_autostart()
        self._refresh_status()
        self._tick()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ 基础
    @staticmethod
    def _ensure_logging() -> None:
        """确保 core.log 已挂上文件 handler（幂等）。"""
        try:
            if core.log.handlers:
                return
            cfg = core.load_config(CONFIG_PATH)
            core.setup_logging(cfg, verbose=False)
        except Exception:
            pass

    def _apply_window_icon(self) -> None:
        ico = RES_DIR / "assets" / "app.ico"
        try:
            if ico.is_file():
                self.iconbitmap(default=str(ico))
        except Exception:
            pass

    def _build(self) -> None:
        self.sidebar = tk.Frame(self, bg=self.t["sidebar"], width=216)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        self.main = tk.Frame(self, bg=self.t["bg"])
        self.main.pack(side="left", fill="both", expand=True)

        self._build_sidebar()
        self._build_pages()

    # ------------------------------------------------------------------ 侧栏
    def _build_sidebar(self) -> None:
        t = self.t
        head = tk.Frame(self.sidebar, bg=t["sidebar"])
        head.pack(fill="x", pady=(26, 22), padx=20)

        try:
            from tkinter import PhotoImage

            png = RES_DIR / "assets" / "app_64.png"
            if png.is_file():
                self.logo_img = PhotoImage(file=str(png))
                tk.Label(head, image=self.logo_img, bg=t["sidebar"]).pack(side="left")
        except Exception:
            pass

        text_box = tk.Frame(head, bg=t["sidebar"])
        text_box.pack(side="left", padx=(10, 0))
        tk.Label(text_box, text="校园网", bg=t["sidebar"], fg=t["text"],
                 font=font(12, "bold")).pack(anchor="w")
        tk.Label(text_box, text="自动登录", bg=t["sidebar"], fg=t["text_sub"],
                 font=font(9)).pack(anchor="w")

        self._nav("dashboard", "◈", "总览")
        self._nav("account", "⚙", "账号设置")
        self._nav("logs", "≡", "运行日志")
        self._nav("about", "ⓘ", "关于")

        spacer = tk.Frame(self.sidebar, bg=t["sidebar"])
        spacer.pack(fill="both", expand=True)

        # 主题切换
        bottom = tk.Frame(self.sidebar, bg=t["sidebar"])
        bottom.pack(fill="x", padx=16, pady=(0, 20))
        self.btn_theme = RoundedButton(
            bottom,
            "☾  深色模式" if not self.dark else "☀  浅色模式",
            command=self._toggle_theme,
            theme=t, style="ghost", width=184, height=36, font_size=9,
        )
        self.btn_theme.pack(fill="x")
        self.btn_theme.configure(bg=t["sidebar"])

        tk.Label(bottom, text=f"v{APP_VERSION}", bg=t["sidebar"], fg=t["text_muted"],
                 font=font(8)).pack(pady=(10, 0))

    def _nav(self, key: str, icon: str, label: str) -> None:
        t = self.t
        item = tk.Frame(self.sidebar, bg=t["sidebar"], cursor="hand2")
        item.pack(fill="x", padx=12, pady=2)
        inner = tk.Frame(item, bg=t["sidebar"], padx=12, pady=9)
        inner.pack(fill="x")
        lbl_icon = tk.Label(inner, text=icon, bg=t["sidebar"], fg=t["text_sub"], font=font(12))
        lbl_icon.pack(side="left")
        lbl_text = tk.Label(inner, text=label, bg=t["sidebar"], fg=t["text_sub"], font=font(10))
        lbl_text.pack(side="left", padx=(10, 0))

        for w in (item, inner, lbl_icon, lbl_text):
            w.bind("<Button-1>", lambda e, k=key: self._show_page(k))
            w.bind("<Enter>", lambda e, f=inner: self._nav_hover(f, True))
            w.bind("<Leave>", lambda e, f=inner: self._nav_hover(f, False))

        self._nav_items[key] = {"row": item, "inner": inner, "icon": lbl_icon, "text": lbl_text}

    def _nav_hover(self, frame: tk.Frame, entering: bool) -> None:
        t = self.t
        active = self._page == self._key_of(frame)
        if active:
            return
        frame.configure(bg=t["hover"] if entering else t["sidebar"])

    def _key_of(self, frame: tk.Frame) -> str:
        for k, v in self._nav_items.items():
            if v["inner"] is frame:
                return k
        return ""

    def _mark_nav(self, key: str) -> None:
        t = self.t
        for k, v in self._nav_items.items():
            if k == key:
                v["inner"].configure(bg=t["accent_soft"])
                v["icon"].configure(bg=t["accent_soft"], fg=t["accent"])
                v["text"].configure(bg=t["accent_soft"], fg=t["accent"], font=font(10, "bold"))
            else:
                v["inner"].configure(bg=t["sidebar"])
                v["icon"].configure(bg=t["sidebar"], fg=t["text_sub"])
                v["text"].configure(bg=t["sidebar"], fg=t["text_sub"], font=font(10))

    # ------------------------------------------------------------------ 页面容器
    def _build_pages(self) -> None:
        self.pages: dict[str, tk.Frame] = {}
        for key in ("dashboard", "account", "logs", "about"):
            frame = tk.Frame(self.main, bg=self.t["bg"])
            self.pages[key] = frame

        self._build_dashboard(self.pages["dashboard"])
        self._build_account(self.pages["account"])
        self._build_logs(self.pages["logs"])
        self._build_about(self.pages["about"])

        self._show_page("dashboard")

    def _show_page(self, key: str) -> None:
        self._page = key
        for k, frame in self.pages.items():
            frame.pack_forget()
        self.pages[key].pack(fill="both", expand=True)
        self._mark_nav(key)
        if key == "logs":
            self._reload_log(force=True)

    # ------------------------------------------------------------------ 总览页
    def _build_dashboard(self, parent: tk.Frame) -> None:
        t = self.t
        wrap = tk.Frame(parent, bg=t["bg"])
        wrap.pack(fill="both", expand=True, padx=28, pady=(24, 20))

        header = tk.Frame(wrap, bg=t["bg"])
        header.pack(fill="x")
        tk.Label(header, text="总览", bg=t["bg"], fg=t["text"], font=font(18, "bold")).pack(side="left")
        self.lbl_header_sub = tk.Label(header, text="", bg=t["bg"], fg=t["text_muted"], font=font(9))
        self.lbl_header_sub.pack(side="left", padx=(12, 0), pady=(6, 0))

        body = tk.Frame(wrap, bg=t["bg"])
        body.pack(fill="both", expand=True, pady=(16, 0))
        body.columnconfigure(0, weight=1, uniform="col")
        body.columnconfigure(1, weight=1, uniform="col")
        body.rowconfigure(2, weight=1)   # 底部弹性空白，卡片保持内容高度

        # ---- 左上：状态卡 ----
        status_card = Card(body, t, padding=20)
        status_card.grid(row=0, column=0, sticky="new", padx=(0, 8), pady=(0, 8))
        sb = status_card.body

        top_row = tk.Frame(sb, bg=t["card"])
        top_row.pack(fill="x")

        self.ring = StatusRing(top_row, t, size=104)
        self.ring.pack(side="left", padx=(0, 16))

        info = tk.Frame(top_row, bg=t["card"])
        info.pack(side="left", fill="both", expand=True)
        self.lbl_status = tk.Label(info, textvariable=self.var_status, bg=t["card"],
                                   fg=t["text"], font=font(16, "bold"))
        self.lbl_status.pack(anchor="w", pady=(14, 3))
        self.lbl_detail = tk.Label(info, textvariable=self.var_detail, bg=t["card"],
                                   fg=t["text_sub"], font=font(9), wraplength=260, justify="left")
        self.lbl_detail.pack(anchor="w")
        self.lbl_account = tk.Label(info, textvariable=self.var_account, bg=t["card"],
                                    fg=t["text_muted"], font=font(9))
        self.lbl_account.pack(anchor="w", pady=(6, 0))

        tk.Frame(sb, bg=t["card_border"], height=1).pack(fill="x", pady=16)

        actions = tk.Frame(sb, bg=t["card"])
        actions.pack(fill="x")
        self.btn_start = RoundedButton(actions, "启动守护", command=self._on_start,
                                       theme=t, style="primary", width=104, height=36)
        self.btn_start.pack(side="left")
        self.btn_stop = RoundedButton(actions, "停止守护", command=self._on_stop,
                                      theme=t, style="ghost", width=100, height=36)
        self.btn_stop.pack(side="left", padx=(8, 0))
        self.btn_check = RoundedButton(actions, "检测", command=lambda: self._run_task(self._task_check),
                                       theme=t, style="ghost", width=76, height=36)
        self.btn_check.pack(side="left", padx=(8, 0))
        self.btn_login = RoundedButton(actions, "登录", command=lambda: self._run_task(self._task_force_login),
                                       theme=t, style="subtle", width=76, height=36)
        self.btn_login.pack(side="left", padx=(8, 0))

        # ---- 右上：指标 + 开机自启 ----
        right_top = tk.Frame(body, bg=t["bg"])
        right_top.grid(row=0, column=1, sticky="new", padx=(8, 0), pady=(0, 8))
        right_top.columnconfigure(0, weight=1)
        right_top.columnconfigure(1, weight=1)

        self._metric(right_top, 0, 0, "检测次数", self.var_checks, t["accent"])
        self._metric(right_top, 0, 1, "登录尝试", self.var_logins, t["warn"])

        auto_card = Card(right_top, t, padding=18)
        auto_card.grid(row=1, column=0, columnspan=2, sticky="new", pady=(8, 0))
        ab = auto_card.body
        row = tk.Frame(ab, bg=t["card"])
        row.pack(fill="x")
        left_col = tk.Frame(row, bg=t["card"])
        left_col.pack(side="left", fill="x", expand=True)
        tk.Label(left_col, text="开机自动启动", bg=t["card"], fg=t["text"],
                 font=font(11, "bold")).pack(anchor="w")
        tk.Label(left_col, text="登录 Windows 后静默运行，不弹窗口", bg=t["card"],
                 fg=t["text_muted"], font=font(9)).pack(anchor="w", pady=(3, 0))
        self.switch_auto = Switch(row, t, self.var_autostart, command=self._on_toggle_autostart)
        self.switch_auto.pack(side="right", pady=(4, 0))

        # ---- 左下：连接信息 ----
        info_card = Card(body, t, padding=20)
        info_card.grid(row=1, column=0, sticky="new", padx=(0, 8), pady=(8, 0))
        ib = info_card.body
        tk.Label(ib, text="连接信息", bg=t["card"], fg=t["text"],
                 font=font(11, "bold")).pack(anchor="w", pady=(0, 12))
        self._kv(ib, "本机 IP", self.var_ip)
        self._kv(ib, "MAC 地址", self.var_mac)
        self._kv(ib, "认证门户", tk.StringVar(value="10.9.1.3:801"))
        self._kv(ib, "下次检测", self.var_next)

        # ---- 右下：最近事件 ----
        event_card = Card(body, t, padding=20)
        event_card.grid(row=1, column=1, sticky="new", padx=(8, 0), pady=(8, 0))
        eb = event_card.body
        tk.Label(eb, text="最近事件", bg=t["card"], fg=t["text"],
                 font=font(11, "bold")).pack(anchor="w", pady=(0, 10))
        self.lbl_event = tk.Label(
            eb, textvariable=self.var_detail, bg=t["card"], fg=t["text_sub"],
            font=font(9), justify="left", anchor="nw", wraplength=320,
        )
        self.lbl_event.pack(anchor="w", fill="x")
        self.lbl_action = tk.Label(
            eb, textvariable=self.var_action, bg=t["card"], fg=t["text_muted"],
            font=font(9), justify="left", anchor="nw", wraplength=320,
        )
        self.lbl_action.pack(anchor="w", fill="x", pady=(8, 0))

    def _metric(self, parent, row: int, col: int, label: str, var, color: str) -> None:
        t = self.t
        card = Card(parent, t, padding=16)
        card.grid(row=row, column=col, sticky="nsew", padx=(0 if col == 0 else 8, 0))
        b = card.body
        tk.Label(b, text=label, bg=t["card"], fg=t["text_muted"], font=font(9)).pack(anchor="w")
        tk.Label(b, textvariable=var, bg=t["card"], fg=color,
                 font=font(20, "bold")).pack(anchor="w", pady=(2, 0))

    def _kv(self, parent, key: str, var) -> None:
        t = self.t
        row = tk.Frame(parent, bg=t["card"])
        row.pack(fill="x", pady=5)
        tk.Label(row, text=key, bg=t["card"], fg=t["text_muted"], font=font(9), width=9,
                 anchor="w").pack(side="left")
        tk.Label(row, textvariable=var, bg=t["card"], fg=t["text"], font=font(9),
                 anchor="e").pack(side="right")

    # ------------------------------------------------------------------ 账号页
    def _build_account(self, parent: tk.Frame) -> None:
        t = self.t
        wrap = tk.Frame(parent, bg=t["bg"])
        wrap.pack(fill="both", expand=True, padx=28, pady=(24, 24))

        tk.Label(wrap, text="账号设置", bg=t["bg"], fg=t["text"],
                 font=font(18, "bold")).pack(anchor="w")
        tk.Label(wrap, text="账号密码只保存在本机 config.ini，不会上传到任何服务器",
                 bg=t["bg"], fg=t["text_muted"], font=font(9)).pack(anchor="w", pady=(4, 16))

        card = Card(wrap, t, padding=24)
        card.pack(fill="x")
        b = card.body
        b.columnconfigure(1, weight=1)

        # 账号
        tk.Label(b, text="账号", bg=t["card"], fg=t["text_sub"], font=font(10),
                 width=8, anchor="w").grid(row=0, column=0, sticky="w", pady=9)
        self.entry_user = RoundEntry(b, t, width=380)
        self.entry_user.grid(row=0, column=1, sticky="w")
        self.entry_user.entry.configure(textvariable=self.var_username)
        self.var_username.trace_add("write", lambda *_: self._update_preview())

        # 密码
        tk.Label(b, text="密码", bg=t["card"], fg=t["text_sub"], font=font(10),
                 width=8, anchor="w").grid(row=1, column=0, sticky="w", pady=9)
        pw_row = tk.Frame(b, bg=t["card"])
        pw_row.grid(row=1, column=1, sticky="w")
        self.entry_pass = RoundEntry(pw_row, t, show="●", width=318)
        self.entry_pass.pack(side="left")
        self.entry_pass.entry.configure(textvariable=self.var_password)
        self.btn_pw = RoundedButton(pw_row, "显示", command=self._toggle_password,
                                    theme=t, style="ghost", width=60, height=40)
        self.btn_pw.pack(side="left", padx=(10, 0))

        # 运营商
        tk.Label(b, text="运营商", bg=t["card"], fg=t["text_sub"], font=font(10),
                 width=8, anchor="w").grid(row=2, column=0, sticky="w", pady=9)
        op_row = tk.Frame(b, bg=t["card"])
        op_row.grid(row=2, column=1, sticky="w")
        self.var_operator.trace_add("write", lambda *_: self._update_operator_hint())
        self.op_buttons: dict[str, tk.Frame] = {}
        for name, code in OPERATORS:
            chip = self._chip(op_row, name, code)
            chip.pack(side="left", padx=(0, 8))
        self.lbl_op_hint = tk.Label(b, text="", bg=t["card"], fg=t["text_muted"], font=font(9))
        self.lbl_op_hint.grid(row=3, column=1, sticky="w", pady=(0, 6))

        # 检测间隔
        tk.Label(b, text="检测间隔", bg=t["card"], fg=t["text_sub"], font=font(10),
                 width=8, anchor="w").grid(row=4, column=0, sticky="w", pady=9)
        iv_row = tk.Frame(b, bg=t["card"])
        iv_row.grid(row=4, column=1, sticky="w", pady=9)
        self.iv_buttons: dict[int, tk.Frame] = {}
        for sec in INTERVAL_PRESETS:
            chip = self._chip(iv_row, self._short_interval(sec), str(sec), is_interval=True)
            chip.pack(side="left", padx=(0, 8))
        self.lbl_interval_hint = tk.Label(b, text="", bg=t["card"], fg=t["text_muted"], font=font(9))
        self.lbl_interval_hint.grid(row=5, column=1, sticky="w")
        self.var_interval.trace_add("write", lambda *_: self._update_interval_hint())

        # 最终提交的账号预览
        tk.Frame(b, bg=t["card_border"], height=1).grid(
            row=6, column=0, columnspan=2, sticky="ew", pady=(16, 14)
        )
        prev = tk.Frame(b, bg=t["card"])
        prev.grid(row=7, column=0, columnspan=2, sticky="w")
        tk.Label(prev, text="实际提交账号", bg=t["card"], fg=t["text_muted"],
                 font=font(9), width=8, anchor="w").pack(side="left")
        self.lbl_preview = tk.Label(prev, text="", bg=t["card"], fg=t["accent"], font=font(9))
        self.lbl_preview.pack(side="left")

        # 保存按钮
        bar = tk.Frame(wrap, bg=t["bg"])
        bar.pack(fill="x", pady=(18, 0))
        RoundedButton(bar, "保存配置", command=self._on_save, theme=t,
                      style="ghost", width=116).pack(side="right")
        RoundedButton(bar, "保存并启动", command=lambda: self._on_save(start_after=True),
                      theme=t, style="primary", width=136).pack(side="right", padx=(0, 10))

    @staticmethod
    def _short_interval(sec: int) -> str:
        if sec < 60:
            return f"{sec} 秒"
        if sec % 3600 == 0:
            return f"{sec // 3600} 小时"
        return f"{sec // 60} 分钟"

    def _chip(self, parent, label: str, value: str, is_interval: bool = False) -> tk.Frame:
        t = self.t
        chip = tk.Frame(parent, bg=t["field"], cursor="hand2")
        inner = tk.Frame(chip, bg=t["field"], padx=14, pady=7)
        inner.pack()
        lbl = tk.Label(inner, text=label, bg=t["field"], fg=t["text_sub"], font=font(9))
        lbl.pack()

        store = self.iv_buttons if is_interval else self.op_buttons
        store[value] = {"row": chip, "inner": inner, "label": lbl}
        chip.bind("<Button-1>", lambda e, v=value: self._select_chip(v, is_interval))
        inner.bind("<Button-1>", lambda e, v=value: self._select_chip(v, is_interval))
        lbl.bind("<Button-1>", lambda e, v=value: self._select_chip(v, is_interval))
        return chip

    def _select_chip(self, value: str, is_interval: bool) -> None:
        if is_interval:
            self.var_interval.set(value)
        else:
            for name, code in OPERATORS:
                if code == value:
                    self.var_operator.set(name)
                    break
        self._paint_chips()

    def _paint_chips(self) -> None:
        t = self.t
        cur_suffix = dict(OPERATORS).get(self.var_operator.get(), "")
        for value, widgets in self.op_buttons.items():
            self._paint_one(widgets, value == cur_suffix)
        try:
            cur_iv = int(float(self.var_interval.get()))
        except Exception:
            cur_iv = -1
        for value, widgets in self.iv_buttons.items():
            self._paint_one(widgets, str(cur_iv) == value)

    def _paint_one(self, widgets: dict, active: bool) -> None:
        t = self.t
        bg = t["accent_soft"] if active else t["field"]
        fg = t["accent"] if active else t["text_sub"]
        for w in widgets.values():
            w.configure(bg=bg)
        widgets["label"].configure(fg=fg, font=font(9, "bold" if active else "normal"))

    # ------------------------------------------------------------------ 日志页
    def _build_logs(self, parent: tk.Frame) -> None:
        t = self.t
        wrap = tk.Frame(parent, bg=t["bg"])
        wrap.pack(fill="both", expand=True, padx=28, pady=(24, 24))

        head = tk.Frame(wrap, bg=t["bg"])
        head.pack(fill="x")
        tk.Label(head, text="运行日志", bg=t["bg"], fg=t["text"], font=font(18, "bold")).pack(side="left")
        RoundedButton(head, "打开文件", command=self._open_log, theme=t,
                      style="ghost", width=96, height=34).pack(side="right")
        RoundedButton(head, "清空显示", command=self._clear_log_view, theme=t,
                      style="ghost", width=96, height=34).pack(side="right", padx=(0, 8))

        holder = tk.Frame(wrap, bg=t["log_bg"])
        holder.pack(fill="both", expand=True, pady=(16, 0))

        self.txt_log = tk.Text(
            holder,
            bg=t["log_bg"], fg=t["log_fg"],
            insertbackground=t["log_fg"],
            font=("Cascadia Mono", 9) if self._has_font("Cascadia Mono") else ("Consolas", 9),
            relief="flat", bd=0, padx=16, pady=14, wrap="none",
            selectbackground=t["accent"], selectforeground="#FFFFFF",
        )
        self.txt_log.pack(side="left", fill="both", expand=True)
        sb = tk.Scrollbar(holder, command=self.txt_log.yview, width=12)
        sb.pack(side="right", fill="y")
        self.txt_log.configure(yscrollcommand=sb.set, state="disabled")
        for tag, color in (
            ("time", t["log_time"]), ("info", t["log_info"]),
            ("warn", t["log_warn"]), ("error", t["log_err"]), ("body", t["log_fg"]),
        ):
            self.txt_log.tag_configure(tag, foreground=color)

    @staticmethod
    def _has_font(name: str) -> bool:
        try:
            import tkinter.font as tkfont

            return name in tkfont.families()
        except Exception:
            return False

    # ------------------------------------------------------------------ 关于页
    def _build_about(self, parent: tk.Frame) -> None:
        t = self.t
        wrap = tk.Frame(parent, bg=t["bg"])
        wrap.pack(fill="both", expand=True, padx=28, pady=(24, 24))

        tk.Label(wrap, text="关于", bg=t["bg"], fg=t["text"], font=font(18, "bold")).pack(anchor="w")

        card = Card(wrap, t, height=250)
        card.pack(fill="x", pady=(16, 0))
        b = card.body
        tk.Label(b, text=f"校园网自动登录  v{APP_VERSION}", bg=t["card"], fg=t["text"],
                 font=font(14, "bold")).pack(anchor="w")
        tk.Label(b, text="苏州大学校园网（Dr.COM ePortal）掉线自动重连工具",
                 bg=t["card"], fg=t["text_sub"], font=font(10)).pack(anchor="w", pady=(8, 0))

        tk.Frame(b, bg=t["card_border"], height=1).pack(fill="x", pady=16)

        info = [
            ("数据目录", str(core.APP_DIR)),
            ("配置文件", str(CONFIG_PATH)),
            ("日志文件", str(LOG_PATH)),
            ("开源协议", "MIT License"),
        ]
        for k, v in info:
            row = tk.Frame(b, bg=t["card"])
            row.pack(fill="x", pady=3)
            tk.Label(row, text=k, bg=t["card"], fg=t["text_muted"], font=font(9),
                     width=10, anchor="w").pack(side="left")
            tk.Label(row, text=v, bg=t["card"], fg=t["text"], font=font(9),
                     anchor="w", wraplength=560, justify="left").pack(side="left")

    # ------------------------------------------------------------------ 主题切换
    def _toggle_theme(self) -> None:
        self.dark = not self.dark
        self.t = Theme.DARK if self.dark else Theme.LIGHT
        core.write_json_atomic(Path(core.APP_DIR) / "ui_state.json", {"dark": self.dark})
        self._rebuild_ui()

    def _rebuild_ui(self) -> None:
        t = self.t
        for child in list(self.winfo_children()):
            child.destroy()
        self._nav_items.clear()
        self.configure(bg=t["bg"])
        self._build()
        self._load_config()
        self._refresh_autostart()
        self._refresh_status()
        self._show_page(self._page)
        self._paint_chips()

    # ------------------------------------------------------------------ 配置
    def _load_config(self) -> None:
        v = core.read_config_values(CONFIG_PATH)
        self.var_username.set(v["username"])
        self.var_password.set(v["password"])
        suffix = v["suffix"].strip()
        name = next((n for n, c in OPERATORS if c == suffix), "校园网")
        self.var_operator.set(name)
        self.var_interval.set(str(int(v["interval"])))
        self._update_interval_hint()
        self._update_operator_hint()
        self._paint_chips()

    def _collect(self) -> dict:
        v = core.read_config_values(CONFIG_PATH)
        suffix = dict(OPERATORS).get(self.var_operator.get(), "")
        v.update(
            {
                "username": self.var_username.get().strip(),
                "password": self.var_password.get(),
                "suffix": suffix,
                "interval": self.var_interval.get().strip(),
            }
        )
        return v

    def _update_interval_hint(self) -> None:
        try:
            sec = int(float(self.var_interval.get()))
        except Exception:
            self.lbl_interval_hint.configure(text="请输入秒数")
            return
        if sec < 30:
            self.lbl_interval_hint.configure(text="最小 30 秒")
        elif sec > 86400:
            self.lbl_interval_hint.configure(text="最大 24 小时")
        else:
            self.lbl_interval_hint.configure(text=f"每 {self._human(sec)} 检测一次")
        self._paint_chips()

    def _update_operator_hint(self) -> None:
        hint = {
            "校园网": "使用统一身份认证账号，无后缀",
            "中国联通": "运营商账号自动追加 @cucc",
            "中国电信": "运营商账号自动追加 @ctc",
            "中国移动": "运营商账号自动追加 @zgyd",
        }.get(self.var_operator.get(), "")
        if hasattr(self, "lbl_op_hint"):
            self.lbl_op_hint.configure(text=hint)
        self._paint_chips()
        self._update_preview()

    def _update_preview(self) -> None:
        """显示真正提交给门户的账号，避免用户对后缀 / 前缀有疑惑。"""
        if not hasattr(self, "lbl_preview"):
            return
        user = self.var_username.get().strip()
        if not user:
            self.lbl_preview.configure(text="—", fg=self.t["text_muted"])
            return
        suffix = dict(OPERATORS).get(self.var_operator.get(), "")
        account = user
        if suffix and "@" not in account:
            account += suffix
        account = ",0," + account
        self.lbl_preview.configure(text=account, fg=self.t["accent"])

    @staticmethod
    def _human(sec: float) -> str:
        sec = int(max(0, sec))
        if sec < 60:
            return f"{sec} 秒"
        m, s = divmod(sec, 60)
        if m < 60:
            return f"{m} 分 {s} 秒" if s else f"{m} 分钟"
        h, m = divmod(m, 60)
        return f"{h} 小时 {m} 分" if m else f"{h} 小时"

    # ------------------------------------------------------------------ 动作
    def _post(self, fn, *args) -> None:
        self._ui_queue.put((fn, args))

    def _drain(self) -> None:
        while True:
            try:
                fn, args = self._ui_queue.get_nowait()
            except queue.Empty:
                return
            try:
                fn(*args)
            except Exception:
                pass

    def _run_task(self, fn) -> None:
        if self._busy:
            self._toast("请等待当前操作完成", "warn")
            return
        self._busy = True
        self.ring.set_state("busy")

        def worker():
            try:
                fn()
            except Exception as exc:
                self._post(self._toast, f"操作失败：{exc}", "bad")
            finally:
                self._busy = False
                self._post(self._refresh_status)

        threading.Thread(target=worker, daemon=True).start()

    def _task_check(self) -> None:
        """手动检测：写日志；检测到掉线时自动登录（与守护进程行为一致）。"""
        cfg = core.load_config(CONFIG_PATH)
        online, detail = core.check_internet(cfg)
        core.log.info("手动检测：%s（%s）", "已联网" if online else "未联网", detail)

        if online:
            self._post(self._toast, f"已联网：{detail}", "ok")
            return

        core.log.warning("手动检测发现公网不可用，开始自动登录")
        if not cfg.username or not cfg.password:
            core.log.error("未填写账号或密码，无法自动登录")
            self._post(self._toast, "未联网，且未填写账号密码", "warn")
            return

        ip = core.get_local_ip()
        if not ip:
            core.log.error("未能获取本机 IP，跳过登录")
            self._post(self._toast, "未联网，且未能获取本机 IP", "bad")
            return

        mac = cfg.mac or core.get_mac(ip)
        ok, msg = core.do_login(cfg, ip, mac)
        if ok:
            core.log.info("手动检测触发的登录成功：%s", msg)
            self._post(self._toast, f"已自动登录：{msg}", "ok")
        else:
            core.log.error("手动检测触发的登录失败：%s", msg)
            self._post(self._toast, f"登录失败：{msg}", "bad")
        self._post(self._refresh_status)

    def _task_force_login(self) -> None:
        cfg = core.load_config(CONFIG_PATH)
        if not cfg.username or not cfg.password:
            core.log.warning("手动登录被拒绝：未填写账号或密码")
            self._post(self._toast, "请先填写账号和密码", "warn")
            return
        ip = core.get_local_ip()
        if not ip:
            core.log.error("手动登录失败：未能获取本机 IP")
            self._post(self._toast, "未能获取本机 IP", "bad")
            return
        mac = cfg.mac or core.get_mac(ip)
        core.log.info("手动登录：本机 IP=%s，MAC=%s，账号=%s", ip, mac, core.build_account(cfg))
        ok, msg = core.do_login(cfg, ip, mac)
        if ok:
            core.log.info("手动登录成功：%s", msg)
        else:
            core.log.error("手动登录失败：%s", msg)
        self._post(self._toast, ("登录成功：" if ok else "登录失败：") + msg, "ok" if ok else "bad")
        self._post(self._refresh_status)

    def _on_save(self, start_after: bool = False) -> None:
        values = self._collect()
        ok, msg = core.save_config_values(CONFIG_PATH, values)
        if not ok:
            self._toast(msg, "warn")
            return
        was_running = core.running_pid() is not None
        if was_running or start_after:
            if was_running:
                core.stop_daemon()
            started, smsg = core.start_daemon(CONFIG_PATH)
            if not started:
                self._toast(f"配置已保存，但启动失败：{smsg}", "bad")
                self._refresh_status()
                return
            self._toast("配置已保存，守护进程已重启" if was_running else "配置已保存，守护进程已启动", "ok")
        else:
            self._toast("配置已保存", "ok")
        self._refresh_status()

    def _on_start(self) -> None:
        values = self._collect()
        if not values["username"] or not values["password"]:
            self._toast("请先在账号设置里填写账号和密码", "warn")
            self._show_page("account")
            return
        ok, msg = core.save_config_values(CONFIG_PATH, values)
        if not ok:
            self._toast(msg, "warn")
            return
        started, smsg = core.start_daemon(CONFIG_PATH)
        self._toast(smsg, "ok" if started else "bad")
        self._refresh_status()

    def _on_stop(self) -> None:
        stopped = core.stop_daemon()
        self._toast("已停止守护进程" if stopped else "停止失败", "ok" if stopped else "bad")
        self._refresh_status()

    def _on_toggle_autostart(self) -> None:
        ok, msg = core.enable_autostart() if self.var_autostart.get() else core.disable_autostart()
        self._toast(msg, "ok" if ok else "bad")
        self._refresh_autostart()

    def _refresh_autostart(self) -> None:
        try:
            self.var_autostart.set(core.autostart_enabled())
        except Exception:
            self.var_autostart.set(False)
        if hasattr(self, "switch_auto"):
            self.switch_auto._redraw()

    def _toggle_password(self) -> None:
        show = not self.var_show_pw.get()
        self.var_show_pw.set(show)
        self.entry_pass.entry.configure(show="" if show else "●")
        self.btn_pw.set_text("隐藏" if show else "显示")

    def _open_log(self) -> None:
        try:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            LOG_PATH.touch(exist_ok=True)
            os.startfile(str(LOG_PATH))
        except Exception as exc:
            self._toast(f"打不开日志：{exc}", "bad")

    def _clear_log_view(self) -> None:
        self.txt_log.configure(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.configure(state="disabled")

    def _toast(self, text: str, kind: str = "info") -> None:
        try:
            Toast(self, text, self.t, kind)
        except Exception:
            pass

    # ------------------------------------------------------------------ 状态
    def _refresh_status(self) -> None:
        t = self.t
        running = core.running_pid() is not None
        state = core.read_json(core.STATE_FILE) if running else {}

        if running:
            online = state.get("online")
            if online is True:
                self.var_status.set("已联网")
                color, ring = t["ok"], "ok"
            elif online is False:
                self.var_status.set("未联网")
                color, ring = t["bad"], "bad"
            else:
                self.var_status.set("运行中")
                color, ring = t["accent"], "busy"
            self.var_detail.set(str(state.get("detail") or "等待首轮检测…"))
            self.var_action.set(str(state.get("last_action") or ""))
            self.var_account.set(f"账号  {state.get('account') or '—'}")
            self.var_ip.set(str(state.get("local_ip") or "—"))
            self.var_mac.set(str(state.get("mac") or "—"))
            self.var_checks.set(str(state.get("checks", 0)))
            self.var_logins.set(str(state.get("logins", 0)))
            if state.get("next_check_at"):
                left = float(state["next_check_at"]) - time.time()
                self.var_next.set(f"{max(0, int(left))} 秒后")
            else:
                self.var_next.set("—")
            self.lbl_header_sub.configure(text="守护进程运行中")
        else:
            self.var_status.set("未运行")
            self.var_detail.set("点击「启动守护」开始自动检测网络")
            self.var_action.set("")
            self.var_account.set("")
            self.var_ip.set("—")
            self.var_mac.set("—")
            self.var_checks.set("0")
            self.var_logins.set("0")
            self.var_next.set("—")
            color, ring = t["text_muted"], "idle"
            self.lbl_header_sub.configure(text="守护进程未启动")

        if not self._busy:
            self.ring.set_state(ring)
        self.lbl_status.configure(fg=color)
        self.btn_start.set_enabled(not running)
        self.btn_stop.set_enabled(running)

    # ------------------------------------------------------------------ 日志流
    def _append_log(self, text: str) -> None:
        self.txt_log.configure(state="normal")
        for line in text.splitlines():
            if not line.strip():
                continue
            parts = line.split(" ", 2)
            if len(parts) >= 3 and parts[0].startswith("20"):
                ts = parts[0] + " " + parts[1]
                rest = parts[2]
                self.txt_log.insert("end", ts + "  ", "time")
                tag = "body"
                if "[INFO" in rest:
                    tag = "info"
                elif "[WARNING" in rest or "[WARN" in rest:
                    tag = "warn"
                elif "[ERROR" in rest:
                    tag = "error"
                self.txt_log.insert("end", rest + "\n", tag)
            else:
                self.txt_log.insert("end", line + "\n", "body")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _reload_log(self, force: bool = False) -> None:
        try:
            if not LOG_PATH.is_file():
                return
            size = LOG_PATH.stat().st_size
            if not force and size == self._last_log_size:
                return
            if force or size < self._last_log_size:
                self._log_pos = 0
                self.txt_log.configure(state="normal")
                self.txt_log.delete("1.0", "end")
                self.txt_log.configure(state="disabled")
            self._last_log_size = size
            with LOG_PATH.open("r", encoding="utf-8", errors="replace") as fh:
                fh.seek(self._log_pos)
                new = fh.read()
                self._log_pos = fh.tell()
            if new.strip():
                self._append_log(new)
        except Exception:
            pass

    # ------------------------------------------------------------------ 心跳
    def _tick(self) -> None:
        try:
            self._drain()
            self._refresh_status()
            if self._page == "logs":
                self._reload_log()
        finally:
            self.after(1500, self._tick)

    def _on_close(self) -> None:
        if core.running_pid() is not None:
            from tkinter import messagebox

            keep = messagebox.askyesnocancel(
                APP_TITLE,
                "守护进程仍在后台运行。\n\n"
                "是：让它继续运行（推荐，最小化到后台）\n"
                "否：停止它并退出\n"
                "取消：回到界面",
                parent=self,
            )
            if keep is None:
                return
            if keep is False:
                core.stop_daemon()
        self.destroy()


def _report_startup_failure(title: str, detail: str) -> None:
    """启动失败时的统一兜底：写日志 + 弹原生对话框。

    用 ctypes 调 MessageBox 而不是 tkinter，因为界面可能根本没建起来。
    """
    try:
        core.log.error("%s\n%s", title, detail)
    except Exception:
        pass
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            None, f"{title}\n\n{detail}", "校园网自动登录 - 启动失败", 0x10
        )
    except Exception:
        try:
            messagebox.showerror(APP_TITLE, f"{title}\n\n{detail}")
        except Exception:
            pass


def main() -> int:
    # 界面自身也要写日志，否则手动检测 / 登录在黑窗用户那里看不到任何记录
    try:
        _cfg = core.load_config(CONFIG_PATH)
        core.setup_logging(_cfg, verbose=False)
        core.log.info("图形界面已启动（%s）", core.APP_DIR)
    except Exception:
        # 日志初始化失败不能挡住界面
        pass

    try:
        app = App()
    except BaseException:
        # 注意用 BaseException：SystemExit / KeyboardInterrupt 也要接住，
        # 否则进程会静默退出，用户看到的就是"双击没反应"
        import traceback

        detail = traceback.format_exc()
        _report_startup_failure(
            "界面初始化失败",
            detail[-1200:] + "\n\n详细信息见 logs\\auto_login.log",
        )
        return 1

    try:
        app.mainloop()
    except BaseException:
        import traceback

        _report_startup_failure("界面运行出错", traceback.format_exc()[-1200:])
        return 1
    finally:
        try:
            core.log.info("图形界面已关闭")
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

