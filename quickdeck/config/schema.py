# -*- coding: utf-8 -*-
"""配置结构：默认值、递归合并、逐字段校验。

sanitize_config 从 main.py 的 159 行大函数拆分为按字段的小函数，
行为与旧实现严格等价（tests/smoke_baseline.py 快照比对保障）。
本模块不弹窗、不退出——异常情况通过返回值交由 UI 层决定。
"""
import copy
import uuid

from quickdeck.constants import BUILTIN_FONT_FAMILY

DEFAULT_CONFIG = {
    "window": {"width": 900, "height": 650, "x": 200, "y": 100},
    "font": {"family": BUILTIN_FONT_FAMILY, "size": 12},
    "card_width": 320,
    "theme_mode": "system",  # "system" | "light" | "dark"
    "shortcuts": [],
    # 网页快捷方式独立存储区（.url 不进文件夹，在"网页快捷方式"视图中管理）
    "web_shortcuts": [],
    # 文件夹快捷方式独立存储区（目录路径不进文件夹分组，
    # 在"文件夹快捷方式"视图中管理，双击在资源管理器中打开）
    "dir_shortcuts": []
}

# merge_dict 允许的最大递归深度：正常配置最多 3-4 层嵌套，
# 32 层已远超合理值；超过即视为恶意构造或损坏，停止递归以防栈溢出。
MERGE_MAX_DEPTH = 32

CARD_WIDTH_MIN, CARD_WIDTH_MAX = 200, 1200
FONT_SIZE_MIN, FONT_SIZE_MAX = 8, 36


def merge_dict(base, override, depth=0):
    """把 override 的字段递归合并到 base，保证 base 拥有完整结构。"""
    if depth >= MERGE_MAX_DEPTH or not isinstance(override, dict):
        return override if isinstance(override, dict) else base
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = merge_dict(base[k], v, depth + 1)
        else:
            base[k] = v
    return base


def _int_or(default, val, lo=None, hi=None):
    try:
        v = int(val)
    except (TypeError, ValueError):
        return default
    if lo is not None and v < lo:
        v = lo
    if hi is not None and v > hi:
        v = hi
    return v


def _san_window(cfg):
    default_w = DEFAULT_CONFIG["window"]
    w = cfg.get("window")
    if not isinstance(w, dict):
        w = {}
    cfg["window"] = {
        "width": _int_or(default_w["width"], w.get("width"),
                         lo=100, hi=20000),
        "height": _int_or(default_w["height"], w.get("height"),
                          lo=100, hi=20000),
        # x/y 允许负值（多显示器左侧屏）；越界最终在 App.__init__
        # 里按当前屏幕再兜底一次
        "x": _int_or(default_w["x"], w.get("x"), lo=-20000, hi=20000),
        "y": _int_or(default_w["y"], w.get("y"), lo=-20000, hi=20000),
    }


def _san_font(cfg):
    default_f = DEFAULT_CONFIG["font"]
    f = cfg.get("font")
    if not isinstance(f, dict):
        f = {}
    fam = f.get("family")
    if not isinstance(fam, str) or not fam.strip():
        fam = default_f["family"]
    cfg["font"] = {
        "family": fam,
        "size": _int_or(default_f["size"], f.get("size"),
                        lo=FONT_SIZE_MIN, hi=FONT_SIZE_MAX),
    }


def _san_scalars(cfg):
    cfg["card_width"] = _int_or(
        DEFAULT_CONFIG["card_width"], cfg.get("card_width"),
        lo=CARD_WIDTH_MIN, hi=CARD_WIDTH_MAX)
    tm = cfg.get("theme_mode")
    if tm not in ("system", "light", "dark"):
        tm = "system"
    cfg["theme_mode"] = tm


def _san_folders(cfg):
    raw_folders = cfg.get("folders")
    clean_folders = []
    if isinstance(raw_folders, list):
        for i, fd in enumerate(raw_folders):
            if not isinstance(fd, dict):
                continue
            fid = fd.get("id")
            if not isinstance(fid, str) or not fid.strip():
                fid = "f_" + uuid.uuid4().hex[:8]
            name = fd.get("name")
            if not isinstance(name, str) or not name.strip():
                name = "未命名"
            clean_folders.append({
                "id": fid, "name": name,
                "order": _int_or(i, fd.get("order"), lo=-10**9, hi=10**9),
                "locked": bool(fd.get("locked")),
                "collapsed": bool(fd.get("collapsed")),
            })
    # 允许为空，加载层会兜底建默认文件夹
    cfg["folders"] = clean_folders


def _san_item(it, i, with_folder):
    """校验单条快捷方式记录；非法（path 缺失）返回 None。"""
    if not isinstance(it, dict):
        return None
    p = it.get("path")
    if not isinstance(p, str) or not p:
        return None
    desc = it.get("description", "")
    if not isinstance(desc, str):
        desc = ""
    title = it.get("title", "")
    if not isinstance(title, str):
        title = ""
    icon = it.get("icon", "")
    if not isinstance(icon, str):
        icon = ""
    try:
        ts = float(it.get("last_launch_ts", 0.0))
    except (TypeError, ValueError):
        ts = 0.0
    if ts < 0:
        ts = 0.0
    out = {
        "path": p, "description": desc,
        "order": _int_or(i, it.get("order"), lo=-10**9, hi=10**9),
        "title": title, "icon": icon,
        "launch_count": _int_or(0, it.get("launch_count"), lo=0, hi=10**9),
        "last_launch_ts": ts,
    }
    if with_folder:
        fid = it.get("folder")
        if not isinstance(fid, str) or not fid:
            fid = ""
        out["folder"] = fid
    return out


def _san_shortcut_areas(cfg):
    raw_items = cfg.get("shortcuts")
    clean_items = []
    if isinstance(raw_items, list):
        for i, it in enumerate(raw_items):
            rec = _san_item(it, i, with_folder=True)
            if rec is not None:
                clean_items.append(rec)
    cfg["shortcuts"] = clean_items

    for area_key in ("web_shortcuts", "dir_shortcuts"):
        raw_area = cfg.get(area_key)
        clean_area = []
        if isinstance(raw_area, list):
            for i, it in enumerate(raw_area):
                rec = _san_item(it, i, with_folder=False)
                if rec is not None:
                    clean_area.append(rec)
        cfg[area_key] = clean_area


def sanitize_config(cfg):
    """加载后逐字段做类型/范围校验，非法值就地回落到默认，返回 cfg 本身。

    merge_dict 后所有字段仍可能被用户手改成任意类型，这里统一约束到
    GUI 期望的形态，避免加载/排序时 raise 导致启动失败或卡片丢失。
    """
    if not isinstance(cfg, dict):
        return copy.deepcopy(DEFAULT_CONFIG)
    _san_window(cfg)
    _san_font(cfg)
    _san_scalars(cfg)
    _san_folders(cfg)
    _san_shortcut_areas(cfg)
    return cfg


def default_config():
    """返回一份经过 sanitize 的默认配置深拷贝。"""
    return sanitize_config(copy.deepcopy(DEFAULT_CONFIG))
