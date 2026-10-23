"""MCP server：把图库暴露给任意支持 MCP 的客户端。

协议是 stdio 上的 JSON-RPC 2.0，一行一条消息，所以不需要任何 MCP SDK，
只要标准库。这样 clone 下来装个 Pillow 就能跑。

暴露的工具分两类：

- **正向**（用户发表情，AI 要懂）：`identify` / `last_pick` / `list` / `show`
- **写入**（AI 学到新含义）：`tag` / `import`
- **反向**（AI 也能发表情）：`pick`

注意 stdout 只能输出 JSON 行，日志一律走 stderr，否则客户端解析会炸。
"""

from __future__ import annotations

import base64
import io
import json
import mimetypes
import sys
import traceback
from pathlib import Path

from .library import Library

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "sticker-sense"
SERVER_VERSION = "0.2.0"

# last_pick.json 超过这个时间就不认了，避免用上一次的旧结果误导
LAST_PICK_TTL = 180


# ---------------------------------------------------------------- 工具定义

TOOLS = [
    {
        "name": "identify",
        "description": (
            "识别用户发来的表情图，返回它的 ID 和全部读法（含义 + 语境提示）。"
            "用户直接粘贴图片、或你没拿到 [sticker:id] 标记时用这个。"
            "拿到读法后请直接按那个情绪调整语气，不要向用户复述识别结果。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图片的本地路径"},
                "image_base64": {
                    "type": "string",
                    "description": "图片的 base64（没有本地路径时用）",
                },
            },
        },
    },
    {
        "name": "last_pick",
        "description": (
            "取用户刚才在桌面挂件里点的表情 ID。"
            "用户粘进来一张表情图但没带 [sticker:id] 标记时，先调这个——"
            "比图像识别精确得多，且能覆盖截图、裁剪等失配情况。"
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "list",
        "description": "列出图库里的表情（ID、主读法、读法条数、最近使用时间）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 30},
                "order": {
                    "type": "string",
                    "enum": ["recent", "added"],
                    "default": "recent",
                    "description": "recent 按最近使用，added 按导入时间",
                },
            },
        },
    },
    {
        "name": "show",
        "description": "查看某张表情的全部读法。想知道一个 ID 到底有几种含义时用。",
        "inputSchema": {
            "type": "object",
            "properties": {"sticker_id": {"type": "string"}},
            "required": ["sticker_id"],
        },
    },
    {
        "name": "tag",
        "description": (
            "给表情写入一条读法。用户解释了这个表情的意思时调用，这是唯一的"
            "「训练」入口。同一个含义重复写入会提高置信度而不是产生重复条目。"
            "写完后简短确认一句即可，不要长篇解释你学到了什么。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sticker_id": {"type": "string"},
                "meaning": {"type": "string", "description": "这个表情表达什么情绪"},
                "context_hint": {
                    "type": "string",
                    "description": "什么语境下用它，比如「对方说了明显不合理的话时」",
                },
                "confidence": {"type": "number", "default": 0.7},
            },
            "required": ["sticker_id", "meaning"],
        },
    },
    {
        "name": "import",
        "description": "导入图片或整个目录到图库。重复的图会按 sha256 自动跳过。",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "pick",
        "description": (
            "从图库里挑一张表情发给用户。用户说「发个表情」「来张图」时用。"
            "mood 会去匹配读法的含义和语境，匹配不到就退回最常用的那张。"
            "返回图片本身，你直接把图片发出去，不需要再解释这是哪个 ID。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "mood": {
                    "type": "string",
                    "description": "想要的情绪关键词，比如「无语」「开心」「敷衍」",
                },
                "sticker_id": {
                    "type": "string",
                    "description": "指定 ID 时直接用，忽略 mood",
                },
            },
        },
    },
]


# ---------------------------------------------------------------- 业务实现


class Session:
    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self.lib = Library(self.data_dir)

    def close(self) -> None:
        self.lib.close()

    # -- 工具实现，返回 (text, extra_content) --

    def t_identify(self, args: dict) -> tuple[str, list]:
        path = args.get("path")
        if not path and args.get("image_base64"):
            path = self._spill_base64(args["image_base64"])
        if not path:
            return "缺少 path 或 image_base64。", []

        p = Path(path).expanduser()
        if not p.exists():
            return f"文件不存在：{p}", []

        res = self.lib.identify(p)
        if not res.get("matched"):
            return (
                "库里没有这张表情。如果用户愿意解释它的意思，"
                "可以自然地问一句，然后用 tag 写入（先用 import 导入它）。"
                f"\n原始结果：{json.dumps(res, ensure_ascii=False)}",
                [],
            )

        body = _readings_text(res["sticker_id"], res["readings"])
        head = f"命中 sticker_id={res['sticker_id']}"
        if res.get("ambiguous"):
            head += "（与另一张分数接近，按语境判断，必要时问一句）"
        return f"{head}\n{body}", []

    def t_last_pick(self, args: dict) -> tuple[str, list]:
        info = self._last_pick()
        if not info:
            return "最近 3 分钟没有挂件点击记录。可以改用 identify。", []
        sid = info["id"]
        shown = self.lib.show(sid)
        if not shown:
            return f"记录里的 {sid} 已不在库中。", []
        return (
            f"用户刚点的表情是 sticker_id={sid}（{info['age']:.0f} 秒前）\n"
            + _readings_text(sid, shown["readings"]),
            [],
        )

    def t_list(self, args: dict) -> tuple[str, list]:
        limit = int(args.get("limit") or 30)
        rows = self.lib.list_stickers(order=args.get("order") or "recent")[:limit]
        if not rows:
            return "图库是空的。用 import 导入图片。", []
        lines = [f"共 {len(rows)} 张（最多显示 {limit}）："]
        for r in rows:
            meaning = r["top_meaning"] or "（未标注）"
            lines.append(
                f"- {r['id']}  {meaning}  "
                f"[{r['reading_count']} 条读法]  最近使用 {r['last_used'] or '—'}"
            )
        return "\n".join(lines), []

    def t_show(self, args: dict) -> tuple[str, list]:
        sid = args.get("sticker_id") or ""
        shown = self.lib.show(sid)
        if not shown:
            return f"没有找到 {sid}。", []
        return _readings_text(sid, shown["readings"]), []

    def t_tag(self, args: dict) -> tuple[str, list]:
        sid = args.get("sticker_id") or ""
        meaning = (args.get("meaning") or "").strip()
        if not sid or not meaning:
            return "sticker_id 和 meaning 都必须给。", []
        if not self.lib.show(sid):
            return f"没有找到 {sid}，先用 import 导入这张图。", []
        res = self.lib.tag(
            sid,
            meaning,
            (args.get("context_hint") or "").strip(),
            float(args.get("confidence") or 0.7),
        )
        verb = "补充了" if res["status"] == "added" else "强化了"
        return f"已为 {sid} {verb}读法：{meaning}", []

    def t_import(self, args: dict) -> tuple[str, list]:
        path = args.get("path")
        if not path:
            return "缺少 path。", []
        p = Path(path).expanduser()
        if not p.exists():
            return f"路径不存在：{p}", []
        results = self.lib.import_path(p)
        added = [r for r in results if r["status"] == "added"]
        dup = len(results) - len(added)
        if not results:
            return "没有找到可导入的图片（支持 png/jpg/jpeg/gif/webp/bmp）。", []
        ids = ", ".join(r["id"] for r in added) or "无"
        return f"导入 {len(added)} 张，跳过重复 {dup} 张。新增 ID：{ids}", []

    def t_pick(self, args: dict) -> tuple[str, list]:
        sid = (args.get("sticker_id") or "").strip()
        if sid:
            row = self.lib.show(sid)
            if not row:
                return f"没有找到 {sid}。", []
        else:
            mood = (args.get("mood") or "").strip()
            row = self._match_mood(mood)
            if not row:
                return "图库是空的，没法挑表情。", []

        sid = row["sticker_id"]
        fname = self._file_of(sid)
        if not fname:
            return f"{sid} 的图片文件丢了。", []

        data, mime = _encode_image(fname)
        content = [{"type": "image", "data": data, "mimeType": mime}]
        self.lib.record_use(sid)
        return f"挑了 {sid}（{_top_meaning(row['readings']) or '未标注'}），图在下面。", content

    # -- 辅助 --

    def _match_mood(self, mood: str) -> dict | None:
        rows = self.lib.list_stickers(order="recent")
        if not rows:
            return None
        if mood:
            scored = []
            for r in rows:
                shown = self.lib.show(r["id"])
                if not shown:
                    continue
                score = 0
                for reading in shown["readings"]:
                    hay = f"{reading['meaning']}{reading['context_hint']}"
                    if mood and mood in hay:
                        score += 2
                    for ch in mood:
                        if ch in hay:
                            score += 1
                if score:
                    scored.append((score, shown))
            if scored:
                scored.sort(key=lambda x: -x[0])
                return scored[0][1]
        # 没有匹配就用最常用的那张
        for r in rows:
            shown = self.lib.show(r["id"])
            if shown:
                return shown
        return None

    def _file_of(self, sid: str) -> Path | None:
        row = self.lib.conn.execute(
            "SELECT file FROM stickers WHERE id = ?", (sid,)
        ).fetchone()
        if not row:
            return None
        p = self.lib.img_dir / row["file"]
        return p if p.exists() else None

    def _last_pick(self) -> dict | None:
        import time

        f = self.data_dir / "last_pick.json"
        if not f.exists():
            return None
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        age = time.time() - float(payload.get("ts") or 0)
        if age > LAST_PICK_TTL:
            return None
        return {"id": payload.get("id"), "age": age}

    def _spill_base64(self, b64: str) -> str | None:
        try:
            raw = base64.b64decode(b64.split(",")[-1])
        except (ValueError, TypeError):
            return None
        tmp = self.data_dir / "_incoming.png"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(raw)
        return str(tmp)


# ---------------------------------------------------------------- 协议层


def _readings_text(sid: str, readings: list[dict]) -> str:
    if not readings:
        return (
            f"{sid} 还没有读法。用户解释它的意思后，用 tag 写入一条——"
            "这是它变聪明的唯一途径。"
        )
    lines = [f"{sid} 的读法："]
    for r in readings:
        ctx = f"（语境：{r['context_hint']}）" if r.get("context_hint") else ""
        lines.append(
            f"- {r['meaning']}{ctx} conf={r['confidence']} 用过 {r['uses']} 次"
        )
    return "\n".join(lines)


def _top_meaning(readings: list[dict]) -> str | None:
    return readings[0]["meaning"] if readings else None


def _encode_image(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    if path.suffix.lower() == ".gif":
        # 动图直接给原始字节，别让客户端以为是静态 png
        mime = "image/gif"
    return base64.b64encode(raw).decode("ascii"), mime


def _ok(msg_id, result) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _err(msg_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def serve(data_dir: str | Path) -> int:
    session = Session(data_dir)
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                _send(_err(None, -32700, "parse error"))
                continue

            msg_id = msg.get("id")
            method = msg.get("method") or ""

            # 通知不需要回复
            if msg_id is None and method.startswith("notifications/"):
                continue

            try:
                if method == "initialize":
                    _send(
                        _ok(
                            msg_id,
                            {
                                "protocolVersion": PROTOCOL_VERSION,
                                "capabilities": {"tools": {"listChanged": False}},
                                "serverInfo": {
                                    "name": SERVER_NAME,
                                    "version": SERVER_VERSION,
                                },
                            },
                        )
                    )
                elif method == "ping":
                    _send(_ok(msg_id, {}))
                elif method == "tools/list":
                    _send(_ok(msg_id, {"tools": TOOLS}))
                elif method == "tools/call":
                    _send(_ok(msg_id, _call(session, msg.get("params") or {})))
                else:
                    _send(_err(msg_id, -32601, f"method not found: {method}"))
            except Exception:
                traceback.print_exc(file=sys.stderr)
                _send(_err(msg_id, -32603, "internal error"))
    finally:
        session.close()
    return 0


def _call(session: Session, params: dict) -> dict:
    name = params.get("name") or ""
    args = params.get("arguments") or {}

    handler = {
        "identify": session.t_identify,
        "last_pick": session.t_last_pick,
        "list": session.t_list,
        "show": session.t_show,
        "tag": session.t_tag,
        "import": session.t_import,
        "pick": session.t_pick,
    }.get(name)

    if handler is None:
        return {
            "content": [{"type": "text", "text": f"未知工具：{name}"}],
            "isError": True,
        }

    try:
        text, extra = handler(args)
        return {"content": [{"type": "text", "text": text}] + extra}
    except Exception as exc:  # 工具内部异常不该拖垮整个 server
        traceback.print_exc(file=sys.stderr)
        return {
            "content": [{"type": "text", "text": f"{name} 执行失败：{exc}"}],
            "isError": True,
        }


def main(data_dir: str | Path = "data") -> int:
    return serve(data_dir)
