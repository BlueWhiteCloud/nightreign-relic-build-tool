"""打包入口：双击 exe 就能用 —— 不用装 Python、不用敲命令、不用懂什么是端口。

流程：
    1. 让系统随便给一个空闲端口，在 127.0.0.1 上把后端跑起来（前端页面也由它一起发）；
    2. 用 Edge / Chrome 的「应用模式」开一个独立窗口 —— 没有地址栏、没有标签栏，
       看着就是个桌面程序；窗口一关，程序跟着退出，不留后台进程；
    3. 本机既没有 Edge 也没有 Chrome 时，退回默认浏览器打开，靠前端心跳判断网页关没关。

为什么要给浏览器一个**临时用户目录**：不然 Edge 会把新窗口交给已经在运行的 Edge 进程，
我们启动的进程立刻退出 —— 程序就会跟着立刻关掉；而且也不该去动玩家自己的浏览器配置。
"""

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import webbrowser
from pathlib import Path

import server


def _quiet_streams() -> None:
    """打包成窗口程序（console=False）后 stdout/stderr 是 None，日志库一写就炸，先兜住。"""
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def _alert(message: str) -> None:
    """出问题弹个系统提示框 —— 没有控制台，不弹框用户只会看到「双击了没反应」。"""
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        messagebox.showerror("黑夜君临遗物配装工具", message)
        root.destroy()
    except Exception:
        pass


def _show_splash():
    """双击后要等几秒（解压 + 读数据表 + 起服务），先给个小窗，别让人以为没反应。"""
    try:
        import tkinter as tk

        root = tk.Tk()
        root.title("黑夜君临遗物配装工具")
        root.attributes("-topmost", True)
        root.resizable(False, False)
        width, height = 340, 132
        left = (root.winfo_screenwidth() - width) // 2
        top = (root.winfo_screenheight() - height) // 3
        root.geometry(f"{width}x{height}+{left}+{top}")
        tk.Label(root, text="黑夜君临遗物配装工具",
                 font=("Microsoft YaHei", 13, "bold")).pack(pady=(26, 8))
        tk.Label(root, text="正在启动，请稍候……",
                 font=("Microsoft YaHei", 9)).pack()
        root.update()
        return root
    except Exception:
        return None


def _close_splash(splash) -> None:
    if splash is None:
        return
    try:
        splash.destroy()
    except Exception:
        pass


def _free_port() -> int:
    """让系统随便给一个当前没人用的端口。"""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _serve(port: int) -> None:
    """在后台线程里跑 uvicorn（它不是主线程，所以自己不会去装信号处理，正好）。"""
    import uvicorn

    uvicorn.run(server.app, host="127.0.0.1", port=port,
                log_config=None, log_level="warning", access_log=False)


def _wait_ready(port: int, splash=None, timeout: float = 90.0) -> bool:
    """等服务真能连上再开窗口，否则用户先看到的是「无法访问此页面」。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if splash is not None:
            try:
                splash.update()          # 让小窗保持响应，不显示成「未响应」
            except Exception:
                splash = None
        with socket.socket() as sock:
            sock.settimeout(0.3)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.15)
    return False


def _find_browser() -> Path | None:
    """找 Edge / Chrome：只有 Chromium 系的浏览器认「应用模式」的 --app 参数。"""
    program_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    program_files_x86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        Path(program_files_x86) / "Microsoft/Edge/Application/msedge.exe",
        Path(program_files) / "Microsoft/Edge/Application/msedge.exe",
        Path(program_files) / "Google/Chrome/Application/chrome.exe",
        Path(program_files_x86) / "Google/Chrome/Application/chrome.exe",
        Path(local_appdata) / "Google/Chrome/Application/chrome.exe",
    ]
    ranking = {"msedge.exe": 0, "chrome.exe": 1}
    found = [path for path in candidates if path.is_file()]
    found.sort(key=lambda path: ranking.get(path.name, 9))
    return found[0] if found else None


def _open_app_window(browser: Path, url: str):
    """用应用模式开独立窗口，返回 (浏览器进程, 临时用户目录)；失败返回 (None, None)。"""
    profile = Path(tempfile.mkdtemp(prefix="relic-app-"))
    (profile / "First Run").touch()      # 有这个标记，Edge 就不会弹首次运行的欢迎页
    try:
        process = subprocess.Popen([
            str(browser),
            f"--app={url}",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-sync",
            "--window-size=1560,1000",
        ])
    except OSError:
        shutil.rmtree(profile, ignore_errors=True)
        return None, None
    return process, profile


def _wait_heartbeat(timeout: float = 300.0, idle: float = 180.0) -> None:
    """等前端心跳：网页关掉之后就没有心跳了，再等一会儿就把程序收掉。"""
    deadline = time.time() + timeout
    while server.last_ping_time() == 0.0 and time.time() < deadline:
        time.sleep(0.5)                  # 网页还没打开（或者在用别的浏览器）
    while time.time() - server.last_ping_time() < idle:
        time.sleep(0.5)


#: 任务栏把窗口图标画多大：Windows 11 的任务栏图标是 24 逻辑像素，再乘显示缩放（150% 就是 36px）
TASKBAR_ICON_BASE = 24


def _icon_file() -> Path | None:
    """找 图标/icon.ico：打包后在解压目录里，直接在仓库里跑就在代码的上一层。"""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    for candidate in (base / "图标" / "icon.ico", base.parent / "图标" / "icon.ico"):
        if candidate.is_file():
            return candidate
    return None


def _find_app_window(pid: int) -> int:
    """在指定进程里找那个看得见的浏览器窗口（Edge 的应用模式，类名 Chrome_WidgetWin_*）。"""
    import ctypes

    user32 = ctypes.windll.user32
    user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
    user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    user32.GetWindowTextLengthW.argtypes = [ctypes.c_void_p]
    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    hits = []

    @ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
    def visit(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        owner = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid:
            return True
        name = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, name, 64)
        if name.value.startswith("Chrome_WidgetWin") and user32.GetWindowTextLengthW(hwnd) > 0:
            hits.append(hwnd)
        return True

    user32.EnumWindows(visit, 0)
    return hits[0] if hits else 0


def _polish_window_icon(process) -> None:
    """把 Edge 应用窗口的任务栏图标换成我们的高清版。

    为什么要多这一步：这个窗口是 Edge 的「应用模式」，窗口图标由 Chromium 从网页 favicon 生成，
    实测它塞进 ICON_BIG 的只有 16×16 —— 而任务栏要把图标画到 24×缩放 那么大（150% 缩放就是 36px），
    16 硬撑成 36，任务栏上就是一团糊。标题栏用的倒是 24×24 的类图标、正好 1:1，所以那边清晰。
    Chromium 那套改不动，只能在窗口出来之后，我们自己把 icon.ico 里对应尺寸的那一档塞进 ICON_BIG；
    它读完 favicon 可能把图标盖回去，所以前几秒反复压几次。
    """
    icon_file = _icon_file()
    if process is None or icon_file is None:
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        user32.GetDpiForWindow.argtypes = [ctypes.c_void_p]
        user32.GetDpiForWindow.restype = ctypes.c_uint
        user32.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint,
                                      ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        user32.LoadImageW.restype = ctypes.c_void_p
        user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                        ctypes.c_void_p, ctypes.c_void_p]
        user32.SendMessageW.restype = ctypes.c_void_p

        deadline = time.time() + 20.0
        hwnd = 0
        while hwnd == 0 and time.time() < deadline:
            hwnd = _find_app_window(process.pid)
            if hwnd == 0:
                time.sleep(0.3)
        if hwnd == 0:
            return

        try:
            dpi = user32.GetDpiForWindow(hwnd)
        except AttributeError:                      # Win10 1607 之前没有这个函数
            dpi = 96
        size = max(16, min(256, round(TASKBAR_ICON_BASE * (dpi or 96) / 96)))
        hicon = user32.LoadImageW(None, str(icon_file), 1, size, size, 0x0010)  # 1=IMAGE_ICON 0x10=LR_LOADFROMFILE
        if not hicon:
            return
        for _ in range(20):                         # 约 8 秒，压过 Chromium 写 favicon 图标的那一下
            user32.SendMessageW(hwnd, 0x0080, 1, hicon)     # 0x80=WM_SETICON 1=ICON_BIG
            time.sleep(0.4)
    except Exception:
        pass


def main() -> int:
    _quiet_streams()
    splash = _show_splash()

    port = _free_port()
    threading.Thread(target=_serve, args=(port,), daemon=True).start()

    if not _wait_ready(port, splash):
        _close_splash(splash)
        _alert("后端没能启动起来（多半是端口被安全软件拦了）。\n"
               "先关掉重开一次；如果一直这样，请把这个情况告诉作者。")
        return 1

    url = f"http://127.0.0.1:{port}/"
    browser = _find_browser()
    process, profile = _open_app_window(browser, url) if browser else (None, None)
    _close_splash(splash)

    if process is None:
        # 没找到 Edge / Chrome：用系统默认浏览器打开，靠心跳收尾
        webbrowser.open(url)
        _wait_heartbeat()
        return 0

    # 后台把任务栏图标换成高清版（Chromium 给的是 16×16，任务栏要画 36px，会糊）
    threading.Thread(target=_polish_window_icon, args=(process,), daemon=True).start()

    try:
        process.wait()                   # 等窗口被关掉
    except KeyboardInterrupt:
        pass
    finally:
        if profile is not None:
            shutil.rmtree(profile, ignore_errors=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        _alert("程序出错了：\n\n" + traceback.format_exc())
        sys.exit(1)
