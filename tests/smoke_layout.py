# -*- coding: utf-8 -*-
"""P6 布局/滚动冒烟：
- compute_cols 纯函数边界
- 布局未变时重复 _reflow 零 grid 调用（增量短路）
- 视图切换往返后卡片全部可见（短路失效接线回归）
- mousewheel 不再因 folders 为空而早退
"""
import os
import sys

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS_DIR))

from quickdeck.ui.layout import compute_cols  # noqa: E402

ok = True


def check(name, cond):
    global ok
    print(f"[{'OK ' if cond else 'FAIL'}] {name}")
    ok = ok and bool(cond)


# ---- 1. compute_cols 边界 ----
check("恰好一列", compute_cols(510, 500) == 1)
check("差 1px 不到两列", compute_cols(1019, 500) == 1)
check("恰好两列", compute_cols(1020, 500) == 2)
check("宽度 0 至少一列", compute_cols(0, 500) == 1)
check("负宽至少一列", compute_cols(-100, 500) == 1)
check("窄卡多列", compute_cols(700, 200) == 3)
check("卡宽 0 防御", compute_cols(500, 0) >= 1)
check("大窗口", compute_cols(2400, 357) == 6)

# ---- 2. 有 GUI 的部分 ----
import main  # noqa: E402

main.save_config = lambda cfg: None
app = main.App()
app.withdraw()
app.update()

from quickdeck.ui.widgets.card import ShortcutCard  # noqa: E402

grid_calls = [0]
_orig_grid = ShortcutCard.grid


def counting_grid(self, *a, **kw):
    grid_calls[0] += 1
    return _orig_grid(self, *a, **kw)


ShortcutCard.grid = counting_grid

f = app.folders[0]
f._reflow()
app.update()
grid_calls[0] = 0
for _ in range(20):
    f._reflow()
check("布局未变 20 次 reflow 零 grid 调用", grid_calls[0] == 0)

# 卡片集合变化后恢复重排
c = f.cards[-1]
f.remove_card(c)
f.add_card(c)
check("集合变化后重新 grid", grid_calls[0] > 0)

# ---- 3. 视图切换往返：卡片全部可见 ----
def set_view(mode):
    label = {v: k for k, v in app._VIEW_MODE_BY_LABEL.items()}[mode]
    app.view_mode_var.set(label)
    app._on_view_mode_change()
    app.update()


for seq in ("usage", "cards", "web", "cards", "dirs", "cards"):
    set_view(seq)
all_visible = all(
    bool(c.grid_info()) for fd in app.folders for c in fd.cards)
check("视图往返后文件夹卡片全部在 grid", all_visible)
in_body = all(
    str(c.grid_info().get("in")) == str(fd.body)
    for fd in app.folders for c in fd.cards)
check("卡片落在各自 folder.body 内", in_body)

# ---- 4. mousewheel：folders 为空也走滚动判断 ----
scrolls = []
app.canvas.yview_scroll = lambda *a: scrolls.append(a)
app.canvas.yview = lambda: (0.2, 0.8)  # 伪造可滚状态


class E:
    delta = -120
    x_root = app.canvas.winfo_rootx() + 10
    y_root = app.canvas.winfo_rooty() + 10


saved_folders = app.folders
app.folders = []
app._on_mousewheel(E())
app.folders = saved_folders
check("无文件夹时滚轮仍生效", len(scrolls) == 1)

ShortcutCard.grid = _orig_grid
app.destroy()
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
