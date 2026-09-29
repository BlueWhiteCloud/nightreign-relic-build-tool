# -*- mode: python ; coding: utf-8 -*-
"""打包脚本：把「Python 后端 + 构建好的前端页面 + 游戏数据表」合成一个 exe。

用法（在 relic_viewer 目录下先构建前端，再打包）：
    npm --prefix web run build
    pyinstaller 黑夜君临遗物配装工具.spec

产物：dist/黑夜君临遗物配装工具.exe
     单文件、双击即用 —— 玩家不用装 Python，也不用敲任何命令。

图标：../图标/icon.ico（由 tools/build_icons.py 从 图标/logo图标.png 生成，
     换了 logo 重跑那个脚本即可，不用改这里）
"""

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    # 游戏数据表 + 前端构建产物都塞进 exe，运行时从 PyInstaller 的解压目录读
    # 图标也塞一份：LoadImage 没法从 exe 自己的图标资源里抠（实测返回空），
    # 但能从 .ico 文件读 —— app.py 靠它把高清图标塞进 Edge 应用窗口，见 _polish_window_icon
    datas=[('Resources', 'Resources'), ('web/dist', 'web/dist'), ('../图标/icon.ico', '图标')],
    hiddenimports=[
        # uvicorn 这些模块是运行时按名字动态导入的，静态分析看不见，必须点出来
        'uvicorn.logging',
        'uvicorn.loops', 'uvicorn.loops.auto',
        'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan', 'uvicorn.lifespan.on',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 这些是被间接 import 拖进来的重家伙，本工具一个都用不到，排掉能省一半体积：
    #   PyQt5 光一个 opengl32sw.dll 就 20MB；Pythonwin 自带一整套 MFC；lxml / jedi / IPython
    #   是别的库的依赖。注意 cryptography **不能排** —— 读存档解密要用它。
    excludes=[
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'shiboken2', 'shiboken6',
        'lxml', 'Pythonwin', 'Cython', 'jedi', 'parso', 'IPython',
        'numpy', 'pandas', 'matplotlib', 'scipy', 'PIL', 'cv2',
        'pydoc_data', 'tkinter.test',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='黑夜君临遗物配装工具',
    # exe 的图标（Windows 资源管理器 / 任务栏 / 快捷方式都读它）
    icon='../图标/icon.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
