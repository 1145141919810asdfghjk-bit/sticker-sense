"""阈值诊断：打印降质探针与全库的打分矩阵，用来校准 SCORE_GATE。

跑法：python scripts/diagnose.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sticker_sense.library import Library  # noqa: E402

DEMO = Path(__file__).resolve().parent.parent / "demo"


def degrade(src: Path, out: Path) -> Path:
    with Image.open(src) as im:
        im = im.convert("RGB")
        w, h = im.size
        im = im.crop((int(w * 0.08), int(h * 0.08), int(w * 0.92), int(h * 0.92)))
        im = im.resize((w // 2, h // 2), Image.Resampling.LANCZOS)
        im.save(out, "JPEG", quality=50)
    return out


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="sticker-diag-"))
    lib = Library(tmp)
    try:
        lib.import_path(DEMO)
        items = lib.list_stickers()
        ids = [i["id"] for i in items]

        print("降质探针 → 全库打分（每行最小值应为自身，且与次小值有明显间隔）\n")
        header = "探针    " + "".join(f"{i:<9}" for i in ids)
        print(header)

        for it in items:
            probe = degrade(Path(it["file"]), tmp / f"p_{it['id']}.jpg")
            from sticker_sense.hashing import signatures

            ranked = lib.rank(signatures(probe))
            score_map = {r["sticker_id"]: r["score"] for r in ranked}
            row = f"{it['id']:<8}"
            for sid in ids:
                val = score_map.get(sid)
                row += f"{val:<9.3f}" if val is not None else f"{'-':<9}"
            best = ranked[0] if ranked else None
            second = ranked[1] if len(ranked) > 1 else None
            mark = "OK " if best and best["sticker_id"] == it["id"] else "XX "
            gap = (
                f"{second['score'] - best['score']:.3f}"
                if best and second
                else "n/a"
            )
            print(f"{row} {mark} best={best['sticker_id'] if best else None} gap={gap}")

        print("\n阈值参考：")
        print("  SCORE_GATE        当前 0.24 —— 低于此值才算命中")
        print("  AMBIGUOUS_MARGIN  当前 0.04 —— 与次佳差距小于此值标记歧义")
        return 0
    finally:
        lib.close()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
