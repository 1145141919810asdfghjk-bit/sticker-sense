from ._console import force_utf8
from .library import Library

# Windows 控制台默认 cp1252，不切的话 print 中文就 UnicodeEncodeError。
# 放在 import 时做，覆盖 cli / picker / webadmin 等所有会输出中文的路径。
force_utf8()

__all__ = ["Library"]
__version__ = "0.2.0"
