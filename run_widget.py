"""挂件启动器：不依赖工作目录。

WMI / 计划任务这类拉起方式不保证 CurrentDirectory，所以入口脚本自己
把项目根塞进 sys.path，并把数据目录解析成绝对路径。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sticker_sense import widget  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(widget.main(str(ROOT / "data")))
