"""全程序共用的日志：一个文件、一个入口。

为什么单独一个模块：要写日志的不止启动流程（app.py），后端接口（server.py）也要写 ——
放进 app.py 会变成循环导入。

文件位置：%LOCALAPPDATA%\\黑夜君临遗物配装工具\\日志.txt
（改这个路径的话，web/index.html 里那段给用户看的占位文案也印着它，记得一起改。）

用户报「黑屏 / 连不上 / 打不开」时，让他把这一份日志发过来基本就能定性 ——
所以凡是「出问题了」的地方都往这里写一条。**别用 print**：打包后没有控制台，print 等于扔了。
"""

import os
import tempfile
import time
import traceback
from pathlib import Path


def log_path() -> Path:
    """日志文件路径。优先 %LOCALAPPDATA%，写不进去就退到临时目录。"""
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    folder = Path(base) / "黑夜君临遗物配装工具"
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        return Path(tempfile.gettempdir()) / "黑夜君临遗物配装工具-日志.txt"
    return folder / "日志.txt"


def log(message: str) -> None:
    """往日志追加一行（带时间）。

    写不进去就算了 —— 记日志这件事本身绝不能把程序搞挂。
    """
    try:
        with open(log_path(), "a", encoding="utf-8") as handle:
            handle.write("%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), message))
    except OSError:
        pass


def log_exception(what: str) -> None:
    """记一条「出事了」+ 当前堆栈。调用点只要一行，堆栈不会丢。"""
    log("%s\n%s" % (what, traceback.format_exc()))
