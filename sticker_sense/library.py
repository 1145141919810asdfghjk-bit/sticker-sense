"""图库核心：导入、识别、读法（readings）的增删改查。

设计要点：
1. 一张表情有多条 readings，不是一个标签。同一个「微笑」在礼貌敷衍和
   压着火时是反义的，做成 key-value 三个月就废。
2. 识别是级联的：sha256 精确 → 8x8 多尺度粗筛 → 16x16 + 颜色细排。
3. 结果带 margin（最佳与次佳的分数差）。margin 太小就标 ambiguous，
   宁可说「不确定」也不要自信地认错。
4. 一切写操作只追加或降权，不硬删读法——误判修正的成本必须极低。
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from . import db
from .hashing import (
    AMBIGUOUS_MARGIN,
    COARSE_GATE,
    FINE_SIZE,
    SCORE_GATE,
    SUPPORTED_EXTS,
    color_distance,
    from_hex,
    min_hamming,
    signatures,
    to_hex,
)

SHORTLIST = 8
FINE_WEIGHT = 0.55
COLOR_WEIGHT = 0.45


class Library:
    def __init__(self, data_dir: str | Path, cross_thread: bool = False):
        self.data_dir = Path(data_dir)
        self.img_dir = self.data_dir / "stickers"
        self.img_dir.mkdir(parents=True, exist_ok=True)
        self.conn = db.connect(self.data_dir, cross_thread=cross_thread)

    def close(self) -> None:
        self.conn.close()

    # ---------- 导入 ----------

    def import_file(self, src: str | Path, source: str = "import") -> dict | None:
        src = Path(src)
        if src.suffix.lower() not in SUPPORTED_EXTS:
            return None

        raw = src.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()

        row = self.conn.execute(
            "SELECT id FROM stickers WHERE sha256 = ?", (sha,)
        ).fetchone()
        if row:
            return {"id": row["id"], "status": "duplicate"}

        sig = signatures(src)
        sid = self._unique_id(sha[:6])
        dest = self.img_dir / f"{sid}{src.suffix.lower()}"
        shutil.copy2(src, dest)

        self.conn.execute(
            "INSERT INTO stickers"
            "(id, file, sha256, hashes_coarse, hashes_fine, color,"
            " width, height, added_at, source) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                sid,
                dest.name,
                sha,
                _dump(sig["coarse"]),
                _dump(sig["fine"]),
                json.dumps(sig["color"]),
                sig["width"],
                sig["height"],
                db.now(),
                source,
            ),
        )
        self.conn.commit()
        return {"id": sid, "status": "added"}

    def import_path(self, target: str | Path) -> list[dict]:
        target = Path(target)
        if target.is_file():
            r = self.import_file(target)
            return [r] if r else []
        results = []
        for p in sorted(target.rglob("*")):
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
                r = self.import_file(p)
                if r:
                    results.append(r)
        return results

    def _unique_id(self, base: str) -> str:
        sid, n = base, 1
        while self.conn.execute("SELECT 1 FROM stickers WHERE id = ?", (sid,)).fetchone():
            n += 1
            sid = f"{base}{n}"
        return sid

    # ---------- 识别 ----------

    def identify(self, path: str | Path, coarse_gate: int | None = None) -> dict:
        """识别一张图。coarse_gate 传 None 时用模块里的默认值。"""
        src = Path(path)
        raw_sha = hashlib.sha256(src.read_bytes()).hexdigest()

        row = self.conn.execute(
            "SELECT * FROM stickers WHERE sha256 = ?", (raw_sha,)
        ).fetchone()
        if row:
            return self._hit(row, coarse=0, fine=0, color=0.0, score=0.0, margin=1.0,
                             method="exact")

        sig = signatures(src)
        ranked = self.rank(sig, coarse_gate=coarse_gate)
        if not ranked:
            return self._miss(None)

        best = ranked[0]
        if best["score"] > SCORE_GATE:
            return self._miss(best)

        row = self.conn.execute(
            "SELECT * FROM stickers WHERE id = ?", (best["sticker_id"],)
        ).fetchone()
        return self._hit(
            row,
            coarse=best["coarse"],
            fine=best["fine"],
            color=best["color"],
            score=best["score"],
            margin=best["margin"],
            method=best["method"],
        )

    def rank(self, sig: dict, coarse_gate: int | None = None) -> list[dict]:
        """级联排序：粗筛出候选，再用细指纹 + 颜色打分。"""
        gate = COARSE_GATE if coarse_gate is None else coarse_gate
        pool: list[dict] = []

        for r in self.conn.execute(
            "SELECT id, hashes_coarse, hashes_fine, color FROM stickers"
        ):
            coarse = min_hamming(sig["coarse"], _load(r["hashes_coarse"]))
            if coarse <= gate:
                pool.append(
                    {
                        "sticker_id": r["id"],
                        "method": "dhash",
                        "coarse": coarse,
                        "fine": min_hamming(sig["fine"], _load(r["hashes_fine"])),
                        "color": color_distance(sig["color"], json.loads(r["color"])),
                    }
                )

        for a in self.conn.execute(
            "SELECT sticker_id, hashes_fine, color FROM aliases"
        ):
            pool.append(
                {
                    "sticker_id": a["sticker_id"],
                    "method": "alias",
                    "coarse": 0,
                    "fine": min_hamming(sig["fine"], _load(a["hashes_fine"])),
                    "color": color_distance(sig["color"], json.loads(a["color"])),
                }
            )

        for item in pool:
            item["score"] = _score(item["fine"], item["color"])

        pool.sort(key=lambda s: s["score"])

        seen: set[str] = set()
        unique: list[dict] = []
        for s in pool:
            if s["sticker_id"] in seen:
                continue
            seen.add(s["sticker_id"])
            unique.append(s)

        for i, s in enumerate(unique):
            s["margin"] = (
                unique[i + 1]["score"] - s["score"] if i + 1 < len(unique) else 1.0
            )
        return unique[:SHORTLIST]

    def _miss(self, nearest: dict | None) -> dict:
        return {
            "matched": False,
            "ambiguous": False,
            "score": nearest["score"] if nearest else None,
            "nearest_id": nearest["sticker_id"] if nearest else None,
            "readings": [],
            "hint": "未知表情。若用户没有解释过它，可以自然地问一句它的意思，"
            "然后调用 tag 写入。不要向用户复述识别过程。",
        }

    def _hit(self, row, coarse: int, fine: int, color: float, score: float,
             margin: float, method: str) -> dict:
        readings = [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM readings WHERE sticker_id = ?"
                " ORDER BY uses DESC, confidence DESC, id ASC",
                (row["id"],),
            )
        ]
        ambiguous = margin < AMBIGUOUS_MARGIN
        hint = (
            "命中，但与另一张表情分数接近（margin 偏小）。优先按当前语境判断，"
            "若明显不符可以问用户一句。"
            if ambiguous
            else "命中。挑选最贴合当前语境的 reading 调整回复语气，不要向用户复述识别结果。"
        )
        return {
            "matched": True,
            "ambiguous": ambiguous,
            "sticker_id": row["id"],
            "score": round(score, 4),
            "margin": round(margin, 4),
            "detail": {"coarse": coarse, "fine": fine, "color": round(color, 2)},
            "method": method,
            "readings": readings,
            "hint": hint,
        }

    # ---------- 读法 ----------

    def tag(
        self,
        sticker_id: str,
        meaning: str,
        context_hint: str = "",
        confidence: float = 0.7,
        origin: str = "user_explained",
    ) -> dict:
        existing = self.conn.execute(
            "SELECT * FROM readings WHERE sticker_id = ? AND meaning = ?",
            (sticker_id, meaning),
        ).fetchone()

        if existing:
            self.conn.execute(
                "UPDATE readings SET context_hint = ?,"
                " confidence = MIN(1.0, confidence + 0.1) WHERE id = ?",
                (context_hint or existing["context_hint"], existing["id"]),
            )
            self.conn.commit()
            return {"id": existing["id"], "status": "reinforced"}

        cur = self.conn.execute(
            "INSERT INTO readings"
            "(sticker_id, meaning, context_hint, confidence, origin, created_at)"
            " VALUES(?,?,?,?,?,?)",
            (sticker_id, meaning, context_hint, confidence, origin, db.now()),
        )
        self.conn.commit()
        return {"id": cur.lastrowid, "status": "added"}

    def record_use(self, sticker_id: str, reading_id: int | None = None) -> None:
        if reading_id is not None:
            self.conn.execute(
                "UPDATE readings SET uses = uses + 1, last_used_at = ? WHERE id = ?",
                (db.now(), reading_id),
            )
        else:
            self.conn.execute(
                "UPDATE readings SET uses = uses + 1, last_used_at = ?"
                " WHERE id = (SELECT id FROM readings WHERE sticker_id = ?"
                " ORDER BY uses DESC, confidence DESC LIMIT 1)",
                (db.now(), sticker_id),
            )
        self.conn.commit()

    def bind_alias(self, sticker_id: str, path: str | Path, note: str = "") -> dict:
        sig = signatures(path)
        self.conn.execute(
            "INSERT INTO aliases(sticker_id, hashes_fine, color, note, created_at)"
            " VALUES(?,?,?,?,?)",
            (sticker_id, _dump(sig["fine"]), json.dumps(sig["color"]), note, db.now()),
        )
        self.conn.commit()
        return {"sticker_id": sticker_id, "status": "alias_bound"}

    # ---------- 查询 ----------

    def show(self, sticker_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM stickers WHERE id = ?", (sticker_id,)
        ).fetchone()
        if not row:
            return None
        return self._hit(row, 0, 0, 0.0, 0.0, 1.0, "direct")

    def list_stickers(self, order: str = "recent") -> list[dict]:
        """order=recent 时按最近使用排序，没用过的按导入时间。

        表情面板应该把常用的顶到前面，否则图一多就得翻半天。
        """
        sql = (
            "SELECT s.*, MAX(r.last_used_at) AS last_used"
            " FROM stickers s LEFT JOIN readings r ON r.sticker_id = s.id"
            " GROUP BY s.id"
        )
        if order == "recent":
            sql += " ORDER BY COALESCE(last_used, s.added_at) DESC"
        else:
            sql += " ORDER BY s.added_at DESC"

        out = []
        for r in self.conn.execute(sql):
            top = self.conn.execute(
                "SELECT meaning FROM readings WHERE sticker_id = ?"
                " ORDER BY uses DESC, confidence DESC LIMIT 1",
                (r["id"],),
            ).fetchone()
            count = self.conn.execute(
                "SELECT COUNT(*) c FROM readings WHERE sticker_id = ?", (r["id"],)
            ).fetchone()["c"]
            out.append(
                {
                    "id": r["id"],
                    "file": (self.img_dir / r["file"]).resolve().as_posix(),
                    "reading_count": count,
                    "top_meaning": top["meaning"] if top else None,
                    "last_used": r["last_used"],
                    "width": r["width"],
                    "height": r["height"],
                }
            )
        return out

    def export_json(self, out: str | Path) -> Path:
        payload = {
            "exported_at": db.now(),
            "stickers": [
                {
                    **dict(r),
                    "readings": [
                        dict(x)
                        for x in self.conn.execute(
                            "SELECT * FROM readings WHERE sticker_id = ?", (r["id"],)
                        )
                    ],
                }
                for r in self.conn.execute("SELECT * FROM stickers")
            ],
        }
        out = Path(out)
        out.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return out


def _score(fine: int, color: float) -> float:
    return FINE_WEIGHT * (fine / (FINE_SIZE * FINE_SIZE)) + COLOR_WEIGHT * color


def _dump(hashes: list[int]) -> str:
    return json.dumps([to_hex(h) for h in hashes])


def _load(text: str) -> list[int]:
    return [from_hex(x) for x in json.loads(text)]
