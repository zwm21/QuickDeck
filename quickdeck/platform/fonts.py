# -*- coding: utf-8 -*-
"""本地字体加载（进程内私有）。"""
import os
import ctypes


def load_local_font(font_path):
    """把同目录的 ttf 字体加载到当前进程，无需系统级安装。"""
    if not os.path.exists(font_path):
        return False
    try:
        FR_PRIVATE = 0x10  # 仅本进程可见
        n = ctypes.windll.gdi32.AddFontResourceExW(font_path, FR_PRIVATE, 0)
        return n > 0
    except Exception:
        return False
