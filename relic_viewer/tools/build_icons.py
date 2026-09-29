"""把一张方形的 logo 源图生成全套图标文件（exe 图标 + 网页标签页图标）。

用法（默认读仓库根目录的 图标/logo图标.png）：
    python tools/build_icons.py
    python tools/build_icons.py --src "..\\图标\\别的名字.png"

生成：
    图标/icon.ico                         多尺寸图标（16~256 共 15 档），打包 exe 用
    relic_viewer/web/public/favicon.ico   网页图标（16~256 共 7 档）
    relic_viewer/web/public/favicon.png   网页图标（256，给现代浏览器 / Windows 当大图源）

源图换名字或换画法以后，重跑一次这个脚本就行 —— 不用手改任何图标文件。
"""

import argparse
from pathlib import Path

from PIL import Image

#: 脚本在 relic_viewer/tools/ 下，往上三层是仓库根目录
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

#: 默认源图（另一版是抠过透明底的 图标/logo图标-透明底.png，想换用它传 --src 即可）
DEFAULT_SRC = REPO_ROOT / "图标" / "logo图标.png"

#: exe 图标要带上的尺寸。
#: Windows 是按「显示缩放」去要图标的：100% 要 16/20/24/32、125% 要 20/24/32/40、
#: 150% 要 24/32/36/48…… 尺寸给全了，系统就不必把某个尺寸硬拉大 ——
#: 任务栏图标发糊，十有八九就是被硬拉大的（比如 150% 下要 36，却只有 32 可用）。
ICO_SIZES = [(16, 16), (20, 20), (24, 24), (28, 28), (32, 32), (36, 36), (40, 40),
             (48, 48), (56, 56), (60, 60), (64, 64), (72, 72), (96, 96),
             (128, 128), (256, 256)]
#: 网页标签页 / 窗口图标用的：浏览器和 Windows 主要从这几个里挑
WEB_ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

#: 体检用的底色（界面与任务栏都是深色）：透明区域会露出它，统计前先合成上去
DARK_BG = (10, 13, 20)


def _make_square(image: Image.Image) -> Image.Image:
    """拍成正方形：图标必须是正的，源图不是正方形就居中裁一块。"""
    width, height = image.size
    if width == height:
        return image
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    return image.crop((left, top, left + side, top + side))


def main() -> int:
    parser = argparse.ArgumentParser(description="生成图标文件")
    parser.add_argument("--src", default=str(DEFAULT_SRC),
                        help="方形 logo 源图（默认 图标/logo图标.png）")
    args = parser.parse_args()

    src = Path(args.src)
    if not src.is_file():
        print(f"找不到源图：{src}")
        return 1

    image = _make_square(Image.open(src).convert("RGBA"))
    print(f"源图：{src}　{image.size[0]}x{image.size[1]}")

    # 每个尺寸都「各自从原图缩一次」。
    # 以前是先把原图缩到 256 当母版、再让 Pillow 从 256 往下缩 —— 等于缩两遍，小尺寸会发虚。
    # Pillow 存 ICO 时，凡是尺寸正好对上的图它就原样收进去（见 IcoImagePlugin._save），
    # 所以这里把每个尺寸都先缩好，用 append_images 一起交给它，就不会有第二次缩放。
    def frames_for(sizes):
        frames = sorted((image.resize(size, Image.LANCZOS) for size in sizes),
                        key=lambda frame: frame.size[0])
        return frames[-1], frames[:-1]      # 最大的那张当主图，其余按尺寸精确匹配

    targets = [
        (REPO_ROOT / "图标" / "icon.ico", ICO_SIZES),
        (REPO_ROOT / "relic_viewer" / "web" / "public" / "favicon.ico", WEB_ICO_SIZES),
    ]
    for path, sizes in targets:
        master, rest = frames_for(sizes)
        path.parent.mkdir(parents=True, exist_ok=True)
        master.save(path, format="ICO", sizes=sizes, append_images=rest)
        print(f"  写出 {path.relative_to(REPO_ROOT)}　尺寸 {sorted(s[0] for s in sizes)}")

    # 网页那张 PNG 给到 256：浏览器画标签页 / 窗口左上角、Windows 做任务栏大图都从它缩，
    # 源图给大点，怎么缩都还有余量（以前只给 64，等于一上来就把路堵死了）。
    png_path = REPO_ROOT / "relic_viewer" / "web" / "public" / "favicon.png"
    image.resize((256, 256), Image.LANCZOS).save(png_path, format="PNG")
    print(f"  写出 {png_path.relative_to(REPO_ROOT)}　256x256")

    # 顺手体检：小尺寸下还剩多少明暗差（差太小说明在深色底上会糊成一团）
    # 源图是透明底的，透明区域会直接露出界面/任务栏的深色，所以先合成到 DARK_BG 上再统计，
    # 否则透明像素被当成黑色/白色，平均值和标准差都是歪的。
    backdrop = Image.new("RGBA", (256, 256), DARK_BG + (255,))
    flattened = Image.alpha_composite(backdrop, image.resize((256, 256), Image.LANCZOS)).convert("L")
    for size in (16, 32, 256):
        small = flattened.resize((size, size), Image.LANCZOS)
        pixels = list(small.getdata())
        average = sum(pixels) / len(pixels)
        spread = (sum((p - average) ** 2 for p in pixels) / len(pixels)) ** 0.5
        print(f"  {size:>3}x{size}: 平均亮度 {average:5.1f}　明暗标准差 {spread:5.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
