"""启动网页版。V8。

    python serve.py              # http://localhost:8000,就绪后自动开浏览器
    python serve.py --lan        # 同时让同一 Wi-Fi 下的手机能打开(打印局域网地址)
    python serve.py --no-open    # 不自动开浏览器
    python serve.py --port=8010  # 换端口

不想敲命令的话,双击项目根目录的 **start-web.bat**。

    python serve.py --watchdog=90   # 每 90 秒若仍卡住则打印全部线程栈

所有逻辑在 app/api/server.py;这里只负责起 uvicorn。
"""

import faulthandler
import os
import socket
import sys
import threading
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)          # .env、data/、models/ 都按项目根目录找;从别处启动也要能跑

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 原生崩溃(段错误、Windows 上的 STATUS_HEAP_CORRUPTION 0xC0000374)默认什么都不打印,
# 进程直接消失,只留一个退出码。开了它至少能拿到崩在哪个 Python 调用栈上。
# 实测这个服务出现过一次 0xC0000374 崩溃和一次单线程死转,当时两样线索都没有。
faulthandler.enable()


def _lan_ip() -> str | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def _open_when_ready(url: str, probe: str) -> None:
    """等服务真的能应答了再开浏览器。

    启动要先加载 embedding 模型、估值模型和十几万个地理多边形,约 20 秒。
    立刻开浏览器只会得到一个"无法连接"的页面,用户以为坏了 —— 所以这里
    轮询到 /api/meta 有响应为止,最多等两分钟。
    """
    for _ in range(240):
        try:
            urllib.request.urlopen(probe, timeout=2).read(1)
            print(f"\n浏览器已打开:{url}\n")
            webbrowser.open(url)
            return
        except Exception:                      # noqa: BLE001 —— 还没起来,继续等
            threading.Event().wait(0.5)
    print(f"\n服务没能在两分钟内就绪。手动打开试试:{url}\n")


def main() -> None:
    import uvicorn

    lan = "--lan" in sys.argv
    host = "0.0.0.0" if lan else "127.0.0.1"
    port = 8000
    for arg in sys.argv[1:]:
        if arg.startswith("--port="):
            port = int(arg.split("=", 1)[1])

    # --watchdog=N:每 N 秒把所有线程的栈打出来一次。
    # 服务卡死时事件循环被饿死,外部什么也问不出来(连 /api/meta 都超时),
    # 只有从进程内部定时 dump 才拿得到"到底是谁在死转"。默认关闭。
    for arg in sys.argv[1:]:
        if arg.startswith("--watchdog="):
            secs = float(arg.split("=", 1)[1])
            faulthandler.dump_traceback_later(secs, repeat=True, exit=False)
            print(f"看门狗已开:每 {secs:g} 秒打印一次线程栈")

    url = f"http://localhost:{port}"
    print("=" * 56)
    print(f"  网页地址:{url}")
    if lan:
        ip = _lan_ip()
        if ip:
            print(f"  手机(同一 Wi-Fi):http://{ip}:{port}")
    print("  首次启动要加载模型和地理数据,约 20 秒,请稍候……")
    print("  关闭这个窗口就停止服务。")
    print("=" * 56)

    if "--no-open" not in sys.argv:
        threading.Thread(target=_open_when_ready,
                         args=(url, f"http://127.0.0.1:{port}/api/meta"),
                         daemon=True).start()

    uvicorn.run("app.api.server:app", host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
