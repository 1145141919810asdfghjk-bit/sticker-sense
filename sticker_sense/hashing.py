"""感知哈希：为每张表情包生成三级指纹。

为什么需要三级：
- 8x8 dHash（64 位）对压缩/缩放极稳，但分辨率太粗，分不清「同模板换字」
  的姐妹表情（实测会认错）。
- 16x16 dHash（256 位）能分辨字形差异，但对裁剪更敏感。
- 颜色网格补上 dHash 转灰度后丢失的颜色信息——同模板不同配色的表情包
  靠这一级就能分开。

识别采用级联：粗筛（8x8 多尺度）→ 细排（16x16 + 颜色加权打分）。
不用 CLIP embedding，因为这里要的是「认出同一张图」而不是「语义相似」。
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

COARSE_SIZE = 8
FINE_SIZE = 16
SCALES = (1.0, 0.85, 0.70, 0.55)
COLOR_GRID = 3

DEFAULT_THRESHOLD = 8
COARSE_GATE = 14
SCORE_GATE = 0.18
AMBIGUOUS_MARGIN = 0.04

SUPPORTED_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


def _flatten(im: Image.Image) -> Image.Image:
    """统一成白底 RGB，透明 PNG / GIF 首帧都能处理。"""
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        return Image.alpha_composite(bg, rgba).convert("RGB")
    return im.convert("RGB")


def _dhash(gray: Image.Image, hash_size: int) -> int:
    small = gray.resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
    px = list(small.getdata())
    bits = 0
    idx = 0
    for row in range(hash_size):
        base = row * (hash_size + 1)
        for col in range(hash_size):
            if px[base + col] > px[base + col + 1]:
                bits |= 1 << idx
            idx += 1
    return bits


def _center_crop(img: Image.Image, ratio: float) -> Image.Image:
    if ratio >= 0.999:
        return img
    w, h = img.size
    cw, ch = max(1, int(w * ratio)), max(1, int(h * ratio))
    left, top = (w - cw) // 2, (h - ch) // 2
    return img.crop((left, top, left + cw, top + ch))


def _color_grid(rgb: Image.Image) -> list[float]:
    """每格存 (r/s, g/s, 亮度)，s = r+g+b。

    用色度而不是绝对 RGB：调亮度、过曝、夜间模式会让绝对 RGB 整体平移，
    实测会把正确结果挤成误判。色度对亮度不敏感，但保留配色差异。
    """
    small = rgb.resize((COLOR_GRID, COLOR_GRID), Image.Resampling.BOX)
    out: list[float] = []
    for r, g, b in list(small.getdata()):
        s = r + g + b + 1e-6
        out.extend((round(r / s, 4), round(g / s, 4), round((r + g + b) / 765.0, 4)))
    return out


def signatures(path: str | Path) -> dict:
    with Image.open(path) as im:
        try:
            im.seek(0)
        except Exception:
            pass
        rgb = _flatten(im)
        gray = rgb.convert("L")
        w, h = rgb.size

        coarse: list[int] = []
        fine: list[int] = []
        for scale in SCALES:
            g = _center_crop(gray, scale)
            coarse.append(_dhash(g, COARSE_SIZE))
            fine.append(_dhash(g, FINE_SIZE))

        return {
            "coarse": coarse,
            "fine": fine,
            "color": _color_grid(_center_crop(rgb, 0.85)),
            "width": w,
            "height": h,
        }


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def min_hamming(probe: list[int], stored: list[int]) -> int:
    return min(hamming(a, b) for a in probe for b in stored)


def color_distance(a: list[float], b: list[float]) -> float:
    """返回 0..1 的色差。色度权重高于亮度权重。"""
    total = 0.0
    for i in range(0, len(a), 3):
        total += abs(a[i] - b[i]) + abs(a[i + 1] - b[i + 1])
        total += 0.25 * abs(a[i + 2] - b[i + 2])
    return min(1.0, total / (len(a) / 3) / 2.25)


def to_hex(value: int) -> str:
    return f"{value:0{(FINE_SIZE * FINE_SIZE) // 4}x}"


def from_hex(text: str) -> int:
    return int(text, 16)
