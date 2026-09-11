"""UI 实验室：备用前端站点的独立服务。

    py _ui-lab/serve_lab.py            # http://localhost:8080
    py _ui-lab/serve_lab.py --port=8090

## 它做什么

1. 静态托管本目录的 index.html / *.css / *.js
2. 把 /api/* 反向代理到已经在跑的 **主站**(默认 http://127.0.0.1:8000)

## 为什么不直接跨域打 8000

主站 app/api/server.py 没有装 CORSMiddleware,浏览器会拦掉跨源请求。
而在主站上一行 CORS 是**改动别人的源文件** —— 本实验室约束是不碰源文件。

所以这里做一个同源代理:浏览器只看见 8080,后端仍是主站那份真引擎
(估值模型、图编排、SSE 全是真的,不是 mock)。

## 为什么必须真流式转发

/api/chat 是 SSE,一次问答约 9 秒、事件一个一个推。若把上游响应整个 read()
完再回给浏览器,进度条会在 9 秒后**一次性**出现 —— 那正是本实验室要修的
那个问题(等待不可见),代理这里必须逐块 flush。

只用标准库:主站跑的是 Python 3.14,没有额外依赖可装。
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
UPSTREAM = "http://127.0.0.1:8000"
DEFAULT_PORT = 8137        # 8080/8081/3000 在本机是 Windows 保留端口,绑不上

# 只转发这几个前缀。白名单而不是"除了静态资源都转发" ——
# 免得哪天主站加了新接口,这里默默跟着暴露一个本实验室没打算支持的东西。
PROXY_PREFIXES = ("/api/",)

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".woff2": "font/woff2",
}


class Lab(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"          # 1.1 才有 keep-alive;1.0 下流式会断
    server_version = "UiLab/1.0"

    # 静态资源一律 no-cache:改完刷新就看到,不然会以为改动没生效。
    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _static(self, path: str) -> None:
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (HERE / rel).resolve()
        # 目录穿越闸:解析后的路径必须仍在本目录内
        if not str(target).startswith(str(HERE)) or not target.is_file():
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        self._send(200, target.read_bytes(), MIME.get(target.suffix, "application/octet-stream"))

    def _proxy(self, method: str) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        req = urllib.request.Request(UPSTREAM + self.path, data=body, method=method)
        for h in ("Content-Type", "Accept", "Accept-Language"):
            if self.headers.get(h):
                req.add_header(h, self.headers[h])

        try:
            up = urllib.request.urlopen(req, timeout=120)
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            self._send(exc.code, payload, exc.headers.get("Content-Type", "text/plain"),
                       {"Cache-Control": "no-cache"})
            return
        except Exception as exc:                                    # noqa: BLE001
            self._send(502, f"主站没应答:{exc}".encode(), "text/plain; charset=utf-8")
            return

        ctype = up.headers.get("Content-Type", "application/octet-stream")
        is_sse = "event-stream" in ctype

        if is_sse:
            # SSE 走 chunked:长度事先不知道,而且必须边收边发。
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            while True:
                chunk = up.read(1024)          # 小步读 —— 大缓冲会把事件攒成一坨
                if not chunk:
                    break
                self.wfile.write(b"%X\r\n" % len(chunk) + chunk + b"\r\n")
                self.wfile.flush()             # 关键:立刻推给浏览器
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
            return

        payload = up.read()
        self._send(200, payload, ctype)

    def do_GET(self) -> None:                                   # noqa: N802
        if self.path.startswith(PROXY_PREFIXES):
            self._proxy("GET")
        else:
            self._static(self.path.split("?")[0])

    def do_POST(self) -> None:                                  # noqa: N802
        if self.path.startswith(PROXY_PREFIXES):
            self._proxy("POST")
        else:
            self._send(405, b"only /api/* accepts POST here", "text/plain; charset=utf-8")

    def log_message(self, fmt: str, *args) -> None:              # 静音:只留错误
        if args and str(args[1]).startswith(("4", "5")):
            sys.stderr.write("  %s\n" % (fmt % args))


def main() -> None:
    port = DEFAULT_PORT
    pinned = False
    for arg in sys.argv[1:]:
        if arg.startswith("--port="):
            port = int(arg.split("=", 1)[1])
            pinned = True
        if arg.startswith("--upstream="):
            global UPSTREAM
            UPSTREAM = arg.split("=", 1)[1].rstrip("/")

    # Windows 上有一批端口被系统"排除保留"(Hyper-V / WSL / Docker 会占),
    # 绑上去报的是 WinError 10013 权限不足 —— 看起来像权限问题,其实是端口不可用。
    # 实测本机 8080/8081/3000 都在保留段里。所以没显式指定端口时自动往后找,
    # 免得每个人都要先猜一遍哪个端口能用。
    srv = None
    if pinned:
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", port), Lab)
        except OSError as exc:
            print(f"端口 {port} 绑不上:{exc}\n换一个:--port=8137")
            return
    else:
        for cand in range(port, port + 60):
            try:
                srv = ThreadingHTTPServer(("127.0.0.1", cand), Lab)
                port = cand
                break
            except OSError:
                continue
        if srv is None:
            print(f"{port}–{port + 59} 全都绑不上。用 --port= 指定一个。")
            return

    print("=" * 56)
    print(f"  UI 实验室   http://localhost:{port}")
    print(f"  真引擎      {UPSTREAM}  (/api/* 反向代理,SSE 真流式)")
    print(f"  主站        http://localhost:8000   ← 两份可以并排看")
    print("  改本目录的文件后直接刷新即可。Ctrl+C 停止。")
    print("=" * 56)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
