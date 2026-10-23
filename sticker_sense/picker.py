"""把图库渲染成可点击的表情面板。

两种形态：
- render()      内联 widget 用，点击走宿主的 sendPrompt 回调
- render_page() 独立 HTML 页面，点击复制 [sticker:id] 到剪贴板

独立页面是不依赖宿主能力的那条路：任何浏览器打开都能用，
复制后粘到任意 AI 聊天框即可。
"""

from __future__ import annotations

from pathlib import Path

from .library import Library

CELL = (
    "aspect-ratio:1;border:0.5px solid var(--color-border-tertiary);"
    "border-radius:10px;background:var(--color-background-secondary);"
    "overflow:hidden;padding:0;cursor:pointer;display:flex;"
    "align-items:center;justify-content:center;"
)


def render(lib: Library, limit: int = 24) -> str:
    items = lib.list_stickers()[:limit]
    if not items:
        return (
            '<div style="padding:16px;font-size:13px;'
            'color:var(--color-text-secondary)">图库还是空的，先导入几张表情包。</div>'
        )

    cells = []
    for it in items:
        label = it["top_meaning"] or "未标注"
        title = f'{it["id"]} · {label}'
        cells.append(
            f'<button style="{CELL}" title="{title}" '
            f"onclick=\"sendPrompt('[sticker:{it['id']}]')\">"
            f'<img src="{it["file"]}" alt="{label}" '
            'style="width:100%;height:100%;object-fit:contain;padding:6px;'
            'pointer-events:none">'
            "</button>"
        )

    return (
        '<h2 class="sr-only">表情包选择器，点击即发送</h2>'
        '<div style="padding:4px 0">'
        '<div style="display:grid;grid-template-columns:repeat(6,1fr);gap:10px">'
        f'{"".join(cells)}'
        "</div>"
        '<div style="margin-top:10px;font-size:12px;'
        'color:var(--color-text-tertiary)">'
        f"共 {len(items)} 张 · 点击即发送</div>"
        "</div>"
    )


PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  :root {{
    --bg: #FBFAF8; --card: #FFFFFF; --line: rgba(0,0,0,.10);
    --text: #1A1A1A; --muted: #6B6B6B; --hint: #9A9A9A;
    --accent: #185FA5; --accent-bg: #E6F1FB;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 28px 32px 48px;
    background: var(--bg); color: var(--text);
    font-family: system-ui, -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
  }}
  h1 {{ font-size: 16px; font-weight: 500; margin: 0 0 4px; }}
  .sub {{ font-size: 13px; color: var(--muted); margin: 0 0 22px; line-height: 1.6; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(104px, 1fr)); gap: 12px; }}
  .cell {{
    position: relative; aspect-ratio: 1; padding: 0; cursor: pointer;
    border: 0.5px solid var(--line); border-radius: 12px;
    background: var(--card); overflow: hidden;
    display: flex; align-items: center; justify-content: center;
    transition: border-color .12s, transform .12s;
  }}
  .cell:hover {{ border-color: var(--accent); transform: translateY(-1px); }}
  .cell:active {{ transform: translateY(0); }}
  .cell img {{ width: 100%; height: 100%; object-fit: contain; padding: 8px; pointer-events: none; }}
  .cap {{
    position: absolute; left: 0; right: 0; bottom: 0;
    padding: 4px 6px; font-size: 11px; line-height: 1.3;
    color: var(--muted); background: rgba(255,255,255,.88);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    text-align: center;
  }}
  .cap.none {{ color: var(--hint); font-style: italic; }}
  #toast {{
    position: fixed; left: 50%; bottom: 28px; transform: translateX(-50%) translateY(8px);
    background: #1A1A1A; color: #fff; font-size: 13px;
    padding: 9px 16px; border-radius: 8px; opacity: 0;
    transition: opacity .18s, transform .18s; pointer-events: none;
  }}
  #toast.show {{ opacity: 1; transform: translateX(-50%) translateY(0); }}
  .empty {{ font-size: 13px; color: var(--muted); }}
</style>
</head>
<body>
<h1>{title}</h1>
<p class="sub">点一张表情，标记会自动复制到剪贴板，粘到聊天框里发出去即可。</p>
<div class="grid">{cells}</div>
<div id="toast"></div>
<script>
function pick(id, token) {{
  var done = function (ok) {{
    show(ok ? '已复制 ' + token + '，粘贴到聊天框' : '复制失败，请手动输入 ' + token);
  }};
  if (navigator.clipboard && navigator.clipboard.writeText) {{
    navigator.clipboard.writeText(token).then(function () {{ done(true); }},
      function () {{ done(false); }});
  }} else {{
    var t = document.createElement('textarea');
    t.value = token; document.body.appendChild(t); t.select();
    var ok = false;
    try {{ ok = document.execCommand('copy'); }} catch (e) {{ ok = false; }}
    document.body.removeChild(t); done(ok);
  }}
}}
var timer = null;
function show(msg) {{
  var el = document.getElementById('toast');
  el.textContent = msg; el.className = 'show';
  clearTimeout(timer);
  timer = setTimeout(function () {{ el.className = ''; }}, 1900);
}}
</script>
</body>
</html>
"""


def render_page(lib: Library, title: str = "表情面板", img_prefix: str = "data/stickers") -> str:
    items = lib.list_stickers()
    if not items:
        cells = '<p class="empty">图库还是空的。先运行 python -m sticker_sense.cli import &lt;你的表情包目录&gt;</p>'
    else:
        cells = "".join(_cell(it, img_prefix) for it in items)

    return PAGE.format(title=title, cells=cells)


def _cell(item: dict, img_prefix: str) -> str:
    sid = item["id"]
    token = f"[sticker:{sid}]"
    name = Path(item["file"]).name
    meaning = item["top_meaning"]
    cap = meaning or "未标注"
    cap_cls = "cap" if meaning else "cap none"
    alt = meaning or sid
    return (
        f'<button class="cell" title="{sid} · {cap}" '
        f"onclick=\"pick('{sid}', '{token}')\">"
        f'<img src="{img_prefix}/{name}" alt="{alt}">'
        f'<span class="{cap_cls}">{cap}</span>'
        "</button>"
    )
