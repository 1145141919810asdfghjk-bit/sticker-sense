"""隔离实验：验证 -transparentcolor 与截图捕获的关系。

跑法：python scripts/test_ball_render.py
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

from PIL import ImageGrab

OUT = Path(__file__).resolve().parent.parent


def build(kind: str, x: int) -> tk.Tk:
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.geometry(f"80x80+{x}+100")

    if kind == "solid":
        root.configure(bg="#E24B4A")
    else:
        root.configure(bg="#FF00FF")
        root.attributes("-transparentcolor", "#FF00FF")
        canvas = tk.Canvas(root, width=80, height=80, bg="#FF00FF", highlightthickness=0)
        canvas.pack()
        canvas.create_oval(6, 6, 74, 74, fill="#FFD51A", outline="#E8B800", width=2)
    root.update()
    return root


def main() -> int:
    a = build("solid", 100)
    b = build("transparent", 220)
    a.update()
    b.update()

    im = ImageGrab.grab(bbox=(80, 80, 340, 200))
    im = im.resize((im.width * 2, im.height * 2), 1)
    im.save(OUT / "render_test.png")
    print("已保存 render_test.png")
    print("  左（100,100）应为纯红方块")
    print("  右（220,100）应为透明背景 + 黄圆")

    a.destroy()
    b.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
