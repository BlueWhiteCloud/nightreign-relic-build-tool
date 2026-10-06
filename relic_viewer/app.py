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

# 日志统一在 applog.py 里（后端 server.py 也要写，放在本文件会循环导入）；
# 这里起别名只是为了让下面的调用点短一点。
from applog import log as _log, log_exception as _log_exception, log_path as _log_path

# server 故意不在顶层导入：它要读数据表、挂静态目录，任何一步出错都会让打包版
# 「双击没反应」（没有控制台，异常直接吞掉）。放到 main() 里导入，出错至少能弹框 + 落日志。
server = None


def _quiet_streams() -> None:
    """打包成窗口程序（console=False）后 stdout/stderr 是 None，日志库一写就炸，先兜住。"""
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def _file_version(path) -> str:
    """读 exe 的文件版本号（如 120.0.2210.91）；读不到返回空串。

    记这个是因为：Chromium 系浏览器太旧会直接跑不动前端（页面一片黑），
    而「桌面有没有 Edge 图标」根本看不出版本 —— 记下来就不用再远程问了。
    """
    try:
        import ctypes
        from ctypes import wintypes

        class VS_FIXEDFILEINFO(ctypes.Structure):
            _fields_ = [("dwSignature", wintypes.DWORD), ("dwStrucVersion", wintypes.DWORD),
                        ("dwFileVersionMS", wintypes.DWORD), ("dwFileVersionLS", wintypes.DWORD),
                        ("dwProductVersionMS", wintypes.DWORD), ("dwProductVersionLS", wintypes.DWORD),
                        ("dwFileFlagsMask", wintypes.DWORD), ("dwFileFlags", wintypes.DWORD),
                        ("dwFileOS", wintypes.DWORD), ("dwFileType", wintypes.DWORD),
                        ("dwFileSubtype", wintypes.DWORD), ("dwFileDateMS", wintypes.DWORD),
                        ("dwFileDateLS", wintypes.DWORD)]

        version = ctypes.windll.version
        size = version.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return ""
        buffer = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(str(path), 0, size, buffer):
            return ""
        pointer = ctypes.c_void_p()
        length = ctypes.c_uint()
        if not version.VerQueryValueW(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)):
            return ""
        if not pointer.value:
            return ""
        info = ctypes.cast(pointer, ctypes.POINTER(VS_FIXEDFILEINFO)).contents
        ms, ls = info.dwFileVersionMS, info.dwFileVersionLS
        return "%d.%d.%d.%d" % (ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF)
    except Exception:
        return ""


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


def _fail(what: str, detail: str = "", *, fatal: bool = False) -> None:
    """「出事了」的统一入口：写日志 + 弹框把日志路径告诉用户。

    只在主线程调用 —— 后台线程里弹 tkinter 窗口会出问题（那种地方只用 _log）。

    :param what:   一句话说清出了什么事。既进日志也显示在对话框上，所以要写人话
    :param detail: 细节 / 堆栈。**只进日志** —— 糊到对话框上用户看不懂，还吓人
    :param fatal:  致命错误：对话框里加一句「程序会退出」
    """
    _log(("[致命] " if fatal else "[错误] ") + what + (("\n" + detail) if detail else ""))
    _alert("%s\n\n%s请把这份日志发给作者：\n%s"
           % (what, "程序会退出。\n\n" if fatal else "", _log_path()))


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
    """在后台线程里跑 uvicorn（它不是主线程，所以自己不会去装信号处理，正好）。

    异常必须自己接住记日志：这个线程挂了，外面只会看到「窗口连不上」，
    真正的原因（端口被占用、数据表读不出来……）否则就跟着 devnull 一起没了。
    """
    import uvicorn

    try:
        uvicorn.run(server.app, host="127.0.0.1", port=port,
                    log_config=None, log_level="warning", access_log=False)
    except Exception:
        _log_exception("后端服务异常退出")


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


#: 把窗口开出来之后，等前端心跳的宽限时间（秒）。
#: 前端一挂载成功就会立刻打一发心跳（见 web/src/main.ts），所以正常情况下 1~3 秒就有；
#: 给到 15 秒是照顾慢机器（机械盘 + 杀软实时扫描，加载那几百 KB 前端要好几秒）。
FIRST_HEARTBEAT_GRACE = 15.0


def _wait_first_heartbeat(timeout: float) -> bool:
    """等前端的第一发心跳，等到返回 True，超时返回 False。

    心跳是判断「页面到底跑起来了没有」最直接的信号：
    前端只有 mount 成功之后才会打（见 web/src/main.ts），
    所以「窗口开着、界面一片黑、又没心跳」= JS 根本没执行。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if server.last_ping_time() > 0.0:
            return True
        time.sleep(0.2)
    return server.last_ping_time() > 0.0


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
            _log("没找到应用窗口，跳过任务栏图标替换")
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
        _log_exception("换任务栏图标失败（不影响使用，只是图标可能发糊）")


def main() -> int:
    global server

    _quiet_streams()
    _log("=" * 50)
    _log("启动（打包版=%s）" % bool(getattr(sys, "frozen", False)))

    # 后端模块特意放到这里导入：它要读数据表、挂静态资源目录，任何一步失败程序都起不来。
    # 以前放在文件顶层，异常发生在 try 之外 —— 打包版没有控制台，用户只会看到「双击没反应」。
    try:
        import server
    except Exception:
        _fail("后端加载失败（多半是程序文件不完整：被杀软清理了，或者压缩包没解压完整）。\n"
              "建议重新解压一次，或者重新下载压缩包。",
              traceback.format_exc(), fatal=True)
        return 1

    splash = _show_splash()

    port = _free_port()
    _log("端口 %d" % port)
    threading.Thread(target=_serve, args=(port,), daemon=True).start()

    if not _wait_ready(port, splash):
        _close_splash(splash)
        _fail("后端没能启动起来（多半是端口被安全软件拦了）。\n先关掉重开一次。", fatal=True)
        return 1

    url = f"http://127.0.0.1:{port}/"
    browser = _find_browser()
    if browser is not None:
        _log("用浏览器：%s（版本 %s）" % (browser, _file_version(browser) or "读不出来"))
    else:
        _log("本机没找到 Edge / Chrome，改用系统默认浏览器")
    process, profile = _open_app_window(browser, url) if browser else (None, None)
    _close_splash(splash)

    if process is None:
        # 没找到 Edge / Chrome：用系统默认浏览器打开，靠心跳收尾
        webbrowser.open(url)
        _wait_heartbeat()
        _log("退出（默认浏览器模式）")
        return 0

    # 后台把任务栏图标换成高清版（Chromium 给的是 16×16，任务栏要画 36px，会糊）
    threading.Thread(target=_polish_window_icon, args=(process,), daemon=True).start()

    # 「窗口开着」不等于「界面画出来了」：有机器上 JS 压根没执行，用户看到的就是
    # 只有边框标题、内容一片黑（而且重启软件没用）。心跳是判断这事儿最直接的信号，
    # 所以先等一发：
    #   等到心跳        → 界面起得来（以后再出问题就是渲染层的事，不是 JS）
    #   等不到、窗口还在 → 界面没画出来，换默认浏览器兜底，并把证据记进日志
    #   等不到、窗口没了 → 用户很快关了，或者 Edge 把窗口交给了已有实例，正常收工
    if _wait_first_heartbeat(FIRST_HEARTBEAT_GRACE):
        _log("已收到前端心跳（界面起得来）")
    elif process.poll() is None:
        webbrowser.open(url)
        _fail("独立窗口好像没能把界面画出来（里面是一片空白）。\n"
              "已经改用你的默认浏览器重新打开，请到那边操作。")
        _wait_heartbeat()
        _log("退出（界面没画出来，走了默认浏览器兜底）")
        # 那个（黑屏）窗口还开着、还占着临时用户目录，这里就别去删它了
        return 0

    try:
        process.wait()                   # 等窗口被关掉
    except KeyboardInterrupt:
        pass
    finally:
        if profile is not None:
            shutil.rmtree(profile, ignore_errors=True)
    _log("退出（窗口已关闭，浏览器返回码 %s）" % process.returncode)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # 最后一道兜底：连 main() 都炸了，至少弹框 + 留日志，绝不静默退出
        _fail("程序遇到了没预料到的错误。", traceback.format_exc(), fatal=True)
        sys.exit(1)
