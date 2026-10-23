"""Windows 剪贴板与模拟粘贴。

为什么要自己写 ctypes 而不装 pywin32：
开源项目多一个依赖就少一批人愿意试。这里的操作都是 Win32 基础调用，
ctypes 够用，零依赖。

关键点：剪贴板可以同时放多种格式。所以点一张表情时，同时写入
- CF_DIB（图片）—— 富文本输入框会优先粘图片，用户看到的就是表情
- CF_UNICODETEXT（标记）—— 纯文本框退化成粘标记，AI 一样能识别

这样不管对方输入框是什么类型，都能落进去。
"""

from __future__ import annotations

import ctypes
import io
import os
import time
from ctypes import wintypes

from PIL import Image

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

CF_DIB = 8
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

VK_CONTROL = 0x11
VK_V = 0x56
KEYEVENTF_KEYUP = 0x0002

MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
PM_REMOVE = 0x0001
SW_RESTORE = 9

user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.OpenClipboard.restype = wintypes.BOOL
user32.EmptyClipboard.restype = wintypes.BOOL
user32.CloseClipboard.restype = wintypes.BOOL
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE

kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalUnlock.restype = wintypes.BOOL
kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]


def _put(fmt: int, payload: bytes) -> None:
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(payload))
    if not handle:
        raise OSError("GlobalAlloc 失败")
    ptr = kernel32.GlobalLock(handle)
    if not ptr:
        kernel32.GlobalFree(handle)
        raise OSError("GlobalLock 失败")
    ctypes.memmove(ptr, payload, len(payload))
    kernel32.GlobalUnlock(handle)
    if not user32.SetClipboardData(fmt, handle):
        kernel32.GlobalFree(handle)
        raise OSError("SetClipboardData 失败")


def set_text(text: str) -> None:
    if not user32.OpenClipboard(None):
        raise OSError("OpenClipboard 失败")
    try:
        user32.EmptyClipboard()
        _put(CF_UNICODETEXT, (text + "\0").encode("utf-16-le"))
    finally:
        user32.CloseClipboard()


def set_image_and_text(img: Image.Image, text: str) -> None:
    """一次写入两种格式，让不同输入框都能接住。"""
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "BMP")
    dib = buf.getvalue()[14:]  # 去掉 BITMAPFILEHEADER，剩下就是 CF_DIB

    if not user32.OpenClipboard(None):
        raise OSError("OpenClipboard 失败")
    try:
        user32.EmptyClipboard()
        _put(CF_DIB, dib)
        _put(CF_UNICODETEXT, (text + "\0").encode("utf-16-le"))
    finally:
        user32.CloseClipboard()


def foreground() -> int:
    return user32.GetForegroundWindow() or 0


def window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    if not hwnd:
        return 0
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def is_own_window(hwnd: int) -> bool:
    """这个窗口是不是挂件自己。

    点球和点面板都会把前台抢到挂件身上，此时记录下来的
    「粘贴目标」就是自己，粘回去必然落空。所以记录前要排掉。
    """
    return bool(hwnd) and window_pid(hwnd) == os.getpid()


def pick_target(host: int) -> int:
    """挑一个可用的粘贴目标：前台不是自己就用前台，否则退回宿主窗口。"""
    fg = foreground()
    if fg and not is_own_window(fg):
        return fg
    return host or 0


def force_foreground(hwnd: int) -> bool:
    """把焦点还给目标窗口。

    SetForegroundWindow 有前台锁，直接调常常失败，
    标准做法是临时 AttachThreadInput 到当前前台线程。
    """
    if not hwnd:
        return False
    user32.ShowWindow(hwnd, SW_RESTORE)
    if user32.SetForegroundWindow(hwnd):
        return True

    fg = user32.GetForegroundWindow()
    cur = kernel32.GetCurrentThreadId()
    t1 = user32.GetWindowThreadProcessId(fg, None)
    t2 = user32.GetWindowThreadProcessId(hwnd, None)
    user32.AttachThreadInput(cur, t1, True)
    user32.AttachThreadInput(cur, t2, True)
    ok = bool(user32.SetForegroundWindow(hwnd))
    user32.AttachThreadInput(cur, t1, False)
    user32.AttachThreadInput(cur, t2, False)
    return ok


def send_paste(delay: float = 0.12) -> None:
    time.sleep(delay)
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(VK_V, 0, 0, 0)
    user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


def register_hotkey(key: int = ord("E"), mods: int = MOD_CONTROL | MOD_SHIFT) -> bool:
    return bool(user32.RegisterHotKey(None, 1, mods | MOD_NOREPEAT, key))


def unregister_hotkey() -> None:
    user32.UnregisterHotKey(None, 1)


# ---------- 窗口定位 ----------
# 挂件要住在 agent 窗口里，而不是满屏乱飘。所以要能找到宿主窗口、
# 拿到它的矩形、并且把自己的窗口设成它的「附属窗口」（owned window）——
# 附属窗口会跟着宿主最小化，也不会盖在别的应用上面。

GWLP_HWNDPARENT = -8
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


def _process_name(pid: int) -> str:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        kernel32.CloseHandle(handle)


def find_host_window(keywords: tuple[str, ...]) -> int:
    """按进程名关键字找主窗口，取面积最大的那个。"""
    found: list[tuple[int, int]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindow(hwnd, 4):  # GW_OWNER=4，跳过弹窗类小窗口
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return True
        path = _process_name(pid.value).lower()
        if not path or not any(k.lower() in path for k in keywords):
            return True
        rect = RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        area = (rect.right - rect.left) * (rect.bottom - rect.top)
        if area > 0:
            found.append((area, hwnd))
        return True

    user32.EnumWindows(callback, 0)
    if not found:
        return 0
    found.sort(reverse=True)
    return found[0][1]


def window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    if not hwnd or not user32.IsWindow(hwnd):
        return None
    rect = RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return rect.left, rect.top, rect.right, rect.bottom


def is_minimized(hwnd: int) -> bool:
    return bool(hwnd) and bool(user32.IsIconic(hwnd))


def toplevel_hwnd(tk_widget) -> int:
    """tkinter 的 winfo_id 返回的是子窗口，真正的顶层窗口是它的父窗口。"""
    return user32.GetParent(tk_widget.winfo_id()) or tk_widget.winfo_id()


def set_owner(hwnd: int, owner: int) -> bool:
    """把窗口设为 owner 的附属窗口。

    注意：实测 tk 的 overrideredirect 窗口上调用 SetWindowLongPtr(GWLP_HWNDPARENT)
    拿不到 owner 关系（GetWindow(GW_OWNER) 仍为 0）。所以挂件不依赖它，
    改用「前台跟随」策略：宿主在前台时置顶显示，切走就收起。
    """
    if not hwnd:
        return False
    user32.SetWindowLongPtrW.argtypes = [
        wintypes.HWND, ctypes.c_int, ctypes.c_void_p
    ]
    user32.SetWindowLongPtrW.restype = ctypes.c_void_p
    user32.SetWindowLongPtrW(hwnd, GWLP_HWNDPARENT, owner)
    return bool(user32.GetWindow(hwnd, 4))


def root_window(hwnd: int) -> int:
    return user32.GetAncestor(hwnd, 2)  # GA_ROOT


def is_active(hwnd: int) -> bool:
    """宿主窗口当前是否处于前台（或前台窗口就是它的子窗口）。"""
    if not hwnd:
        return False
    fg = user32.GetForegroundWindow()
    if not fg:
        return False
    return root_window(fg) == root_window(hwnd)
