# -*- coding: utf-8 -*-
"""主题 token 表——全应用唯一色源（P8 视觉升级：蓝色系现代扁平风）。

角色说明：
- app_bg/folder_bg/header_bg/card_bg/panel_bg：由外到内的层次底色
- border/border_strong：可主题化描边（配合 highlightthickness 使用，
  替代旧版不可调色的 relief="solid"）
- accent/accent_hover：品牌强调色（拖拽指示线、hover 高亮、启动反馈）
- fg/fg_secondary：主/次级文字
- *_hover_bg：鼠标悬停反馈
- P12/P13 header 图标按钮常驻色块三档底色：danger_bg（删除红系）、
  collapse_bg/_hover/_active（折叠绿系，P13 起未锁定才显示）、
  lock_bg/_hover/_active（锁定金系）；lock_fg 为锁定按钮单色金字，
  danger_fg_muted 为禁用删除按钮的弱化红。锁定态三按钮一律压平
  header_bg（见 FolderFrame.refresh_header_state），色块仅用于未锁定态
"""

LIGHT_THEME = {
    "name": "light",
    "app_bg": "#F3F4F6",
    "panel_bg": "#FFFFFF",
    "card_bg": "#FFFFFF",
    "card_hover_bg": "#F5F8FE",
    "desc_bg": "#F3F4F6",
    "folder_bg": "#FAFBFC",
    "header_bg": "#EDEFF2",
    "fg": "#1B1F24",
    "fg_secondary": "#656D76",
    "header_fg": "#656D76",
    "border": "#E2E5EA",
    "border_strong": "#CDD2DA",
    "accent": "#2F6FEB",
    "accent_hover": "#1F5FD8",
    "selected_bg": "#E4EDFF",
    "danger_fg": "#C0392B",
    "danger_hover_bg": "#FDECEA",
    "danger_active_bg": "#FADBD8",
    "header_active_bg": "#DDE1E6",
    "btn_bg": "#FFFFFF",
    "btn_hover_bg": "#EDEFF2",
    "btn_active_bg": "#E2E5EA",
    # P12/P13：header 图标按钮常驻色块（浅红/浅绿/浅金）
    "danger_bg": "#FDF4F3",
    "collapse_fg": "#1A7F37",
    "collapse_bg": "#D7F0DE",
    "collapse_bg_hover": "#C2E8CD",
    "collapse_bg_active": "#ACE0BC",
    "lock_fg": "#9A6700",
    "lock_bg": "#FBF3DC",
    "lock_bg_hover": "#F5E6B8",
    "lock_bg_active": "#EDD896",
    "danger_fg_muted": "#B85C55",
}

DARK_THEME = {
    "name": "dark",
    "app_bg": "#17181B",
    "panel_bg": "#1E1F23",
    "card_bg": "#26282D",
    "card_hover_bg": "#2F3238",
    "desc_bg": "#33363D",
    "folder_bg": "#1C1D21",
    "header_bg": "#26282D",
    "fg": "#E6E8EB",
    "fg_secondary": "#9BA3AE",
    "header_fg": "#9BA3AE",
    "border": "#33363D",
    "border_strong": "#454951",
    "accent": "#4C8DFF",
    "accent_hover": "#6BA1FF",
    "selected_bg": "#22304A",
    "danger_fg": "#F0796B",
    "danger_hover_bg": "#3A2422",
    "danger_active_bg": "#5C2B2B",
    "header_active_bg": "#31343A",
    "btn_bg": "#26282D",
    "btn_hover_bg": "#31343A",
    "btn_active_bg": "#3A3E45",
    # P12/P13：header 图标按钮常驻色块（暗红/暗绿/暗金）
    "danger_bg": "#2F1F1E",
    "collapse_fg": "#4CC38A",
    "collapse_bg": "#1E4230",
    "collapse_bg_hover": "#2A523C",
    "collapse_bg_active": "#366449",
    "lock_fg": "#E3B341",
    "lock_bg": "#3A321F",
    "lock_bg_hover": "#4A3E22",
    "lock_bg_active": "#5C4C28",
    "danger_fg_muted": "#B06A64",
}
