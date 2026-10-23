"""诊断脚本：启动挂件后检查它到底建出了什么窗口。

跑法：python scripts/inspect_widget.py
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
u = ctypes.windll.user32

WS_CHILD = 0x40000000
WS_POPUP = 0x80000000
GWL_STYLE = -16


def dump(pid: int) -> None:
    rows: list[str] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def walk(hwnd, _lparam):
        p = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value != pid:
            return True
        r = wintypes.RECT()
        u.GetWindowRect(hwnd, ctypes.byref(r))
        cls = ctypes.create_unicode_buffer(256)
        u.GetClassNameW(hwnd, cls, 256)
        title = ctypes.create_unicode_buffer(256)
        u.GetWindowTextW(hwnd, title, 256)
        style = u.GetWindowLongW(hwnd, GWL_STYLE)
        flags = []
        if style & WS_CHILD:
            flags.append("CHILD")
        if style & WS_POPUP:
            flags.append("POPUP")
        rows.append(
            f"  hwnd={hwnd} class={cls.value!r} title={title.value!r} "
            f"rect=({r.left},{r.top},{r.right},{r.bottom}) "
            f"visible={bool(u.IsWindowVisible(hwnd))} style={'|'.join(flags)}"
        )
        return True

    u.EnumWindows(walk, 0)
    if not rows:
        print("  （没有任何顶层窗口）")
    for row in rows:
        print(row)


def main() -> int:
    exe = Path("D:/python310/pythonw.exe")
    if not exe.exists():
        exe = Path(sys.executable)
    proc = subprocess.Popen(
        [str(exe), "-m", "sticker_sense.cli", "widget"],
        cwd=str(ROOT),
        creationflags=0x00000008,
    )
    print(f"启动 pid={proc.pid}，等待 3 秒…")
    time.sleep(3)
    print(f"进程存活：{proc.poll() is None}")
    dump(proc.pid)

    print("\n枚举全部子窗口：")

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def child(hwnd, _lparam):
        r = wintypes.RECT()
        u.GetWindowRect(hwnd, ctypes.byref(r))
        cls = ctypes.create_unicode_buffer(256)
        u.GetClassNameW(hwnd, cls, 256)
        print(f"  child hwnd={hwnd} class={cls.value!r} rect=({r.left},{r.top},{r.right},{r.bottom})")
        return True

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def top(hwnd, _lparam):
        p = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == proc.pid:
            u.EnumChildWindows(hwnd, child, 0)
        return True

    u.EnumWindows(top, 0)

    proc.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
