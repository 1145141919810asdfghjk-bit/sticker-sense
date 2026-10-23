"""MCP server 协议自测：真的起进程、真的走 stdio JSON-RPC。

不 mock，因为最容易错的地方就是协议层（stdout 混进日志、id 对不上、
image content block 形状不对）。这些只有真跑才测得出来。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sticker_sense.library import Library  # noqa: E402

PY = Path(sys.executable)
DEMO = ROOT / "demo"

passed = 0
failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


class Client:
    def __init__(self, data_dir: Path):
        import os

        env = dict(os.environ)
        env["STICKER_DATA"] = str(data_dir)
        self.proc = subprocess.Popen(
            [str(PY), str(ROOT / "run_mcp.py")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            cwd=str(ROOT),
            env=env,
        )
        self._id = 0

    def send(self, method: str, params: dict | None = None, notify: bool = False):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            self._id += 1
            msg["id"] = self._id
        self.proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        if notify:
            return None
        line = self.proc.stdout.readline()
        if not line:
            err = self.proc.stderr.read()
            raise RuntimeError(f"server 没回话。stderr:\n{err}")
        return json.loads(line)

    def call(self, name: str, args: dict | None = None) -> dict:
        resp = self.send("tools/call", {"name": name, "arguments": args or {}})
        return resp.get("result", {})

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


def text_of(result: dict) -> str:
    for block in result.get("content", []):
        if block.get("type") == "text":
            return block.get("text", "")
    return ""


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="sticker-mcp-"))
    data = tmp / "data"

    # 准备一个有内容的图库
    lib = Library(data)
    ids = []
    for p in sorted(DEMO.glob("*.png")):
        r = lib.import_file(p)
        if r and r["status"] == "added":
            ids.append(r["id"])
    lib.tag(ids[0], "无语到不想解释", "对方说了明显不合理的话时")
    lib.tag(ids[0], "礼貌性敷衍", "不想继续这个话题时")
    lib.close()
    print(f"准备图库：{len(ids)} 张，基准 id={ids[0]}\n")

    c = Client(data)
    try:
        # 1. 握手
        init = c.send("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "selftest", "version": "0"},
        })
        check("initialize 返回 serverInfo",
              init.get("result", {}).get("serverInfo", {}).get("name") == "sticker-sense",
              json.dumps(init)[:200])
        check("initialize 声明 tools 能力",
              "tools" in init.get("result", {}).get("capabilities", {}))

        c.send("notifications/initialized", notify=True)

        # 2. 工具清单
        tl = c.send("tools/list")
        tools = tl.get("result", {}).get("tools", [])
        names = {t["name"] for t in tools}
        check("tools/list 返回 7 个工具", len(tools) == 7, str(names))
        check("工具名齐全",
              names == {"identify", "last_pick", "list", "show", "tag", "import", "pick"},
              str(names))
        check("每个工具都有 inputSchema",
              all("inputSchema" in t for t in tools))

        # 3. list
        r = c.call("list")
        t = text_of(r)
        check("list 能列出表情", ids[0] in t, t[:200])

        # 4. show
        r = c.call("show", {"sticker_id": ids[0]})
        t = text_of(r)
        check("show 返回读法", "无语到不想解释" in t and "礼貌性敷衍" in t, t[:200])

        # 5. tag 写入新读法
        r = c.call("tag", {
            "sticker_id": ids[0],
            "meaning": "看透不说透",
            "context_hint": "对方装傻时",
        })
        check("tag 写入成功", "已为" in text_of(r), text_of(r))

        r = c.call("show", {"sticker_id": ids[0]})
        check("tag 后能读回", "看透不说透" in text_of(r), text_of(r)[:200])

        # 6. identify：拿同一张图认
        r = c.call("identify", {"path": str((data / "stickers").glob("*").__next__())})
        check("identify 命中", "命中" in text_of(r), text_of(r)[:200])

        # 7. identify：库里没有的图
        stranger = tmp / "stranger.png"
        from PIL import Image

        Image.new("RGB", (64, 64), (10, 200, 30)).save(stranger)
        r = c.call("identify", {"path": str(stranger)})
        check("identify 拒绝陌生图", "库里没有" in text_of(r), text_of(r)[:200])

        # 8. pick：返回图片本身
        r = c.call("pick", {"mood": "无语"})
        blocks = r.get("content", [])
        img = [b for b in blocks if b.get("type") == "image"]
        check("pick 返回 image block", len(img) == 1, json.dumps(blocks)[:200])
        if img:
            import base64

            raw = base64.b64decode(img[0]["data"])
            check("pick 的图片能解码成 PNG", raw[:8] == b"\x89PNG\r\n\x1a\n", str(raw[:8]))
            check("pick 带 mimeType", bool(img[0].get("mimeType")))

        # 9. last_pick：没有记录时给出提示
        r = c.call("last_pick")
        check("last_pick 无记录时友好提示", "没有" in text_of(r), text_of(r)[:200])

        # 10. 未知工具
        r = c.call("no_such_tool")
        check("未知工具返回 isError", r.get("isError") is True)

        # 11. 未知方法
        bad = c.send("tools/nonexistent")
        check("未知方法返回 -32601",
              bad.get("error", {}).get("code") == -32601, json.dumps(bad)[:200])

        # 12. stdout 必须是纯 JSON 行
        check("进程仍存活（stdout 没被污染）", c.proc.poll() is None)

    finally:
        c.close()
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nMCP 自测：{passed} 通过 · {failed} 失败")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
