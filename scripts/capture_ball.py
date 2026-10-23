"""用 PrintWindow 直接抓窗口内容，验证分层窗口（-transparentcolor）是否真的画出来了。

ImageGrab 走 BitBlt，抓不到 WS_EX_LAYERED 窗口；PrintWindow 直接问窗口要画面。
跑法：python scripts/capture_ball.py
"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sticker_sense.library import Library  # noqa: E402
from sticker_sense.widget import Widget  # noqa: E402

u = ctypes.windll.user32
g = ctypes.windll.gdi32

PW_RENDERFULLCONTENT = 0x00000002


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


def grab_window(hwnd: int, w: int, h: int) -> Image.Image:
    hdc_screen = u.GetDC(0)
    hdc = g.CreateCompatibleDC(hdc_screen)
    bmp = g.CreateCompatibleBitmap(hdc_screen, w, h)
    g.SelectObject(hdc, bmp)

    ok = u.PrintWindow(hwnd, hdc, PW_RENDERFULLCONTENT)

    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0

    buf = ctypes.create_string_buffer(w * h * 4)
    g.GetDIBits(hdc, bmp, 0, h, buf, ctypes.byref(bmi), 0)

    img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")

    g.DeleteObject(bmp)
    g.DeleteDC(hdc)
    u.ReleaseDC(0, hdc_screen)
    print(f"PrintWindow 返回 {ok}")
    return img


def main() -> int:
    lib = Library(ROOT / "data")
    w = Widget(lib)
    for _ in range(8):
        w.root.update()
        time.sleep(0.1)

    hwnd = ctypes.windll.user32.GetParent(w.root.winfo_id()) or w.root.winfo_id()
    print(f"球窗口 hwnd={hwnd} 尺寸={w.root.winfo_width()}x{w.root.winfo_height()}")

    img = grab_window(hwnd, w.root.winfo_width(), w.root.winfo_height())
    colors = img.getcolors(maxcolors=100000) or []
    colors.sort(reverse=True)
    print("出现最多的颜色：", colors[:4])
    img.resize((img.width * 4, img.height * 4), Image.Resampling.NEAREST).save(
        ROOT / "ball_printwindow.png"
    )
    print("已保存 ball_printwindow.png")

    w.quit()
    lib.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
