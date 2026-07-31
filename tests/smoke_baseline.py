# -*- coding: utf-8 -*-
"""P0 基线冒烟测试。

- 不写用户 config.json（monkeypatch save_config 为捕获模式）
- 断言：文件夹/卡片数量与 config 一致；save_state 往返幂等
- 产出：tests/baseline_config_snapshot.json（save_state 输出快照，
  供后续重构阶段逐字段比对）
"""
import json
import os
import sys

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, REPO_DIR)

import main  # noqa: E402


def expected_routing(cfg):
    """按 _add_card 的路由规则推算三个存储区的期望卡片数。
    路由优先级：目录 → dir 区；.url → web 区；其余 → 文件夹区。
    去重按规范化绝对路径（跨区判重）。"""
    seen = set()
    folder_n = web_n = dir_n = 0

    def norm(p):
        return os.path.normcase(os.path.normpath(os.path.abspath(p)))

    for item in cfg.get("shortcuts", []):
        p = item["path"]
        k = norm(p)
        if k in seen:
            continue
        seen.add(k)
        if os.path.isdir(p):
            dir_n += 1
        elif p.lower().endswith(".url"):
            web_n += 1
        else:
            folder_n += 1
    for item in cfg.get("web_shortcuts", []):
        k = norm(item["path"])
        if k in seen:
            continue
        seen.add(k)
        web_n += 1
    for item in cfg.get("dir_shortcuts", []):
        k = norm(item["path"])
        if k in seen:
            continue
        seen.add(k)
        dir_n += 1
    return folder_n, web_n, dir_n


def main_test():
    # 捕获而非写盘
    captured = []
    main.save_config = lambda cfg: captured.append(
        json.loads(json.dumps(cfg, ensure_ascii=False)))

    cfg_on_disk = main.load_config()
    exp_folder_cards, exp_web, exp_dir = expected_routing(cfg_on_disk)
    exp_folders = len(cfg_on_disk.get("folders", [])) or 1

    app = main.App()
    app.withdraw()
    app.update()

    ok = True

    def check(name, actual, expect):
        nonlocal ok
        status = "OK " if actual == expect else "FAIL"
        if actual != expect:
            ok = False
        print(f"[{status}] {name}: actual={actual} expect={expect}")

    check("folders 数量", len(app.folders), exp_folders)
    check("文件夹区卡片数",
          sum(len(f.cards) for f in app.folders), exp_folder_cards)
    check("网页区卡片数", len(app.web_cards), exp_web)
    check("目录区卡片数", len(app.dir_cards), exp_dir)

    # 往返幂等：连续两次 save_state 输出一致
    app.save_state()
    app.save_state()
    check("save_state 捕获次数>=2", len(captured) >= 2, True)
    a, b = captured[-2], captured[-1]
    check("save_state 幂等", a == b, True)

    # 快照落盘（这是测试自己的产物，不是用户配置）
    snap_path = os.path.join(TESTS_DIR, "baseline_config_snapshot.json")
    with open(snap_path, "w", encoding="utf-8") as f:
        json.dump(b, f, ensure_ascii=False, indent=2)
    print(f"[OK ] 快照已写入 {snap_path}")

    # 信息性对比：save 输出 vs 磁盘配置（路由迁移等会造成差异，仅报告）
    for key in ("folders", "shortcuts", "web_shortcuts", "dir_shortcuts"):
        da, db = cfg_on_disk.get(key), b.get(key)
        if da != db:
            print(f"[INFO] save 输出与磁盘配置在 '{key}' 存在差异 "
                  f"(磁盘 {len(da) if isinstance(da, list) else '?'} 项 / "
                  f"输出 {len(db) if isinstance(db, list) else '?'} 项)")

    app.destroy()
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main_test())
