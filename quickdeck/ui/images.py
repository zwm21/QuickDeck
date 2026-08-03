# -*- coding: utf-8 -*-
"""PIL 生成的界面位图（P8：圆角卡片底图）。

tk 无真透明：圆角矩形按已知容器底色（folder_bg）预合成，
贴在卡片底层 Label 上。2x 超采样再缩小，边缘平滑。
按 (尺寸+三色) 做 LRU 缓存；主题切换时 invalidate() 整表失效。
"""
from collections import OrderedDict

from PIL import Image, ImageDraw, ImageTk

_MAX_CACHE = 96
_cache = OrderedDict()   # key -> ImageTk.PhotoImage


def rounded_card_image(w, h, radius, fill, outline, bg):
    """圆角卡片底图：fill 填充、1px outline 描边、四角外露 bg。"""
    w, h = max(4, int(w)), max(4, int(h))
    key = (w, h, radius, fill, outline, bg)
    photo = _cache.get(key)
    if photo is not None:
        _cache.move_to_end(key)
        return photo
    s = 2  # 超采样倍率（圆角边缘平滑）
    img = Image.new("RGB", (w * s, h * s), bg)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w * s - 1, h * s - 1],
                        radius=radius * s, fill=fill)
    img = img.resize((w, h), Image.LANCZOS)
    # 描边在最终分辨率补画：超采样缩小会把 1px 线冲淡成几乎不可见
    d2 = ImageDraw.Draw(img)
    d2.rounded_rectangle([0, 0, w - 1, h - 1],
                         radius=radius, outline=outline, width=1)
    photo = ImageTk.PhotoImage(img)
    _cache[key] = photo
    while len(_cache) > _MAX_CACHE:
        _cache.popitem(last=False)
    return photo


def invalidate():
    """清空缓存（主题切换后旧配色的底图全部失效）。"""
    _cache.clear()
