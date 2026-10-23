"""把标准输出切成 UTF-8。

Windows 的控制台默认编码是 cp1252（GitHub Actions 的 Windows runner 就是），
`print` 一个中文就 UnicodeEncodeError。这不是边缘情况：`cli list` 输出的 JSON
带 `ensure_ascii=False`，同样会崩。

所以在包被 import 的时候就切掉，比在每个 print 前想办法可靠。
"""

from __future__ import annotations

import sys


def force_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            # 已经被夺走或者不是 TextIOWrapper，忽略
            pass
