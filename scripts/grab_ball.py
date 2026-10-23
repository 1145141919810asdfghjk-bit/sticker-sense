"""用 PrintWindow 抓挂件窗口（ImageGrab 抓不到分层窗口）。"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys

from PIL import Image
import _utf8  # noqa: F401  Windows 控制台默认 cp1252，不切 print 中文会崩

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

PW_RENDERFULLCONTENT = 0x00000002
GA_ROOT = 2


def find_widget():
    hits = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def proc(hwnd, lparam):
        if user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, buf, 256)
            if buf.value == "TkTopLevel":
                n = user32.GetWindowTextLengthW(hwnd)
                t = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, t, n + 1)
                if "表情" in t.value:
                    hits.append(hwnd)
        return True

    user32.EnumWindows(proc, 0)
    return hits[0] if hits else None


def grab(hwnd):
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    hdc = user32.GetWindowDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mdc, bmp)
    ok = user32.PrintWindow(hwnd, mdc, PW_RENDERFULLCONTENT)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
            ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
            ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
            ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
            ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD),
        ]

    bi = BITMAPINFOHEADER()
    bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.biWidth = w
    bi.biHeight = -h
    bi.biPlanes = 1
    bi.biBitCount = 32
    bi.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)

    img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(hwnd, hdc)
    return ok, img, (r.left, r.top, r.right, r.bottom)


hwnd = find_widget()
if not hwnd:
    print("没找到挂件窗口")
    sys.exit(1)

ok, img, rect = grab(hwnd)
img.convert("RGB").save("ball_now.png")
colors = img.convert("RGB").getcolors(maxcolors=1000000) or []
colors.sort(reverse=True)
print(f"hwnd={hwnd} rect={rect} PrintWindow={ok}")
print(f"主色前 6: {colors[:6]}")
print("已保存 ball_now.png")
