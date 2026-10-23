"""命令行入口。阶段 1-2 的验证工具，也是后续 MCP 的工具层。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .library import Library


def _out(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="sticker", description="表情包语义图库")
    ap.add_argument("--data", default="data", help="数据目录，默认 ./data")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("import", help="导入图片或整个目录")
    p.add_argument("path")

    p = sub.add_parser("identify", help="识别一张图")
    p.add_argument("path")
    p.add_argument(
        "--threshold",
        type=int,
        default=None,
        help="粗筛的汉明距离上限，默认用 hashing.py 里的 COARSE_GATE",
    )

    p = sub.add_parser("tag", help="给表情写入一条读法")
    p.add_argument("sticker_id")
    p.add_argument("meaning")
    p.add_argument("--context", default="")
    p.add_argument("--confidence", type=float, default=0.7)
    p.add_argument("--origin", default="user_explained")

    p = sub.add_parser("show", help="查看某个表情的全部读法")
    p.add_argument("sticker_id")

    sub.add_parser("list", help="列出图库")

    p = sub.add_parser("use", help="记录一次使用（让读法排序更准）")
    p.add_argument("sticker_id")
    p.add_argument("--reading", type=int, default=None)

    p = sub.add_parser("alias", help="人工绑定：告诉库这张图属于哪个 ID")
    p.add_argument("sticker_id")
    p.add_argument("path")
    p.add_argument("--note", default="")

    p = sub.add_parser("export", help="导出人类可读的 JSON")
    p.add_argument("out")

    p = sub.add_parser("picker", help="输出可点击面板的 HTML 片段（内联用）")
    p.add_argument("--limit", type=int, default=24)

    p = sub.add_parser("page", help="生成独立的可点击面板网页")
    p.add_argument("out", nargs="?", default="picker.html")
    p.add_argument("--title", default="表情面板")

    sub.add_parser("widget", help="启动桌面悬浮挂件（点一下自动粘进输入框）")

    sub.add_parser("mcp", help="以 MCP server 运行（stdio JSON-RPC，供客户端接入）")

    p = sub.add_parser("admin", help="启动本地网页管理端")
    p.add_argument("--port", type=int, default=8777)
    p.add_argument("--no-open", action="store_true", help="不自动打开浏览器")

    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    lib = Library(args.data)

    try:
        if args.cmd == "import":
            results = lib.import_path(args.path)
            added = [r for r in results if r["status"] == "added"]
            dup = [r for r in results if r["status"] == "duplicate"]
            _out({"added": len(added), "duplicate": len(dup), "items": results})

        elif args.cmd == "identify":
            _out(lib.identify(args.path, args.threshold))

        elif args.cmd == "tag":
            _out(
                lib.tag(
                    args.sticker_id,
                    args.meaning,
                    args.context,
                    args.confidence,
                    args.origin,
                )
            )

        elif args.cmd == "show":
            res = lib.show(args.sticker_id)
            if not res:
                print(f"没有找到 {args.sticker_id}", file=sys.stderr)
                return 1
            _out(res)

        elif args.cmd == "list":
            _out(lib.list_stickers())

        elif args.cmd == "use":
            lib.record_use(args.sticker_id, args.reading)
            _out({"status": "ok", "sticker_id": args.sticker_id})

        elif args.cmd == "alias":
            _out(lib.bind_alias(args.sticker_id, args.path, args.note))

        elif args.cmd == "export":
            _out({"exported": str(lib.export_json(args.out))})

        elif args.cmd == "picker":
            from . import picker

            print(picker.render(lib, args.limit))

        elif args.cmd == "page":
            from . import picker

            out = Path(args.out)
            out.write_text(picker.render_page(lib, args.title), encoding="utf-8")
            _out({"page": str(out.resolve())})

        elif args.cmd == "widget":
            lib.close()
            from . import widget

            return widget.main(args.data)

        elif args.cmd == "mcp":
            lib.close()
            from . import mcp_server

            return mcp_server.main(args.data)

        elif args.cmd == "admin":
            lib.close()
            from . import webadmin

            return webadmin.main(args.data, args.port, open_browser=not args.no_open)

    finally:
        lib.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
