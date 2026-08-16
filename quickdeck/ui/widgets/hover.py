# -*- coding: utf-8 -*-
"""hover 绑定工具：Enter/Leave 切换控件底色（P8 视觉升级）。

颜色以「token 名」登记、事件发生时从 app.theme 取值，
因此无需在主题切换时重绑。
"""


def _resolve(token):
    """token 名可以是字符串，或返回 token 名的零参回调。
    回调在事件发生时求值——正常态底色随控件状态（如文件夹锁定态）
    变化时，Leave 恢复的才是当前态应有的底色。"""
    return token() if callable(token) else token


def bind_hover(app, widget, normal_token, hover_token,
               also_fg=None):
    """给控件绑定 hover 底色切换。
    normal_token/hover_token 为 token 名或返回 token 名的零参回调。
    also_fg=(normal_fg_token, hover_fg_token) 可同时切文字色。
    disabled 控件不做任何 hover 反馈，避免"可点击"错觉；
    其底色复位由状态所有者（如 FolderFrame.refresh_header_state）负责。"""

    def on_enter(_e):
        try:
            if str(widget.cget("state")) == "disabled":
                return
            kw = {"bg": app.theme[_resolve(hover_token)]}
            if also_fg:
                kw["fg"] = app.theme[also_fg[1]]
            widget.configure(**kw)
        except Exception:
            pass

    def on_leave(_e):
        try:
            if str(widget.cget("state")) == "disabled":
                return
            kw = {"bg": app.theme[_resolve(normal_token)]}
            if also_fg:
                kw["fg"] = app.theme[also_fg[0]]
            widget.configure(**kw)
        except Exception:
            pass

    widget.bind("<Enter>", on_enter, add="+")
    widget.bind("<Leave>", on_leave, add="+")
