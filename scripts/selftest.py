"""回归测试：验证识别在压缩、缩放、裁剪、调亮度、截图转发后仍能认回同一张图，
同时验证库里没有的图不会被误认。

跑法：python scripts/selftest.py
"""

from __future__ import annotations

import io
import random
import shutil
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sticker_sense.library import Library  # noqa: E402

DEMO = Path(__file__).resolve().parent.parent / "demo"


def degrade(src: Path, kind: str, out: Path) -> Path:
    with Image.open(src) as im:
        im = im.convert("RGB")
        w, h = im.size
        if kind == "half_jpeg":
            im.resize((w // 2, h // 2), Image.Resampling.LANCZOS).save(
                out, "JPEG", quality=55
            )
        elif kind == "double_webp":
            im.resize((w * 2, h * 2), Image.Resampling.BICUBIC).save(
                out, "WEBP", quality=80
            )
        elif kind == "crop85":
            cw, ch = int(w * 0.85), int(h * 0.85)
            left, top = (w - cw) // 2, (h - ch) // 2
            im.crop((left, top, left + cw, top + ch)).save(out, "PNG")
        elif kind == "bright":
            ImageEnhance.Brightness(im).enhance(1.15).save(out, "JPEG", quality=70)
        elif kind == "screenshot":
            buf = io.BytesIO()
            im.resize((w // 2, h // 2)).save(buf, "JPEG", quality=40)
            buf.seek(0)
            Image.open(buf).convert("RGB").resize((w, h)).save(out, "PNG")
    return out


def negatives(tmp: Path) -> list[Path]:
    random.seed(7)
    paths = []

    solid = Image.new("RGB", (240, 240), (140, 80, 200))
    paths.append(_save(solid, tmp / "neg_solid.png"))

    noise = Image.new("RGB", (240, 240))
    noise.putdata([(random.randint(0, 255),) * 3 for _ in range(240 * 240)])
    paths.append(_save(noise, tmp / "neg_noise.png"))

    grad = Image.new("RGB", (240, 240))
    for y in range(240):
        for x in range(240):
            grad.putpixel((x, y), (x, x, y))
    paths.append(_save(grad, tmp / "neg_grad.png"))

    box = Image.new("RGB", (240, 240), (255, 255, 255))
    draw = ImageDraw.Draw(box)
    draw.rectangle((20, 20, 220, 220), outline=(0, 0, 0), width=6)
    paths.append(_save(box, tmp / "neg_box.png"))
    return paths


def _save(im: Image.Image, path: Path) -> Path:
    im.save(path)
    return path


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="sticker-selftest-"))
    lib = Library(tmp)
    try:
        lib.import_path(DEMO)
        items = lib.list_stickers()
        print(f"导入 {len(items)} 张\n")
        if not items:
            print("没有可测的图，先跑 scripts/make_demo.py")
            return 1

        sample = Path(items[0]["file"])
        truth = items[0]["id"]
        lib.tag(truth, "无语到不想解释", "对方说了明显不合理的话时")
        lib.tag(truth, "礼貌性敷衍", "不想继续这个话题时")

        cases = ["half_jpeg", "double_webp", "crop85", "bright", "screenshot"]
        passed = 0
        print(f"正样本（基准 {Path(sample).name} id={truth}）")
        for kind in cases:
            out = degrade(sample, kind, tmp / f"probe_{kind}.png")
            res = lib.identify(out)
            ok = res.get("matched") and res.get("sticker_id") == truth
            passed += 1 if ok else 0
            print(
                f"  {'PASS' if ok else 'FAIL'}  {kind:<12} "
                f"score={res.get('score')}  matched={res.get('sticker_id')}"
            )

        print("\n负样本（库里没有的图，必须拒绝）")
        neg_pass = 0
        for p in negatives(tmp):
            res = lib.identify(p)
            ok = not res.get("matched")
            neg_pass += 1 if ok else 0
            print(f"  {'PASS' if ok else 'FAIL'}  {p.name:<16} matched={res.get('matched')}")

        total = len(cases) + neg_pass
        print(f"\n正样本 {passed}/{len(cases)} · 负样本 {neg_pass}/4 · 合计 {total}/{len(cases) + 4}")

        print("\n读法回读：")
        for r in lib.show(truth)["readings"]:
            print(f"  - {r['meaning']}（语境：{r['context_hint']}）conf={r['confidence']}")

        return 0 if passed == len(cases) and neg_pass == 4 else 2
    finally:
        lib.close()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
