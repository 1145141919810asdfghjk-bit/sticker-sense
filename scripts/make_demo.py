"""生成 6 张示例表情（小黄脸），用于跑通流程和做回归测试。

刻意不用文字标签，而是画成真正的表情图形——占位素材也不该丑。
正式使用时删掉 demo/ 目录，换成自己的表情包。
"""

from pathlib import Path

from PIL import Image, ImageDraw
import _utf8  # noqa: F401  Windows 控制台默认 cp1252，不切 print 中文会崩

SIZE = 240
FACE = (255, 213, 26)
FACE_EDGE = (232, 184, 0)
INK = (52, 44, 20)
BLUSH = (255, 168, 160)
TEAR = (108, 190, 240)

LW = 7
EYE_L = (88, 100)
EYE_R = (152, 100)
EYE_R_RAD = 12


def _face(draw: ImageDraw.ImageDraw) -> None:
    pad = 12
    draw.ellipse((pad, pad, SIZE - pad, SIZE - pad), fill=FACE)
    draw.ellipse((pad, pad, SIZE - pad, SIZE - pad), outline=FACE_EDGE, width=3)


def _dot(draw, center, r=EYE_R_RAD) -> None:
    x, y = center
    draw.ellipse((x - r, y - r, x + r, y + r), fill=INK)


def _line(draw, x1, y1, x2, y2, width=LW) -> None:
    draw.line((x1, y1, x2, y2), fill=INK, width=width)
    for x, y in ((x1, y1), (x2, y2)):
        draw.ellipse((x - width / 2, y - width / 2, x + width / 2, y + width / 2), fill=INK)


def _arc(draw, box, start, end, width=LW) -> None:
    draw.arc(box, start, end, fill=INK, width=width)


def wuyu(d: ImageDraw.ImageDraw) -> None:
    _line(d, 72, 100, 104, 100)
    _line(d, 136, 100, 168, 100)
    _line(d, 100, 170, 140, 170)


def pofang(d: ImageDraw.ImageDraw) -> None:
    _arc(d, (70, 92, 106, 124), 0, 180)
    _arc(d, (134, 92, 170, 124), 0, 180)
    d.ellipse((96, 142, 144, 192), fill=INK)
    d.polygon([(72, 118), (84, 118), (78, 142)], fill=TEAR)
    d.polygon([(156, 118), (168, 118), (162, 142)], fill=TEAR)


def deyi(d: ImageDraw.ImageDraw) -> None:
    _arc(d, (70, 88, 106, 120), 180, 360)
    _arc(d, (134, 88, 170, 120), 180, 360)
    _arc(d, (78, 128, 162, 190), 0, 180, width=8)


def fuyan(d: ImageDraw.ImageDraw) -> None:
    _dot(d, (EYE_L[0], EYE_L[1] - 2), 11)
    _line(d, 136, 96, 168, 96)
    _line(d, 108, 172, 150, 168, width=6)
    d.ellipse((60, 148, 78, 160), fill=BLUSH)
    d.ellipse((162, 148, 180, 160), fill=BLUSH)


def baobao(d: ImageDraw.ImageDraw) -> None:
    _dot(d, (EYE_L[0], EYE_L[1] + 2), 17)
    _dot(d, (EYE_R[0], EYE_R[1] + 2), 17)
    d.ellipse((82, 90, 94, 102), fill=(255, 255, 255))
    d.ellipse((146, 90, 158, 102), fill=(255, 255, 255))
    d.ellipse((110, 150, 130, 166), fill=INK)
    d.ellipse((52, 132, 84, 150), fill=BLUSH)
    d.ellipse((156, 132, 188, 150), fill=BLUSH)


def zhennu(d: ImageDraw.ImageDraw) -> None:
    _line(d, 68, 80, 106, 94, width=8)
    _line(d, 172, 80, 134, 94, width=8)
    _dot(d, (EYE_L[0], EYE_L[1] + 6), 11)
    _dot(d, (EYE_R[0], EYE_R[1] + 6), 11)
    d.rectangle((94, 146, 146, 186), fill=INK)
    d.rectangle((104, 156, 136, 176), fill=(160, 70, 70))


ITEMS = [
    ("无语", wuyu),
    ("破防", pofang),
    ("得意", deyi),
    ("敷衍", fuyan),
    ("求抱抱", baobao),
    ("震怒", zhennu),
]


def main() -> None:
    out_dir = Path(__file__).resolve().parent.parent / "demo"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, fn in ITEMS:
        img = Image.new("RGB", (SIZE, SIZE), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        _face(draw)
        fn(draw)
        img.save(out_dir / f"{name}.png")
    print(f"生成 {len(ITEMS)} 张到 {out_dir}")


if __name__ == "__main__":
    main()
