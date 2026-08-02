# -*- coding: utf-8 -*-
"""P5a 主题注册制冒烟：浅↔深切换后各类控件配色全部落地；
删除卡片后注册表自动剪除；重复切换无累积泄漏。"""
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


main.save_config = lambda cfg: None
app = main.App()
app.withdraw()
app.update()

L, D = main.LIGHT_THEME, main.DARK_THEME


def assert_theme(th, tag):
    card = app.folders[0].cards[0]
    f = app.folders[0]
    check(f"{tag}: root bg", app.cget("bg") == th["app_bg"])
    check(f"{tag}: card bg", card.cget("bg") == th["card_bg"])
    check(f"{tag}: card title fg",
          card.title_label.cget("fg") == th["fg"])
    check(f"{tag}: desc entry bg",
          card.desc_entry.cget("bg") == th["desc_bg"])
    check(f"{tag}: folder bg", f.cget("bg") == th["folder_bg"])
    check(f"{tag}: header bg", f.header.cget("bg") == th["header_bg"])
    check(f"{tag}: 工具栏按钮 bg", app.add_btn.cget("bg") == th["btn_bg"])
    # P8 起删除按钮常态用次级色，hover 才显危险色
    check(f"{tag}: 删除按钮 fg",
          card.del_btn.cget("fg") == th["fg_secondary"])
    check(f"{tag}: 卡片描边 border",
          card.cget("highlightbackground") == th["border"])


app.theme_mode = "dark"
app.apply_theme(D)
app.update()
assert_theme(D, "dark")

app.theme_mode = "light"
app.apply_theme(L)
app.update()
assert_theme(L, "light")

# 注册表剪除：删掉一张卡片再切主题，注册数应减少且不报错
n_before = app.tm.count()
victim = None
for f in app.folders:
    if not f.locked and f.cards:
        victim = f.cards[-1]
        break
if victim is not None:
    app.remove_card(victim)
    app.update()
    app.apply_theme(D)
    app.update()
    n_after = app.tm.count()
    check("删卡后注册表剪除", n_after < n_before)
    app.apply_theme(L)
    app.update()
    check("再次切换注册数稳定", app.tm.count() == n_after)

app.destroy()
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
