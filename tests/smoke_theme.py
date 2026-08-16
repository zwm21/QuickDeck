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
    # P8b 起卡片本体为容器底色，卡面由圆角底图绘制
    check(f"{tag}: card 外底色", card.cget("bg") == th["folder_bg"])
    check(f"{tag}: 圆角底图配色",
          card._surface_state is not None
          and card._surface_state[2] == th["card_bg"]
          and card._surface_state[3] == th["border_strong"])
    check(f"{tag}: card title fg",
          card.title_label.cget("fg") == th["fg"])
    check(f"{tag}: 描述轨道 bg",
          card.desc_rail.cget("bg") == th["border_strong"])
    check(f"{tag}: 描述标记 bg",
          card._desc_mark.cget("bg") == th["accent"])
    check(f"{tag}: folder bg", f.cget("bg") == th["folder_bg"])
    check(f"{tag}: header bg", f.header.cget("bg") == th["header_bg"])
    check(f"{tag}: 工具栏按钮 bg", app.add_btn.cget("bg") == th["btn_bg"])
    check(f"{tag}: 底部分隔条 bg",
          app.bottom_sep.cget("bg") == th["border"])
    # P12：header 图标按钮——字体统一 Segoe UI Symbol / 应用字号
    icon_font = f._icon_font
    check(f"{tag}: 图标字体族", icon_font.actual("family") == "Segoe UI Symbol")
    check(f"{tag}: 图标字体字号",
          icon_font.actual("size")
          == max(8, int(app.app_font.cget("size"))))
    for w, wl in ((f.drag_handle, "把手"), (f.lock_btn, "锁"),
                  (f.collapse_btn, "折叠"), (f.del_btn, "删除")):
        check(f"{tag}: {wl}按钮字体", w.cget("font") == icon_font.name)
    # P12：三按钮常驻色块
    check(f"{tag}: 锁按钮 bg/fg", f.lock_btn.cget("bg") == th["lock_bg"]
          and f.lock_btn.cget("fg") == th["lock_fg"]
          and f.lock_btn.cget("activebackground") == th["lock_bg_active"]
          and f.lock_btn.cget("activeforeground") == th["lock_fg"])
    check(f"{tag}: 折叠按钮 bg/fg", f.collapse_btn.cget("bg") == th["accent_bg"]
          and f.collapse_btn.cget("fg") == th["accent"]
          and f.collapse_btn.cget("activebackground")
          == th["accent_bg_active"]
          and f.collapse_btn.cget("activeforeground")
          == th["accent_hover"])
    check(f"{tag}: 折叠按钮 ▼", f.collapse_btn.cget("text") == "\u25BC")
    # 删除按钮底色随锁定态：锁定灰底 / 解锁浅红底
    del_bg_exp = th["header_bg"] if f.locked else th["danger_bg"]
    check(f"{tag}: 删除按钮 bg/fg", f.del_btn.cget("bg") == del_bg_exp
          and f.del_btn.cget("fg") == th["danger_fg"]
          and f.del_btn.cget("activeforeground") == th["danger_fg"]
          and f.del_btn.cget("disabledforeground") == th["danger_fg_muted"])


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

# P12：锁定/折叠状态视觉（在真实 folders[0] 上做，先存后恢复）
_f = app.folders[0]
_old_locked, _old_collapsed = _f.locked, _f.collapsed
try:
    _f.set_locked(True)
    app.update()
    check("锁定: 删除按钮 disabled",
          str(_f.del_btn.cget("state")) == "disabled")
    check("锁定: 删除按钮灰底", _f.del_btn.cget("bg") == L["header_bg"])
    check("锁定: 锁图标 🔒", _f.lock_btn.cget("text") == "\U0001F512")
    check("锁定: 名字 readonly",
          str(_f.name_entry.cget("state")) == "readonly")
    # 切深色：注册表刷新后钩子应保持灰底，而非刷回常驻红底
    app.apply_theme(D)
    app.update()
    check("切深色: 锁定删除按钮仍灰底",
          _f.del_btn.cget("bg") == D["header_bg"])
    check("切深色: 删除按钮 fg 常驻红",
          _f.del_btn.cget("fg") == D["danger_fg"])
    _f.set_locked(False)
    app.update()
    check("解锁: 删除按钮恢复红底",
          _f.del_btn.cget("bg") == D["danger_bg"])
    check("解锁: 锁图标 🔓", _f.lock_btn.cget("text") == "\U0001F513")
    _f.set_collapsed(True)
    app.update()
    check("折叠: ▶", _f.collapse_btn.cget("text") == "\u25B6")
    _f.set_collapsed(False)
    app.update()
    check("展开: ▼", _f.collapse_btn.cget("text") == "\u25BC")
    app.apply_theme(L)  # 回浅色，不向后残留
    app.update()
finally:
    _f.set_locked(_old_locked)
    _f.set_collapsed(_old_collapsed)

app.destroy()
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
