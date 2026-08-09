# -*- coding: utf-8 -*-
"""布局纯函数（无 tk 依赖，可单测）。"""

CARD_GAP = 6  # 每列宽度余量：等于卡片 grid padx 两侧之和


def compute_cols(avail_width, card_width, gap=CARD_GAP):
    """由可用宽度与卡片宽度算列数（至少 1 列）。"""
    unit = int(card_width) + gap
    if unit <= 0:
        return 1
    return max(1, int(avail_width) // unit)


def grid_signature(cards, ncols, card_width):
    """一次网格布局的签名：列数/卡宽/卡片序列都未变时可跳过重排。"""
    return (int(ncols), int(card_width), tuple(id(c) for c in cards))
