"""模拟点击挂件球，验证面板弹出。"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
import time
import _utf8  # noqa: F401  Windows 控制台默认 cp1252，不切 print 中文会崩

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

PW_RENDERFULLCONTENT = 0x00000002


def tk_windows():
    out = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def proc(hwnd, lparam):
        if user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, buf, 256)
            if buf.value == "TkTopLevel":
                n = user32.GetWindowTextLengthW(hwnd)
                t = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, t, n + 1)
                r = wt.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(r))
                out.append((hwnd, t.value, (r.left, r.top, r.right, r.bottom)))
        return True

    user32.EnumWindows(proc, 0)
    return out


def grab(hwnd, path):
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    hdc = user32.GetWindowDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mdc, bmp)
    user32.PrintWindow(hwnd, mdc, PW_RENDERFULLCONTENT)

    class BIH(ctypes.Structure):
        _fields_ = [
            ("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
            ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
            ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
            ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
            ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD),
        ]

    bi = BIH()
    bi.biSize = ctypes.sizeof(BIH)
    bi.biWidth = w
    bi.biHeight = -h
    bi.biPlanes = 1
    bi.biBitCount = 32
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
    from PIL import Image
    img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1)
    img.convert("RGB").save(path)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(hwnd, hdc)
    return (w, h)


before = tk_windows()
print("点击前 Tk 窗口:")
for hwnd, t, r in before:
    print(f"  hwnd={hwnd} title={t!r} rect={r}")

ball = None
for hwnd, t, r in before:
    if t == "表情挂件" and (r[2] - r[0]) <= 80:
        ball = (hwnd, r)
        break

if not ball:
    print("没找到球")
    sys.exit(1)

cx = (ball[1][0] + ball[1][2]) // 2
cy = (ball[1][1] + ball[1][3]) // 2
print(f"\n点击 ({cx},{cy}) ...")
user32.SetCursorPos(cx, cy)
time.sleep(0.2)
user32.mouse_event(0x0002, 0, 0, 0, 0)  # left down
time.sleep(0.08)
user32.mouse_event(0x0004, 0, 0, 0, 0)  # left up
time.sleep(0.8)

after = tk_windows()
print("\n点击后 Tk 窗口:")
big = None
for hwnd, t, r in after:
    w, h = r[2] - r[0], r[3] - r[1]
    print(f"  hwnd={hwnd} title={t!r} rect={r} size=({w}x{h})")
    if w > 100 and h > 100:
        big = (hwnd, r)

if big:
    size = grab(big[0], "panel_now.png")
    print(f"\n✅ 面板已弹出 {big[1]} 尺寸={size} → panel_now.png")
else:
    print("\n❌ 没有大窗口，面板没弹出")
