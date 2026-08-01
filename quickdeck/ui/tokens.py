# -*- coding: utf-8 -*-
"""主题 token 表——全应用唯一色源。

P5 阶段：色值与旧版完全一致（保证重构行为等价）；
P8 视觉升级时在此统一调整并扩充角色（accent/border/hover 等）。
"""

LIGHT_THEME = {
    "name": "light",
    "app_bg": "#F0F0F0",           # 主窗口 / 滚动区背景
    "panel_bg": "#F8F9FA",         # 底部字体设置卡片
    "card_bg": "#FFFFFF",          # 快捷方式卡片
    "desc_bg": "#F4F4F4",          # 描述输入框
    "folder_bg": "#F5F5F5",        # 文件夹框体 / body
    "header_bg": "#E0E0E0",        # 文件夹 header
    "fg": "#000000",               # 常规文字
    "header_fg": "#333333",        # header 上的图标按钮
    "danger_fg": "#B22222",        # 删除类按钮文字
    "danger_active_bg": "#FADBD8",
    "header_active_bg": "#D0D0D0",
    "btn_bg": "#F0F0F0",           # 工具栏按钮
    "btn_active_bg": "#E2E2E2",
}

DARK_THEME = {
    "name": "dark",
    "app_bg": "#1F1F1F",
    "panel_bg": "#2A2A2A",
    "card_bg": "#2D2D30",
    "desc_bg": "#3C3C3C",
    "folder_bg": "#262626",
    "header_bg": "#333333",
    "fg": "#E6E6E6",
    "header_fg": "#CCCCCC",
    "danger_fg": "#E57373",
    "danger_active_bg": "#5C2B2B",
    "header_active_bg": "#454545",
    "btn_bg": "#3A3A3A",
    "btn_active_bg": "#4A4A4A",
}
