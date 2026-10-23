"""网页管理端自测：起一个真 HTTP server，用 urllib 打各个接口。

覆盖：列表、详情、写读法、降权（不是删除）、上传导入、图片服务、
目录穿越防护、404。
"""

from __future__ import annotations

import base64
import json
import shutil
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sticker_sense import webadmin  # noqa: E402
from sticker_sense.library import Library  # noqa: E402

passed = 0
failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


def get(base, path):
    with urllib.request.urlopen(base + path, timeout=10) as r:
        return r.status, r.read()


def getj(base, path):
    st, raw = get(base, path)
    return st, json.loads(raw.decode("utf-8"))


def postj(base, path, payload):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="sticker-admin-"))
    data = tmp / "data"
    lib = Library(data)
    ids = []
    for p in sorted((ROOT / "demo").glob("*.png")):
        r = lib.import_file(p)
        if r and r["status"] == "added":
            ids.append(r["id"])
    lib.tag(ids[0], "无语到不想解释", "对方说了明显不合理的话时")
    lib.close()

    state = webadmin.State(data)
    webadmin.Handler.state = state
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), webadmin.Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    print(f"测试服务 {base}，图库 {len(ids)} 张，基准 {ids[0]}\n")

    try:
        st, raw = get(base, "/")
        check("首页返回 HTML", st == 200 and b"<html" in raw.lower())

        st, rows = getj(base, "/api/list")
        check("list 返回全部", st == 200 and len(rows) == len(ids), str(len(rows)))
        check("list 标记待说明", any(r["pending"] for r in rows))
        check("list 带 file 名", all(r["file"] for r in rows))

        st, d = getj(base, f"/api/detail?id={ids[0]}")
        check("detail 返回读法", st == 200 and len(d["readings"]) == 1, str(d)[:150])

        st, img = get(base, f"/img/{d['file']}")
        check("图片能取到", st == 200 and img[:8] == b"\x89PNG\r\n\x1a\n")

        st, r = postj(base, "/api/tag", {
            "sticker_id": ids[0], "meaning": "看透不说透", "context_hint": "对方装傻时"
        })
        check("tag 写入成功", st == 200 and len(r["detail"]["readings"]) == 2, str(r)[:150])

        rid = r["detail"]["readings"][0]["id"]
        before = r["detail"]["readings"][0]["confidence"]
        st, r2 = postj(base, "/api/weaken", {"reading_id": rid})
        check("降权降低置信度", st == 200 and r2["confidence"] < before,
              f"{before} -> {r2.get('confidence')}")
        check("降权不删除条目", len(r2["detail"]["readings"]) == 2)

        png = (ROOT / "demo" / sorted((ROOT / "demo").glob("*.png"))[0].name).read_bytes()
        b64 = base64.b64encode(png).decode("ascii")
        st, r3 = postj(base, "/api/import", {"name": "again.png", "data_base64": b64})
        check("重复图被识别为 duplicate", r3.get("status") == "duplicate", str(r3))

        from PIL import Image
        import io

        buf = io.BytesIO()
        Image.new("RGB", (40, 40), (20, 120, 220)).save(buf, "PNG")
        b64n = base64.b64encode(buf.getvalue()).decode("ascii")
        st, r4 = postj(base, "/api/import", {"name": "fresh.png", "data_base64": b64n})
        check("新图导入成功", r4.get("status") == "added", str(r4))

        st, r5 = postj(base, "/api/alias",
                       {"sticker_id": ids[0], "data_base64": b64n, "note": "测试"})
        check("绑定相似图成功", st == 200 and len(r5["detail"]["aliases"]) == 1,
              str(r5)[:150])

        st, r6 = postj(base, "/api/tag", {"sticker_id": "nope", "meaning": "x"})
        check("不存在的 id 返回 404", st == 404)

        # 目录穿越：必须拿不到
        try:
            st, _ = get(base, "/img/..%2f..%2flibrary.db")
            trav = st == 404
        except urllib.error.HTTPError as e:
            trav = e.code == 404
        check("目录穿越被挡住", trav)

        st, _ = getj(base, "/api/list")
        check("导入后总数增加", len(_) == len(ids) + 1, str(len(_)))

    finally:
        httpd.shutdown()
        state.lib.close()
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n管理端自测：{passed} 通过 · {failed} 失败")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
