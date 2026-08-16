# -*- coding: utf-8 -*-
"""全局常量（尺寸、字体、定时器）。重构中作为跨模块共享的唯一常量源。"""

# 卡片图标默认尺寸（缓存 key 的默认档；P8c 起显示尺寸按卡宽分档）
ICON_SIZE = 32

# P8c 图标分档：卡宽 <380 → 32px，<520 → 40px，其余 → 48px
ICON_TIERS = ((380, 32), (520, 40))
ICON_TIER_MAX = 48


def icon_size_for(card_width):
    """按卡片宽度返回图标显示尺寸档位。"""
    for limit, size in ICON_TIERS:
        if int(card_width) < limit:
            return size
    return ICON_TIER_MAX

# 内置字体家族名（TTF 文件内 name table 记录的家族名，
# 通常与去掉扩展名的文件名一致）
BUILTIN_FONT_FAMILY = "HYWenHei-65W"

# P12 header 图标按钮专用字体族：Segoe UI Symbol 覆盖 header 全部六个
# 字形码位 ☰🔓🔒▼▶✖（fontTools cmap 实测）。族不跟随用户字体
# （换任意字体族都不会丢字形），只字号跟随应用字号。
ICON_FONT_FAMILY = "Segoe UI Symbol"

# P14：图标字号 = 应用字号 - 2。Segoe UI Symbol 行高比 HYWenHei 高
# 一档，-2 才能把按钮高度复原到 P12 前水平。Tk 按钮 chrome 随字号/
# 字体族非线性变化（@10≈10px、@24≈32px），此值经全字号实测校准，
# smoke_theme 的探针基准断言（应用字体族 @N-1）依赖这层关系，
# 改动需重跑全字号校准
ICON_FONT_DELTA = 2


def icon_font_size_for(app_size):
    """图标按钮字号（P14 校准公式 N-2，下限 8 同应用字号）。"""
    return max(8, int(app_size) - ICON_FONT_DELTA)
