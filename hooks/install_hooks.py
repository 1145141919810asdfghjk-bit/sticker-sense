"""把 SessionStart hook 装进 WorkBuddy 的 settings.json。

装完之后：每次 WorkBuddy 会话启动，挂件会自动起来；会话窗口关掉，挂件自己退出。

用法：
    python hooks/install_hooks.py            # 安装
    python hooks/install_hooks.py --remove   # 卸载

注意：WorkBuddy 的 hook 配置在启动时缓存，装完必须**完全退出**再启动才生效
（点窗口关闭按钮不算退出，要真正退出进程）。
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 用来识别「这条 hook 是不是我们自己装的」，重复安装时先清掉旧的
MARKER = "session_start.py"

CANDIDATES = [
    Path(sys.executable),
    Path("D:/python310/python.exe"),
    Path("/usr/bin/python3"),
    Path("/usr/local/bin/python3"),
]


def pick_python() -> str:
    """找一个同时带 tkinter 和 Pillow 的解释器——挂件两个都要。"""
    seen: set[str] = set()
    for cand in CANDIDATES:
        if not cand or str(cand) in seen or not cand.exists():
            continue
        seen.add(str(cand))
        try:
            ok = subprocess.run(
                [str(cand), "-c", "import tkinter, PIL"],
                capture_output=True, timeout=15,
            ).returncode == 0
        except Exception:
            ok = False
        if ok:
            return str(cand).replace("\\", "/")
    return sys.executable.replace("\\", "/")


def settings_path() -> Path:
    home = Path.home()
    for p in (home / ".workbuddy-ai" / "settings.json",
              home / ".workbuddy" / "settings.json"):
        if p.exists():
            return p
    return home / ".workbuddy-ai" / "settings.json"


def build_entry(python_exe: str) -> dict:
    hook_script = (ROOT / "hooks" / "session_start.py").as_posix()
    command = f'"{python_exe}" "{hook_script}"'
    return {
        "hooks": [
            {"type": "command", "command": command, "timeout": 10}
        ]
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--remove", action="store_true")
    ap.add_argument("--settings", default=None)
    args = ap.parse_args()

    path = Path(args.settings) if args.settings else settings_path()
    if not path.exists():
        print(f"找不到 {path}")
        return 1

    data = json.loads(path.read_text(encoding="utf-8"))
    hooks = data.setdefault("hooks", {})
    entries = hooks.setdefault("SessionStart", [])

    # 先清掉旧的自己，避免重复安装
    kept = [
        e for e in entries
        if not any(MARKER in h.get("command", "") for h in e.get("hooks", []))
    ]
    entries[:] = kept

    if args.remove:
        if not entries:
            hooks.pop("SessionStart", None)
        action = "已卸载"
    else:
        python_exe = pick_python()
        entries.append(build_entry(python_exe))
        action = f"已安装（解释器 {python_exe}）"

    backup = path.with_suffix(".json.bak")
    shutil.copy2(path, backup)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"{action}")
    print(f"配置：{path}")
    print(f"备份：{backup}")
    print()
    print("下一步：完全退出 WorkBuddy 再启动（关窗口不算退出），")
    print("        如果 /hooks 面板里能看到 SessionStart，确认一下即可。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
