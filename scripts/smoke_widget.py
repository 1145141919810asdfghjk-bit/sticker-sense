"""挂件冒烟测试：构建窗口、开面板、关面板，不进 mainloop。

跑法：python scripts/smoke_widget.py
注意：会短暂弹出悬浮球，并在最后写入一次剪贴板。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402

from sticker_sense import clipboard  # noqa: E402
from sticker_sense.library import Library  # noqa: E402
from sticker_sense.widget import Widget  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    lib = Library(ROOT / "data")
    try:
        w = Widget(lib)
        w.root.update()
        print("悬浮球构建 OK")
        print(f"  宿主窗口 hwnd={w.host} rect={clipboard.window_rect(w.host)}")
        print(f"  球位置 ({w.root.winfo_x()}, {w.root.winfo_y()})")

        w.open_panel()
        w.root.update()
        print(f"面板构建 OK，图片引用 {len(w._photos)} 张")

        w.refresh_panel()
        w.root.update()
        print(f"面板刷新 OK，图片引用 {len(w._photos)} 张")

        w.close_panel()
        w.root.update()
        print("面板关闭 OK")

        img = Image.new("RGB", (64, 64), (255, 213, 26))
        clipboard.set_image_and_text(img, "[sticker:selftest]")
        print("剪贴板写入 OK（图片 + 文本双格式）")

        w.quit()
        print("全部通过")
        return 0
    finally:
        lib.close()


if __name__ == "__main__":
    raise SystemExit(main())
