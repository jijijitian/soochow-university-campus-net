"""系统托盘图标（纯 ctypes 实现，不依赖第三方库）。

用 Shell_NotifyIcon 在任务栏通知区放一个图标，支持：
- 左键单击 / 双击：恢复主窗口
- 右键菜单：显示窗口、立即检测、启动/停止守护、退出

实现要点：
- 创建一个仅消息窗口（message-only window）接收托盘回调
- 托盘消息由系统投递到该窗口，用 WNDPROC 处理
- 菜单用 CreatePopupMenu / TrackPopupMenu
- 因为主线程跑 tkinter 的 mainloop，托盘窗口的消息循环放在独立线程里
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import threading
import time
from pathlib import Path
from typing import Callable

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# ---- 常量 ----
WM_USER = 0x0400
WM_TRAYICON = WM_USER + 20
RETRY_TIMER_ID = 0x7F01
WM_TIMER = 0x0113

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002

NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
NIF_INFO = 0x00000010

NIIF_INFO = 0x00000001
NIIF_WARNING = 0x00000002
NIIF_ERROR = 0x00000003

WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B

MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
MF_CHECKED = 0x00000008
TPM_LEFTALIGN = 0x0000
TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
LR_DEFAULTSIZE = 0x0040

CS_DBLCLKS = 0x0008
WS_OVERLAPPED = 0x00000000

SW_RESTORE = 9
SW_SHOW = 5


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("hWnd", wt.HWND),
        ("uID", wt.UINT),
        ("uFlags", wt.UINT),
        ("uCallbackMessage", wt.UINT),
        ("hIcon", wt.HICON),
        ("szTip", wt.WCHAR * 128),
        ("dwState", wt.DWORD),
        ("dwStateMask", wt.DWORD),
        ("szInfo", wt.WCHAR * 256),
        ("uVersion", wt.UINT),
        ("szInfoTitle", wt.WCHAR * 64),
        ("dwInfoFlags", wt.DWORD),
    ]


WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM
)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wt.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE),
        ("hIcon", wt.HICON),
        ("hCursor", wt.HANDLE),
        ("hbrBackground", wt.HBRUSH),
        ("lpszMenuName", wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR),
    ]


# 显式声明签名，避免 64 位下 LPARAM 溢出
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.CreateWindowExW.restype = wt.HWND
user32.CreateWindowExW.argtypes = [
    wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID,
]
user32.RegisterClassW.restype = ctypes.c_ushort
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.LoadImageW.restype = wt.HANDLE
user32.LoadImageW.argtypes = [
    wt.HINSTANCE, wt.LPCWSTR, wt.UINT, ctypes.c_int, ctypes.c_int, wt.UINT
]
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.CreatePopupMenu.restype = wt.HMENU
user32.AppendMenuW.argtypes = [wt.HMENU, wt.UINT, ctypes.c_size_t, wt.LPCWSTR]
user32.TrackPopupMenu.argtypes = [
    wt.HMENU, wt.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, wt.LPVOID
]
user32.DestroyMenu.argtypes = [wt.HMENU]
user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
user32.EnableMenuItem.argtypes = [wt.HMENU, wt.UINT, wt.UINT]
user32.SetTimer.argtypes = [wt.HWND, ctypes.c_size_t, wt.UINT, wt.LPVOID]
user32.SetTimer.restype = ctypes.c_size_t
user32.KillTimer.argtypes = [wt.HWND, ctypes.c_size_t]
user32.KillTimer.restype = wt.BOOL
user32.DestroyWindow.argtypes = [wt.HWND]
user32.UnregisterClassW.argtypes = [wt.LPCWSTR, wt.HINSTANCE]
kernel32.GetModuleHandleW.restype = wt.HMODULE
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
shell32.Shell_NotifyIconW.argtypes = [wt.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]


class TrayIcon:
    """任务栏托盘图标。

    callbacks 里可用的键：
        show      左键单击 / 菜单「显示主窗口」
        check     菜单「立即检测」
        login     菜单「立即登录」
        toggle    菜单「启动/停止守护」
        quit      菜单「退出程序」
        status    返回当前状态文本（用于菜单项显示与提示）
    """

    def __init__(
        self,
        icon_path: Path | None = None,
        title: str = "校园网自动登录",
        callbacks: dict[str, Callable[[], None]] | None = None,
        status_provider: Callable[[], tuple[str, str]] | None = None,
    ) -> None:
        self.title = title
        self.icon_path = icon_path
        self.cb = callbacks or {}
        self.status_provider = status_provider

        self._hwnd = None
        self._hicon = None
        self._added = False
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._wndproc = None
        self._class_name = f"PyTrayWnd_{id(self)}"
        self.last_error = ""

    # ------------------------------------------------------------------ 对外
    def start(self) -> bool:
        """在后台线程启动托盘。返回是否成功创建初始图标。"""
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="tray-icon"
        )
        self._thread.start()
        return self._ready.wait(timeout=5.0)

    def stop(self) -> None:
        """移除托盘图标并结束消息循环。"""
        try:
            if self._hwnd and self._added:
                nid = self._make_nid()
                shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
                self._added = False
        except Exception:
            pass
        try:
            if self._hwnd:
                user32.PostMessageW(self._hwnd, 0x0012, 0, 0)  # WM_QUIT
        except Exception:
            pass

    def notify(self, title: str, text: str, kind: str = "info") -> None:
        """弹一个气泡提示。"""
        if not self._added:
            return
        try:
            nid = self._make_nid()
            nid.uFlags = NIF_INFO
            nid.szInfo = text[:200]
            nid.szInfoTitle = title[:60]
            nid.dwInfoFlags = {
                "info": NIIF_INFO,
                "warn": NIIF_WARNING,
                "error": NIIF_ERROR,
            }.get(kind, NIIF_INFO)
            shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))
        except Exception:
            pass

    def update_tip(self, text: str) -> None:
        if not self._added:
            return
        try:
            nid = self._make_nid()
            nid.uFlags = NIF_TIP
            nid.szTip = text[:120]
            shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))
        except Exception:
            pass

    # ------------------------------------------------------------------ 内部
    def _make_nid(self) -> NOTIFYICONDATAW:
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAYICON
        nid.hIcon = self._hicon
        nid.szTip = self.title[:120]
        return nid

    def _run(self) -> None:
        try:
            hinst = kernel32.GetModuleHandleW(None)
            self._wndproc = WNDPROC(self._on_message)

            wc = WNDCLASSW()
            wc.style = CS_DBLCLKS
            wc.lpfnWndProc = self._wndproc
            wc.hInstance = hinst
            wc.lpszClassName = self._class_name
            user32.RegisterClassW(ctypes.byref(wc))

            self._hwnd = user32.CreateWindowExW(
                0, self._class_name, self.title,
                WS_OVERLAPPED, 0, 0, 0, 0, None, None, hinst, None,
            )
            if not self._hwnd:
                self.last_error = "无法创建托盘消息窗口"
                self._ready.set()
                return

            if self.icon_path and Path(self.icon_path).is_file():
                self._hicon = user32.LoadImageW(
                    None, str(self.icon_path), IMAGE_ICON, 0, 0,
                    LR_LOADFROMFILE | LR_DEFAULTSIZE,
                )

            # 添加图标。若失败（例如 explorer 尚未就绪、或权限受限），
            # 不退出，而是保留消息窗口并定时重试，系统恢复后能自动接上。
            nid = self._make_nid()
            for attempt in range(3):
                if shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
                    self._added = True
                    break
                self.last_error = (
                    f"Shell_NotifyIcon 失败，错误码 {ctypes.get_last_error()}"
                )
                time.sleep(0.4 * (attempt + 1))

            self._ready.set()

            if not self._added:
                # 启动一个轻量重试定时器（每 30 秒一次，最多 10 次）
                user32.SetTimer(self._hwnd, RETRY_TIMER_ID, 30000, None)

            msg = wt.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            self._ready.set()
        finally:
            try:
                if self._hwnd:
                    user32.KillTimer(self._hwnd, RETRY_TIMER_ID)
                    user32.DestroyWindow(self._hwnd)
                user32.UnregisterClassW(self._class_name, kernel32.GetModuleHandleW(None))
            except Exception:
                pass

    def _retry_add(self) -> None:
        """重试添加托盘图标。"""
        if self._added:
            return
        try:
            nid = self._make_nid()
            if shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
                self._added = True
                self.last_error = ""
                user32.KillTimer(self._hwnd, RETRY_TIMER_ID)
        except Exception:
            pass

    def _on_message(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_TRAYICON:
                event = lparam & 0xFFFF
                if event in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                    self._invoke("show")
                elif event in (WM_RBUTTONUP, WM_CONTEXTMENU):
                    self._show_menu()
                return 0
            if msg == WM_TIMER and wparam == RETRY_TIMER_ID:
                self._retry_add()
                return 0
            if msg == 0x0012:  # WM_QUIT
                return 0
        except Exception:
            pass
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _invoke(self, key: str) -> None:
        fn = self.cb.get(key)
        if fn:
            try:
                fn()
            except Exception:
                pass

    def _show_menu(self) -> None:
        menu = user32.CreatePopupMenu()
        if not menu:
            return

        status_text, detail = "—", ""
        if self.status_provider:
            try:
                status_text, detail = self.status_provider()
            except Exception:
                pass

        ids: dict[int, str] = {}
        next_id = 1

        # 状态行（禁用）
        label = f"状态：{status_text}"
        if detail:
            label += f"（{detail}）"
        user32.AppendMenuW(menu, MF_STRING, 0, label[:60])
        user32.EnableMenuItem(menu, 0, 0x00000001 | 0x00000002)  # 灰掉

        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)

        for key, text in (
            ("show", "显示主窗口"),
            ("check", "立即检测"),
            ("login", "立即登录"),
            ("toggle", "启动 / 停止守护"),
        ):
            user32.AppendMenuW(menu, MF_STRING, next_id, text)
            ids[next_id] = key
            next_id += 1

        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, next_id, "退出程序")
        ids[next_id] = "quit"

        pt = wt.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        # 必须先 SetForegroundWindow，否则菜单点外部不会消失
        user32.SetForegroundWindow(self._hwnd)
        cmd = user32.TrackPopupMenu(
            menu, TPM_LEFTALIGN | TPM_RIGHTBUTTON | TPM_RETURNCMD,
            pt.x, pt.y, 0, self._hwnd, None,
        )
        user32.PostMessageW(self._hwnd, 0x0000, 0, 0)  # WM_NULL
        user32.DestroyMenu(menu)

        if cmd and cmd in ids:
            self._invoke(ids[cmd])
