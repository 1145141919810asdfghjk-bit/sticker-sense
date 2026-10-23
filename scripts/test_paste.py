"""端到端验证「写剪贴板 → 抢回焦点 → Ctrl+V」这条链路。

自建一个 Tk 文本框当靶子：它只认 CF_UNICODETEXT，
正好能验证双格式剪贴板的纯文本回退分支。
"""

from __future__ import annotations

import sys
import threading
import time
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from sticker_sense import clipboard  # noqa: E402

TOKEN = "[sticker:pastecheck]"

root = tk.Tk()
root.title("粘贴靶子")
root.geometry("420x160+240+240")
text = tk.Text(root, font=("Consolas", 11))
text.pack(fill="both", expand=True, padx=8, pady=8)
text.insert("1.0", "")
root.update()
root.focus_force()

result = {"ok": False, "content": ""}


def worker():
    time.sleep(1.0)
    hwnd = clipboard.toplevel_hwnd(root)
    print(f"靶子 hwnd={hwnd}")

    # 造一张小图，模拟真实表情
    img = Image.new("RGB", (48, 48), (255, 213, 26))
    clipboard.set_image_and_text(img, TOKEN)

    # 抢焦点前先确认焦点在哪
    print(f"粘贴前前台 pid={clipboard.window_pid(clipboard.foreground())} 自己={clipboard.is_own_window(clipboard.foreground())}")

    ok = clipboard.force_foreground(hwnd)
    print(f"force_foreground={ok}")
    clipboard.send_paste(0.2)

    time.sleep(0.5)
    result["content"] = text.get("1.0", "end").strip()
    result["ok"] = TOKEN in result["content"]
    root.after(200, root.destroy)


threading.Thread(target=worker, daemon=True).start()
root.mainloop()

print(f"\n文本框内容 = {result['content']!r}")
print("✅ 粘贴链路正常" if result["ok"] else "❌ 粘贴没进来")
sys.exit(0 if result["ok"] else 1)
