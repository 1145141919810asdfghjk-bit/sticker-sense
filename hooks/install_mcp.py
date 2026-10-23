"""把 MCP server 装进客户端的 mcp.json。

装完之后 AI 就能自己调 identify / tag / pick 这些工具，
不用再靠人肉跑命令行。

用法：
    python hooks/install_mcp.py            # 安装
    python hooks/install_mcp.py --remove   # 卸载

支持 WorkBuddy（~/.workbuddy-ai/mcp.json）和 Claude Desktop
（~/Library/Application Support/Claude/claude_desktop_config.json 等），
--config 可以指定任意路径。
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER_KEY = "sticker-sense"

CANDIDATES = [
    Path(sys.executable),
    Path("D:/python310/python.exe"),
    Path("/usr/bin/python3"),
    Path("/usr/local/bin/python3"),
]


def pick_python() -> str:
    """MCP server 只需要 Pillow，不需要 tkinter。"""
    seen: set[str] = set()
    for cand in CANDIDATES:
        if not cand or str(cand) in seen or not cand.exists():
            continue
        seen.add(str(cand))
        try:
            ok = subprocess.run(
                [str(cand), "-c", "import PIL"],
                capture_output=True, timeout=15,
            ).returncode == 0
        except Exception:
            ok = False
        if ok:
            return str(cand).replace("\\", "/")
    return sys.executable.replace("\\", "/")


def config_candidates() -> list[Path]:
    home = Path.home()
    return [
        home / ".workbuddy-ai" / "mcp.json",
        home / ".workbuddy" / "mcp.json",
        home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
        home / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json",
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--remove", action="store_true")
    ap.add_argument("--config", default=None, help="指定 mcp.json 路径")
    args = ap.parse_args()

    if args.config:
        path = Path(args.config).expanduser()
    else:
        # 优先用已经存在的配置；都没有就写 WorkBuddy 的默认位置
        existing = [p for p in config_candidates() if p.exists()]
        path = existing[0] if existing else config_candidates()[0]

    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8") or "{}")
        except ValueError:
            print(f"{path} 不是合法 JSON，先手动修一下")
            return 1

    servers = data.setdefault("mcpServers", {})

    if args.remove:
        if SERVER_KEY in servers:
            servers.pop(SERVER_KEY)
            action = "已卸载"
        else:
            action = "本来就没装"
    else:
        python_exe = pick_python()
        servers[SERVER_KEY] = {
            "command": python_exe,
            "args": [(ROOT / "run_mcp.py").as_posix()],
            "env": {"STICKER_DATA": (ROOT / "data").as_posix()},
        }
        action = f"已安装（解释器 {python_exe}）"

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_suffix(".json.bak")
        shutil.copy2(path, backup)
    else:
        backup = None

    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(action)
    print(f"配置：{path}")
    if backup:
        print(f"备份：{backup}")
    print()
    print("下一步：重启客户端，然后在自定义连接器里对这个 server 点「信任」。")
    print("        AI 之后就能自己调 identify / tag / pick 了。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
