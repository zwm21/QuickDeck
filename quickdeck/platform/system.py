# -*- coding: utf-8 -*-
"""系统集成：读取系统深浅色偏好。"""


def system_prefers_light():
    """读注册表 AppsUseLightTheme（1=浅色，0=深色）。读不到按浅色处理。"""
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion"
            r"\Themes\Personalize"
        ) as k:
            v, _t = winreg.QueryValueEx(k, "AppsUseLightTheme")
            return bool(v)
    except Exception:
        return True
