#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
校园网自动登录 - 图形界面
==========================

双击 校园网自动登录.pyw 即可打开（.pyw 不会弹黑窗口）。

界面提供三块能力：
1. 账号设置：账号、密码、运营商、检测间隔，保存后立即生效；
2. 运行控制：启动 / 停止后台守护、立即检测、立即登录、查看日志；
3. 其他设置：开机自启开关（当前用户，无需管理员权限）。

底层全部复用 auto_login.py，界面只负责读写配置和启停进程。
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))

import auto_login as core  # noqa: E402

APP_TITLE = "校园网自动登录"
CONFIG_PATH = APP_DIR / "config.ini"
LOG_PATH = APP_DIR / "logs" / "auto_login.log"

OPERATORS = [
    ("校园网", ""),
    ("中国联通", "@cucc"),
    ("中国电信", "@ctc"),
    ("中国移动", "@zgyd"),
]

# 常用检测间隔，单位秒
INTERVAL_PRESETS = [
    ("1 分钟", 60),
    ("2 分钟", 120),
    ("5 分钟（推荐）", 300),
    ("10 分钟", 600),
    ("30 分钟", 1800),
]


def human_seconds(seconds: float) -> str:
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds} 秒"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} 分 {sec} 秒" if sec else f"{minutes} 分钟"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} 小时 {minutes} 分" if minutes else f"{hours} 小时"


def human_time(ts: float) -> str:
    if not ts:
        return "—"
    try:
        return time.strftime("%H:%M:%S", time.localtime(ts))
    except Exception:
        return "—"


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.minsize(720, 620)
        self.geometry("760x660")
        self.resizable(True, True)

        self._busy = False
        self._last_log_size = 0
        self._log_pos = 0
        # 后台线程不能直接操作 Tk 控件，统一用队列回到主线程处理
        self._ui_queue: queue.Queue = queue.Queue()

        self.var_username = tk.StringVar()
        self.var_password = tk.StringVar()
        self.var_operator = tk.StringVar(value="校园网")
        self.var_interval = tk.StringVar(value="300")
        self.var_autostart = tk.BooleanVar(value=False)

        self.var_status = tk.StringVar(value="正在读取状态…")
        self.var_detail = tk.StringVar(value="")
        self.var_account = tk.StringVar(value="")
        self.var_identity = tk.StringVar(value="")
        self.var_counters = tk.StringVar(value="")
        self.var_next = tk.StringVar(value="")

        self._build_style()
        self._build_ui()
        self._load_config_to_form()
        self._refresh_autostart()
        self._refresh_status()
        self._tick()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ 样式
    def _build_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("vista")
        except Exception:
            pass
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("Hint.TLabel", foreground="#666666")
        style.configure("Status.TLabel", font=("Microsoft YaHei UI", 12, "bold"))
        style.configure("Ok.TLabel", foreground="#1a7f37", font=("Microsoft YaHei UI", 12, "bold"))
        style.configure("Bad.TLabel", foreground="#b42318", font=("Microsoft YaHei UI", 12, "bold"))
        style.configure("Idle.TLabel", foreground="#666666", font=("Microsoft YaHei UI", 12, "bold"))
        style.configure("Card.TLabelframe", padding=10)
        style.configure("Card.TLabelframe.Label", font=("Microsoft YaHei UI", 10, "bold"))

    # ------------------------------------------------------------------ 界面
    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=(12, 10, 12, 10))
        outer.pack(fill="both", expand=True)

        self._build_status_card(outer)
        self._build_account_card(outer)
        self._build_actions_card(outer)
        self._build_log_card(outer)

    def _build_status_card(self, parent: ttk.Frame) -> None:
        card = ttk.LabelFrame(parent, text="当前状态", style="Card.TLabelframe")
        card.pack(fill="x", pady=(0, 8))

        head = ttk.Frame(card)
        head.pack(fill="x")
        self.lbl_status = ttk.Label(head, textvariable=self.var_status, style="Idle.TLabel")
        self.lbl_status.pack(side="left")
        ttk.Label(head, textvariable=self.var_counters, style="Hint.TLabel").pack(side="right")

        ttk.Label(card, textvariable=self.var_detail, style="Hint.TLabel", wraplength=700).pack(
            anchor="w", pady=(4, 0)
        )
        ttk.Label(card, textvariable=self.var_account, style="Hint.TLabel").pack(anchor="w")
        ttk.Label(card, textvariable=self.var_identity, style="Hint.TLabel").pack(anchor="w")
        ttk.Label(card, textvariable=self.var_next, style="Hint.TLabel").pack(anchor="w")

    def _build_account_card(self, parent: ttk.Frame) -> None:
        card = ttk.LabelFrame(parent, text="账号设置", style="Card.TLabelframe")
        card.pack(fill="x", pady=(0, 8))
        card.columnconfigure(1, weight=1)

        ttk.Label(card, text="账号").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        entry_user = ttk.Entry(card, textvariable=self.var_username)
        entry_user.grid(row=0, column=1, sticky="ew", pady=4)

        ttk.Label(card, text="密码").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        pw_frame = ttk.Frame(card)
        pw_frame.grid(row=1, column=1, sticky="ew", pady=4)
        pw_frame.columnconfigure(0, weight=1)
        self.entry_password = ttk.Entry(pw_frame, textvariable=self.var_password, show="●")
        self.entry_password.grid(row=0, column=0, sticky="ew")
        self.btn_show_pw = ttk.Button(pw_frame, text="显示", width=6, command=self._toggle_password)
        self.btn_show_pw.grid(row=0, column=1, padx=(6, 0))

        ttk.Label(card, text="运营商").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        op_frame = ttk.Frame(card)
        op_frame.grid(row=2, column=1, sticky="ew", pady=4)
        self.combo_operator = ttk.Combobox(
            op_frame,
            textvariable=self.var_operator,
            values=[name for name, _ in OPERATORS],
            state="readonly",
            width=16,
        )
        self.combo_operator.pack(side="left")
        ttk.Label(
            op_frame,
            text="校园网账号选“校园网”；运营商宽带账号选对应运营商",
            style="Hint.TLabel",
        ).pack(side="left", padx=(10, 0))

        ttk.Label(card, text="检测间隔").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=4)
        iv_frame = ttk.Frame(card)
        iv_frame.grid(row=3, column=1, sticky="ew", pady=4)
        self.combo_interval = ttk.Combobox(
            iv_frame,
            textvariable=self.var_interval,
            values=[str(v) for _, v in INTERVAL_PRESETS],
            width=8,
        )
        self.combo_interval.pack(side="left")
        ttk.Label(iv_frame, text="秒").pack(side="left", padx=(4, 12))
        self.combo_interval.bind("<<ComboboxSelected>>", self._on_interval_preset)
        self.lbl_interval_hint = ttk.Label(iv_frame, text="", style="Hint.TLabel")
        self.lbl_interval_hint.pack(side="left")
        self.var_interval.trace_add("write", lambda *_: self._update_interval_hint())

        btn_row = ttk.Frame(card)
        btn_row.grid(row=4, column=0, columnspan=2, sticky="e", pady=(8, 0))
        ttk.Button(btn_row, text="保存配置", command=self._on_save).pack(side="left", padx=(0, 6))
        self.btn_save_start = ttk.Button(
            btn_row, text="保存并启动", command=lambda: self._on_save(start_after=True)
        )
        self.btn_save_start.pack(side="left")

    def _build_actions_card(self, parent: ttk.Frame) -> None:
        card = ttk.LabelFrame(parent, text="运行控制", style="Card.TLabelframe")
        card.pack(fill="x", pady=(0, 8))

        row = ttk.Frame(card)
        row.pack(fill="x")
        self.btn_start = ttk.Button(row, text="启动守护", command=self._on_start)
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(row, text="停止守护", command=self._on_stop)
        self.btn_stop.pack(side="left", padx=(6, 0))
        ttk.Button(row, text="立即检测", command=lambda: self._run_task(self._task_check)).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(row, text="立即登录", command=lambda: self._run_task(self._task_force_login)).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(row, text="打开日志", command=self._open_log).pack(side="left", padx=(6, 0))

        ttk.Separator(card, orient="horizontal").pack(fill="x", pady=8)

        auto_row = ttk.Frame(card)
        auto_row.pack(fill="x")
        self.chk_autostart = ttk.Checkbutton(
            auto_row,
            text="开机自动启动（登录 Windows 后后台运行，不弹窗口）",
            variable=self.var_autostart,
            command=self._on_toggle_autostart,
        )
        self.chk_autostart.pack(side="left")
        ttk.Label(
            auto_row, text="当前用户生效，不需要管理员权限", style="Hint.TLabel"
        ).pack(side="left", padx=(10, 0))

    def _build_log_card(self, parent: ttk.Frame) -> None:
        card = ttk.LabelFrame(parent, text="运行日志（最近 200 行）", style="Card.TLabelframe")
        card.pack(fill="both", expand=True)
        card.rowconfigure(0, weight=1)
        card.columnconfigure(0, weight=1)

        self.txt_log = tk.Text(
            card,
            height=10,
            wrap="none",
            font=("Consolas", 9),
            background="#fbfbfb",
            relief="solid",
            borderwidth=1,
        )
        self.txt_log.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(card, orient="vertical", command=self.txt_log.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.txt_log.configure(yscrollcommand=scroll.set, state="disabled")

    # ------------------------------------------------------------------ 表单
    def _load_config_to_form(self) -> None:
        values = core.read_config_values(CONFIG_PATH)
        self.var_username.set(values["username"])
        self.var_password.set(values["password"])
        suffix = values["suffix"].strip()
        name = "校园网"
        for label, code in OPERATORS:
            if code == suffix:
                name = label
                break
        if suffix and name == "校园网":
            # 未知运营商后缀，保留原值让用户自己看
            self.combo_operator.configure(values=[n for n, _ in OPERATORS] + [suffix])
            name = suffix
        self.var_operator.set(name)
        self.var_interval.set(str(int(values["interval"])))
        self._update_interval_hint()

    def _update_interval_hint(self) -> None:
        raw = self.var_interval.get().strip()
        try:
            value = int(float(raw))
        except Exception:
            self.lbl_interval_hint.configure(text="请输入秒数，最小 30")
            return
        if value < 30:
            self.lbl_interval_hint.configure(text="最小 30 秒")
        elif value > 86400:
            self.lbl_interval_hint.configure(text="最大 86400 秒（24 小时）")
        else:
            self.lbl_interval_hint.configure(text=f"即每 {human_seconds(value)} 检测一次")

    def _on_interval_preset(self, _event=None) -> None:
        self._update_interval_hint()

    def _toggle_password(self) -> None:
        if self.entry_password.cget("show"):
            self.entry_password.configure(show="")
            self.btn_show_pw.configure(text="隐藏")
        else:
            self.entry_password.configure(show="●")
            self.btn_show_pw.configure(text="显示")

    # ------------------------------------------------------------------ 保存
    def _collect_config(self) -> dict:
        values = core.read_config_values(CONFIG_PATH)
        operator = self.var_operator.get().strip()
        suffix = next((code for name, code in OPERATORS if name == operator), operator)
        values.update(
            {
                "username": self.var_username.get().strip(),
                "password": self.var_password.get(),
                "suffix": suffix,
                "interval": self.var_interval.get().strip(),
            }
        )
        return values

    def _on_save(self, start_after: bool = False) -> None:
        values = self._collect_config()
        ok, message = core.save_config_values(CONFIG_PATH, values)
        if not ok:
            messagebox.showwarning(APP_TITLE, message, parent=self)
            return

        was_running = core.running_pid() is not None
        if was_running:
            core.stop_daemon()
        if start_after or was_running:
            started, start_msg = core.start_daemon(CONFIG_PATH)
            if not started:
                messagebox.showerror(APP_TITLE, f"配置已保存，但启动失败：{start_msg}", parent=self)
                self._refresh_status()
                return
            message = f"{message}，守护进程已重启"
        self._append_log(f"[界面] {message}")
        self._refresh_status()
        if not start_after:
            messagebox.showinfo(APP_TITLE, message, parent=self)

    # ------------------------------------------------------------------ 控制
    def _post(self, func, *args) -> None:
        """把要在主线程执行的调用放进队列。"""
        self._ui_queue.put((func, args))

    def _drain_queue(self) -> None:
        while True:
            try:
                func, args = self._ui_queue.get_nowait()
            except queue.Empty:
                return
            try:
                func(*args)
            except Exception:
                pass

    def _run_task(self, func) -> None:
        if self._busy:
            return
        self._busy = True
        self._append_log("[界面] 操作进行中…")

        def worker() -> None:
            try:
                func()
            except Exception as exc:  # 兜底，避免线程异常静默
                self._post(self._append_log, f"[界面] 出错：{exc}")
            finally:
                self._busy = False
                self._post(self._refresh_status)

        threading.Thread(target=worker, daemon=True).start()

    def _task_check(self) -> None:
        cfg = core.load_config(CONFIG_PATH)
        online, detail = core.check_internet(cfg)
        text = f"当前状态：{'已联网' if online else '未联网'}（{detail}）"
        self._post(self._append_log, f"[界面] {text}")
        self._post(lambda: messagebox.showinfo(APP_TITLE, text, parent=self))

    def _task_force_login(self) -> None:
        cfg = core.load_config(CONFIG_PATH)
        if not cfg.username or not cfg.password:
            self._post(lambda: messagebox.showwarning(APP_TITLE, "请先填写账号和密码", parent=self))
            return
        ip = core.get_local_ip()
        if not ip:
            self._post(lambda: messagebox.showwarning(APP_TITLE, "未能获取本机 IP", parent=self))
            return
        mac = cfg.mac or core.get_mac(ip)
        ok, message = core.do_login(cfg, ip, mac)
        self._post(self._append_log, f"[界面] 手动登录：{message}")
        self._post(
            lambda: messagebox.showinfo(
                APP_TITLE, f"{'登录成功' if ok else '登录失败'}\n\n{message}", parent=self
            )
        )

    def _on_start(self) -> None:
        values = self._collect_config()
        if not values["username"] or not values["password"]:
            messagebox.showwarning(APP_TITLE, "请先填写账号和密码", parent=self)
            return
        ok, message = core.save_config_values(CONFIG_PATH, values)
        if not ok:
            messagebox.showwarning(APP_TITLE, message, parent=self)
            return
        started, start_msg = core.start_daemon(CONFIG_PATH)
        self._append_log(f"[界面] {start_msg}")
        if not started:
            messagebox.showerror(APP_TITLE, start_msg, parent=self)
        self._refresh_status()

    def _on_stop(self) -> None:
        stopped = core.stop_daemon()
        self._append_log("[界面] 已停止守护进程" if stopped else "[界面] 停止失败，请查看日志")
        if not stopped:
            messagebox.showerror(APP_TITLE, "停止失败，可能有权限问题", parent=self)
        self._refresh_status()

    def _open_log(self) -> None:
        try:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            if not LOG_PATH.exists():
                LOG_PATH.touch()
            os.startfile(str(LOG_PATH))  # noqa: S606
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"打不开日志：{exc}", parent=self)

    # ------------------------------------------------------------------ 自启
    def _refresh_autostart(self) -> None:
        try:
            self.var_autostart.set(core.autostart_enabled())
        except Exception:
            self.var_autostart.set(False)

    def _on_toggle_autostart(self) -> None:
        want = self.var_autostart.get()
        if want:
            ok, message = core.enable_autostart()
        else:
            ok, message = core.disable_autostart()
        self._append_log(f"[界面] {message}")
        if not ok:
            messagebox.showerror(APP_TITLE, message, parent=self)
        self._refresh_autostart()

    # ------------------------------------------------------------------ 状态
    def _refresh_status(self) -> None:
        running = core.running_pid() is not None
        state = core.read_json(core.STATE_FILE) if running else {}

        if running:
            online = state.get("online")
            if online is True:
                self.var_status.set("● 运行中 · 已联网")
                self.lbl_status.configure(style="Ok.TLabel")
            elif online is False:
                self.var_status.set("● 运行中 · 未联网")
                self.lbl_status.configure(style="Bad.TLabel")
            else:
                self.var_status.set("● 运行中 · 尚未检测")
                self.lbl_status.configure(style="Status.TLabel")
            self.var_detail.set(str(state.get("detail") or "等待第一轮检测…"))
            account = state.get("account") or "—"
            self.var_account.set(f"账号：{account}")
            ip = state.get("local_ip") or "—"
            mac = state.get("mac") or "—"
            self.var_identity.set(f"本机 IP：{ip}    MAC：{mac}")
            checks = state.get("checks", 0)
            logins = state.get("logins", 0)
            self.var_counters.set(f"检测 {checks} 次 · 登录尝试 {logins} 次")
            if state.get("next_check_at"):
                left = float(state["next_check_at"]) - time.time()
                self.var_next.set(
                    f"下次检测：{human_time(state['next_check_at'])}（{human_seconds(left)}后）"
                )
            else:
                self.var_next.set("")
        else:
            self.var_status.set("○ 未运行")
            self.lbl_status.configure(style="Idle.TLabel")
            self.var_detail.set("守护进程未启动，点击下方“启动守护”开始自动检测")
            self.var_account.set("")
            self.var_identity.set("")
            self.var_counters.set("")
            self.var_next.set("")

        self.btn_start.state(["disabled"] if running else ["!disabled"])
        self.btn_stop.state(["!disabled"] if running else ["disabled"])

    # ------------------------------------------------------------------ 日志
    def _append_log(self, line: str) -> None:
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", line + "\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _reload_log(self) -> None:
        try:
            if not LOG_PATH.is_file():
                return
            size = LOG_PATH.stat().st_size
            if size == self._last_log_size:
                return
            if size < self._last_log_size:
                self._log_pos = 0
            self._last_log_size = size
            with LOG_PATH.open("r", encoding="utf-8", errors="replace") as fh:
                fh.seek(self._log_pos)
                new = fh.read()
                self._log_pos = fh.tell()
            if not new.strip():
                return
            lines = [ln for ln in new.splitlines() if ln.strip()][-200:]
            self.txt_log.configure(state="normal")
            self.txt_log.insert("end", "\n".join(lines) + "\n")
            # 只保留最近 200 行，避免界面越跑越卡
            total = int(self.txt_log.index("end-1c").split(".")[0])
            if total > 400:
                self.txt_log.delete("1.0", f"{total - 200}.0")
                self._log_pos = 0
            self.txt_log.see("end")
            self.txt_log.configure(state="disabled")
        except Exception:
            pass

    # ------------------------------------------------------------------ 心跳
    def _tick(self) -> None:
        try:
            self._drain_queue()
            self._refresh_status()
            self._reload_log()
        finally:
            self.after(2000, self._tick)

    def _on_close(self) -> None:
        running = core.running_pid() is not None
        if running:
            keep = messagebox.askyesnocancel(
                APP_TITLE,
                "守护进程仍在后台运行。\n\n"
                "选择“是”：让它继续在后台运行（推荐）\n"
                "选择“否”：停止它并退出\n"
                "选择“取消”：回到界面",
                parent=self,
            )
            if keep is None:
                return
            if keep is False:
                core.stop_daemon()
        self.destroy()


def main() -> int:
    try:
        app = App()
    except Exception as exc:
        import traceback

        traceback.print_exc()
        try:
            messagebox.showerror(APP_TITLE, f"界面启动失败：{exc}")
        except Exception:
            pass
        return 1
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
