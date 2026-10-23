"""检查挂件窗口的层级与可见性：球中心点最顶层窗口是谁。"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import _utf8  # noqa: F401  Windows 控制台默认 cp1252，不切 print 中文会崩

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

user32.FindWindowW.restype = wt.HWND
user32.WindowFromPoint.restype = wt.HWND
user32.GetAncestor.restype = wt.HWND

GA_ROOT = 2
GA_ROOTOWNER = 3


def rect(hwnd):
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)


def title(hwnd):
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def cls(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def pid_of(hwnd):
    p = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
    return p.value


# 1. 找挂件顶层窗口：枚举所有窗口，找 tk 的 overrideredirect 窗口
found = []


@ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
def enum_proc(hwnd, lparam):
    if user32.IsWindowVisible(hwnd):
        c = cls(hwnd)
        t = title(hwnd)
        p = pid_of(hwnd)
        r = rect(hwnd)
        w = r[2] - r[0]
        h = r[3] - r[1]
        if c == "TkTopLevel" or (50 <= w <= 400 and 50 <= h <= 500 and p and "python" in "python"):
            found.append((hwnd, c, t, p, r))
    return True


user32.EnumWindows(enum_proc, 0)

print("=== 可见 Tk 窗口 ===")
for hwnd, c, t, p, r in found:
    print(f"hwnd={hwnd} cls={c} title={t!r} pid={p} rect={r} size=({r[2]-r[0]}x{r[3]-r[1]})")

# 2. 前台窗口
fg = user32.GetForegroundWindow()
print(f"\n=== 前台窗口 ===")
print(f"hwnd={fg} cls={cls(fg)} title={title(fg)!r} pid={pid_of(fg)} rect={rect(fg)}")
print(f"root(fg)={user32.GetAncestor(fg, GA_ROOT)}")

# 3. 对每个挂件窗口，取中心点做命中测试
print("\n=== 命中测试 ===")
for hwnd, c, t, p, r in found:
    cx = (r[0] + r[2]) // 2
    cy = (r[1] + r[3]) // 2
    hit = user32.WindowFromPoint(wt.POINT(cx, cy))
    root = user32.GetAncestor(hit, GA_ROOT)
    print(f"挂件 hwnd={hwnd} 中心=({cx},{cy})")
    print(f"  命中 hwnd={hit} cls={cls(hit)} pid={pid_of(hit)}")
    print(f"  命中 root={root} cls={cls(root)} title={title(root)!r} pid={pid_of(root)}")
    print(f"  {'✅ 球在最顶层' if root == hwnd or hit == hwnd else '❌ 被遮挡'}")
