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
