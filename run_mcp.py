"""MCP server 启动器：不依赖工作目录。

客户端（WorkBuddy / Claude Desktop 等）拉起进程时的 cwd 不可控，
所以入口脚本自己把项目根塞进 sys.path，数据目录解析成绝对路径。
用 STICKER_DATA 环境变量可以换数据目录。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sticker_sense import mcp_server  # noqa: E402

if __name__ == "__main__":
    data = os.environ.get("STICKER_DATA") or str(ROOT / "data")
    raise SystemExit(mcp_server.main(data))
