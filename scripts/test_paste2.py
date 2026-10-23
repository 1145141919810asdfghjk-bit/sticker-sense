"""逐段排查粘贴链路：剪贴板内容对不对 → 前台对不对 → 键盘焦点对不对。"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
import tkinter as tk
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from sticker_sense import clipboard  # noqa: E402

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# 64 位下句柄默认按 int 返回会被截断，必须显式声明
user32.GetClipboardData.restype = ctypes.c_void_p
user32.GetClipboardData.argtypes = [wintypes.UINT]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
user32.GetFocus.restype = ctypes.c_void_p

TOKEN = "[sticker:pastecheck]"

root = tk.Tk()
root.title("粘贴靶子")
root.geometry("420x160+240+240")
text = tk.Text(root, font=("Consolas", 11))
text.pack(fill="both", expand=True, padx=8, pady=8)
root.update()
root.focus_force()
text.focus_set()
root.update()


def read_clip_text() -> str:
    CF_UNICODETEXT = 13
    if not user32.OpenClipboard(None):
        return "<打不开剪贴板>"
    try:
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return "<没有 CF_UNICODETEXT>"
        p = kernel32.GlobalLock(h)
        if not p:
            return "<锁不住>"
        try:
            s = ctypes.wstring_at(p)
        finally:
            kernel32.GlobalUnlock(h)
        return s
    finally:
        user32.CloseClipboard()


def focused_window_of_foreground():
    fg = user32.GetForegroundWindow()
    tid = user32.GetWindowThreadProcessId(fg, None)
    cur = kernel32.GetCurrentThreadId()
    user32.AttachThreadInput(cur, tid, True)
    f = user32.GetFocus()
    user32.AttachThreadInput(cur, tid, False)
    return fg, f


def worker():
    time.sleep(1.2)
    hwnd = clipboard.toplevel_hwnd(root)

    img = Image.new("RGB", (48, 48), (255, 213, 26))
    clipboard.set_image_and_text(img, TOKEN)
    print(f"1) 剪贴板文本 = {read_clip_text()!r}")

    ok = clipboard.force_foreground(hwnd)
    time.sleep(0.2)
    fg, f = focused_window_of_foreground()
    print(f"2) force_foreground={ok} 前台={fg}(期望 {hwnd}) 焦点={f}")

    clipboard.send_paste(0.15)
    time.sleep(0.6)

    content = text.get("1.0", "end").strip()
    print(f"3) 文本框 = {content!r}")

    if TOKEN not in content:
        print("   → Ctrl+V 没生效，改用 WM_PASTE 直接给 Text 控件发消息再试")
        # 找到 Tk 的 Text 子窗口（RichEdit 或 TkChild）
        text_hwnd = f
        WM_PASTE = 0x0302
        user32.SendMessageW(text_hwnd, WM_PASTE, 0, 0)
        time.sleep(0.4)
        content2 = text.get("1.0", "end").strip()
        print(f"   WM_PASTE 后 = {content2!r}")

    root.after(200, root.destroy)


threading.Thread(target=worker, daemon=True).start()
root.mainloop()
