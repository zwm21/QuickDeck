# -*- coding: utf-8 -*-
"""高 DPI 感知。"""
import ctypes


def enable_dpi_awareness():
    """让程序按物理像素工作，避免高 DPI 屏上图标/文字模糊。"""
    try:
        # Windows 8.1+ 推荐 API
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            # 兼容更老的 Windows
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
