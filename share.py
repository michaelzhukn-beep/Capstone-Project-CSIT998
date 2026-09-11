"""一键对外分享:起服务 + 开 Cloudflare 隧道,把公网地址打出来。

    python share.py                # 端口 8000,服务没起就顺带起
    python share.py --port=8010    # 换端口
    python share.py --attach       # 服务已经在跑了,只开隧道

双击 share-web.bat 效果一样。

⚠️ **这条隧道没有密码。** 拿到地址的人都能打开,也都能改「假设」那两个参数
(假设是进程级的,一个人改了所有人都变)。给同学测 bug 够用,别把它当成
可以公开挂着的东西 —— 关掉这个窗口,地址立刻失效。

**每次重开,地址都是新的。** Cloudflare 的 Quick Tunnel 就是这么设计的:
不用登录、不用配置,代价是随机域名、随开随弃。要固定域名得注册账号建
命名隧道,那是另一回事,四个人测 bug 不值得。
"""

import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

# Windows 控制台默认 GBK,中文和 ⚠️ 会直接抛 UnicodeEncodeError。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent

# Quick Tunnel 的地址长这样:https://word-word-word-word.trycloudflare.com
_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")

# cloudflared 装在哪儿。winget / scoop / choco 各放各的,而且刚装完那个终端
# 窗口的 PATH 还是旧的 —— 只靠 which 会在"明明装了却说没装"上浪费很久。
_CANDIDATES = (
    "cloudflared",
    r"%LOCALAPPDATA%\Microsoft\WinGet\Links\cloudflared.exe",
    r"%USERPROFILE%\scoop\shims\cloudflared.exe",
    r"%ProgramData%\chocolatey\bin\cloudflared.exe",
    r"%ProgramFiles%\cloudflared\cloudflared.exe",
    r"%ProgramFiles(x86)%\cloudflared\cloudflared.exe",
)

_INSTALL_HELP = """
  没找到 cloudflared —— 隧道就是靠它打的。装一次,以后都不用管。

  最省事(管理员身份打开 PowerShell 或终端):

      winget install --id Cloudflare.cloudflared

  装完**把这个窗口关掉重开**再跑一次 —— 新装的程序不会出现在
  已经开着的窗口的 PATH 里,这一步最容易卡住。

  没有 winget 就去下载单文件,放进本项目目录即可:
      https://github.com/cloudflare/cloudflared/releases
      (选 cloudflared-windows-amd64.exe,改名成 cloudflared.exe)
"""


def find_cloudflared() -> str | None:
    """按顺序找 cloudflared:PATH、几个包管理器的默认位置、项目目录。"""
    for raw in _CANDIDATES:
        path = os.path.expandvars(raw)
        found = shutil.which(path) if os.sep not in path else (path if Path(path).exists() else None)
        if found:
            return found
    local = ROOT / "cloudflared.exe"          # 手动下载丢在项目目录里的
    return str(local) if local.exists() else None


def server_alive(port: int, timeout: float = 1.5) -> bool:
    """/api/meta 能应答就算活着。用它而不是"端口是否被占用":
    端口占着可能是别的程序,也可能是本服务还在加载模型(那时连不上但端口已绑)。"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/meta", timeout=timeout):
            return True
    except Exception:                          # noqa: BLE001
        return False


def wait_ready(port: int, proc: subprocess.Popen | None, limit: float = 240) -> bool:
    """等服务就绪。首次要加载 500MB 的 embedding 模型,20 秒起步,冷启动更久。

    同时盯着子进程:它要是自己退了(数据库没开、端口被占),就别再傻等
    —— 那正是上一次卡住的地方,等满两分钟才说"没能就绪",而真正的报错
    早就打在上面了。
    """
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            print(f"\n  服务进程已退出(退出码 {proc.returncode})。")
            print("  往上翻看它的报错 —— 最常见的是数据库没起来:")
            print("      docker compose -f db/docker-compose.yml up -d\n")
            return False
        if server_alive(port):
            return True
        time.sleep(1.0)
    print("\n  服务四分钟内没就绪。先单独跑 python serve.py 看看它报什么。\n")
    return False


def start_server(port: int) -> subprocess.Popen:
    """起 serve.py。**不接管它的输出** —— 让加载进度和报错原样打在同一个窗口里,
    出问题时用户不用再去别处找日志。"""
    return subprocess.Popen(
        [sys.executable, str(ROOT / "serve.py"), "--no-open", f"--port={port}"],
        cwd=str(ROOT),
    )


def copy_to_clipboard(text: str) -> bool:
    """顺手复制到剪贴板 —— 地址是随机域名,手抄一遍很容易错一个字母。"""
    try:
        subprocess.run(["clip"], input=text, text=True, check=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True
    except Exception:                          # noqa: BLE001
        return False


def banner(url: str, port: int, copied: bool) -> None:
    line = "=" * 60
    print("\n" + line)
    print("  隧道已打通,把下面这个地址发给同学:")
    print()
    print(f"      {url}")
    print()
    if copied:
        print("  (已复制到剪贴板,直接粘贴即可)")
    print(f"  本机自己看:http://localhost:{port}")
    print()
    print("  几件要知道的事:")
    print("    · 没有密码,拿到地址的人都能用")
    print("    · 关掉这个窗口,地址立刻失效")
    print("    · 每次重开都是新地址,旧的不能再用")
    print("    · 右上角能切中英文,发给外国同学也读得懂")
    print(line + "\n")


def main() -> int:
    port = 8000
    for arg in sys.argv[1:]:
        if arg.startswith("--port="):
            port = int(arg.split("=", 1)[1])
    attach_only = "--attach" in sys.argv

    exe = find_cloudflared()
    if not exe:
        print(_INSTALL_HELP)
        return 1

    # ---- 1. 服务 ----
    child = None
    if server_alive(port):
        print(f"  端口 {port} 上的服务已经在跑,直接给它开隧道。")
    elif attach_only:
        print(f"  --attach 说服务已经在跑,但 http://127.0.0.1:{port}/api/meta 没有应答。")
        print("  去掉 --attach 让我顺带把它起起来,或者先自己跑 python serve.py。")
        return 1
    else:
        print(f"  端口 {port} 上没有服务,先把它起起来(首次要加载模型,约 20 秒)……\n")
        child = start_server(port)
        if not wait_ready(port, child):
            if child and child.poll() is None:
                child.terminate()
            return 1
        print("\n  服务就绪。正在打隧道……")

    # ---- 2. 隧道 ----
    # --no-autoupdate:免得它中途自己升级把连接断掉。
    # stderr 并进 stdout:cloudflared 把那个带地址的方框打在 stderr 上,
    # 分开读的话最关键的一行反而拿不到。
    tunnel = subprocess.Popen(
        [exe, "tunnel", "--no-autoupdate", "--url", f"http://localhost:{port}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )

    found: list[str] = []
    tail: list[str] = []

    def pump() -> None:
        """读隧道输出:抓到地址就打横幅,其余的只留最后几行备查。
        cloudflared 平时话很多(每条连接都报一次),全打出来会把横幅冲走 ——
        而横幅上那个地址正是用户唯一需要看的东西。"""
        for line in tunnel.stdout:
            tail.append(line.rstrip())
            del tail[:-40]
            if not found:
                m = _URL_RE.search(line)
                if m:
                    found.append(m.group(0))
                    banner(m.group(0), port, copy_to_clipboard(m.group(0)))

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()

    # 隧道起来了却迟迟不给地址(被墙、被限流、DNS 不通),要有个说法 ——
    # 干等着什么都不打印,用户只会以为是自己电脑慢。
    started = time.monotonic()
    warned = False

    try:
        while True:
            if not found and not warned and time.monotonic() - started > 45:
                warned = True
                print("\n  等了 45 秒还没拿到地址,多半是连不上 Cloudflare。")
                print("  cloudflared 最近几行:")
                for line in tail[-8:]:
                    print("    " + line)
                print("  还在等,要放弃就按 Ctrl+C。\n")
            if tunnel.poll() is not None:
                print("\n  隧道断了。cloudflared 最后几行输出:\n")
                for line in tail[-15:]:
                    print("    " + line)
                print("\n  多半是网络不通,或者 Cloudflare 临时限流,过一会儿再试。\n")
                return 1
            if child is not None and child.poll() is not None:
                print(f"\n  服务进程退出了(退出码 {child.returncode}),隧道也就没意义了。\n")
                return 1
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n  收到 Ctrl+C,正在收摊……")
    finally:
        for proc, name in ((tunnel, "隧道"), (child, "服务")):
            if proc is None or proc.poll() is not None:
                continue
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
            print(f"  {name}已关闭。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
