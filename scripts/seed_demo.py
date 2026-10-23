"""把 demo/ 导入图库并写入示例读法，方便快速体验。

跑法：python scripts/seed_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sticker_sense.library import Library  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

READINGS = {
    "无语": [
        ("无语到不想解释", "对方说了明显不合理的话时"),
        ("礼貌性敷衍", "不想继续这个话题但不好直接拒绝"),
    ],
    "破防": [("被戳到痛处，情绪绷不住", "被提到加班、体重、存款这类话题时")],
    "得意": [("我就知道会这样", "自己的判断被证实、对方认输时")],
    "敷衍": [("行行行你说得对", "不想争论但也不想认同时")],
    "求抱抱": [("需要被安慰", "状态很差但不想直说时")],
    "震怒": [("真的生气了", "被反复冒犯、忍耐到极限时")],
}


def main() -> int:
    lib = Library(ROOT / "data")
    try:
        name2id: dict[str, str] = {}
        for name in READINGS:
            src = ROOT / "demo" / f"{name}.png"
            if not src.exists():
                print(f"缺少 {src}，先跑 scripts/make_demo.py")
                return 1
            res = lib.import_file(src)
            name2id[name] = res["id"]

        for name, items in READINGS.items():
            for meaning, context in items:
                lib.tag(name2id[name], meaning, context)

        print("图库已就绪：")
        for i in lib.list_stickers():
            print(f"  {i['id']}  {i['top_meaning']}")
        return 0
    finally:
        lib.close()


if __name__ == "__main__":
    raise SystemExit(main())
