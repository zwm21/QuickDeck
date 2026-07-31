# -*- coding: utf-8 -*-
"""程序化截图：四视图 x 浅/深主题，共 8 张。

用法：python tests/capture_screens.py [输出子目录名，默认 baseline]
产物：tests/screens/<名字>/{light|dark}_{cards|usage|web|dirs}.png

- 不写用户 config.json（monkeypatch save_config 为 no-op）
- 窗口置顶后用 PIL.ImageGrab 按窗口矩形抓屏
"""
import os
import sys
import time

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, REPO_DIR)

import main  # noqa: E402
from PIL import ImageGrab  # noqa: E402

VIEW_MODES = ("cards", "usage", "web", "dirs")


def pump(app, seconds):
    """跑事件循环一段时间，让异步图标回填、布局稳定。"""
    end = time.time() + seconds
    while time.time() < end:
        app.update()
        time.sleep(0.03)


def grab_window(app, out_path):
    app.update_idletasks()
    x = app.winfo_rootx()
    y = app.winfo_rooty()
    w = app.winfo_width()
    h = app.winfo_height()
    # 含标题栏往上扩一点，便于核对标题栏配色（DWM 深色标题栏）
    img = ImageGrab.grab(bbox=(x, y - 36, x + w, y + h), all_screens=True)
    img.save(out_path)
    print(f"saved {out_path}")


def set_view(app, mode):
    label = {v: k for k, v in app._VIEW_MODE_BY_LABEL.items()}[mode]
    app.view_mode_var.set(label)
    app._on_view_mode_change()


def main_capture():
    name = sys.argv[1] if len(sys.argv) > 1 else "baseline"
    out_dir = os.path.join(TESTS_DIR, "screens", name)
    os.makedirs(out_dir, exist_ok=True)

    main.save_config = lambda cfg: None  # 绝不写用户配置
    main.enable_dpi_awareness()

    app = main.App()
    app.attributes("-topmost", True)
    app.lift()
    pump(app, 2.5)  # 等异步图标回填

    for mode_name, theme in (("light", main.LIGHT_THEME),
                             ("dark", main.DARK_THEME)):
        app.theme_mode = "light" if mode_name == "light" else "dark"
        if theme is not app.theme:
            app.apply_theme(theme)
        pump(app, 0.5)
        for view in VIEW_MODES:
            set_view(app, view)
            pump(app, 0.6)
            grab_window(app, os.path.join(out_dir,
                                          f"{mode_name}_{view}.png"))
        set_view(app, "cards")

    app.destroy()
    print("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main_capture())
