"""``python -m resume_tailor <serve|mcp>`` 入口。"""

from __future__ import annotations

import argparse

from .serve import run
from .serve_mcp import run_stdio


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m resume_tailor")
    sub = parser.add_subparsers(dest="command")
    serve_parser = sub.add_parser("serve", help="启动本地内容面 HTTP 服务")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=4319)
    sub.add_parser("mcp", help="以 MCP stdio 传输运行（供 DSH mcp-client 接入）")
    args = parser.parse_args()

    if args.command == "serve":
        run(host=args.host, port=args.port)
    elif args.command == "mcp":
        run_stdio()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
