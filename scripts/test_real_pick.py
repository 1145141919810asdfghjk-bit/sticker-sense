"""真实链路测试：点球 → 点第一个表情 → 看焦点和剪贴板是否落到宿主。"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import sys
import time
from pathlib import Path
import _utf8  # noqa: F401  Windows 控制台默认 cp1252，不切 print 中文会崩

user32 = ctypes.windll.user32

ROOT = Path(__file__).resolve().parent.parent
GA_ROOT = 2

user32.GetFocus.restype = ctypes.c_void_p
user32.WindowFromPoint.restype = wt.HWND


def cls(hwnd):
    b = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, b, 256)
    return b.value


def title(hwnd):
    n = user32.GetWindowTextLengthW(hwnd)
    b = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, b, n + 1)
    return b.value


def pid_of(hwnd):
    p = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
    return p.value


def tk_windows():
    out = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def proc(hwnd, lparam):
        if user32.IsWindowVisible(hwnd) and cls(hwnd) == "TkTopLevel":
            if "表情" in title(hwnd):
                r = wt.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(r))
                out.append((hwnd, (r.left, r.top, r.right, r.bottom)))
        return True

    user32.EnumWindows(proc, 0)
    return out


def click(x, y):
    user32.SetCursorPos(x, y)
    time.sleep(0.15)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.07)
    user32.mouse_event(0x0004, 0, 0, 0, 0)


wins = tk_windows()
ball = None
for hwnd, r in wins:
    if (r[2] - r[0]) <= 80:
        ball = (hwnd, r)
        break
if not ball:
    print("没找到球")
    sys.exit(1)

bh, br = ball
print(f"球 rect={br}")
click((br[0] + br[2]) // 2, (br[1] + br[3]) // 2)
time.sleep(0.8)

wins = tk_windows()
panel = None
for hwnd, r in wins:
    if (r[2] - r[0]) > 100:
        panel = (hwnd, r)
if not panel:
    print("面板没弹出")
    sys.exit(1)

ph, pr = panel
print(f"面板 rect={pr}")
# 第一个格子：左上角留出 padding 和标题行
cx = pr[0] + 60
cy = pr[1] + 95
print(f"点第一个表情 ({cx},{cy})")
click(cx, cy)
time.sleep(1.2)

fg = user32.GetForegroundWindow()
print(f"\n点完后前台: hwnd={fg} cls={cls(fg)} title={title(fg)!r} pid={pid_of(fg)}")
print(f"  前台 root pid={pid_of(user32.GetAncestor(fg, GA_ROOT))}")

lp = ROOT / "data" / "last_pick.json"
if lp.exists():
    d = json.loads(lp.read_text(encoding="utf-8"))
    age = time.time() - d.get("ts", 0)
    print(f"last_pick: id={d.get('id')} 距今 {age:.1f}s")
else:
    print("last_pick.json 不存在")

# 还剩几个 Tk 窗口（面板应已关闭）
print(f"\n剩余挂件窗口: {[(h, r) for h, r in tk_windows()]}")
