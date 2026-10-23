"""本地网页管理端：批量导图、看读法、改绑定。

只用标准库的 http.server，没有前端构建、没有 npm、没有外网依赖。
绑 127.0.0.1，只在本机开。

设计上守一条线：**读法只降权，不硬删**。误判修正的成本必须极低，
删掉就再也找不回来了，降权还能反悔。
"""

from __future__ import annotations

import base64
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .library import Library

MAX_UPLOAD = 12 * 1024 * 1024


class State:
    """一个进程一个连接，加锁串行化——本地单用户够用，也避免 WAL 争抢。

    ThreadingHTTPServer 每个请求一个线程，所以连接必须允许跨线程，
    并发安全由这把锁保证。
    """

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self.lib = Library(self.data_dir, cross_thread=True)
        self.lock = threading.Lock()


def _reading_dict(r) -> dict:
    return {
        "id": r["id"],
        "meaning": r["meaning"],
        "context_hint": r["context_hint"] or "",
        "confidence": round(r["confidence"], 2),
        "uses": r["uses"],
        "origin": r["origin"],
        "last_used_at": r["last_used_at"],
    }


class Handler(BaseHTTPRequestHandler):
    state: State
    server_version = "sticker-sense-admin"

    # ---------- 基础 ----------

    def log_message(self, fmt, *args):  # 静音，别把终端刷满
        pass

    def _json(self, obj, code: int = 200) -> None:
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _html(self, text: str) -> None:
        raw = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if length <= 0 or length > MAX_UPLOAD:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            return {}

    # ---------- 路由 ----------

    def do_GET(self) -> None:
        url = urlparse(self.path)
        path = url.path

        if path in ("/", "/index.html"):
            self._html(PAGE)
            return

        if path == "/api/list":
            with self.state.lock:
                self._json(self._list())
            return

        if path == "/api/detail":
            qs = parse_qs(url.query)
            sid = (qs.get("id") or [""])[0]
            with self.state.lock:
                self._json(self._detail(sid))
            return

        if path.startswith("/img/"):
            self._serve_image(path[len("/img/"):])
            return

        self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        url = urlparse(self.path)
        body = self._body()

        if url.path == "/api/tag":
            self._tag(body)
        elif url.path == "/api/weaken":
            self._weaken(body)
        elif url.path == "/api/import":
            self._import(body)
        elif url.path == "/api/alias":
            self._alias(body)
        else:
            self._json({"error": "not found"}, 404)

    # ---------- 业务 ----------

    def _list(self) -> list[dict]:
        lib = self.state.lib
        out = []
        for r in lib.list_stickers(order="recent"):
            out.append(
                {
                    "id": r["id"],
                    "file": Path(r["file"]).name,
                    "top_meaning": r["top_meaning"],
                    "reading_count": r["reading_count"],
                    "pending": r["reading_count"] == 0,
                    "last_used": r["last_used"],
                    "width": r["width"],
                    "height": r["height"],
                }
            )
        return out

    def _detail(self, sid: str) -> dict:
        lib = self.state.lib
        row = lib.conn.execute(
            "SELECT * FROM stickers WHERE id = ?", (sid,)
        ).fetchone()
        if not row:
            return {"error": "not found"}
        readings = [
            _reading_dict(r)
            for r in lib.conn.execute(
                "SELECT * FROM readings WHERE sticker_id = ?"
                " ORDER BY confidence DESC, uses DESC, id ASC",
                (sid,),
            )
        ]
        aliases = [
            {"id": a["id"], "note": a["note"], "created_at": a["created_at"]}
            for a in lib.conn.execute(
                "SELECT * FROM aliases WHERE sticker_id = ? ORDER BY id DESC", (sid,)
            )
        ]
        return {
            "id": sid,
            "file": row["file"],
            "readings": readings,
            "aliases": aliases,
            "added_at": row["added_at"],
            "width": row["width"],
            "height": row["height"],
        }

    def _tag(self, body: dict) -> None:
        sid = (body.get("sticker_id") or "").strip()
        meaning = (body.get("meaning") or "").strip()
        if not sid or not meaning:
            self._json({"error": "sticker_id 和 meaning 必填"}, 400)
            return
        with self.state.lock:
            if not self.state.lib.show(sid):
                self._json({"error": f"没有找到 {sid}"}, 404)
                return
            res = self.state.lib.tag(
                sid,
                meaning,
                (body.get("context_hint") or "").strip(),
                float(body.get("confidence") or 0.7),
            )
            self._json({**res, "detail": self._detail(sid)})

    def _weaken(self, body: dict) -> None:
        """降权而不是删除。删了就找不回来，降权还能反悔。"""
        rid = body.get("reading_id")
        if rid is None:
            self._json({"error": "reading_id 必填"}, 400)
            return
        with self.state.lock:
            row = self.state.lib.conn.execute(
                "SELECT sticker_id, confidence FROM readings WHERE id = ?", (rid,)
            ).fetchone()
            if not row:
                self._json({"error": "没有这条读法"}, 404)
                return
            new_conf = max(0.05, round(row["confidence"] * 0.4, 3))
            self.state.lib.conn.execute(
                "UPDATE readings SET confidence = ? WHERE id = ?", (new_conf, rid)
            )
            self.state.lib.conn.commit()
            self._json(
                {
                    "status": "weakened",
                    "confidence": new_conf,
                    "detail": self._detail(row["sticker_id"]),
                }
            )

    def _import(self, body: dict) -> None:
        name = (body.get("name") or "upload.png").strip()
        data = body.get("data_base64") or ""
        if not data:
            self._json({"error": "没有收到图片数据"}, 400)
            return
        try:
            raw = base64.b64decode(data.split(",")[-1])
        except (ValueError, TypeError):
            self._json({"error": "base64 解不开"}, 400)
            return

        suffix = Path(name).suffix.lower() or ".png"
        tmp_dir = self.state.data_dir / "_incoming"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp = tmp_dir / f"up_{abs(hash(name)) % 10**8}{suffix}"
        tmp.write_bytes(raw)

        with self.state.lock:
            res = self.state.lib.import_file(tmp, source="admin")
        try:
            tmp.unlink()
        except OSError:
            pass

        if not res:
            self._json({"error": f"不支持的格式：{suffix}"}, 400)
            return
        self._json(res)

    def _alias(self, body: dict) -> None:
        sid = (body.get("sticker_id") or "").strip()
        data = body.get("data_base64") or ""
        if not sid or not data:
            self._json({"error": "sticker_id 和图片都必填"}, 400)
            return
        try:
            raw = base64.b64decode(data.split(",")[-1])
        except (ValueError, TypeError):
            self._json({"error": "base64 解不开"}, 400)
            return

        tmp_dir = self.state.data_dir / "_incoming"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp = tmp_dir / "alias.png"
        tmp.write_bytes(raw)
        with self.state.lock:
            if not self.state.lib.show(sid):
                self._json({"error": f"没有找到 {sid}"}, 404)
                return
            res = self.state.lib.bind_alias(sid, tmp, body.get("note") or "")
            detail = self._detail(sid)
        try:
            tmp.unlink()
        except OSError:
            pass
        self._json({**res, "detail": detail})

    def _serve_image(self, name: str) -> None:
        # 只允许取 stickers 目录下的文件，防目录穿越
        safe = Path(name).name
        target = self.state.lib.img_dir / safe
        if not target.exists():
            self._json({"error": "not found"}, 404)
            return
        raw = target.read_bytes()
        mime = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
        }.get(target.suffix.lower(), "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "max-age=3600")
        self.end_headers()
        self.wfile.write(raw)


PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>表情图库 · 管理</title>
<style>
  :root{
    --bg:#f6f6f4; --panel:#fff; --ink:#1b1b19; --muted:#6d6d66;
    --line:#e4e3de; --accent:#c8a01a; --accent-soft:#fdf6dd;
    --amber:#e0a300; --danger:#b4423a;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
    font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
  header{position:sticky;top:0;z-index:10;background:rgba(246,246,244,.92);
    backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}
  .bar{max-width:1180px;margin:0 auto;padding:14px 22px;display:flex;
    align-items:center;gap:16px;flex-wrap:wrap}
  h1{font-size:16px;margin:0;font-weight:650;letter-spacing:.02em}
  .stats{display:flex;gap:14px;color:var(--muted);font-size:12.5px}
  .stats b{color:var(--ink);font-weight:600}
  .spacer{flex:1}
  input[type=search]{border:1px solid var(--line);background:#fff;border-radius:8px;
    padding:7px 12px;font-size:13px;width:220px;outline:none}
  input[type=search]:focus{border-color:var(--accent)}
  button{font:inherit;cursor:pointer;border-radius:8px;border:1px solid var(--line);
    background:#fff;padding:7px 13px;color:var(--ink);transition:.15s}
  button:hover{border-color:#c9c7c0;background:#faf9f7}
  button.primary{background:var(--ink);color:#fff;border-color:var(--ink)}
  button.primary:hover{background:#333}
  button.ghost{background:transparent;border-color:transparent;color:var(--muted)}
  button.ghost:hover{color:var(--danger);background:#fbf1f0}
  main{max-width:1180px;margin:0 auto;padding:22px}
  .grid{display:grid;gap:14px;
    grid-template-columns:repeat(auto-fill,minmax(148px,1fr))}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:12px;
    padding:12px;cursor:pointer;transition:.15s;position:relative}
  .card:hover{border-color:#cfcdc5;box-shadow:0 3px 14px rgba(0,0,0,.055);
    transform:translateY(-1px)}
  .card.pending{border-color:#efd79a;background:#fffdf6}
  .card img{width:100%;aspect-ratio:1;object-fit:contain;display:block;
    background:#fbfbfa;border-radius:8px}
  .card .id{font-family:ui-monospace,Consolas,monospace;font-size:11px;
    color:var(--muted);margin-top:9px}
  .card .mean{font-size:12.5px;margin-top:3px;min-height:20px;
    overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .card .mean.none{color:var(--amber)}
  .badge{position:absolute;top:8px;right:8px;background:var(--amber);color:#fff;
    font-size:10.5px;padding:1px 7px;border-radius:20px}
  .badge.n{background:#ecebe6;color:var(--muted)}
  .empty{color:var(--muted);text-align:center;padding:60px 0}

  .drawer{position:fixed;top:0;right:0;height:100%;width:min(460px,92vw);
    background:#fff;border-left:1px solid var(--line);z-index:20;
    transform:translateX(100%);transition:transform .22s ease;
    display:flex;flex-direction:column}
  .drawer.open{transform:none;box-shadow:-8px 0 30px rgba(0,0,0,.08)}
  .drawer-head{padding:16px 20px;border-bottom:1px solid var(--line);
    display:flex;align-items:center;gap:12px}
  .drawer-head .sid{font-family:ui-monospace,Consolas,monospace;font-size:12px;
    color:var(--muted)}
  .drawer-body{padding:18px 20px;overflow:auto;flex:1}
  .drawer-body img.hero{width:132px;height:132px;object-fit:contain;
    border:1px solid var(--line);border-radius:10px;background:#fbfbfa;
    display:block;margin-bottom:18px}
  .sec{font-size:12px;color:var(--muted);text-transform:uppercase;
    letter-spacing:.08em;margin:20px 0 10px}
  .sec:first-child{margin-top:0}
  .reading{border:1px solid var(--line);border-radius:10px;padding:11px 13px;
    margin-bottom:9px}
  .reading .m{font-weight:600}
  .reading .c{font-size:12.5px;color:var(--muted);margin-top:3px}
  .reading .meta{font-size:11.5px;color:var(--muted);margin-top:6px;
    display:flex;align-items:center;gap:10px;flex-wrap:wrap}
  .reading .meta .dot{width:5px;height:5px;border-radius:50%;
    background:var(--accent);display:inline-block}
  .reading form{display:inline}
  label{display:block;font-size:12.5px;color:var(--muted);margin:10px 0 5px}
  input[type=text],textarea,select{width:100%;border:1px solid var(--line);
    border-radius:8px;padding:8px 11px;font:inherit;font-size:13px;outline:none;
    background:#fff;resize:vertical}
  input[type=text]:focus,textarea:focus{border-color:var(--accent)}
  .row{display:flex;gap:8px;margin-top:12px}
  .hint{font-size:12px;color:var(--muted);margin-top:6px;line-height:1.5}
  .toast{position:fixed;bottom:24px;left:50%;transform:translate(-50%,20px);
    background:var(--ink);color:#fff;padding:9px 18px;border-radius:20px;
    font-size:13px;opacity:0;pointer-events:none;transition:.22s;z-index:40}
  .toast.show{opacity:1;transform:translate(-50%,0)}
  .toast.bad{background:var(--danger)}
</style>
</head>
<body>
<header>
  <div class="bar">
    <h1>表情图库</h1>
    <div class="stats">
      <span>共 <b id="s-total">0</b> 张</span>
      <span>读法 <b id="s-readings">0</b> 条</span>
      <span>待说明 <b id="s-pending">0</b> 张</span>
    </div>
    <div class="spacer"></div>
    <input type="search" id="q" placeholder="搜 ID 或含义…">
    <button class="primary" id="btn-upload">＋ 导入图片</button>
    <input type="file" id="file" accept="image/*" multiple hidden>
  </div>
</header>

<main>
  <div class="grid" id="grid"></div>
  <div class="empty" id="empty" hidden>图库还是空的。点右上角「导入图片」开始。</div>
</main>

<aside class="drawer" id="drawer">
  <div class="drawer-head">
    <div>
      <div style="font-weight:600">表情详情</div>
      <div class="sid" id="d-id">—</div>
    </div>
    <div class="spacer"></div>
    <button class="ghost" id="d-close">关闭</button>
  </div>
  <div class="drawer-body" id="d-body"></div>
</aside>

<div class="toast" id="toast"></div>

<script>
const $ = (s) => document.querySelector(s);
let ALL = [];
let CUR = null;

function toast(msg, bad){
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'toast show' + (bad ? ' bad' : '');
  clearTimeout(t._t);
  t._t = setTimeout(() => { t.className = 'toast'; }, 1900);
}

async function api(path, opt){
  const r = await fetch(path, opt);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
  return j;
}

function esc(s){
  return String(s == null ? '' : s).replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

const ORIGIN = {
  user_explained: '用户解释',
  ai_inferred: 'AI 推断',
  seed: '示例',
  admin: '管理端'
};
function originText(o){ return ORIGIN[o] || o; }

async function load(){
  ALL = await api('/api/list');
  const total = ALL.length;
  const readings = ALL.reduce((a, x) => a + x.reading_count, 0);
  const pending = ALL.filter(x => x.pending).length;
  $('#s-total').textContent = total;
  $('#s-readings').textContent = readings;
  $('#s-pending').textContent = pending;
  render();
}

function render(){
  const q = ($('#q').value || '').trim().toLowerCase();
  const rows = ALL.filter(x =>
    !q || x.id.includes(q) || (x.top_meaning || '').toLowerCase().includes(q));
  const g = $('#grid');
  g.innerHTML = rows.map(x => `
    <div class="card ${x.pending ? 'pending' : ''}" data-id="${x.id}">
      ${x.pending ? '<span class="badge">待说明</span>'
                 : `<span class="badge n">${x.reading_count}</span>`}
      <img src="/img/${encodeURIComponent(x.file)}" alt="" loading="lazy">
      <div class="id">${x.id}</div>
      <div class="mean ${x.top_meaning ? '' : 'none'}">${esc(x.top_meaning || '还没读法')}</div>
    </div>`).join('');
  $('#empty').hidden = ALL.length > 0;
  g.querySelectorAll('.card').forEach(el =>
    el.onclick = () => openDetail(el.dataset.id));
}

async function openDetail(id){
  CUR = id;
  const d = await api('/api/detail?id=' + encodeURIComponent(id));
  $('#d-id').textContent = id + ' · ' + d.width + '×' + d.height;
  const body = $('#d-body');

  const readings = d.readings.length ? d.readings.map(r => `
    <div class="reading">
      <div class="m">${esc(r.meaning)}</div>
      ${r.context_hint ? `<div class="c">${esc(r.context_hint)}</div>` : ''}
      <div class="meta">
        <span class="dot"></span>置信 ${r.confidence}
        <span>用过 ${r.uses} 次</span>
        <span>${esc(originText(r.origin))}</span>
        <form data-weaken="${r.id}" style="margin-left:auto">
          <button class="ghost" type="submit" title="降权而不是删除，可反悔">降权</button>
        </form>
      </div>
    </div>`).join('') : '<div class="hint">还没有读法。填一条，它就开始懂这个表情了。</div>';

  body.innerHTML = `
    <img class="hero" src="/img/${encodeURIComponent(d.file)}" alt="">
    <div class="sec">读法（${d.readings.length}）</div>
    ${readings}
    <div class="sec">补一条读法</div>
    <form id="f-tag">
      <label>表达什么情绪</label>
      <input type="text" name="meaning" placeholder="比如：无语到不想解释" required>
      <label>什么语境下用（可选，但很有用）</label>
      <input type="text" name="context" placeholder="比如：对方说了明显不合理的话时">
      <div class="row"><button class="primary" type="submit">写入</button></div>
    </form>
    <div class="sec">绑定相似图</div>
    <div class="hint">同一个表情常有好几个版本（不同截图、不同压缩）。绑一张过来，
      以后认到它也算这张。</div>
    <div class="row"><button id="btn-alias">选一张相似图</button></div>
    <input type="file" id="alias-file" accept="image/*" hidden>
  `;

  body.querySelectorAll('[data-weaken]').forEach(f => {
    f.onsubmit = async (e) => {
      e.preventDefault();
      try{
        const r = await api('/api/weaken', {
          method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({reading_id: Number(f.dataset.weaken)})
        });
        toast('已降权到 ' + r.confidence);
        openDetail(id); load();
      }catch(err){ toast(err.message, true); }
    };
  });

  body.querySelector('#f-tag').onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try{
      await api('/api/tag', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({
          sticker_id: id,
          meaning: fd.get('meaning'),
          context_hint: fd.get('context')
        })
      });
      toast('已写入');
      openDetail(id); load();
    }catch(err){ toast(err.message, true); }
  };

  body.querySelector('#btn-alias').onclick = () => body.querySelector('#alias-file').click();
  body.querySelector('#alias-file').onchange = async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    const b64 = await toB64(f);
    try{
      await api('/api/alias', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({sticker_id: id, data_base64: b64, note: f.name})
      });
      toast('已绑定');
      openDetail(id);
    }catch(err){ toast(err.message, true); }
  };

  $('#drawer').classList.add('open');
}

function toB64(file){
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(r.result);
    r.onerror = rej;
    r.readAsDataURL(file);
  });
}

$('#q').oninput = render;
$('#d-close').onclick = () => $('#drawer').classList.remove('open');
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') $('#drawer').classList.remove('open');
});

$('#btn-upload').onclick = () => $('#file').click();
$('#file').onchange = async (e) => {
  const files = [...e.target.files];
  if (!files.length) return;
  let added = 0, dup = 0, bad = 0;
  for (const f of files){
    try{
      const b64 = await toB64(f);
      const r = await api('/api/import', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({name: f.name, data_base64: b64})
      });
      if (r.status === 'added') added++; else dup++;
    }catch(err){ bad++; }
  }
  e.target.value = '';
  toast(`导入 ${added} 张` + (dup ? `，跳过重复 ${dup}` : '') + (bad ? `，失败 ${bad}` : ''));
  load();
};

load();

// 支持 #id 直链，方便把某张表情发给别人看
if (location.hash.length > 1){
  const target = decodeURIComponent(location.hash.slice(1));
  if (target) openDetail(target).catch(() => {});
}
</script>
</body>
</html>
"""


def main(data_dir: str | Path, port: int = 8777, open_browser: bool = True) -> int:
    state = State(data_dir)
    Handler.state = state

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"管理端已启动：{url}")
    print(f"数据目录：{state.data_dir.resolve()}")
    print("Ctrl+C 结束。")

    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        httpd.server_close()
        state.lib.close()
    return 0
