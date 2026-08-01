# -*- coding: utf-8 -*-
"""主题管理器：控件注册角色制。

旧实现在 ShortcutCard.apply_theme / FolderFrame.apply_theme /
App._apply_theme_body 三处硬编码枚举控件上色，新增控件极易漏刷。
现在控件创建后注册一次「tk 选项 → 主题 token」映射，切换主题时
统一遍历刷新；已销毁控件在遍历时自动剪除。
"""
import tkinter as tk


class ThemeManager:
    def __init__(self, theme):
        self.theme = theme
        self._registry = []  # [(widget, {tk_option: token}), ...]

    def register(self, widget, **options):
        """登记控件的主题映射，如 register(w, bg="card_bg", fg="fg")。
        创建时控件已按当前主题着色，注册本身不重复 configure。"""
        self._registry.append((widget, options))

    def apply(self, theme):
        """整体切换主题：刷新所有存活控件，剪除已销毁的注册项。"""
        self.theme = theme
        alive = []
        for w, opts in self._registry:
            try:
                if not w.winfo_exists():
                    continue
                w.configure(**{o: theme[t] for o, t in opts.items()})
                alive.append((w, opts))
            except tk.TclError:
                continue
        self._registry = alive

    def count(self):
        return len(self._registry)
