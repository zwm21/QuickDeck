# -*- coding: utf-8 -*-
"""悬浮气泡提示（P10）：卡片描述轨道悬停时显示完整描述。

模块级单例——同一时刻至多一个气泡，避免鼠标快速扫过一排卡片时
留下多个 Toplevel。
"""
import tkinter as tk

SHOW_DELAY_MS = 350
WRAP_WIDTH = 360

_tip = None      # tk.Toplevel
_label = None
_job = None      # 挂起的延迟显示 after id
_owner = None    # 发起延迟的 app，用于 after_cancel
_target = None   # 当前气泡归属的控件


def show(app, widget, text):
    """延迟 SHOW_DELAY_MS 后在 widget 下方显示 text。
    对同一控件重复调用不重启计时，避免指针在轨道内移动时闪烁。"""
    global _job, _owner, _target
    if _target is widget and (_job is not None or _tip is not None):
        return
    hide()
    if not text:
        return
    _owner = app
    _target = widget
    _job = app.after(SHOW_DELAY_MS, lambda: _popup(app, widget, text))


def hide():
    """立即隐藏气泡并取消挂起的显示。"""
    global _tip, _label, _job, _owner, _target
    if _job is not None and _owner is not None:
        try:
            _owner.after_cancel(_job)
        except Exception:
            pass
    _job = None
    _owner = None
    _target = None
    if _tip is not None:
        try:
            _tip.destroy()
        except Exception:
            pass
    _tip = None
    _label = None


def _popup(app, widget, text):
    global _tip, _label, _job
    _job = None
    th = app.theme
    try:
        if not widget.winfo_exists():
            return
        x = widget.winfo_rootx()
        y = widget.winfo_rooty() + widget.winfo_height() + 6
    except tk.TclError:
        return
    try:
        _tip = tk.Toplevel(app)
        _tip.overrideredirect(True)
        _tip.attributes("-topmost", True)
        _label = tk.Label(
            _tip, text=text, font=app.font_desc,
            wraplength=WRAP_WIDTH, justify="left",
            bg=th["panel_bg"], fg=th["fg"], padx=10, pady=6,
            highlightthickness=1,
            highlightbackground=th["border_strong"],
            highlightcolor=th["border_strong"],
        )
        _label.pack()
        # 先量出实际尺寸再定位，越界则朝屏内回弹
        _tip.update_idletasks()
        w, h = _tip.winfo_width(), _tip.winfo_height()
        sw, sh = _tip.winfo_screenwidth(), _tip.winfo_screenheight()
        x = max(0, min(x, sw - w))
        if y + h > sh:
            y = max(0, widget.winfo_rooty() - h - 6)
        _tip.geometry(f"+{x}+{y}")
    except tk.TclError:
        hide()
