# -*- coding: utf-8 -*-
"""P3 配置层冒烟：
- 真实 config.json 经新 sanitize 后与旧行为等价（往返加载稳定）
- ConfigStore 原子写 / bak 轮转 / 损坏隔离恢复链路（在临时目录）
- 伴生路径随 active_file 动态派生（修旧版陈旧全局 bug）
- 深嵌套 JSON 不触发 RecursionError；类型错乱配置可排序可加载
"""
import json
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(TESTS_DIR)
sys.path.insert(0, REPO)

from quickdeck.config.schema import (  # noqa: E402
    sanitize_config, merge_dict, default_config, DEFAULT_CONFIG)
from quickdeck.config.store import ConfigStore  # noqa: E402
import copy  # noqa: E402

ok = True


def check(name, cond):
    global ok
    print(f"[{'OK ' if cond else 'FAIL'}] {name}")
    ok = ok and bool(cond)


# ---- 1. 真实配置 sanitize 幂等 ----
real = json.load(open(os.path.join(REPO, "config.json"), encoding="utf-8"))
merged = merge_dict(copy.deepcopy(DEFAULT_CONFIG), copy.deepcopy(real))
s1 = sanitize_config(copy.deepcopy(merged))
s2 = sanitize_config(copy.deepcopy(s1))
check("真实配置 sanitize 幂等", s1 == s2)
check("真实配置卡片无丢失",
      len(s1["shortcuts"]) == len(real["shortcuts"]))

# ---- 2. 深嵌套不炸栈 ----
deep = {}
cur = deep
for _ in range(2000):
    cur["x"] = {}
    cur = cur["x"]
try:
    merge_dict(copy.deepcopy(DEFAULT_CONFIG), deep)
    check("2000 层嵌套无 RecursionError", True)
except RecursionError:
    check("2000 层嵌套无 RecursionError", False)

# ---- 3. 类型错乱可救 ----
bad = {"window": "nope", "font": {"size": "abc"}, "card_width": 99999,
       "theme_mode": 42, "folders": [1, {"id": 7, "name": ""}],
       "shortcuts": [{"path": 1}, {"path": "C:/x.exe", "order": "z"}],
       "web_shortcuts": "x", "dir_shortcuts": None}
sb = sanitize_config(merge_dict(copy.deepcopy(DEFAULT_CONFIG), bad))
check("window 回默认", sb["window"]["width"] == 900)
check("card_width clamp 1200", sb["card_width"] == 1200)
check("theme_mode 回 system", sb["theme_mode"] == "system")
check("非法 shortcut 丢弃", len(sb["shortcuts"]) == 1)
check("shortcuts 可排序", sorted(
    sb["shortcuts"], key=lambda s: s["order"]) is not None)

# ---- 4. ConfigStore 读写链路（临时目录） ----
with tempfile.TemporaryDirectory() as td:
    portable = os.path.join(td, "portable", "config.json")
    appdata = os.path.join(td, "appdata", "config.json")
    os.makedirs(os.path.dirname(portable))

    st = ConfigStore(portable, appdata)
    check("portable 目录可写时选 portable",
          os.path.normcase(st.active_file) == os.path.normcase(portable))

    cfg = default_config()
    cfg["card_width"] = 333
    st.save(cfg)
    check("save 后主文件存在", os.path.exists(portable))
    st.save(cfg)
    check("二次 save 后 .bak 轮转", os.path.exists(st.bak_file))

    loaded, notices = st.load()
    check("load 回读 card_width", loaded["card_width"] == 333 and
          notices == [])

    # 损坏主文件 → bak 恢复 + corrupt 隔离
    open(portable, "w").write("{broken json")
    loaded2, notices2 = st.load()
    check("损坏后经 .bak 恢复", loaded2 is not None and
          loaded2["card_width"] == 333)
    check("产生 restored_from_bak 通知",
          any(n["kind"] == "restored_from_bak" for n in notices2))
    check("坏文件隔离为 .corrupt", os.path.exists(st.corrupt_file))

    # 主文件与 bak 都坏 → unrecoverable
    open(portable, "w").write("{broken")
    open(st.bak_file, "w").write("{also broken")
    loaded3, notices3 = st.load()
    check("双坏返回 None + unrecoverable",
          loaded3 is None and
          any(n["kind"] == "unrecoverable" for n in notices3))

    # 伴生路径动态派生
    st.active_file = appdata
    check("bak 路径随 active 切换",
          st.bak_file == appdata + ".bak")

print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
