"""验证：点击球之后，前台窗口到底是宿主还是挂件自己。"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
import time

user32 = ctypes.windll.user32

GA_ROOT = 2


def cls(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def title(hwnd):
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def tk_ball():
    hits = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def proc(hwnd, lparam):
        if user32.IsWindowVisible(hwnd):
            if cls(hwnd) == "TkTopLevel":
                r = wt.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(r))
                if (r.right - r.left) <= 80 and "表情" in title(hwnd):
                    hits.append((hwnd, (r.left, r.top, r.right, r.bottom)))
        return True

    user32.EnumWindows(proc, 0)
    return hits[0] if hits else None


fg = user32.GetForegroundWindow()
print(f"点击前前台: {cls(fg)} / {title(fg)!r}")

b = tk_ball()
if not b:
    print("没找到球")
    sys.exit(1)
hwnd, r = b
cx, cy = (r[0] + r[2]) // 2, (r[1] + r[3]) // 2
print(f"球 hwnd={hwnd} rect={r}")

user32.SetCursorPos(cx, cy)
time.sleep(0.15)
user32.mouse_event(0x0002, 0, 0, 0, 0)
time.sleep(0.08)
user32.mouse_event(0x0004, 0, 0, 0, 0)
time.sleep(0.6)

fg2 = user32.GetForegroundWindow()
print(f"\n点击后前台: hwnd={fg2} cls={cls(fg2)} title={title(fg2)!r}")
print(f"  前台 root = {user32.GetAncestor(fg2, GA_ROOT)}")
print(f"  球   root = {user32.GetAncestor(hwnd, GA_ROOT)}")
same = user32.GetAncestor(fg2, GA_ROOT) == user32.GetAncestor(hwnd, GA_ROOT)
print(f"  {'⚠️ 前台变成了挂件自己 —— 粘回会失败' if same else '✅ 前台仍是宿主，粘回没问题'}")

# 关掉面板
user32.keybd_event(0x1B, 0, 0, 0)
time.sleep(0.05)
user32.keybd_event(0x1B, 0, 2, 0)
