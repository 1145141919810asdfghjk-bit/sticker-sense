"""让 Windows 控制台能 print 中文。

Windows 默认编码是 cp1252（GitHub Actions 的 Windows runner 就是），
`print` 一个中文直接 UnicodeEncodeError。CI 上三个脚本曾全挂在这一点。

用法：在会输出中文的脚本顶部 `import _utf8  # noqa: F401`。
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
            pass


force_utf8()
