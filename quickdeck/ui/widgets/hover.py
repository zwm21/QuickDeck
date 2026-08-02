# -*- coding: utf-8 -*-
"""hover 绑定工具：Enter/Leave 切换控件底色（P8 视觉升级）。

颜色以「token 名」登记、事件发生时从 app.theme 取值，
因此无需在主题切换时重绑。
"""


def bind_hover(app, widget, normal_token, hover_token,
               also_fg=None):
    """给控件绑定 hover 底色切换。
    also_fg=(normal_fg_token, hover_fg_token) 可同时切文字色。"""

    def on_enter(_e):
        try:
            kw = {"bg": app.theme[hover_token]}
            if also_fg:
                kw["fg"] = app.theme[also_fg[1]]
            widget.configure(**kw)
        except Exception:
            pass

    def on_leave(_e):
        try:
            kw = {"bg": app.theme[normal_token]}
            if also_fg:
                kw["fg"] = app.theme[also_fg[0]]
            widget.configure(**kw)
        except Exception:
            pass

    widget.bind("<Enter>", on_enter, add="+")
    widget.bind("<Leave>", on_leave, add="+")
