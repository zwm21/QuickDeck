# -*- coding: utf-8 -*-
"""P7 拖拽冒烟：
- motion 期间数据顺序不变（幽灵+指示线预览），release 才 commit
- 拖拽阈值：小位移不触发幽灵
- 跨文件夹落位正确、同文件夹重排正确
- 锁定文件夹的卡片在控件层被拦截
- 清理：release 后幽灵销毁、指示线隐藏
"""
import os
import sys

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS_DIR))

import main  # noqa: E402

ok = True


def check(name, cond):
    global ok
    print(f"[{'OK ' if cond else 'FAIL'}] {name}")
    ok = ok and bool(cond)


class E:
    def __init__(self, x, y):
        self.x_root = int(x)
        self.y_root = int(y)


main.save_config = lambda cfg: None
app = main.App()
app.update()  # 需要真实几何坐标，不 withdraw

dnd = app.dnd

# 找两个未锁定且有卡片的文件夹。拖拽机制与锁定无关，而用户真实配置
# 里可能所有有卡片的分组都上了锁——就地解锁/展开来备好前置状态
# （save_config 已被打掉，不会写回用户配置）。
def _prepare(exclude=None):
    for f in app.folders:
        if f is exclude or not f.cards:
            continue
        if f.locked:
            f.set_locked(False)
        if f.collapsed:
            f.set_collapsed(False)
        return f
    return None


src = _prepare()
dst = _prepare(exclude=src)
assert src is not None and dst is not None, "需要两个有卡片的文件夹"
app.update()
card = src.cards[0]
cx = card.winfo_rootx() + 10
cy = card.winfo_rooty() + 10

# ---- 1. 阈值：小位移不激活 ----
dnd.card_start(card, E(cx, cy))
dnd.card_motion(card, E(cx + 3, cy + 3))
check("小位移不建幽灵", dnd._ghost is None and not dnd._active)
dnd.card_end(card, E(cx + 3, cy + 3))
check("未激活 release 不改数据", card in src.cards)

# ---- 2. 跨文件夹拖拽：motion 不动数据，release 落位 ----
order_before = list(src.cards)
dst_first = dst.cards[0] if dst.cards else None
tx = (dst_first.winfo_rootx() + 5) if dst_first else \
    (dst.body.winfo_rootx() + 20)
ty = (dst_first.winfo_rooty() + 5) if dst_first else \
    (dst.body.winfo_rooty() + 20)

dnd.card_start(card, E(cx, cy))
dnd.card_motion(card, E(cx + 30, cy + 30))
check("越过阈值建幽灵", dnd._ghost is not None and dnd._active)
dnd.card_motion(card, E(tx, ty))
check("motion 期间源文件夹顺序不变", list(src.cards) == order_before)
check("motion 期间目标未插入", card not in dst.cards)
check("指示线已放置", dnd._indicator is not None
      and bool(dnd._indicator.place_info()))
n_dst = len(dst.cards)
dnd.card_end(card, E(tx, ty))
app.update()
check("release 后卡片落入目标文件夹",
      card in dst.cards and card not in src.cards)
check("目标文件夹卡片数 +1", len(dst.cards) == n_dst + 1)
check("release 后落位下标 0", dst.cards.index(card) == 0)
check("幽灵已销毁", dnd._ghost is None)
check("指示线已隐藏", not dnd._indicator.place_info())
check("卡片可见（已 grid）", bool(card.grid_info()))

# ---- 3. 同文件夹重排（P7 语义修正：pos = 排除自身后的最终下标） ----
def drag_to(c, tx_, ty_):
    sx = c.winfo_rootx() + 10
    sy = c.winfo_rooty() + 10
    dnd.card_start(c, E(sx, sy))
    dnd.card_motion(c, E(sx + 30, sy + 30))
    dnd.card_motion(c, E(tx_, ty_))
    dnd.card_end(c, E(tx_, ty_))
    app.update()


# 先把测试卡移回源文件夹，保证存在一个 >=3 卡的未锁定文件夹
app.move_card_to_folder(card, src)
app.update()
f2 = next((f for f in app.folders
           if len(f.cards) >= 3 and not f.locked and not f.collapsed), None)
if f2 is not None:
    dst = f2
    card = dst.cards[0]
    # 3a. 拖到相邻下一位（旧实现因双重 -1 修正而原地不动的 bug 场景）
    nxt = dst.cards[1]
    drag_to(card, nxt.winfo_rootx() + nxt.winfo_width() - 5,
            nxt.winfo_rooty() + nxt.winfo_height() // 2)
    check("拖到相邻下一位生效", dst.cards.index(card) == 1)

    # 3b. 拖到末尾
    last = dst.cards[-1]
    drag_to(card, last.winfo_rootx() + last.winfo_width() - 5,
            last.winfo_rooty() + last.winfo_height() - 5)
    check("同文件夹拖至末尾", dst.cards.index(card) == len(dst.cards) - 1)

    # 3c. 停留原位：拖起后落回自己身上，顺序不变且卡片可见
    order_now = list(dst.cards)
    drag_to(card, card.winfo_rootx() + card.winfo_width() // 2,
            card.winfo_rooty() + card.winfo_height() // 2)
    check("落回原位顺序不变", list(dst.cards) == order_now)
    check("落回原位卡片可见", bool(card.grid_info()))

    # 3d. 拖回开头
    first = dst.cards[0]
    drag_to(card, first.winfo_rootx() + 3,
            first.winfo_rooty() + first.winfo_height() // 2)
    check("拖回开头", dst.cards.index(card) == 0)

# ---- 4. 锁定文件夹：控件层拦截 ----
locked_f = next((f for f in app.folders if f.locked and f.cards), None)
if locked_f is not None:
    lc = locked_f.cards[0]
    lc._on_drag_start(E(100, 100))
    check("锁定卡片 start 被拦截", dnd.card is not lc)

# ---- 5. 文件夹拖拽：release 才换序 ----
f0 = app.folders[0]
f1 = app.folders[1]
h0y = f0.header.winfo_rooty() + 3
h0x = f0.header.winfo_rootx() + 10
order0 = list(app.folders)
dnd.folder_start(f0, E(h0x, h0y))
target_y = f1.winfo_rooty() + f1.winfo_height() - 2
dnd.folder_motion(f0, E(h0x, target_y))
check("folder motion 期间顺序不变", list(app.folders) == order0)
dnd.folder_end(f0, E(h0x, target_y))
app.update()
check("folder release 后换序", app.folders[0] is f1
      and app.folders[1] is f0)

app.destroy()
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
