# -*- coding: utf-8 -*-
"""P4 数据层冒烟：
- 卡片/文件夹业务字段的唯一真源是数据类（property 转发一致性）
- 各类变更（重命名/描述/启动计数/移动/删除/锁定/折叠）落入模型
- save_state 输出由模型 to_record 生成且与磁盘 config 数据键等价
- mark_dirty 400ms 防抖：连发变更合并为一次写盘
"""
import json
import os
import sys
import copy

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(TESTS_DIR)
sys.path.insert(0, REPO)

import main  # noqa: E402
from quickdeck.model.workspace import Shortcut, Folder  # noqa: E402

ok = True


def check(name, cond):
    global ok
    print(f"[{'OK ' if cond else 'FAIL'}] {name}")
    ok = ok and bool(cond)


saves = []
main.save_config = lambda cfg: saves.append(copy.deepcopy(cfg))

app = main.App()
app.withdraw()
app.update()

# ---- 1. 数据键与磁盘配置等价（加载→序列化 round-trip） ----
app.save_state()
disk = json.load(open(os.path.join(REPO, "config.json"), encoding="utf-8"))
out = saves[-1]
for key in ("folders", "shortcuts", "web_shortcuts", "dir_shortcuts"):
    check(f"round-trip '{key}' 与磁盘等价", out[key] == disk[key])

# ---- 2. property 转发一致性 ----
card = app.folders[0].cards[0]
check("card.path 来自 item", card.path == card.item.path)
card.custom_title = "改名测试"
check("custom_title 写入 item", card.item.title == "改名测试")
card.custom_title = ""
card.launch_count += 1
check("launch_count 写入 item", card.item.launch_count >= 1)
f0 = app.folders[0]
old_locked = f0.locked
f0.set_locked(True)
check("set_locked 写入 meta", f0.meta.locked is True)
f0.set_locked(old_locked)
f0.set_collapsed(True)
check("set_collapsed 写入 meta", f0.meta.collapsed is True)
f0.set_collapsed(False)

# ---- 3. 描述编辑经 desc_var 同步进模型 ----
card.desc_var.set("新描述xyz")
card._sync_desc()
check("desc 同步进 item", card.item.description == "新描述xyz")

# ---- 4. save 输出反映模型变更 ----
card.item.description = "desc2"
card.desc_var.set("desc2")
app.save_state()
rec = saves[-1]["shortcuts"][0]
check("save 输出含模型变更", rec["description"] == "desc2"
      and rec["launch_count"] >= 1)

# ---- 5. mark_dirty 防抖合并 ----
import time


def pump(seconds):
    t0 = time.time()
    while time.time() - t0 < seconds:
        app.update()
        time.sleep(0.02)


pump(0.8)  # 排空窗口 Configure 等遗留定时器，避免干扰计数
n0 = len(saves)
for _ in range(10):
    app.mark_dirty()
check("mark_dirty 不立即写盘", len(saves) == n0)
pump(0.7)
check("防抖后恰写盘 1 次", len(saves) == n0 + 1)

# ---- 6. 卡片移动/删除后顺序与 UI 一致 ----
if len(app.folders) >= 2 and app.folders[1].cards:
    c = app.folders[1].cards[0]
    target = app.folders[0]
    if not target.locked and not app.folders[1].locked:
        app.move_card_to_folder(c, target)
        app.save_state()
        recs = [r for r in saves[-1]["shortcuts"]
                if r["folder"] == target.id]
        check("移动后落目标文件夹末尾",
              recs[-1]["path"] == c.item.path)

app.destroy()
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
