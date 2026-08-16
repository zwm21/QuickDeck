# -*- coding: utf-8 -*-
"""P5a 主题注册制冒烟：浅↔深切换后各类控件配色全部落地；
删除卡片后注册表自动剪除；重复切换无累积泄漏。"""
import os
import sys

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS_DIR))

import tkinter as tk  # noqa: E402
from tkinter import font as tkFont  # noqa: E402

import main  # noqa: E402
from quickdeck.constants import icon_font_size_for  # noqa: E402

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
    # P12/P15/P16：header 图标按钮——App 级共享字体（Segoe UI
    # Symbol），字号走 constants.icon_font_size_for 公式（N-2）
    icon_font = f._icon_font
    check(f"{tag}: 图标字体族", icon_font.actual("family") == "Segoe UI Symbol")
    check(f"{tag}: 图标字体字号",
          icon_font.actual("size")
          == icon_font_size_for(int(app.app_font.cget("size"))))
    check(f"{tag}: header 字体 App 级共享",
          f._icon_font is app.folder_icon_font
          and f._name_font is app.folder_name_font)
    for w, wl in ((f.drag_handle, "把手"), (f.lock_btn, "锁"),
                  (f.collapse_btn, "折叠"), (f.del_btn, "删除")):
        check(f"{tag}: {wl}按钮字体", w.cget("font") == icon_font.name)
    # P14：图标按钮高度不超过改前基准（同族字体 N-1 的探针按钮）
    probe = tk.Button(
        app, text="x", relief="flat", bd=0, pady=0,
        font=tkFont.Font(family=app.app_font.cget("family"),
                         size=max(8, int(app.app_font.cget("size")) - 1)))
    probe.update_idletasks()
    base_h = probe.winfo_reqheight()
    probe.destroy()
    check(f"{tag}: 按钮高度<=改前基准+2",
          all(w.winfo_reqheight() <= base_h + 2 for w in
              (f.lock_btn, f.collapse_btn, f.del_btn)))
    # P15：三按钮容器为正方形（读配置值，withdraw 窗口下成立），
    # 且边长不低于字体行高（防退化成 1px 假正方形）
    line_h = icon_font.metrics("linespace")
    check(f"{tag}: 三按钮容器正方形",
          all(h.cget("width") == h.cget("height") and int(h.cget("width")) > 0
              for h in (f.lock_holder, f.collapse_holder, f.del_holder)))
    check(f"{tag}: 正方形边长下界(>=字体行高)",
          all(int(h.cget("width")) >= line_h
              for h in (f.lock_holder, f.collapse_holder, f.del_holder)))
    # P13：三按钮常驻色块——底色随锁定态压平/恢复，断言按状态算期望
    flat = f.locked
    check(f"{tag}: 锁按钮 bg/fg",
          f.lock_btn.cget("bg")
          == (th["header_bg"] if flat else th["lock_bg"])
          and f.lock_btn.cget("fg") == th["lock_fg"]
          and f.lock_btn.cget("activebackground")
          == (th["header_active_bg"] if flat else th["lock_bg_active"])
          and f.lock_btn.cget("activeforeground") == th["lock_fg"])
    check(f"{tag}: 折叠按钮 bg/fg",
          f.collapse_btn.cget("bg")
          == (th["header_bg"] if flat else th["collapse_bg"])
          and f.collapse_btn.cget("fg")
          == (th["fg_secondary"] if flat else th["collapse_fg"])
          and f.collapse_btn.cget("activebackground")
          == (th["header_active_bg"] if flat
              else th["collapse_bg_active"])
          and f.collapse_btn.cget("activeforeground")
          == (th["fg_secondary"] if flat else th["collapse_fg"]))
    check(f"{tag}: 折叠按钮 ▼", f.collapse_btn.cget("text") == "\u25BC")
    del_bg_exp = th["header_bg"] if flat else th["danger_bg"]
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

# P13：锁定/折叠状态矩阵（在真实 folders[0] 上做，先存后恢复）
_f = app.folders[0]
_old_locked, _old_collapsed = _f.locked, _f.collapsed
try:
    _f.set_locked(True)
    app.update()
    check("锁定: 删除按钮 disabled",
          str(_f.del_btn.cget("state")) == "disabled")
    check("锁定: 三按钮全部压平灰底",
          _f.del_btn.cget("bg") == L["header_bg"]
          and _f.collapse_btn.cget("bg") == L["header_bg"]
          and _f.lock_btn.cget("bg") == L["header_bg"])
    check("锁定: 三按钮 active 档退中性",
          _f.collapse_btn.cget("activebackground")
          == L["header_active_bg"]
          and _f.lock_btn.cget("activebackground")
          == L["header_active_bg"])
    check("锁定: 折叠 fg 退次级灰",
          _f.collapse_btn.cget("fg") == L["fg_secondary"])
    check("锁定: 锁图标 🔒", _f.lock_btn.cget("text") == "\U0001F512")
    check("锁定: 名字 readonly",
          str(_f.name_entry.cget("state")) == "readonly")
    # 切深色：注册表刷新后钩子应保持压平，而非刷回语义色块
    app.apply_theme(D)
    app.update()
    check("切深色: 锁定三按钮仍压平",
          _f.del_btn.cget("bg") == D["header_bg"]
          and _f.collapse_btn.cget("bg") == D["header_bg"]
          and _f.lock_btn.cget("bg") == D["header_bg"])
    check("切深色: 删除按钮 fg 常驻红",
          _f.del_btn.cget("fg") == D["danger_fg"])
    _f.set_locked(False)
    app.update()
    check("解锁: 三按钮恢复语义色块",
          _f.del_btn.cget("bg") == D["danger_bg"]
          and _f.collapse_btn.cget("bg") == D["collapse_bg"]
          and _f.lock_btn.cget("bg") == D["lock_bg"])
    check("解锁: 折叠 fg 回绿",
          _f.collapse_btn.cget("fg") == D["collapse_fg"])
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

# P16：字号跟随——运行时走真实路径（字号控件 -> _apply_font_now），
# 正方形边长必须立即跟到新字体度量（审查期 bug：旧实现读到过期值，
# holder 27px 装不下 50px 按钮需求，字形被裁）
_ff = app.folders[0]
_old_sz = int(app.app_font.cget("size"))
_new_sz = 29 if _old_sz < 21 else 11  # 拉开差距，确保边长必然变化
_side_before = int(_ff.lock_holder.cget("height"))
app.font_size_var.set(str(_new_sz))
app._apply_font_now()
app.update_idletasks()
check("字号跟随: 边长已变化", int(_ff.lock_holder.cget("height")) != _side_before)
check("字号跟随: 边长==按钮自然高度(无裁切)",
      all(int(h.cget("height")) == b.winfo_reqheight()
          for h, b in ((_ff.lock_holder, _ff.lock_btn),
                       (_ff.collapse_holder, _ff.collapse_btn),
                       (_ff.del_holder, _ff.del_btn))))
check("字号跟随: 共享图标字体已单点更新",
      app.folder_icon_font.actual("size") == icon_font_size_for(_new_sz))
app.font_size_var.set(str(_old_sz))
app._apply_font_now()
app.update_idletasks()

# P16：hover 动态 token 解析——_resolve 单测 + 离屏可见窗口 E2E
#（withdraw 下 event_generate 实测不派发；离屏 deiconify 可派发）
from quickdeck.ui.widgets.hover import _resolve  # noqa: E402
check("hover._resolve 字符串直通", _resolve("fg") == "fg")
check("hover._resolve 回调求值", _resolve(lambda: "card_bg") == "card_bg")

_th = app.theme
app.geometry("+-32000+-32000")  # 先挪离屏再显示，避免窗口闪现
app.deiconify()
app.update()
_hf = app.folders[0]
_old_lock = _hf.locked
try:
    _hf.set_locked(False)
    app.update()
    _hf.del_btn.event_generate("<Enter>")
    app.update()
    check("hover E2E: 解锁 Enter->红系 hover 底",
          _hf.del_btn.cget("bg") == _th["danger_hover_bg"])
    # 悬停中锁定：Leave 应恢复"当前锁定态"灰底而非语义色块（P13 回归点）
    _hf.set_locked(True)
    app.update()
    _hf.del_btn.event_generate("<Leave>")
    app.update()
    check("hover E2E: 锁定后 Leave 仍灰底",
          _hf.del_btn.cget("bg") == _th["header_bg"])
    # disabled 守卫：禁用按钮 Enter 不做任何 hover 反馈
    _hf.del_btn.event_generate("<Enter>")
    app.update()
    check("hover E2E: disabled Enter 无反馈",
          _hf.del_btn.cget("bg") == _th["header_bg"])
finally:
    _hf.set_locked(_old_lock)
    app.withdraw()
    app.update()

app.destroy()
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
