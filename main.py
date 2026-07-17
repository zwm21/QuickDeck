# -*- coding: utf-8 -*-
"""
QuickDeck —— Windows 桌面快捷方式管理器
------------------------------------------------
- 通过图形界面管理 .lnk / .exe 快捷方式
- 支持拖拽排序、字体全局调整、窗口大小/位置记忆
- 依赖：tkinter（标准库）+ pywin32 + Pillow
"""

import os
import sys
import json
import copy
import time
import uuid
import queue
import ctypes
import hashlib
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, font as tkFont, filedialog, messagebox, simpledialog

# ---- 可选依赖：tkinterdnd2（文件拖放进窗口） --------------------
# 缺失时程序正常运行，只是没有"从资源管理器拖文件进来"的能力。
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    HAS_DND = True
except ImportError:
    HAS_DND = False

# ---- 可选依赖：pywin32 + Pillow ----------------------------------
# 若缺失，程序仍能启动，但会禁用图标提取与添加功能，并弹窗提示。
try:
    import win32com.client
    import win32gui
    import win32ui
    import win32con
    from PIL import Image, ImageTk, ImageDraw
    HAS_WIN32 = True
    _IMPORT_ERR = ""
except ImportError as e:  # pragma: no cover
    HAS_WIN32 = False
    _IMPORT_ERR = str(e)


# ================================================================
# 常量与默认配置
# ================================================================
# APP_DIR：可写目录（放 config.json）
#   - 直接运行脚本：脚本所在目录
#   - PyInstaller 打包：exe 所在目录（不是 _MEIPASS 临时目录）
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))


def _resource_path(name):
    """
    只读资源的路径（如内置字体）。
    - 打包后：从 PyInstaller 解压目录 `_MEIPASS` 找
    - 开发时：从脚本所在目录找
    """
    base = getattr(sys, "_MEIPASS", None) \
        or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, name)


CONFIG_FILE = os.path.join(APP_DIR, "config.json")

# APPDATA 兜底目录（exe 目录写不进时用，如装在 Program Files 的场景）
APPDATA_DIR = os.path.join(
    os.environ.get("APPDATA") or os.path.expanduser("~"), "QuickDeck"
)
APPDATA_CONFIG_FILE = os.path.join(APPDATA_DIR, "config.json")


def _dir_writable(d):
    """探测目录是否真的可写（Program Files 下 os.access 不可靠）。"""
    try:
        probe = os.path.join(d, ".qd_write_test")
        with open(probe, "w") as f:
            f.write("x")
        os.remove(probe)
        return True
    except OSError:
        return False


def _select_config_file():
    """Portable 优先：exe 目录存在 config.json 或目录可写 → 用 exe 目录；
    否则降级到 %APPDATA%/QuickDeck/config.json。"""
    # 两处都存在时优先 exe 目录（Portable 语义）
    if os.path.exists(CONFIG_FILE):
        return CONFIG_FILE
    if os.path.exists(APPDATA_CONFIG_FILE):
        # exe 目录没有配置但 APPDATA 有 → 曾经降级过，继续用 APPDATA
        return APPDATA_CONFIG_FILE
    # 都不存在：首次运行，按可写性决定落点
    if _dir_writable(APP_DIR):
        return CONFIG_FILE
    try:
        os.makedirs(APPDATA_DIR, exist_ok=True)
    except OSError:
        pass
    return APPDATA_CONFIG_FILE


# ACTIVE_CONFIG_FILE 是本次运行实际使用的配置路径；save_config 写失败时
# 会自动切到 APPDATA 再试一次并更新它
ACTIVE_CONFIG_FILE = _select_config_file()
LOCAL_FONT_FILE = _resource_path("HYWenHei-65W.ttf")

# 内置字体家族名（TTF 文件内 name table 记录的家族名，
# 通常与去掉扩展名的文件名一致）
BUILTIN_FONT_FAMILY = "HYWenHei-65W"

ICON_SIZE = 32  # 卡片上显示的图标像素尺寸

DEFAULT_CONFIG = {
    "window": {"width": 900, "height": 650, "x": 200, "y": 100},
    "font": {"family": BUILTIN_FONT_FAMILY, "size": 12},
    "card_width": 500,
    "theme_mode": "system",  # "system" | "light" | "dark"
    "shortcuts": [],
    # 网页快捷方式独立存储区（.url 不进文件夹，在"网页快捷方式"视图中管理）
    "web_shortcuts": [],
    # 文件夹快捷方式独立存储区（目录路径不进文件夹分组，
    # 在"文件夹快捷方式"视图中管理，双击在资源管理器中打开）
    "dir_shortcuts": []
}


# ================================================================
# 主题（浅色 / 深色）
# ================================================================
LIGHT_THEME = {
    "name": "light",
    "app_bg": "#F0F0F0",           # 主窗口 / 滚动区背景
    "panel_bg": "#F8F9FA",         # 底部字体设置卡片
    "card_bg": "#FFFFFF",          # 快捷方式卡片
    "desc_bg": "#F4F4F4",          # 描述输入框
    "folder_bg": "#F5F5F5",        # 文件夹框体 / body
    "header_bg": "#E0E0E0",        # 文件夹 header
    "fg": "#000000",               # 常规文字
    "header_fg": "#333333",        # header 上的图标按钮
    "danger_fg": "#B22222",        # 删除类按钮文字
    "danger_active_bg": "#FADBD8",
    "header_active_bg": "#D0D0D0",
    "btn_bg": "#F0F0F0",           # 工具栏按钮
    "btn_active_bg": "#E2E2E2",
}

DARK_THEME = {
    "name": "dark",
    "app_bg": "#1F1F1F",
    "panel_bg": "#2A2A2A",
    "card_bg": "#2D2D30",
    "desc_bg": "#3C3C3C",
    "folder_bg": "#262626",
    "header_bg": "#333333",
    "fg": "#E6E6E6",
    "header_fg": "#CCCCCC",
    "danger_fg": "#E57373",
    "danger_active_bg": "#5C2B2B",
    "header_active_bg": "#454545",
    "btn_bg": "#3A3A3A",
    "btn_active_bg": "#4A4A4A",
}


def system_prefers_light():
    """读注册表 AppsUseLightTheme（1=浅色，0=深色）。读不到按浅色处理。"""
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion"
            r"\Themes\Personalize"
        ) as k:
            v, _t = winreg.QueryValueEx(k, "AppsUseLightTheme")
            return bool(v)
    except Exception:
        return True


# ================================================================
# 高 DPI 感知
# ================================================================
def enable_dpi_awareness():
    """让程序按物理像素工作，避免高 DPI 屏上图标/文字模糊。"""
    try:
        # Windows 8.1+ 推荐 API
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            # 兼容更老的 Windows
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


# ================================================================
# 配置读写
# ================================================================
def _cfg_paths(cfg_file):
    """由主配置路径派生 bak/tmp/corrupt 三个伴生路径。"""
    return cfg_file + ".bak", cfg_file + ".tmp", cfg_file + ".corrupt"


# 兼容旧引用（基于启动时选中的路径；save_config 降级后以
# ACTIVE_CONFIG_FILE 的派生为准）
CONFIG_BAK_FILE, CONFIG_TMP_FILE, CONFIG_CORRUPT_FILE = \
    _cfg_paths(ACTIVE_CONFIG_FILE)

# _merge_dict 允许的最大递归深度：正常配置最多 3-4 层嵌套，
# 32 层已远超合理值；超过即视为恶意构造或损坏，停止递归以防栈溢出。
_MERGE_MAX_DEPTH = 32


def _merge_dict(base, override, depth=0):
    """把 override 的字段递归合并到 base，保证 base 拥有完整结构。

    - depth 超过 _MERGE_MAX_DEPTH 时不再递归，直接用 override 覆盖，
      避免构造超深嵌套的 JSON 触发 RecursionError。
    - override 不是 dict 时也直接返回 base（防御 _sanitize 前的调用者）。
    """
    if depth >= _MERGE_MAX_DEPTH or not isinstance(override, dict):
        return override if isinstance(override, dict) else base
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = _merge_dict(base[k], v, depth + 1)
        else:
            base[k] = v
    return base


def _sanitize_config(cfg):
    """加载后逐字段做类型/范围校验，非法值就地回落到默认，返回 cfg 本身。

    load_config 走 _merge_dict 后所有字段仍可能被用户手改成任意类型，
    这里把它们统一约束到 GUI 期望的形态，避免 App.__init__ / 加载卡片
    / sorted key 等地方直接 raise 导致启动失败或卡片全部丢失。
    """
    if not isinstance(cfg, dict):
        return copy.deepcopy(DEFAULT_CONFIG)

    # ---- window ----
    default_w = DEFAULT_CONFIG["window"]
    w = cfg.get("window")
    if not isinstance(w, dict):
        w = {}
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
    cfg["window"] = {
        "width": _int_or(default_w["width"], w.get("width"),
                         lo=100, hi=20000),
        "height": _int_or(default_w["height"], w.get("height"),
                          lo=100, hi=20000),
        # x/y 允许负值（多显示器左侧屏），范围放宽；越界最终会在
        # App.__init__ 里按当前屏幕再兜底一次
        "x": _int_or(default_w["x"], w.get("x"), lo=-20000, hi=20000),
        "y": _int_or(default_w["y"], w.get("y"), lo=-20000, hi=20000),
    }

    # ---- font ----
    default_f = DEFAULT_CONFIG["font"]
    f = cfg.get("font")
    if not isinstance(f, dict):
        f = {}
    fam = f.get("family")
    if not isinstance(fam, str) or not fam.strip():
        fam = default_f["family"]
    cfg["font"] = {
        "family": fam,
        "size": _int_or(default_f["size"], f.get("size"), lo=8, hi=36),
    }

    # ---- card_width ----
    cfg["card_width"] = _int_or(
        DEFAULT_CONFIG["card_width"], cfg.get("card_width"),
        lo=200, hi=1200
    )

    # ---- theme_mode ----
    tm = cfg.get("theme_mode")
    if tm not in ("system", "light", "dark"):
        tm = "system"
    cfg["theme_mode"] = tm

    # ---- folders ----
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
            order = _int_or(i, fd.get("order"), lo=-10**9, hi=10**9)
            locked = bool(fd.get("locked"))
            collapsed = bool(fd.get("collapsed"))
            clean_folders.append({
                "id": fid, "name": name,
                "order": order, "locked": locked,
                "collapsed": collapsed,
            })
    cfg["folders"] = clean_folders  # 允许为空，_load_from_config 会兜底建默认

    # ---- shortcuts ----
    raw_items = cfg.get("shortcuts")
    clean_items = []
    if isinstance(raw_items, list):
        for i, it in enumerate(raw_items):
            if not isinstance(it, dict):
                continue
            p = it.get("path")
            if not isinstance(p, str) or not p:
                continue
            desc = it.get("description", "")
            if not isinstance(desc, str):
                desc = ""
            fid = it.get("folder")
            if not isinstance(fid, str) or not fid:
                fid = ""
            order = _int_or(i, it.get("order"), lo=-10**9, hi=10**9)
            title = it.get("title", "")
            if not isinstance(title, str):
                title = ""
            icon = it.get("icon", "")
            if not isinstance(icon, str):
                icon = ""
            lc = _int_or(0, it.get("launch_count"), lo=0, hi=10**9)
            try:
                ts = float(it.get("last_launch_ts", 0.0))
            except (TypeError, ValueError):
                ts = 0.0
            if ts < 0:
                ts = 0.0
            clean_items.append({
                "path": p, "description": desc,
                "folder": fid, "order": order,
                "title": title, "icon": icon,
                "launch_count": lc, "last_launch_ts": ts,
            })
    cfg["shortcuts"] = clean_items

    # ---- 独立存储区（web_shortcuts / dir_shortcuts，
    #      与 shortcuts 同构但无 folder 字段） ----
    for area_key in ("web_shortcuts", "dir_shortcuts"):
        raw_area = cfg.get(area_key)
        clean_area = []
        if isinstance(raw_area, list):
            for i, it in enumerate(raw_area):
                if not isinstance(it, dict):
                    continue
                p = it.get("path")
                if not isinstance(p, str) or not p:
                    continue
                desc = it.get("description", "")
                if not isinstance(desc, str):
                    desc = ""
                order = _int_or(i, it.get("order"), lo=-10**9, hi=10**9)
                title = it.get("title", "")
                if not isinstance(title, str):
                    title = ""
                icon = it.get("icon", "")
                if not isinstance(icon, str):
                    icon = ""
                lc = _int_or(0, it.get("launch_count"), lo=0, hi=10**9)
                try:
                    ts = float(it.get("last_launch_ts", 0.0))
                except (TypeError, ValueError):
                    ts = 0.0
                if ts < 0:
                    ts = 0.0
                clean_area.append({
                    "path": p, "description": desc, "order": order,
                    "title": title, "icon": icon,
                    "launch_count": lc, "last_launch_ts": ts,
                })
        cfg[area_key] = clean_area

    return cfg


def _read_config_file(path):
    """读取并合并到默认结构；失败时抛异常。"""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    with open(path, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    if not isinstance(loaded, dict):
        raise ValueError("config root is not a JSON object")
    cfg = _merge_dict(cfg, loaded)
    return _sanitize_config(cfg)


def load_config():
    """从 ACTIVE_CONFIG_FILE 加载配置。

    - 文件不存在：返回默认。
    - 加载失败：先隔离坏文件到 *.corrupt，再尝试 .bak；
      两个都不行时用 messagebox 让用户在"备份坏文件并使用默认" /
      "退出程序检查文件" 之间选择，避免下次 save 无声覆盖坏数据。
    """
    cfg_file = ACTIVE_CONFIG_FILE
    bak_file, _tmp, corrupt_file = _cfg_paths(cfg_file)

    if not os.path.exists(cfg_file):
        # 主文件缺失但有 .bak，尝试恢复
        if os.path.exists(bak_file):
            try:
                return _read_config_file(bak_file)
            except Exception as e:
                print(f"[QuickDeck] load bak fallback failed: {e}",
                      file=sys.stderr)
        return _sanitize_config(copy.deepcopy(DEFAULT_CONFIG))

    try:
        return _read_config_file(cfg_file)
    except Exception as primary_err:
        print(f"[QuickDeck] load_config primary error: {primary_err}",
              file=sys.stderr)

    # 主文件读取失败：尝试 .bak
    bak_cfg = None
    bak_err = None
    if os.path.exists(bak_file):
        try:
            bak_cfg = _read_config_file(bak_file)
        except Exception as e:
            bak_err = e
            print(f"[QuickDeck] load_config bak error: {e}",
                  file=sys.stderr)

    # 有可用 .bak：把损坏主文件挪走 → 用 .bak 覆盖 → 使用 .bak
    if bak_cfg is not None:
        try:
            os.replace(cfg_file, corrupt_file)
        except Exception:
            pass
        # 弹窗告知，避免用户以为一切正常
        try:
            messagebox.showwarning(
                "配置文件损坏",
                "config.json 无法解析，已隔离为 config.json.corrupt，"
                "并使用最近一次成功保存的备份 config.json.bak 恢复。"
            )
        except Exception:
            pass
        return bak_cfg

    # .bak 也不可用：询问用户
    try:
        choice = messagebox.askyesno(
            "配置文件损坏",
            "config.json 无法解析，且没有可用的 .bak 备份。\n\n"
            f"主文件错误：{primary_err}\n"
            + (f"备份错误：{bak_err}\n" if bak_err else "")
            + "\n是（Yes）：备份坏文件为 config.json.corrupt 并使用默认设置继续启动。"
            "\n否（No）：立即退出程序，让你手动检查文件。"
        )
    except Exception:
        choice = True  # 无 GUI 环境时默认继续
    if not choice:
        sys.exit(1)
    try:
        os.replace(cfg_file, corrupt_file)
    except Exception:
        pass
    return _sanitize_config(copy.deepcopy(DEFAULT_CONFIG))


def _write_config_to(cfg, cfg_file):
    """把 cfg 原子写到 cfg_file（tmp + fsync + os.replace + bak 轮转）。
    失败时抛异常（由 save_config 决定是否降级重试）。"""
    bak_file, tmp_file, _corrupt = _cfg_paths(cfg_file)
    d = os.path.dirname(cfg_file)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    # 1) 写临时文件；先 flush + fsync 保证内容真的到磁盘再 rename
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        try:
            f.flush()
            os.fsync(f.fileno())
        except (OSError, AttributeError):
            pass
    # 2) 先把当前主文件挪到 .bak（保留上次成功的完整版本），
    #    然后把 tmp 原子替换为主文件
    if os.path.exists(cfg_file):
        try:
            os.replace(cfg_file, bak_file)
        except OSError as e:
            print(f"[QuickDeck] backup rotate failed: {e}",
                  file=sys.stderr)
    os.replace(tmp_file, cfg_file)


def save_config(cfg):
    """原子写回配置。

    Portable 优先：先写 ACTIVE_CONFIG_FILE（初始为 exe 目录，除非启动时
    已降级）。写失败（如 exe 在 Program Files、权限不足）时自动降级到
    %APPDATA%/QuickDeck/config.json 再试一次，并把 ACTIVE_CONFIG_FILE
    永久切过去，本次会话后续保存都直接走 APPDATA。
    """
    global ACTIVE_CONFIG_FILE
    try:
        _write_config_to(cfg, ACTIVE_CONFIG_FILE)
        return
    except Exception as e:
        print(f"[QuickDeck] save_config error at "
              f"{ACTIVE_CONFIG_FILE}: {e}", file=sys.stderr)
        # 清理可能残留的 tmp，避免下次干扰
        _b, tmp_file, _c = _cfg_paths(ACTIVE_CONFIG_FILE)
        try:
            if os.path.exists(tmp_file):
                os.remove(tmp_file)
        except OSError:
            pass

    # 已经在 APPDATA 还失败：没有更低的降级层，放弃本次保存
    if os.path.normcase(ACTIVE_CONFIG_FILE) == \
            os.path.normcase(APPDATA_CONFIG_FILE):
        return

    # 降级 APPDATA 重试
    try:
        _write_config_to(cfg, APPDATA_CONFIG_FILE)
        ACTIVE_CONFIG_FILE = APPDATA_CONFIG_FILE
        print(f"[QuickDeck] config fell back to {APPDATA_CONFIG_FILE}",
              file=sys.stderr)
    except Exception as e:
        print(f"[QuickDeck] save_config appdata fallback error: {e}",
              file=sys.stderr)


# ================================================================
# 本地字体加载
# ================================================================
def load_local_font(font_path):
    """把同目录的 ttf 字体加载到当前进程，无需系统级安装。"""
    if not os.path.exists(font_path):
        return False
    try:
        FR_PRIVATE = 0x10  # 仅本进程可见
        n = ctypes.windll.gdi32.AddFontResourceExW(font_path, FR_PRIVATE, 0)
        return n > 0
    except Exception:
        return False


# ================================================================
# 图标提取
# ================================================================

# ---- Windows 常量 ----------------------------------------------
_SHGFI_ICON = 0x00000100
_SHGFI_LARGEICON = 0x00000000
_SHGFI_USEFILEATTRIBUTES = 0x00000010

_IID_IShellItem_STR = "{43826D1E-E718-42EE-BC55-A1E261C37BFE}"
_IID_IShellItemImageFactory_STR = "{BCC18B79-BA16-442F-80C4-8A59C30C463B}"

_SIIGBF_BIGGERSIZEOK = 0x00000001  # 允许返回比请求更大的位图
_SIIGBF_ICONONLY = 0x00000004      # 只要图标，不要缩略图


# ---- 结构体（前置，供 API 原型引用） ---------------------------
class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_byte * 8),
    ]


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_ulong),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", ctypes.c_ushort),
        ("biBitCount", ctypes.c_ushort),
        ("biCompression", ctypes.c_ulong),
        ("biSizeImage", ctypes.c_ulong),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", ctypes.c_ulong),
        ("biClrImportant", ctypes.c_ulong),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", _BITMAPINFOHEADER),
        ("bmiColors", ctypes.c_ulong * 3),
    ]


class _BITMAP(ctypes.Structure):
    _fields_ = [
        ("bmType", ctypes.c_long),
        ("bmWidth", ctypes.c_long),
        ("bmHeight", ctypes.c_long),
        ("bmWidthBytes", ctypes.c_long),
        ("bmPlanes", ctypes.c_ushort),
        ("bmBitsPixel", ctypes.c_ushort),
        ("bmBits", ctypes.c_void_p),
    ]


class _SHFILEINFOW(ctypes.Structure):
    _fields_ = [
        ("hIcon", ctypes.c_void_p),
        ("iIcon", ctypes.c_int),
        ("dwAttributes", ctypes.c_ulong),
        ("szDisplayName", ctypes.c_wchar * 260),
        ("szTypeName", ctypes.c_wchar * 80),
    ]


# ---- Win API 原型集中声明 --------------------------------------
# 不声明 argtypes 会让 ctypes 默认把参数当 c_int，
# 64 位地址值超过 int 范围时会抛 "int too long to convert"。
# 注意：ctypes.HRESULT 作为 restype 时，返回值 < 0（表示失败）会自动 raise OSError，
# 我们希望"失败=返回 None"，因此下面全部改用 c_long 手动检查 hr。
_APIS_INITED = False


def _norm_path(path):
    """规范化为绝对路径 + 反斜杠分隔。
    某些 shell API（SHCreateItemFromParsingName）对 `C:/foo/bar` 这种正斜杠路径
    返回 E_INVALIDARG，必须转成 `C:\\foo\\bar` 才能被解析。
    """
    if not path:
        return path
    try:
        return os.path.normpath(os.path.abspath(path))
    except Exception:
        return path


def _init_win_apis():
    global _APIS_INITED
    if _APIS_INITED:
        return
    try:
        ole32 = ctypes.windll.ole32
        shell32 = ctypes.windll.shell32
        gdi32 = ctypes.windll.gdi32
        user32 = ctypes.windll.user32

        ole32.CLSIDFromString.argtypes = [
            ctypes.c_wchar_p, ctypes.POINTER(_GUID)
        ]
        ole32.CLSIDFromString.restype = ctypes.c_long

        ole32.CoInitializeEx.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong
        ]
        ole32.CoInitializeEx.restype = ctypes.c_long

        shell32.SHCreateItemFromParsingName.argtypes = [
            ctypes.c_wchar_p, ctypes.c_void_p,
            ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)
        ]
        shell32.SHCreateItemFromParsingName.restype = ctypes.c_long

        shell32.SHGetFileInfoW.argtypes = [
            ctypes.c_wchar_p, ctypes.c_ulong,
            ctypes.POINTER(_SHFILEINFOW), ctypes.c_uint, ctypes.c_uint
        ]
        # SHGetFileInfoW 返回 DWORD_PTR，64 位平台是 8 字节
        shell32.SHGetFileInfoW.restype = ctypes.c_void_p

        gdi32.GetObjectW.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p
        ]
        gdi32.GetObjectW.restype = ctypes.c_int

        gdi32.GetDIBits.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_uint, ctypes.c_uint,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint
        ]
        gdi32.GetDIBits.restype = ctypes.c_int

        gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
        gdi32.DeleteObject.restype = ctypes.c_int

        gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
        gdi32.CreateCompatibleDC.restype = ctypes.c_void_p

        gdi32.CreateDIBSection.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
            ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_ulong
        ]
        gdi32.CreateDIBSection.restype = ctypes.c_void_p

        gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        gdi32.SelectObject.restype = ctypes.c_void_p

        gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
        gdi32.DeleteDC.restype = ctypes.c_int

        gdi32.GdiFlush.argtypes = []
        gdi32.GdiFlush.restype = ctypes.c_int

        user32.GetDC.argtypes = [ctypes.c_void_p]
        user32.GetDC.restype = ctypes.c_void_p

        user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        user32.ReleaseDC.restype = ctypes.c_int

        user32.DrawIconEx.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
            ctypes.c_int, ctypes.c_int, ctypes.c_uint,
            ctypes.c_void_p, ctypes.c_uint
        ]
        user32.DrawIconEx.restype = ctypes.c_int

        user32.DestroyIcon.argtypes = [ctypes.c_void_p]
        user32.DestroyIcon.restype = ctypes.c_int

        # PrivateExtractIconsW：更宽容的图标提取（可指定尺寸，处理更多格式）
        user32.PrivateExtractIconsW.argtypes = [
            ctypes.c_wchar_p, ctypes.c_int,
            ctypes.c_int, ctypes.c_int,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_uint),
            ctypes.c_uint, ctypes.c_uint
        ]
        user32.PrivateExtractIconsW.restype = ctypes.c_uint

        # 幕布截屏窗口（视图切换防残影第三层，见 App._show_paint_curtain）
        gdi32.CreateCompatibleBitmap.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p

        gdi32.BitBlt.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int,
            ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_uint
        ]
        gdi32.BitBlt.restype = ctypes.c_int

        user32.CreateWindowExW.argtypes = [
            ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_wchar_p,
            ctypes.c_uint,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_void_p
        ]
        user32.CreateWindowExW.restype = ctypes.c_void_p

        user32.DestroyWindow.argtypes = [ctypes.c_void_p]
        user32.DestroyWindow.restype = ctypes.c_int

        user32.UpdateWindow.argtypes = [ctypes.c_void_p]
        user32.UpdateWindow.restype = ctypes.c_int

        # wParam/lParam 都是指针宽度：STM_SETIMAGE 的 lParam 传 HBITMAP，
        # c_void_p restype 返回的句柄在 32 位值高位为 1 时是符号扩展的
        # 64 位无符号大整数，默认 c_int 转换会溢出（是否触发取决于系统
        # 分配的句柄值，表现为时好时坏）
        user32.SendMessageW.argtypes = [
            ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
        user32.SendMessageW.restype = ctypes.c_void_p

        # HMODULE 是模块基址，64 位高熵 ASLR 下可能超出 32 位，
        # 必须显式 c_void_p（默认 c_int 会截断）
        kernel32 = ctypes.windll.kernel32
        kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
        kernel32.GetModuleHandleW.restype = ctypes.c_void_p

        _APIS_INITED = True
    except Exception as e:
        print(f"[QuickDeck] _init_win_apis error: {e}", file=sys.stderr)


# ---- COM 辅助 ---------------------------------------------------
# COM 初始化是 per-thread 的：主线程和图标 worker 线程都要各自
# CoInitializeEx 一次，用 thread-local 记录本线程是否已初始化
_com_tls = threading.local()


def _iid(s):
    _init_win_apis()
    g = _GUID()
    ctypes.windll.ole32.CLSIDFromString(s, ctypes.byref(g))
    return g


def _ensure_com():
    if getattr(_com_tls, "inited", False):
        return
    _init_win_apis()
    try:
        # 0x2 = COINIT_APARTMENTTHREADED（STA；tk 主线程与 worker 均适用）
        ctypes.windll.ole32.CoInitializeEx(None, 0x2)
    except Exception:
        pass
    _com_tls.inited = True


def _com_release(obj_ptr):
    """调用 IUnknown::Release (vtable[2])。"""
    if not obj_ptr or not obj_ptr.value:
        return
    try:
        vtbl = ctypes.cast(
            obj_ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
        )[0]
        rel_ft = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
        rel_addr = vtbl[2]
        if rel_addr:
            ctypes.cast(ctypes.c_void_p(rel_addr), rel_ft)(obj_ptr)
    except Exception:
        pass


# ---- 解析 .lnk --------------------------------------------------
def resolve_shortcut(lnk_path):
    """解析 .lnk 得到 (target, icon_path, icon_index)。"""
    lnk_path = _norm_path(lnk_path)
    try:
        shell = win32com.client.Dispatch("WScript.Shell")
        sc = shell.CreateShortcut(lnk_path)
        target = sc.TargetPath or ""
        icon_location = sc.IconLocation or ""
        # IconLocation 常见形式："C:\\...\\foo.exe,0"
        if icon_location and "," in icon_location:
            head, tail = icon_location.rsplit(",", 1)
            icon_path = head.strip() or target
            try:
                icon_index = int(tail)
            except ValueError:
                icon_index = 0
        else:
            icon_path = icon_location.strip() or target
            icon_index = 0
        # 展开 %SystemRoot% 之类的环境变量 + 规范化分隔符
        if target:
            target = _norm_path(os.path.expandvars(target))
        if icon_path:
            icon_path = _norm_path(os.path.expandvars(icon_path))
        return target, icon_path, icon_index
    except Exception as e:
        print(f"[QuickDeck] resolve_shortcut error: {e}", file=sys.stderr)
        return "", "", 0


# ---- HICON → PIL ------------------------------------------------
def _image_has_visible_pixels(img):
    """判断 PIL RGBA 图像是否有可见像素（alpha 或 RGB 有非零）。"""
    if img is None:
        return False
    try:
        bbox = img.getbbox()
    except Exception:
        return False
    return bbox is not None


def _rescue_alpha(img):
    """若图像 alpha 全 0 但 RGB 有内容（DrawIconEx 未写 alpha 的常见情形），
    根据 RGB 是否非零补一个"看得见"的 alpha，避免图片被当成完全透明。
    """
    if img is None:
        return None
    try:
        r, g, b, a = img.split()
        # 若 alpha 有任何非零值，认为原图 alpha 是有效的，直接返回
        if a.getextrema()[1] != 0:
            return img
        # alpha 全 0：用 RGB 的最大分量作为 alpha（非零像素 → 255）
        from PIL import ImageChops, ImageMath
        max_rgb = ImageChops.lighter(ImageChops.lighter(r, g), b)
        # 二值化：>0 → 255
        new_a = max_rgb.point(lambda v: 255 if v > 0 else 0, mode="L")
        return Image.merge("RGBA", (r, g, b, new_a))
    except Exception as e:
        print(f"[QuickDeck] _rescue_alpha error: {e}", file=sys.stderr)
        return img


def _hicon_to_pil(hicon, size=ICON_SIZE):
    """把 HICON 绘制到 32bit BGRA DIB 并转成 PIL.Image (RGBA)。
    调用后 **一定** 会 DestroyIcon(hicon)。失败返回 None。

    用 CreateDIBSection 而不是 CreateCompatibleBitmap，保证：
      1) 32bit 位深固定（避免 DDB 遇到 24bpp 桌面时数据错位）
      2) 拿到原始 BGRA 字节，不受显示驱动格式差异影响
    并且对 alpha 全 0 的图标做兜底（DrawIconEx 对无 alpha 遗留图标
    不会写入 alpha 通道，会导致 PhotoImage 显示为完全透明）。
    """
    if not hicon:
        return None
    _init_win_apis()
    gdi32 = ctypes.windll.gdi32
    user32 = ctypes.windll.user32

    hdc_screen = None
    memdc = None
    hbmp = None
    try:
        hdc_screen = user32.GetDC(None)
        if not hdc_screen:
            return None
        memdc = gdi32.CreateCompatibleDC(hdc_screen)
        if not memdc:
            return None

        bi = _BITMAPINFO()
        bi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bi.bmiHeader.biWidth = size
        bi.bmiHeader.biHeight = -size  # top-down，与 PIL 顺序一致
        bi.bmiHeader.biPlanes = 1
        bi.bmiHeader.biBitCount = 32
        bi.bmiHeader.biCompression = 0  # BI_RGB

        bits_ptr = ctypes.c_void_p()
        hbmp = gdi32.CreateDIBSection(
            hdc_screen, ctypes.byref(bi), 0,  # DIB_RGB_COLORS
            ctypes.byref(bits_ptr), None, 0
        )
        if not hbmp or not bits_ptr.value:
            return None

        old = gdi32.SelectObject(memdc, hbmp)
        # DIB 由系统零初始化，DrawIconEx 会把 icon 混色到透明黑背景上
        user32.DrawIconEx(memdc, 0, 0, hicon,
                          size, size, 0, None, 3)  # DI_NORMAL = 3
        gdi32.SelectObject(memdc, old)
        # 确保 GDI 已把绘图指令刷到 DIB 内存
        gdi32.GdiFlush()

        # DIB 内存直接映射；读取时拷贝一份，避免释放后悬空
        raw = ctypes.string_at(bits_ptr.value, size * size * 4)
        img = Image.frombuffer("RGBA", (size, size), raw, "raw", "BGRA", 0, 1)
        # DrawIconEx 对老式（无 alpha）图标不会写 alpha，需补救
        img = _rescue_alpha(img)
        # 完全空的图像视为失败，让调用方走下一条兜底
        if not _image_has_visible_pixels(img):
            return None
        return img
    except Exception as e:
        print(f"[QuickDeck] _hicon_to_pil error: {e}", file=sys.stderr)
        return None
    finally:
        if hbmp:
            try: gdi32.DeleteObject(hbmp)
            except Exception: pass
        if memdc:
            try: gdi32.DeleteDC(memdc)
            except Exception: pass
        if hdc_screen:
            try: user32.ReleaseDC(None, hdc_screen)
            except Exception: pass
        try: user32.DestroyIcon(hicon)
        except Exception: pass


# ---- ExtractIconEx -----------------------------------------------
def extract_icon_image(path, index=0, size=ICON_SIZE):
    """ExtractIconEx 从 exe/dll/ico 抽取图标 → PIL.Image。"""
    if not path or not os.path.exists(path):
        return None
    try:
        large, small = win32gui.ExtractIconEx(path, index, 1)
    except Exception:
        return None
    icons = list(large) + list(small)
    if not icons:
        return None
    hicon = icons[0]
    for h in icons[1:]:
        try: win32gui.DestroyIcon(h)
        except Exception: pass
    return _hicon_to_pil(hicon, size)


# ---- PrivateExtractIconsW 兜底 ----------------------------------
def private_extract_icon(path, size=ICON_SIZE):
    """用 user32.PrivateExtractIconsW 提取指定尺寸的图标。
    比 ExtractIconEx 更宽容：能拿到 .NET 内嵌资源、非常规打包 exe 的图标，
    且可以直接请求任意尺寸而不用后续缩放。
    """
    if not path:
        return None
    path = _norm_path(path)
    if not os.path.exists(path):
        return None
    _init_win_apis()
    try:
        hicon_out = ctypes.c_void_p()
        id_out = ctypes.c_uint()
        # LR_DEFAULTCOLOR = 0x00000000
        n = ctypes.windll.user32.PrivateExtractIconsW(
            path, 0,
            size, size,
            ctypes.byref(hicon_out),
            ctypes.byref(id_out),
            1, 0
        )
        if n == 0 or n == 0xFFFFFFFF or not hicon_out.value:
            return None
        return _hicon_to_pil(hicon_out.value, size)
    except Exception as e:
        print(f"[QuickDeck] private_extract_icon error: {e} path={path}",
              file=sys.stderr)
        return None


# ---- SHGetFileInfoW 兜底 -----------------------------------------
def shget_icon_image(path, size=ICON_SIZE):
    """shell32.SHGetFileInfoW → Explorer 里显示的图标。"""
    if not path:
        return None
    path = _norm_path(path)
    _init_win_apis()
    try:
        info = _SHFILEINFOW()
        flags = _SHGFI_ICON | _SHGFI_LARGEICON
        if not os.path.exists(path):
            flags |= _SHGFI_USEFILEATTRIBUTES
        ret = ctypes.windll.shell32.SHGetFileInfoW(
            path, 0, ctypes.byref(info), ctypes.sizeof(info), flags
        )
        if not ret or not info.hIcon:
            print(f"[QuickDeck] shget_icon_image: no icon for {path}",
                  file=sys.stderr)
            return None
        return _hicon_to_pil(info.hIcon, size)
    except Exception as e:
        print(f"[QuickDeck] shget_icon_image error: {e} path={path}",
              file=sys.stderr)
        return None


# ---- HBITMAP → PIL -----------------------------------------------
def _hbitmap_to_pil(hbmp_value, size):
    """把 HBITMAP 转 PIL.Image。调用方负责 DeleteObject。"""
    _init_win_apis()
    hdc = None
    try:
        bm = _BITMAP()
        if ctypes.windll.gdi32.GetObjectW(
            hbmp_value, ctypes.sizeof(bm), ctypes.byref(bm)
        ) == 0:
            return None
        w, h = int(bm.bmWidth), int(bm.bmHeight)
        if w <= 0 or h <= 0:
            return None

        bi = _BITMAPINFO()
        bi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bi.bmiHeader.biWidth = w
        bi.bmiHeader.biHeight = -h  # 顶到底
        bi.bmiHeader.biPlanes = 1
        bi.bmiHeader.biBitCount = 32
        bi.bmiHeader.biCompression = 0  # BI_RGB

        buf = (ctypes.c_ubyte * (w * h * 4))()
        hdc = ctypes.windll.user32.GetDC(None)
        got = ctypes.windll.gdi32.GetDIBits(
            hdc, hbmp_value, 0, h,
            ctypes.byref(buf), ctypes.byref(bi), 0  # DIB_RGB_COLORS
        )
        if got == 0:
            return None

        img = Image.frombuffer(
            "RGBA", (w, h), bytes(buf), "raw", "BGRA", 0, 1
        )
        if (w, h) != (size, size):
            img = img.resize((size, size), Image.LANCZOS)
        # 有些 shell 返回的位图 alpha 全 0（无 alpha 语义），补救一下
        img = _rescue_alpha(img)
        if not _image_has_visible_pixels(img):
            return None
        return img
    except Exception as e:
        print(f"[QuickDeck] _hbitmap_to_pil error: {e}", file=sys.stderr)
        return None
    finally:
        if hdc:
            try:
                ctypes.windll.user32.ReleaseDC(None, hdc)
            except Exception:
                pass


# ---- IShellItemImageFactory 兜底 ---------------------------------
def imagefactory_icon(path, size=ICON_SIZE):
    """通过 IShellItemImageFactory::GetImage 拿图标。
    Windows Vista+，Explorer 用来显示大图标/缩略图的现代 API。
    对 .NET 内嵌资源 / UWP / 特殊打包效果最好。
    """
    if not path:
        return None
    # SHCreateItemFromParsingName 对 `C:/...` 正斜杠路径直接 E_INVALIDARG
    path = _norm_path(path)
    _init_win_apis()
    _ensure_com()

    item_ptr = ctypes.c_void_p()
    factory_ptr = ctypes.c_void_p()
    hbmp = ctypes.c_void_p()
    try:
        iid_item = _iid(_IID_IShellItem_STR)
        iid_factory = _iid(_IID_IShellItemImageFactory_STR)

        # SHCreateItemFromParsingName(pszPath, pbc, riid, ppv)
        hr = ctypes.windll.shell32.SHCreateItemFromParsingName(
            path, None,
            ctypes.byref(iid_item), ctypes.byref(item_ptr)
        )
        if hr != 0 or not item_ptr.value:
            print(
                f"[QuickDeck] imagefactory_icon: "
                f"SHCreateItem hr=0x{hr & 0xFFFFFFFF:08x} for {path}",
                file=sys.stderr,
            )
            return None

        # item->QueryInterface(IID_IShellItemImageFactory, &factory)
        vtbl_item = ctypes.cast(
            item_ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
        )[0]
        qi_ft = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p,
            ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)
        )
        qi_addr = vtbl_item[0]
        if not qi_addr:
            return None
        # 用 c_void_p 显式包一层，避免 int 直接 cast 到 CFUNCTYPE
        qi = ctypes.cast(ctypes.c_void_p(qi_addr), qi_ft)
        hr = qi(item_ptr, ctypes.byref(iid_factory), ctypes.byref(factory_ptr))
        if hr != 0 or not factory_ptr.value:
            print(
                f"[QuickDeck] imagefactory_icon: "
                f"QueryInterface hr=0x{hr & 0xFFFFFFFF:08x} for {path}",
                file=sys.stderr,
            )
            return None

        # factory->GetImage((cx, cy), flags, &hbmp) (vtable[3])
        sz = _SIZE(size * 2, size * 2)  # 请求 2x 拿更清晰的 jumbo 版本再缩放
        vtbl_fac = ctypes.cast(
            factory_ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
        )[0]
        gi_ft = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p,
            _SIZE, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)
        )
        gi_addr = vtbl_fac[3]
        if not gi_addr:
            return None
        gi = ctypes.cast(ctypes.c_void_p(gi_addr), gi_ft)
        hr = gi(
            factory_ptr, sz,
            _SIIGBF_BIGGERSIZEOK | _SIIGBF_ICONONLY,
            ctypes.byref(hbmp)
        )
        if hr != 0 or not hbmp.value:
            print(
                f"[QuickDeck] imagefactory_icon: "
                f"GetImage hr=0x{hr & 0xFFFFFFFF:08x} for {path}",
                file=sys.stderr,
            )
            return None

        return _hbitmap_to_pil(hbmp.value, size)
    except Exception as e:
        print(f"[QuickDeck] imagefactory_icon error: {e} path={path}",
              file=sys.stderr)
        return None
    finally:
        if hbmp and hbmp.value:
            try:
                ctypes.windll.gdi32.DeleteObject(hbmp)
            except Exception:
                pass
        _com_release(factory_ptr)
        _com_release(item_ptr)


# ---- 对外统一入口 -----------------------------------------------
def _parse_url_icon(path):
    """从 .url（INI 格式）解析 IconFile= / IconIndex= 字段。

    .url 由浏览器/系统生成，编码不统一：常见 ANSI（含本地化路径）、
    UTF-8（可能带 BOM）、少数 UTF-16。按 BOM → utf-8 → 本机 ANSI
    顺序尝试解码。解析失败返回 ("", 0)。"""
    try:
        with open(path, "rb") as f:
            raw = f.read(64 * 1024)  # .url 都是小文件，防御性截断
    except OSError:
        return "", 0
    text = None
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            text = raw.decode("utf-16")
        except UnicodeDecodeError:
            pass
    if text is None:
        for enc in ("utf-8-sig", "mbcs"):
            try:
                text = raw.decode(enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue
    if text is None:
        return "", 0
    icon_file, icon_index = "", 0
    for line in text.splitlines():
        line = line.strip()
        low = line.lower()
        if low.startswith("iconfile="):
            icon_file = os.path.expandvars(line.split("=", 1)[1].strip())
        elif low.startswith("iconindex="):
            try:
                icon_index = int(line.split("=", 1)[1].strip())
            except ValueError:
                pass
    return icon_file, icon_index


def get_icon_for_file(path, size=ICON_SIZE):
    """
    多层兜底图标提取：
      .lnk:
        1) IconLocation → ExtractIconEx
        2) TargetPath → ExtractIconEx
        3) IShellItemImageFactory 对 lnk 本身
        4) IShellItemImageFactory 对 TargetPath
        5) SHGetFileInfoW 对 lnk 本身
        6) SHGetFileInfoW 对 TargetPath
      .url:
        1) INI 的 IconFile=（图像文件走 PIL；exe/dll 走 ExtractIconEx）
        2) IShellItemImageFactory / SHGetFileInfoW 对 .url 本身
           （系统通常给默认浏览器图标）
      其他:
        1) ExtractIconEx
        2) IShellItemImageFactory
        3) SHGetFileInfoW
    """
    if not HAS_WIN32:
        return None
    # 统一入口保证当前线程完成 COM 初始化（worker 线程里的
    # WScript.Shell Dispatch 与 IShellItemImageFactory 都依赖它）
    _ensure_com()
    path = _norm_path(path)
    ext = os.path.splitext(path)[1].lower()
    tried = set()

    if ext == ".lnk":
        target, icon_path, icon_index = resolve_shortcut(path)

        if icon_path:
            key = (icon_path.lower(), icon_index)
            if key not in tried:
                tried.add(key)
                img = extract_icon_image(icon_path, icon_index, size)
                if img is not None:
                    return img
        if target:
            key = (target.lower(), 0)
            if key not in tried:
                tried.add(key)
                img = extract_icon_image(target, 0, size)
                if img is not None:
                    return img

        # PrivateExtractIconsW：能处理 .NET 内嵌资源等 ExtractIconEx 拿不到的场景
        if target:
            img = private_extract_icon(target, size)
            if img is not None:
                return img

        img = imagefactory_icon(path, size)
        if img is not None:
            return img
        if target:
            img = imagefactory_icon(target, size)
            if img is not None:
                return img

        img = shget_icon_image(path, size)
        if img is not None:
            return img
        if target:
            img = shget_icon_image(target, size)
            if img is not None:
                return img
    elif ext == ".url":
        icon_file, icon_index = _parse_url_icon(path)
        if icon_file and os.path.exists(icon_file):
            # favicon 缓存常见为 .ico/.png 图像文件，直接 PIL 加载
            if icon_file.lower().endswith(
                    (".ico", ".png", ".jpg", ".jpeg", ".bmp", ".gif")):
                try:
                    img = Image.open(icon_file)
                    img.load()
                    if img.mode != "RGBA":
                        img = img.convert("RGBA")
                    return img.resize((size, size), Image.LANCZOS)
                except Exception:
                    pass
            # IconFile 指向 exe/dll 等含图标资源的 PE 文件
            img = extract_icon_image(icon_file, icon_index, size)
            if img is not None:
                return img
        # 兜底：对 .url 本身走 shell 提取（通常得到默认浏览器图标）
        img = imagefactory_icon(path, size)
        if img is not None:
            return img
        img = shget_icon_image(path, size)
        if img is not None:
            return img
    else:
        img = extract_icon_image(path, 0, size)
        if img is not None:
            return img
        img = private_extract_icon(path, size)
        if img is not None:
            return img
        img = imagefactory_icon(path, size)
        if img is not None:
            return img
        img = shget_icon_image(path, size)
        if img is not None:
            return img
    return None


def get_title_for_file(path):
    """默认标题：文件名（不含扩展名）。
    目录路径取末级目录名（不做去扩展名——目录名里的点是名字的一部分）；
    盘符根目录（如 C:\\）basename 为空，退回显示完整路径。"""
    base = os.path.basename(path.rstrip("\\/"))
    if not base:
        return path
    if os.path.isdir(path):
        return base
    return os.path.splitext(base)[0]


def make_default_icon(size=ICON_SIZE):
    """当所有图标提取路径都失败时，用 PIL 画一个占位符。"""
    img = Image.new("RGBA", (size, size), (230, 230, 230, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([2, 2, size - 3, size - 3],
                outline=(120, 120, 120, 255), width=2)
    # 画一个"+"号意味"未识别"
    d.line([(size // 4, size // 2), (3 * size // 4, size // 2)],
           fill=(80, 80, 80, 255), width=2)
    d.line([(size // 2, size // 4), (size // 2, 3 * size // 4)],
           fill=(80, 80, 80, 255), width=2)
    return img


# ================================================================
# 图标缓存（内存 dict + 磁盘 PNG，key = 规范化路径 + mtime）
# ================================================================
_icon_mem_cache = {}
_icon_cache_lock = threading.Lock()


def _icon_cache_key(path):
    """(规范化绝对路径, mtime_ns)；文件不存在时 mtime 记 0。
    mtime 进 key 保证快捷方式被替换/更新后缓存自动失效。"""
    p = os.path.normcase(os.path.abspath(path))
    try:
        mtime = os.stat(p).st_mtime_ns
    except OSError:
        mtime = 0
    return p, mtime


def _icon_cache_file(key):
    name = hashlib.sha1(
        f"{key[0]}|{key[1]}".encode("utf-8", "replace")).hexdigest()
    return os.path.join(
        os.path.dirname(ACTIVE_CONFIG_FILE), "icon_cache", name + ".png")


def icon_cache_get(path):
    """先查内存，再查磁盘 PNG（磁盘命中会回填内存）。未命中返回 None。"""
    key = _icon_cache_key(path)
    with _icon_cache_lock:
        pil = _icon_mem_cache.get(key)
    if pil is not None:
        return pil
    fp = _icon_cache_file(key)
    try:
        if os.path.exists(fp):
            img = Image.open(fp)
            img.load()
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            with _icon_cache_lock:
                _icon_mem_cache[key] = img
            return img
    except Exception as e:
        print(f"[QuickDeck] icon cache read failed: {e}", file=sys.stderr)
    return None


def icon_cache_put(path, pil):
    """写内存 + 磁盘。磁盘写失败只打日志（缓存是加速手段，不是功能依赖）。"""
    key = _icon_cache_key(path)
    with _icon_cache_lock:
        _icon_mem_cache[key] = pil
    fp = _icon_cache_file(key)
    try:
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        pil.save(fp, "PNG")
    except Exception as e:
        print(f"[QuickDeck] icon cache write failed: {e}", file=sys.stderr)


def icon_cache_remove(path):
    """删除该路径当前 key 的内存 + 磁盘缓存条目（右键"刷新图标"用）。

    覆盖缓存盲区：key 含 mtime，但 .lnk 指向的目标 exe 升级换图标时
    .lnk 本身的 mtime 不变，缓存 key 相同导致永远命中陈旧图标——
    删掉条目后重新提取即可拿到新图标。"""
    key = _icon_cache_key(path)
    with _icon_cache_lock:
        _icon_mem_cache.pop(key, None)
    fp = _icon_cache_file(key)
    try:
        if os.path.exists(fp):
            os.remove(fp)
    except OSError as e:
        print(f"[QuickDeck] icon cache remove failed: {e}", file=sys.stderr)


# ================================================================
# 快捷方式卡片
# ================================================================
class ShortcutCard(tk.Frame):
    """一张快捷方式卡片，宽度由 App.card_width 动态决定（默认 500px）。
    可拖拽（换顺序 / 跨文件夹）、可双击启动。
    """

    # 兼容旧引用；实际生效值走 App.card_width（可由 UI 实时调整）
    CARD_WIDTH = 500

    def __init__(self, master, app, path, description="",
                 custom_title="", custom_icon="",
                 launch_count=0, last_launch_ts=0.0):
        th = app.theme
        super().__init__(master, bd=1, relief="solid",
                         padx=8, pady=6, bg=th["card_bg"])
        self.app = app
        self.path = path
        self.folder = None  # 由 FolderFrame.add_card / insert_card 设置
        self.custom_title = custom_title or ""
        self.custom_icon = custom_icon or ""
        # 使用统计（"按使用排序"视图的排序依据；随 config 持久化）
        self.launch_count = max(0, int(launch_count or 0))
        self.last_launch_ts = max(0.0, float(last_launch_ts or 0.0))

        # 图标：
        #   1) 自定义图标文件 → 同步加载（本地图像，开销小）
        #   2) (path, mtime) 缓存命中 → 同步用缓存（含磁盘 PNG，重启后有效）
        #   3) 未命中 → 先贴默认占位图标，交给 App 的 worker 线程异步提取，
        #      避免几十张卡片启动时把 UI 卡住
        pil = None
        pending_async = False
        if self.custom_icon:
            pil = self._load_icon_file(self.custom_icon)
        if pil is None and HAS_WIN32:
            pil = icon_cache_get(path)
        if pil is None:
            pil = app.default_icon_img
            pending_async = HAS_WIN32
        self.icon_pil = pil
        self.icon_photo = ImageTk.PhotoImage(pil)

        self.icon_label = tk.Label(self, image=self.icon_photo,
                                   bg=th["card_bg"], cursor="fleur")
        self.icon_label.pack(side="left", padx=(0, 8))

        mid = tk.Frame(self, bg=th["card_bg"])
        mid.pack(side="left", fill="both", expand=True)
        self.mid = mid

        title_text = self.custom_title or get_title_for_file(path)
        self.title_label = tk.Label(mid, text=title_text, anchor="w",
                                    font=app.app_font, bg=th["card_bg"],
                                    fg=th["fg"], cursor="fleur")
        self.title_label.pack(fill="x")

        self.desc_var = tk.StringVar(value=description)
        self.desc_entry = tk.Entry(mid, textvariable=self.desc_var,
                                   font=app.app_font, relief="flat",
                                   bg=th["desc_bg"], fg=th["fg"],
                                   insertbackground=th["fg"],
                                   readonlybackground=th["desc_bg"])
        self.desc_entry.pack(fill="x", pady=(3, 0))
        self.desc_entry.bind("<FocusOut>",
                             lambda e: self.app.save_state())
        self.desc_entry.bind("<Return>",
                             lambda e: self.app.save_state())

        self.del_btn = tk.Button(self, text="\u274C",  # ❌
                                 width=3, font=app.app_font, relief="flat",
                                 bg=th["card_bg"], fg=th["danger_fg"],
                                 activebackground=th["danger_active_bg"],
                                 command=self._on_delete)
        self.del_btn.pack(side="right", padx=(8, 0))

        # 拖拽 & 双击（不绑 Entry / 删除按钮，避免影响文本编辑与点击）
        for w in (self, mid, self.icon_label, self.title_label):
            w.bind("<ButtonPress-1>", self._on_drag_start)
            w.bind("<B1-Motion>", self._on_drag_motion)
            w.bind("<ButtonRelease-1>", self._on_drag_end)
            w.bind("<Double-Button-1>", self._on_double_click)
            w.bind("<Button-3>", self._on_right_click)

        # widget 就绪后再入队异步提取（结果经主线程轮询回填）
        if pending_async:
            app.request_icon(self)

    def set_extracted_icon(self, pil):
        """worker 线程提取完成后由主线程调用，回填真实图标。
        若期间用户已设置自定义图标，则忽略迟到的提取结果。"""
        if self.custom_icon:
            return
        try:
            self.icon_pil = pil
            self.icon_photo = ImageTk.PhotoImage(pil)
            self.icon_label.configure(image=self.icon_photo)
        except tk.TclError:
            pass  # 卡片可能已被销毁

    # ---- 自定义图标 ----
    @staticmethod
    def _load_icon_file(icon_path):
        """从 .ico/.png/.jpg 等图像文件加载卡片图标；失败返回 None。"""
        try:
            if not icon_path or not os.path.exists(icon_path):
                return None
            img = Image.open(icon_path)
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            img = img.resize((ICON_SIZE, ICON_SIZE), Image.LANCZOS)
            return img
        except Exception as e:
            print(f"[QuickDeck] load custom icon failed: {e}",
                  file=sys.stderr)
            return None

    def set_custom_icon(self, icon_path):
        """替换图标；icon_path 为空字符串时恢复自动提取。"""
        pil = None
        if icon_path:
            pil = self._load_icon_file(icon_path)
            if pil is None:
                messagebox.showwarning(
                    "替换图标失败", f"无法读取图像文件：\n{icon_path}")
                return False
        if pil is None and HAS_WIN32:
            pil = get_icon_for_file(self.path)
        if pil is None:
            pil = self.app.default_icon_img
        self.custom_icon = icon_path or ""
        self.icon_pil = pil
        self.icon_photo = ImageTk.PhotoImage(pil)
        self.icon_label.configure(image=self.icon_photo)
        return True

    def set_custom_title(self, title):
        """重命名标题；title 为空时恢复文件名默认标题。"""
        self.custom_title = (title or "").strip()
        self.title_label.configure(
            text=self.custom_title or get_title_for_file(self.path))

    # ---- 右键菜单 ----
    def _on_right_click(self, e):
        th = self.app.theme
        menu = tk.Menu(self, tearoff=0, font=self.app.app_font,
                       bg=th["card_bg"], fg=th["fg"],
                       activebackground=th["header_active_bg"],
                       activeforeground=th["fg"])
        locked = (self.folder is not None
                  and getattr(self.folder, "locked", False))
        state = "disabled" if locked else "normal"
        menu.add_command(label="重命名标题",
                         command=self._menu_rename, state=state)
        menu.add_command(label="替换图标",
                         command=self._menu_change_icon, state=state)
        # 刷新图标：删缓存重提取。不改任何用户数据，锁定时也允许；
        # 已设自定义图标时无意义（显示的不是自动提取结果），禁用
        menu.add_command(
            label="刷新图标", command=self._menu_refresh_icon,
            state="disabled" if (self.custom_icon or not HAS_WIN32)
            else "normal")
        menu.add_command(label="编辑描述",
                         command=self._menu_edit_desc, state=state)
        menu.add_separator()
        # 移动到指定文件夹（锁定时禁止移出）
        move_menu = tk.Menu(menu, tearoff=0, font=self.app.app_font,
                            bg=th["card_bg"], fg=th["fg"],
                            activebackground=th["header_active_bg"],
                            activeforeground=th["fg"])
        # 独立存储区卡片（网页区 / 文件夹区）不属于任何文件夹分组
        standalone = (self in getattr(self.app, "web_cards", [])
                      or self in getattr(self.app, "dir_cards", []))
        for f in self.app.folders:
            if f is self.folder:
                continue
            # 目标 folder 上锁的也不作为落点
            item_state = "disabled" if (locked or f.locked) else "normal"
            move_menu.add_command(
                label=f.name, state=item_state,
                command=lambda tf=f: self.app.move_card_to_folder(self, tf))
        # 独立区卡片不进文件夹分组，不提供"移动到文件夹"
        menu.add_cascade(label="移动到文件夹", menu=move_menu,
                         state="disabled" if standalone
                         else (state if len(self.app.folders) > 1
                               else "disabled"))
        menu.add_separator()
        menu.add_command(label="打开文件所在位置",
                         command=self._menu_open_location)
        menu.add_command(label="复制路径", command=self._menu_copy_path)
        menu.add_separator()
        menu.add_command(label="删除卡片", state=state,
                         command=self._on_delete)
        try:
            menu.tk_popup(e.x_root, e.y_root)
        finally:
            menu.grab_release()

    def _menu_rename(self):
        cur = self.custom_title or get_title_for_file(self.path)
        new = simpledialog.askstring(
            "重命名标题", "新标题（留空恢复文件名默认标题）：",
            initialvalue=cur, parent=self.app)
        if new is None:
            return  # 用户取消
        self.set_custom_title(new)
        self.app.save_state()

    def _menu_change_icon(self):
        p = filedialog.askopenfilename(
            title="选择图标图像",
            filetypes=[("图像文件", "*.ico;*.png;*.jpg;*.jpeg;*.bmp;*.gif"),
                       ("所有文件", "*.*")],
            parent=self.app)
        if not p:
            return
        if self.set_custom_icon(p):
            self.app.save_state()

    def _menu_refresh_icon(self):
        """删除该卡片的图标缓存条目并重新入队异步提取。
        解决"目标应用升级后卡片仍显示旧图标"（缓存 key 的 mtime 盲区）。"""
        if self.custom_icon or not HAS_WIN32:
            return
        icon_cache_remove(self.path)
        # 先回落占位图标，提取完成后由主线程轮询回填
        if self.app.default_icon_img is not None:
            self.set_extracted_icon(self.app.default_icon_img)
        self.app.request_icon(self)

    def _menu_edit_desc(self):
        new = simpledialog.askstring(
            "编辑描述", "描述：",
            initialvalue=self.desc_var.get(), parent=self.app)
        if new is None:
            return
        self.desc_var.set(new)
        self.app.save_state()

    def _menu_open_location(self):
        """在资源管理器中打开文件所在位置并选中该文件。"""
        p = self.path
        try:
            if os.path.exists(p):
                subprocess.Popen(
                    ["explorer", "/select,", os.path.normpath(p)])
            else:
                d = os.path.dirname(p)
                if os.path.isdir(d):
                    os.startfile(d)
                else:
                    messagebox.showwarning(
                        "无法打开", f"文件和所在目录都不存在：\n{p}")
        except Exception as e:
            messagebox.showerror("无法打开位置", f"{p}\n\n{e}")

    def _menu_copy_path(self):
        try:
            self.app.clipboard_clear()
            self.app.clipboard_append(self.path)
        except Exception:
            pass

    def _on_delete(self):
        # 所属文件夹上锁时禁止删除
        if self.folder is not None and getattr(self.folder, "locked", False):
            return
        self.app.remove_card(self)

    def _on_drag_start(self, e):
        if self.folder is not None and getattr(self.folder, "locked", False):
            return
        self.app.card_drag_start(self, e)

    def _on_drag_motion(self, e):
        if self.folder is not None and getattr(self.folder, "locked", False):
            return
        self.app.card_drag_motion(self, e)

    def _on_drag_end(self, e):
        if self.folder is not None and getattr(self.folder, "locked", False):
            return
        self.app.card_drag_end(self, e)

    def _on_double_click(self, e):
        # 上锁时唯一保留的行为：双击启动
        self.app.launch_card(self)

    # ---- 锁定状态可视化 ----
    def apply_lock_state(self, locked):
        """描述框改为只读、删除按钮禁用；双击/拖拽通过绑定内 flag 已拦截。"""
        state = "disabled" if locked else "normal"
        try:
            # Entry 用 readonly 可以保留内容可见，disabled 会变灰但也可
            self.desc_entry.configure(
                state="readonly" if locked else "normal"
            )
        except Exception:
            pass
        try:
            self.del_btn.configure(state=state)
        except Exception:
            pass
        # 光标反馈：拖拽把手/图标/标题不再显示 fleur 移动光标
        cursor = "arrow" if locked else "fleur"
        for w in (self, self.icon_label, self.title_label):
            try:
                w.configure(cursor=cursor)
            except Exception:
                pass

    # ---- 主题 ----
    def apply_theme(self):
        """按 app.theme 重刷本卡片配色（运行时深/浅色切换用）。"""
        th = self.app.theme
        try:
            self.configure(bg=th["card_bg"])
            self.icon_label.configure(bg=th["card_bg"])
            self.mid.configure(bg=th["card_bg"])
            self.title_label.configure(bg=th["card_bg"], fg=th["fg"])
            self.desc_entry.configure(
                bg=th["desc_bg"], fg=th["fg"],
                insertbackground=th["fg"],
                readonlybackground=th["desc_bg"])
            self.del_btn.configure(
                bg=th["card_bg"], fg=th["danger_fg"],
                activebackground=th["danger_active_bg"])
        except tk.TclError:
            pass


# ================================================================
# 文件夹
# ================================================================
class FolderFrame(tk.Frame):
    """一个文件夹 section：header（拖拽把手 + 名字 + 删除）+ 卡片 grid 容器。

    卡片的 tk parent 是 App.inner_frame，通过 grid(in_=body) 显示在这里；
    这样跨文件夹移动卡片时不用销毁 / 重建，也就不用重新提取图标。
    """

    # 每列宽度单位：卡片宽度 + 一点 padding 余量；从 app.card_width 动态取
    @property
    def _CARD_UNIT(self):
        return int(self.app.card_width) + 10

    def __init__(self, master, app, folder_id, name):
        th = app.theme
        super().__init__(master, bd=1, relief="solid", bg=th["folder_bg"])
        self.app = app
        self.id = folder_id
        self.name = name
        self.cards = []
        self._num_cols = 1
        self.locked = False  # 上锁时禁用名字编辑 / 卡片编辑 / 卡片拖拽 / 删除
        self.collapsed = False  # 折叠时隐藏卡片区（body），header 保留；与 locked 相互独立

        # ---- header（紧凑：小 padding，无冗余空间） ----
        header = tk.Frame(self, bg=th["header_bg"], padx=4, pady=1)
        header.pack(fill="x")
        self.header = header

        # 用小号字（约为 app 字体的 0.9 倍）让 header 更矮
        self._header_font = tkFont.Font(
            family=app.app_font.cget("family"),
            size=max(8, int(app.app_font.cget("size")) - 1)
        )

        self.drag_handle = tk.Label(
            header, text="\u2630", font=self._header_font,  # ☰
            bg=th["header_bg"], fg=th["fg"], cursor="fleur", padx=2
        )
        self.drag_handle.pack(side="left")

        self.name_var = tk.StringVar(value=name)
        self.name_entry = tk.Entry(
            header, textvariable=self.name_var,
            font=self._header_font, bd=0, bg=th["header_bg"],
            fg=th["fg"], insertbackground=th["fg"],
            readonlybackground=th["header_bg"],
            highlightthickness=0
        )
        self.name_entry.pack(side="left", fill="x", expand=True, padx=(2, 4))
        self.name_entry.bind("<FocusOut>", lambda e: self._on_rename())
        self.name_entry.bind("<Return>", lambda e: self._on_rename())

        # 上锁按钮：🔓/🔒 切换；点击调 toggle_lock
        self.lock_btn = tk.Button(
            header, text="\U0001F513",  # 🔓
            font=self._header_font, relief="flat", bd=0,
            bg=th["header_bg"], fg=th["header_fg"],
            activebackground=th["header_active_bg"],
            padx=4, pady=0,
            command=self._on_toggle_lock
        )
        self.lock_btn.pack(side="right", padx=(0, 2))

        # 折叠按钮：▾（展开中，点击收起）/ ▸（已收起，点击展开）；
        # 收起时隐藏整个卡片区（body），header 保留。与锁定相互独立。
        self.collapse_btn = tk.Button(
            header, text="\u25BE",  # ▾
            font=self._header_font, relief="flat", bd=0,
            bg=th["header_bg"], fg=th["header_fg"],
            activebackground=th["header_active_bg"],
            padx=4, pady=0,
            command=self._on_toggle_collapse
        )
        self.collapse_btn.pack(side="right", padx=(0, 2))

        # 用小号 ✕ 按钮替代原来的"删除文件夹"文本按钮，
        # 让 header 高度显著变矮；保留同样的悬停危险色反馈
        self.del_btn = tk.Button(
            header, text="\u2716",  # ✖
            font=self._header_font, relief="flat", bd=0,
            bg=th["header_bg"], fg=th["danger_fg"],
            activebackground=th["danger_active_bg"],
            padx=4, pady=0,
            command=self._on_delete
        )
        self.del_btn.pack(side="right")

        # ---- body（卡片 grid 容器；padding 也收紧） ----
        self.body = tk.Frame(self, bg=th["folder_bg"], padx=4, pady=3)
        self.body.pack(fill="both", expand=True)
        self.body.bind("<Configure>", self._on_body_configure)

        # ---- 拖拽 header 换文件夹顺序 ----
        for w in (header, self.drag_handle):
            w.bind("<ButtonPress-1>", self._on_folder_drag_start)
            w.bind("<B1-Motion>", self._on_folder_drag_motion)
            w.bind("<ButtonRelease-1>", self._on_folder_drag_end)

    def refresh_header_font(self):
        """app 字体变化时，让 header 内部小号字跟着刷新。"""
        try:
            self._header_font.configure(
                family=self.app.app_font.cget("family"),
                size=max(8, int(self.app.app_font.cget("size")) - 1)
            )
        except Exception:
            pass

    def apply_theme(self):
        """按 app.theme 重刷本文件夹配色（运行时深/浅色切换用）。"""
        th = self.app.theme
        try:
            self.configure(bg=th["folder_bg"])
            self.header.configure(bg=th["header_bg"])
            self.drag_handle.configure(bg=th["header_bg"], fg=th["fg"])
            self.name_entry.configure(
                bg=th["header_bg"], fg=th["fg"],
                insertbackground=th["fg"],
                readonlybackground=th["header_bg"])
            self.lock_btn.configure(
                bg=th["header_bg"], fg=th["header_fg"],
                activebackground=th["header_active_bg"])
            self.collapse_btn.configure(
                bg=th["header_bg"], fg=th["header_fg"],
                activebackground=th["header_active_bg"])
            self.del_btn.configure(
                bg=th["header_bg"], fg=th["danger_fg"],
                activebackground=th["danger_active_bg"])
            self.body.configure(bg=th["folder_bg"])
        except tk.TclError:
            pass

    # ---- 事件 ----
    def _on_rename(self):
        # 锁定时 name_entry 已是 disabled，正常不会走到这；作双保险
        if self.locked:
            if self.name_var.get() != self.name:
                self.name_var.set(self.name)
            return
        new_name = self.name_var.get().strip()
        if not new_name:
            self.name_var.set(self.name)
            return
        if new_name != self.name:
            self.name = new_name
            self.app.save_state()

    def _on_delete(self):
        if self.locked:
            return
        self.app.delete_folder(self)

    def _on_toggle_lock(self):
        self.set_locked(not self.locked)
        self.app.save_state()

    def set_locked(self, locked):
        """切换本 folder 的锁定态，并把状态传播到 header + 所有卡片。"""
        self.locked = bool(locked)
        # header 视觉：图标切换 + name_entry 禁用/启用 + 删除按钮禁用/启用
        try:
            self.lock_btn.configure(
                text="\U0001F512" if self.locked else "\U0001F513"  # 🔒 / 🔓
            )
        except Exception:
            pass
        try:
            # 用 readonly 保留文字可见与选取，但不允许键入
            self.name_entry.configure(
                state="readonly" if self.locked else "normal"
            )
        except Exception:
            pass
        try:
            self.del_btn.configure(
                state="disabled" if self.locked else "normal"
            )
        except Exception:
            pass
        # 传播到所有卡片
        for c in self.cards:
            try:
                c.apply_lock_state(self.locked)
            except Exception:
                pass

    def _on_toggle_collapse(self):
        self.set_collapsed(not self.collapsed)
        self.app.save_state()

    def set_collapsed(self, collapsed):
        """折叠/展开卡片区。header（含名字/锁/删除按钮）始终保留。"""
        self.collapsed = bool(collapsed)
        try:
            self.collapse_btn.configure(
                text="\u25B8" if self.collapsed else "\u25BE")  # ▸ / ▾
        except Exception:
            pass
        if self.collapsed:
            try:
                self.body.pack_forget()
            except Exception:
                pass
        else:
            try:
                self.body.pack(fill="both", expand=True)
            except Exception:
                pass
            # 展开后重排一次，保证卡片布局/列数与当前宽度一致
            try:
                self._reflow()
            except Exception:
                pass
        # 折叠/展开改变内容高度，但 inner_frame 是 canvas window item、
        # 高度未绑定内容，reqheight 变化不必然触发它的 <Configure>，
        # 滚动区可能停留在旧值。先结清挂起的几何计算（after_idle 时序
        # 不可靠——回调可能排在 packer 的几何重算之前跑），再主动重算
        try:
            self.app.update_idletasks()
            self.app._update_scrollregion()
        except Exception:
            pass

    def _on_folder_drag_start(self, e):
        # 文件夹之间仍可拖动（不受 lock 影响）
        self.app.folder_drag_start(self, e)

    def _on_folder_drag_motion(self, e):
        self.app.folder_drag_motion(self, e)

    def _on_folder_drag_end(self, e):
        self.app.folder_drag_end(self, e)

    def _on_body_configure(self, event):
        new_cols = self._compute_num_cols(event.width)
        if new_cols != self._num_cols:
            self._num_cols = new_cols
            self._reflow()

    def _compute_num_cols(self, body_width):
        return max(1, int(body_width) // self._CARD_UNIT)

    # ---- 卡片管理 ----
    def add_card(self, card):
        self.cards.append(card)
        card.folder = self
        try:
            card.apply_lock_state(self.locked)
        except Exception:
            pass
        self._reflow()

    def insert_card(self, card, pos):
        pos = max(0, min(pos, len(self.cards)))
        self.cards.insert(pos, card)
        card.folder = self
        try:
            card.apply_lock_state(self.locked)
        except Exception:
            pass
        self._reflow()

    def remove_card(self, card):
        if card in self.cards:
            self.cards.remove(card)
        self._reflow()

    def _reflow(self):
        """按当前 num_cols 把 cards 重排到 body 的 grid。"""
        # 视图切换批处理中禁止一切 update_idletasks：它是全局刷新，
        # 会把切换中途的半成品布局刷上屏（卡片新旧坐标混杂 → 肉眼可见
        # 的重叠残影）。宽度改从 inner_frame 直接读——canvas 通过
        # itemconfigure 恒同步其宽度，不需要等几何刷新
        batch = getattr(self.app, "_view_switch_batch", False)
        actual_w = 0
        if batch:
            try:
                mw = self.master.winfo_width()
                if mw > 24:
                    actual_w = mw - 24
            except Exception:
                pass
        if actual_w <= 1:
            # 先让 body 完成挂起的几何计算，读到真实宽度再决定列数；
            # 否则新建的空文件夹 body.winfo_width() 可能仍是 1，
            # 导致 _num_cols 停留在初始 1，且列 minsize=500 超出 body 实际宽度。
            try:
                self.body.update_idletasks()
            except Exception:
                pass
            actual_w = self.body.winfo_width()
            # body 刚 pack 完还未完成 fill 扩展时 winfo_width=1，
            # 逐级向上兜底：folder 自身宽度 → 上层 inner_frame 宽度。
            # 减去 body 的 padx=6 左右两侧共 12px。
            if actual_w <= 1:
                fw = self.winfo_width()
                if fw > 12:
                    actual_w = fw - 12
            if actual_w <= 1:
                try:
                    mw = self.master.winfo_width()
                    if mw > 24:
                        actual_w = mw - 24
                except Exception:
                    pass
        if actual_w > 1:
            self._num_cols = self._compute_num_cols(actual_w)

        # 无论 card 之前用的是 pack 还是 grid（且是否在别的 folder），
        # 都清一遍，避免 tk 拒绝在两个几何管理器之间切换的边角情况
        for c in self.cards:
            try:
                c.grid_forget()
            except Exception:
                pass
            try:
                c.pack_forget()
            except Exception:
                pass
        cw = int(self.app.card_width)
        for col in range(self._num_cols):
            self.body.grid_columnconfigure(col, minsize=cw, weight=0)
        # 收敛：清掉多余列的最小宽度配置
        for col in range(self._num_cols, self._num_cols + 8):
            self.body.grid_columnconfigure(col, minsize=0, weight=0)
        for i, c in enumerate(self.cards):
            r, col = i // self._num_cols, i % self._num_cols
            c.grid(row=r, column=col, in_=self.body,
                   padx=4, pady=4, sticky="ew")
            # tkinter 的 -in 参数只改显示位置，不改 stacking order。
            # card 的 tk parent 是 App.inner_frame，folder 也是。stacking
            # 顺序按创建时间：老 folder < 老 card < 新 folder < ...。
            # 如果 card 显示位置落在比它更"上层"的 folder.body 里，
            # 后绘制的 folder.body 会用自己的背景色覆盖 card → 卡片消失。
            # 每次 grid 后 tkraise 一下，把 card 顶到 inner_frame 最上层，
            # 保证任何后来创建的 folder.body 都画在它下面。
            try:
                c.tkraise()
            except Exception:
                pass
        # 强制立即完成布局（批处理时跳过，统一由 _refresh_view 末尾刷新）
        if not batch:
            try:
                self.update_idletasks()
            except Exception:
                pass
            # inner_frame 作为 canvas window item 的高度由 App 显式管理
            # （见 _update_scrollregion），内容高度变化不会自发触发它的
            # <Configure>——凡经过 _reflow 的增删/重排都在这里主动同步
            try:
                self.app._update_scrollregion()
            except Exception:
                pass


# ================================================================
# 主应用窗口
# ================================================================
# tkinterdnd2 可用时用 TkinterDnD.Tk 作基类（在 tk 解释器里加载 tkdnd
# 扩展，OLE 文件拖放才能生效）；缺失则回退 tk.Tk，功能自动禁用
_TK_BASE = TkinterDnD.Tk if HAS_DND else tk.Tk


class App(_TK_BASE):
    """QuickDeck 主窗口。
    数据模型：
      self.folders: List[FolderFrame]
      folder.cards: List[ShortcutCard]
      card.folder:  反向引用所属文件夹
    """

    DEFAULT_FOLDER_ID = "default"

    def __init__(self):
        super().__init__()
        self.title("QuickDeck")
        # 构建/加载期间隐藏窗口。_create_folder 里的 update() 会把事件循环
        # 整个跑一遍，若窗口此时可见就会把"卡片还堆在 1 列、宽度未分配"的
        # 中间态画出来（启动时闪现条状画面的根因）。全部就绪后再 deiconify。
        self.withdraw()

        self.cfg = load_config()
        load_local_font(LOCAL_FONT_FILE)

        # 主题模式：system（跟随系统，轮询注册表）/ light / dark（固定）
        self.theme_mode = self.cfg.get("theme_mode", "system")
        self.theme = self._resolve_theme()

        # _sanitize_config 已经把 window.* 保证为 int 且在合理范围；
        # 但配置里记的 x/y 可能对应已拔掉的显示器坐标（多屏用户）。
        # 用当前主屏尺寸做一次可见性校验：若窗口右下角完全在屏幕外，
        # 就把 x/y 重置到主屏可见范围内，避免"启动后窗口飞到看不见的地方"。
        wcfg = self.cfg["window"]
        w = int(wcfg["width"])
        h = int(wcfg["height"])
        x = int(wcfg["x"])
        y = int(wcfg["y"])
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        # 至少要有 100x60 的区域落在主屏内（覆盖大部分多屏边缘可拖回场景），
        # 否则视为不可见，重排到主屏居中
        visible_x_min = -w + 100
        visible_x_max = sw - 100
        visible_y_min = 0        # 顶部标题栏不能被裁掉
        visible_y_max = sh - 60
        if not (visible_x_min <= x <= visible_x_max
                and visible_y_min <= y <= visible_y_max):
            x = max(0, (sw - w) // 2)
            y = max(0, (sh - h) // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(560, 380)

        self.app_font = tkFont.Font(
            family=self.cfg["font"].get("family", BUILTIN_FONT_FAMILY),
            size=int(self.cfg["font"].get("size", 12))
        )
        # 卡片宽度（运行时可调，实时影响所有 folder 的 grid 列宽）
        try:
            self.card_width = int(self.cfg.get("card_width", 500))
        except (TypeError, ValueError):
            self.card_width = 500
        self.card_width = max(200, min(1200, self.card_width))

        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass

        self.default_icon_img = make_default_icon() if HAS_WIN32 else None

        # 状态
        self.folders = []
        self.dragging_card = None
        self.dragging_folder = None
        self._save_timer = None
        self._font_apply_timer = None
        # 视图模式："cards"（文件夹卡片视图）
        # / "usage"（按使用频率+最近启动的临时只读平铺视图）
        # / "web"（网页快捷方式独立存储区：.url 卡片不进文件夹，
        #   在该视图中单独存放，可拖拽排序/编辑/删除）
        # / "dirs"（文件夹快捷方式独立存储区：目录路径卡片，
        #   双击在资源管理器中打开，与 web 区同构）。
        # 视图选择不持久化，启动恒为 cards
        self.view_mode = "cards"
        self.web_cards = []   # 网页区卡片（独立于 folders，顺序即存储顺序）
        self.dir_cards = []   # 文件夹区卡片（同上，存目录路径）
        self._flat_cards = []
        self._flat_ncols = 1
        # 视图切换批处理标志：_refresh_view 全程为 True，抑制
        # _reflow / _reflow_flat 的中间 update_idletasks（防半成品
        # 布局上屏造成的卡片重叠残影），末尾统一刷新一次
        self._view_switch_batch = False
        # WM_SETREDRAW 冻结标志：_freeze_paint 置位，防嵌套冻结
        # 提前解冻（WM_SETREDRAW 无引用计数，内层 TRUE 会立即解除
        # 外层的冻结），见 _freeze_paint / _thaw_paint
        self._paint_frozen = False
        # 幕布标志：_show_paint_curtain 置位，防嵌套挂两层幕布
        # （_on_view_mode_change 与其内部的 _refresh_view 各有入口）
        self._curtain_active = False

        # 图标异步提取：worker 线程从 _icon_queue 取任务，
        # 提取结果放 _icon_results，由主线程定时轮询回填
        # （不在 worker 里直接碰 tk——tkinter 跨线程调用不安全）
        self._icon_queue = queue.Queue()
        self._icon_results = queue.Queue()
        self._icon_worker = threading.Thread(
            target=self._icon_worker_main, daemon=True,
            name="QuickDeckIconWorker")
        self._icon_worker.start()
        self.after(120, self._poll_icon_results)

        self._build_ui()
        self._apply_style_font()
        self._apply_style_theme()
        self._apply_titlebar_dark()
        self._apply_class_bg_brush()
        self.after(5000, self._poll_theme_change)

        if not HAS_WIN32:
            messagebox.showwarning(
                "缺少依赖",
                "未检测到 pywin32 / Pillow，图标提取与卡片功能已禁用。\n\n"
                "请执行：\n  pip install pywin32 Pillow\n\n"
                f"错误详情：{_IMPORT_ERR}"
            )
            self.add_btn.configure(state="disabled")
            self.multi_add_btn.configure(state="disabled")
            self.add_dir_btn.configure(state="disabled")
            self.multi_add_dir_btn.configure(state="disabled")
            self.new_folder_btn.configure(state="disabled")
        else:
            self._load_from_config()

        self.bind("<Configure>", self._on_window_configure)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # 文件拖放进窗口即添加（tkinterdnd2 可用且 win32 功能未禁用时）
        if HAS_DND and HAS_WIN32:
            try:
                self.drop_target_register(DND_FILES)
                self.dnd_bind("<<Drop>>", self._on_file_drop)
            except Exception as e:
                print(f"[QuickDeck] dnd register failed: {e}",
                      file=sys.stderr)

        # 与开头的 withdraw 配对：先结清所有挂起的几何计算，
        # 保证显示出来的第一帧就是完整布局
        try:
            self.update_idletasks()
        except Exception:
            pass
        self.deiconify()

    # ============================================================
    # 图标异步提取
    # ============================================================
    def request_icon(self, card):
        """把卡片入队，由 worker 线程提取真实图标。"""
        self._icon_queue.put(card)

    def _icon_worker_main(self):
        """worker 线程主循环：提取图标 → 写缓存 → 结果入队。
        只读 card.path（str，不可变），不触碰任何 tk 对象。"""
        _ensure_com()  # per-thread COM 初始化（thread-local 记录）
        while True:
            card = self._icon_queue.get()
            if card is None:  # 预留退出信号
                break
            try:
                path = card.path
                pil = icon_cache_get(path)
                if pil is None:
                    pil = get_icon_for_file(path)
                    if pil is not None:
                        icon_cache_put(path, pil)
                if pil is not None:
                    self._icon_results.put((card, pil))
            except Exception as e:
                print(f"[QuickDeck] icon worker error: {e}",
                      file=sys.stderr)

    def _poll_icon_results(self):
        """主线程轮询提取结果，回填到仍然存活的卡片上。"""
        try:
            while True:
                card, pil = self._icon_results.get_nowait()
                try:
                    if card.winfo_exists():
                        card.set_extracted_icon(pil)
                except tk.TclError:
                    pass  # 卡片已销毁
        except queue.Empty:
            pass
        self.after(120, self._poll_icon_results)

    # ============================================================
    # 文件拖放
    # ============================================================
    def _on_file_drop(self, event):
        """资源管理器拖文件到窗口：按类型路由——
        目录进文件夹快捷方式区，.url 进网页区，其余进最后一个文件夹。"""
        try:
            # event.data 是 Tcl 列表格式，含空格路径会被 {} 包住
            paths = self.tk.splitlist(event.data)
        except Exception:
            return
        target = self.folders[-1] if self.folders else None
        added = 0
        for p in paths:
            if not p:
                continue
            # 目录由 _add_card 路由到 dir_cards 独立区
            if self._add_card(p, "", folder=target):
                added += 1
        if added:
            self.save_state()

    # ============================================================
    # 便捷 accessors
    # ============================================================
    @property
    def all_cards(self):
        return [c for f in self.folders for c in f.cards]

    @property
    def every_card(self):
        """文件夹分组区 + 网页区 + 文件夹快捷方式区全部卡片
        （去重、主题、usage 排序用）。"""
        return self.all_cards + self.web_cards + self.dir_cards

    def folder_by_id(self, fid):
        for f in self.folders:
            if f.id == fid:
                return f
        return None

    # ============================================================
    # UI 构建
    # ============================================================
    def _build_ui(self):
        th = self.theme
        self.configure(bg=th["app_bg"])

        bottom = tk.Frame(self, bg=th["app_bg"])
        bottom.pack(side="bottom", fill="x")
        self.bottom_frame = bottom

        # 全局字体设置卡片
        font_card = tk.Frame(bottom, bd=1, relief="solid",
                             padx=8, pady=6, bg=th["panel_bg"])
        font_card.pack(side="bottom", fill="x", padx=8, pady=(0, 8))
        self.font_card = font_card
        self._panel_labels = []

        lbl = tk.Label(font_card, text="全局字体：",
                       font=self.app_font, bg=th["panel_bg"], fg=th["fg"])
        lbl.pack(side="left")
        self._panel_labels.append(lbl)
        self.font_family_var = tk.StringVar(value=self.app_font.cget("family"))
        families = sorted({f for f in tkFont.families() if f.strip()})
        for extra in (BUILTIN_FONT_FAMILY, self.app_font.cget("family")):
            if extra and extra not in families:
                families.append(extra)
        families.sort()
        self.font_family_cb = ttk.Combobox(
            font_card, textvariable=self.font_family_var,
            values=families, width=26
        )
        self.font_family_cb.pack(side="left", padx=(4, 12))
        self.font_family_cb.bind("<<ComboboxSelected>>", self._on_font_change)
        self.font_family_cb.bind("<Return>", self._on_font_change)
        self.font_family_cb.bind("<FocusOut>", self._on_font_change)

        lbl = tk.Label(font_card, text="字号：",
                       font=self.app_font, bg=th["panel_bg"], fg=th["fg"])
        lbl.pack(side="left")
        self._panel_labels.append(lbl)
        self.font_size_var = tk.StringVar(
            value=str(int(self.app_font.cget("size"))))
        self.font_size_spin = tk.Spinbox(
            font_card, from_=8, to=36, width=5,
            textvariable=self.font_size_var,
            font=self.app_font, command=self._on_font_change,
            bg=th["desc_bg"], fg=th["fg"], insertbackground=th["fg"],
            buttonbackground=th["btn_bg"]
        )
        self.font_size_spin.pack(side="left", padx=4)
        self.font_size_spin.bind("<KeyRelease>", self._on_font_change)
        self.font_size_spin.bind("<FocusOut>", self._on_font_change)

        # 卡片宽度调节
        lbl = tk.Label(font_card, text="卡片宽度：",
                       font=self.app_font, bg=th["panel_bg"], fg=th["fg"])
        lbl.pack(side="left", padx=(12, 0))
        self._panel_labels.append(lbl)
        self.card_width_var = tk.StringVar(value=str(int(self.card_width)))
        # tk.Spinbox 的箭头默认只在按下瞬间触发一次，长按不连续；
        # 这里保留 Spinbox 作为可键盘输入/单击的入口，但另外把两个自定义
        # 小箭头贴在旁边，用 ButtonPress/ButtonRelease + after 实现按住连续变化
        self.card_width_spin = tk.Spinbox(
            font_card, from_=200, to=1200, width=6,
            textvariable=self.card_width_var,
            font=self.app_font, command=self._on_card_width_change,
            increment=1,
            bg=th["desc_bg"], fg=th["fg"], insertbackground=th["fg"],
            buttonbackground=th["btn_bg"]
        )
        self.card_width_spin.pack(side="left", padx=(4, 0))
        self.card_width_spin.bind("<KeyRelease>",
                                  self._on_card_width_change)
        self.card_width_spin.bind("<FocusOut>",
                                  self._on_card_width_change)
        # 状态：长按定时器 + 当前方向
        self._cw_repeat_after = None
        self._cw_repeat_dir = 0
        arrow_up = tk.Button(
            font_card, text="\u25B2",  # ▲
            font=self._make_small_font(), relief="flat", bd=1,
            padx=2, pady=0, width=2, takefocus=0,
            bg=th["btn_bg"], fg=th["fg"],
            activebackground=th["btn_active_bg"], activeforeground=th["fg"]
        )
        arrow_up.pack(side="left", padx=(2, 0))
        arrow_dn = tk.Button(
            font_card, text="\u25BC",  # ▼
            font=self._make_small_font(), relief="flat", bd=1,
            padx=2, pady=0, width=2, takefocus=0,
            bg=th["btn_bg"], fg=th["fg"],
            activebackground=th["btn_active_bg"], activeforeground=th["fg"]
        )
        arrow_dn.pack(side="left", padx=(2, 0))
        arrow_up.bind("<ButtonPress-1>",
                      lambda e: self._cw_repeat_begin(+1))
        arrow_up.bind("<ButtonRelease-1>",
                      lambda e: self._cw_repeat_end())
        arrow_dn.bind("<ButtonPress-1>",
                      lambda e: self._cw_repeat_begin(-1))
        arrow_dn.bind("<ButtonRelease-1>",
                      lambda e: self._cw_repeat_end())
        self.card_width_arrow_up = arrow_up
        self.card_width_arrow_dn = arrow_dn

        # 主题模式选择（浅色 / 深色 / 跟随系统）
        lbl = tk.Label(font_card, text="主题：",
                       font=self.app_font, bg=th["panel_bg"], fg=th["fg"])
        lbl.pack(side="left", padx=(12, 0))
        self._panel_labels.append(lbl)
        self._THEME_MODE_LABELS = {
            "system": "跟随系统", "light": "浅色", "dark": "深色"}
        self._THEME_MODE_BY_LABEL = {
            v: k for k, v in self._THEME_MODE_LABELS.items()}
        self.theme_mode_var = tk.StringVar(
            value=self._THEME_MODE_LABELS.get(self.theme_mode, "跟随系统"))
        self.theme_mode_cb = ttk.Combobox(
            font_card, textvariable=self.theme_mode_var,
            values=["跟随系统", "浅色", "深色"],
            state="readonly", width=8
        )
        self.theme_mode_cb.pack(side="left", padx=(4, 0))
        self.theme_mode_cb.bind("<<ComboboxSelected>>",
                                self._on_theme_mode_change)

        # 视图切换（卡片视图 / 按使用排序 / 网页快捷方式 / 文件夹快捷方式）
        lbl = tk.Label(font_card, text="视图：",
                       font=self.app_font, bg=th["panel_bg"], fg=th["fg"])
        lbl.pack(side="left", padx=(12, 0))
        self._panel_labels.append(lbl)
        self._VIEW_MODE_LABELS = {
            "cards": "卡片视图", "usage": "按使用排序",
            "web": "网页快捷方式", "dirs": "文件夹快捷方式"}
        self._VIEW_MODE_BY_LABEL = {
            v: k for k, v in self._VIEW_MODE_LABELS.items()}
        self.view_mode_var = tk.StringVar(
            value=self._VIEW_MODE_LABELS["cards"])
        self.view_mode_cb = ttk.Combobox(
            font_card, textvariable=self.view_mode_var,
            values=["卡片视图", "按使用排序", "网页快捷方式", "文件夹快捷方式"],
            state="readonly", width=14
        )
        self.view_mode_cb.pack(side="left", padx=(4, 0))
        self.view_mode_cb.bind("<<ComboboxSelected>>",
                               self._on_view_mode_change)

        # 工具栏
        toolbar = tk.Frame(bottom, bg=th["app_bg"])
        toolbar.pack(side="bottom", fill="x", padx=8, pady=(6, 0))
        self.toolbar = toolbar

        self.add_btn = tk.Button(
            toolbar, text="添加快捷方式",
            font=self.app_font, command=self._on_add,
            padx=10, pady=4,
            bg=th["btn_bg"], fg=th["fg"],
            activebackground=th["btn_active_bg"], activeforeground=th["fg"]
        )
        self.add_btn.pack(side="left")

        self.multi_add_btn = tk.Button(
            toolbar, text="多选添加快捷方式",
            font=self.app_font, command=self._on_multi_add,
            padx=10, pady=4,
            bg=th["btn_bg"], fg=th["fg"],
            activebackground=th["btn_active_bg"], activeforeground=th["fg"]
        )
        self.multi_add_btn.pack(side="left", padx=(8, 0))

        self.new_folder_btn = tk.Button(
            toolbar, text="新建文件夹",
            font=self.app_font, command=self._on_new_folder,
            padx=10, pady=4,
            bg=th["btn_bg"], fg=th["fg"],
            activebackground=th["btn_active_bg"], activeforeground=th["fg"]
        )
        self.new_folder_btn.pack(side="left", padx=(8, 0))

        self.add_dir_btn = tk.Button(
            toolbar, text="添加文件夹快捷方式",
            font=self.app_font, command=self._on_add_dir,
            padx=10, pady=4,
            bg=th["btn_bg"], fg=th["fg"],
            activebackground=th["btn_active_bg"], activeforeground=th["fg"]
        )
        self.add_dir_btn.pack(side="left", padx=(8, 0))

        self.multi_add_dir_btn = tk.Button(
            toolbar, text="多选添加文件夹快捷方式",
            font=self.app_font, command=self._on_multi_add_dir,
            padx=10, pady=4,
            bg=th["btn_bg"], fg=th["fg"],
            activebackground=th["btn_active_bg"], activeforeground=th["fg"]
        )
        self.multi_add_dir_btn.pack(side="left", padx=(8, 0))

        self.open_dir_btn = tk.Button(
            toolbar, text="打开程序目录",
            font=self.app_font, command=self._on_open_app_dir,
            padx=10, pady=4,
            bg=th["btn_bg"], fg=th["fg"],
            activebackground=th["btn_active_bg"], activeforeground=th["fg"]
        )
        self.open_dir_btn.pack(side="left", padx=(8, 0))
        # 工具栏按钮按当前视图显隐（构建完成后立即按 cards 视图整理）
        self._update_toolbar_buttons()

        # 可滚动列表
        list_wrap = tk.Frame(self, bg=th["app_bg"])
        list_wrap.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        self.list_wrap = list_wrap

        self.canvas = tk.Canvas(list_wrap, highlightthickness=0,
                                bg=th["app_bg"])
        self.canvas.pack(side="left", fill="both", expand=True)

        self.scrollbar = ttk.Scrollbar(
            list_wrap, orient="vertical", command=self.canvas.yview
        )
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.inner_frame = tk.Frame(self.canvas, bg=th["app_bg"])
        self.inner_window = self.canvas.create_window(
            (0, 0), window=self.inner_frame, anchor="nw"
        )
        self.inner_frame.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        # 临时平铺视图容器（按使用排序 / 网页快捷方式 / 文件夹快捷方式共用）。
        # 与 folder 同为 inner_frame 的直接子级，卡片 grid(in_=) 进来即可，
        # 切回卡片视图时 pack_forget 隐藏。空标签在视图无卡片时提示，
        # 文案随 view_mode 在 _reflow_flat 里切换
        self.flat_view = tk.Frame(self.inner_frame, bg=th["folder_bg"],
                                  padx=4, pady=3)
        self.flat_view.bind("<Configure>", self._on_flat_configure)
        self._FLAT_EMPTY_TEXT = {
            "web": "（没有 .url 网页快捷方式）",
            "dirs": "（没有文件夹快捷方式）",
            "usage": "（没有任何卡片）"}
        self._flat_empty_label = tk.Label(
            self.flat_view, text=self._FLAT_EMPTY_TEXT["web"],
            font=self.app_font, bg=th["folder_bg"], fg=th["fg"])

    def _apply_style_font(self):
        fam = self.app_font.cget("family")
        sz = int(self.app_font.cget("size"))
        tup = (fam, sz)
        for name in ("TCombobox", "TButton", "TLabel",
                     "TEntry", "TSpinbox"):
            try:
                self.style.configure(name, font=tup)
            except tk.TclError:
                pass
        self.option_add("*TCombobox*Listbox.font", tup)
        if hasattr(self, "font_family_cb"):
            try:
                self.font_family_cb.configure(font=tup)
            except tk.TclError:
                pass

    # ============================================================
    # 主题（深/浅色）
    # ============================================================
    def _apply_style_theme(self):
        """ttk 控件（Combobox / Scrollbar）按当前主题配色。"""
        th = self.theme
        try:
            self.style.configure(
                "TCombobox",
                fieldbackground=th["desc_bg"], background=th["btn_bg"],
                foreground=th["fg"], arrowcolor=th["fg"])
            self.style.map(
                "TCombobox",
                fieldbackground=[("readonly", th["desc_bg"])],
                foreground=[("readonly", th["fg"])])
            self.style.configure(
                "Vertical.TScrollbar",
                background=th["btn_bg"], troughcolor=th["app_bg"],
                arrowcolor=th["fg"])
            # 下拉列表（非 ttk 部分）用 option_add
            self.option_add("*TCombobox*Listbox.background", th["desc_bg"])
            self.option_add("*TCombobox*Listbox.foreground", th["fg"])
        except tk.TclError:
            pass

    def _apply_class_bg_brush(self):
        """把 Tk 窗口类的背景刷设为主题底色（best-effort）。

        Tk 在 Windows 上注册的窗口类 hbrBackground 为 NULL：收到
        WM_ERASEBKGND 时 DefWindowProc 不做任何填充，真正的内容绘制
        推迟到 Tk 的 idle 回调。Win11 会在窗口最小化时丢弃 DWM 合成
        表面，恢复时表面为全黑，在几百个控件的 idle 重绘逐个完成前
        直接露出黑色（"恢复最小化时黑边一闪"的根因）。

        给窗口类挂上主题色实心刷后，系统级曝光（恢复、遮挡后露出）
        的擦除阶段会先填主题色，黑闪变为同色填充=不可见；Tk 内部
        重绘用 InvalidateRect(..., FALSE) 不触发擦除，平时行为不变。

        SetClassLongPtr 按"窗口类"生效：Tk 所有子控件共用 TkChild
        类、顶层 wrapper 用独立类，各设一次即覆盖全部窗口。
        """
        try:
            th = self.theme["app_bg"]  # "#RRGGBB"
            colorref = (int(th[1:3], 16)
                        | int(th[3:5], 16) << 8
                        | int(th[5:7], 16) << 16)  # COLORREF = 0x00BBGGRR
            gdi32 = ctypes.windll.gdi32
            user32 = ctypes.windll.user32
            new_brush = gdi32.CreateSolidBrush(colorref)
            if not new_brush:
                return
            # 64 位下必须用 SetClassLongPtrW 并声明指针宽度的签名，
            # 否则句柄被截断；32 位 Python 无此符号，回退 SetClassLongW
            set_cls = getattr(user32, "SetClassLongPtrW", None) \
                or user32.SetClassLongW
            set_cls.restype = ctypes.c_ssize_t
            set_cls.argtypes = [ctypes.c_ssize_t, ctypes.c_int,
                                ctypes.c_ssize_t]
            GCLP_HBRBACKGROUND = -10
            self.update_idletasks()
            child = self.winfo_id()                 # TkChild 类
            top = user32.GetParent(child)           # 顶层 wrapper 类
            for hwnd in {child, top}:
                if hwnd:
                    set_cls(hwnd, GCLP_HBRBACKGROUND, new_brush)
            # 释放上一次主题切换时创建的旧刷子（类已不再引用它）
            old = getattr(self, "_bg_brush", None)
            if old:
                gdi32.DeleteObject(old)
            self._bg_brush = new_brush
        except Exception:
            pass

    def _apply_titlebar_dark(self):
        """Windows 10 1809+ / 11：让标题栏跟随深色主题（best-effort）。

        只在目标值与上次实际写入的值不同时才调用 DWM。浅色是系统默认，
        从未进过深色就完全不碰该属性——Win11 上给窗口写过
        DWMWA_USE_IMMERSIVE_DARK_MODE（即使值为 0）后，窗口会走深浅色
        感知的合成路径，最小化恢复时未完成重绘的区域会先被合成为黑色
        （浅色模式下"卡片间隙黑边一闪"的根因）。
        """
        want = 0 if self.theme is LIGHT_THEME else 1
        if want == getattr(self, "_titlebar_dark_val", 0):
            return
        try:
            self.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            val = ctypes.c_int(want)
            # 20 = DWMWA_USE_IMMERSIVE_DARK_MODE；旧版本 build 用 19
            for attr in (20, 19):
                r = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(val), ctypes.sizeof(val))
                if r == 0:
                    self._titlebar_dark_val = want
                    break
        except Exception:
            pass

    def apply_theme(self, theme):
        """运行时切换整套主题：App 级控件 + 所有 folder + 所有 card。

        幕布防黑边：主题切换与视图切换是同一类绘制时序问题——几十个
        控件逐个 reconfigure 的重绘是渐进的，中途 _apply_titlebar_dark
        切换 DWMWA_USE_IMMERSIVE_DARK_MODE 还会触发 DWM 合成路径重建，
        把尚未完成重绘的客户区区域合成为黑色（切换瞬间的黑边）。复用
        _show_paint_curtain 盖住全程，重绘与 DWM 重建都在幕布下完成，
        撤幕即完整新主题帧。"""
        curtain = self._show_paint_curtain()
        try:
            self._apply_theme_body(theme)
            if curtain:
                # 幕布之下把全部控件的重绘做完再撤幕
                try:
                    self.update()
                except Exception:
                    pass
        finally:
            self._hide_paint_curtain(curtain)

    def _apply_theme_body(self, theme):
        self.theme = theme
        th = theme
        try:
            self.configure(bg=th["app_bg"])
            self.bottom_frame.configure(bg=th["app_bg"])
            self.toolbar.configure(bg=th["app_bg"])
            self.list_wrap.configure(bg=th["app_bg"])
            self.canvas.configure(bg=th["app_bg"])
            self.inner_frame.configure(bg=th["app_bg"])
            self.flat_view.configure(bg=th["folder_bg"])
            self._flat_empty_label.configure(bg=th["folder_bg"],
                                             fg=th["fg"])
            self.font_card.configure(bg=th["panel_bg"])
            for lbl in self._panel_labels:
                lbl.configure(bg=th["panel_bg"], fg=th["fg"])
            for spin in (self.font_size_spin, self.card_width_spin):
                spin.configure(bg=th["desc_bg"], fg=th["fg"],
                               insertbackground=th["fg"],
                               buttonbackground=th["btn_bg"])
            for btn in (self.add_btn, self.multi_add_btn,
                        self.new_folder_btn, self.add_dir_btn,
                        self.multi_add_dir_btn, self.open_dir_btn,
                        self.card_width_arrow_up, self.card_width_arrow_dn):
                btn.configure(bg=th["btn_bg"], fg=th["fg"],
                              activebackground=th["btn_active_bg"],
                              activeforeground=th["fg"])
        except tk.TclError:
            pass
        self._apply_style_theme()
        self._apply_titlebar_dark()
        self._apply_class_bg_brush()
        for f in self.folders:
            try:
                f.apply_theme()
            except Exception:
                pass
        for c in self.every_card:
            try:
                c.apply_theme()
            except Exception:
                pass

    def _resolve_theme(self):
        """按当前 theme_mode 解析出应使用的主题 dict。"""
        if self.theme_mode == "light":
            return LIGHT_THEME
        if self.theme_mode == "dark":
            return DARK_THEME
        return LIGHT_THEME if system_prefers_light() else DARK_THEME

    def _on_theme_mode_change(self, event=None):
        mode = self._THEME_MODE_BY_LABEL.get(
            self.theme_mode_var.get(), "system")
        if mode == self.theme_mode:
            return
        self.theme_mode = mode
        want = self._resolve_theme()
        if want is not self.theme:
            self.apply_theme(want)
        self.save_state()  # 主题没变也要把模式选择持久化

    def _poll_theme_change(self):
        """每 5 秒查一次注册表；仅"跟随系统"模式下响应系统深/浅色变化。"""
        if self.theme_mode == "system":
            want = self._resolve_theme()
            if want is not self.theme:
                self.apply_theme(want)
        self.after(5000, self._poll_theme_change)

    # ============================================================
    # 视图切换（卡片视图 / 按使用排序 / 网页快捷方式 / 文件夹快捷方式）
    # ============================================================
    def _on_view_mode_change(self, event=None):
        mode = self._VIEW_MODE_BY_LABEL.get(
            self.view_mode_var.get(), "cards")
        if mode == self.view_mode:
            return
        self.view_mode = mode
        # 三层防残影（见 _show_paint_curtain / _freeze_paint）：
        # 幕布原位盖住旧帧 → 冻结中完成几何重建（含工具栏 repack）→
        # 幕布之下把切换排队的事件与逐 widget 重绘全部做完 → 撤幕
        curtain = self._show_paint_curtain()
        try:
            frozen = self._freeze_paint()
            try:
                self._update_toolbar_buttons()
                self._refresh_view()
            finally:
                self._thaw_paint(frozen)
            if curtain:
                # update() 处理完 <Configure> 触发的二次 reflow 与全部
                # Expose 绘制后返回，撤幕露出的即完整新帧
                try:
                    self.update()
                except Exception:
                    pass
        finally:
            self._hide_paint_curtain(curtain)

    def _update_toolbar_buttons(self):
        """工具栏按钮按当前视图显隐：
        cards：添加 / 多选添加 / 新建文件夹 / 打开程序目录；
        usage：只留打开程序目录（临时只读视图，无添加语义）；
        web：添加 / 多选添加 / 打开程序目录（文件对话框含 .url 过滤）；
        dirs：添加文件夹快捷方式 / 多选添加文件夹快捷方式 / 打开程序目录。"""
        visible = {
            "cards": (self.add_btn, self.multi_add_btn,
                      self.new_folder_btn, self.open_dir_btn),
            "usage": (self.open_dir_btn,),
            "web": (self.add_btn, self.multi_add_btn, self.open_dir_btn),
            "dirs": (self.add_dir_btn, self.multi_add_dir_btn,
                     self.open_dir_btn),
        }.get(self.view_mode, (self.open_dir_btn,))
        all_btns = (self.add_btn, self.multi_add_btn, self.new_folder_btn,
                    self.add_dir_btn, self.multi_add_dir_btn,
                    self.open_dir_btn)
        for b in all_btns:
            try:
                b.pack_forget()
            except tk.TclError:
                pass
        # 按固定顺序重新 pack，保证按钮排列稳定
        first = True
        for b in all_btns:
            if b not in visible:
                continue
            b.pack(side="left", padx=(0 if first else 8, 0))
            first = False

    def _flat_card_list(self):
        """当前平铺视图应显示的卡片列表。
        usage：三个存储区全部卡片按使用排序（临时只读视图）；
        web / dirs：对应独立存储区的存储顺序本身（可拖拽排序）。"""
        if self.view_mode == "usage":
            # 使用频率优先，同频次按最近启动；从未启动过的排最后
            return sorted(
                self.every_card,
                key=lambda c: (-c.launch_count, -c.last_launch_ts))
        if self.view_mode == "web":
            return list(self.web_cards)
        if self.view_mode == "dirs":
            return list(self.dir_cards)
        return []

    # WM_SETREDRAW / RedrawWindow 常量
    _WM_SETREDRAW = 0x000B
    _RDW_REPAINT = 0x0001 | 0x0004 | 0x0080 | 0x0100  # INVALIDATE|ERASE|ALLCHILDREN|UPDATENOW

    def _freeze_paint(self):
        """WM_SETREDRAW(FALSE)：冻结客户区 HWND 及其全部子 HWND 的屏幕
        更新，屏幕定格当前画面。

        视图切换重叠残影的真正根因在 Win32 层：Tk 在 Windows 上每个
        widget 都是独立 HWND，一次 update_idletasks 内部对每张卡片逐个
        SetWindowPos，其屏幕效果是立即的——系统把该窗口现有像素 bitblt
        到新位置，腾出的旧区域只标记 invalidate，擦除要等回到 mainloop
        处理 WM_PAINT 之后。窗口期内"新位置卡片 + 旧位置陈旧像素"同屏，
        即同一张卡片出现两次的重叠画面。因此无论把 Tcl 层 flush 压缩到
        几次都无效（_view_switch_batch 只解决了多帧半成品布局问题）。
        冻结期间 SetWindowPos 只改几何不上屏，几何计算（winfo_* /
        update_idletasks）完全不受影响。

        返回冻结的 hwnd（交给 _thaw_paint），已冻结（嵌套调用）或
        失败时返回 None——WM_SETREDRAW 无引用计数，嵌套必须由外层
        统一解冻。"""
        if self._paint_frozen:
            return None
        try:
            hwnd = self.winfo_id()  # 客户区 HWND（wrapper 的子窗口）
            ctypes.windll.user32.SendMessageW(
                hwnd, self._WM_SETREDRAW, 0, 0)
        except Exception:
            return None
        self._paint_frozen = True
        return hwnd

    def _thaw_paint(self, hwnd):
        """WM_SETREDRAW(TRUE) + RedrawWindow(RDW_ALLCHILDREN)：解冻并
        令整棵子树一次性重绘——屏幕从完整旧帧直接切到完整新帧。
        hwnd 为 None（嵌套冻结的内层 / 冻结失败）时不做任何事。"""
        if not hwnd:
            return
        self._paint_frozen = False
        try:
            user32 = ctypes.windll.user32
            user32.SendMessageW(hwnd, self._WM_SETREDRAW, 1, 0)
            user32.RedrawWindow(hwnd, None, None, self._RDW_REPAINT)
        except Exception:
            pass

    # 幕布窗口常量
    _CURTAIN_STYLE = 0x80000000 | 0x10000000 | 0x0000000E  # WS_POPUP|WS_VISIBLE|SS_BITMAP
    _CURTAIN_EXSTYLE = 0x08000000 | 0x00000080  # WS_EX_NOACTIVATE|WS_EX_TOOLWINDOW
    _STM_SETIMAGE = 0x0172
    _SRCCOPY = 0x00CC0020

    def _show_paint_curtain(self):
        """截取客户区当前像素，用原生 Win32 STATIC 位图弹窗原位盖住。

        防残影第三层（根治）。WM_SETREDRAW 冻结只解决了布局期间
        SetWindowPos 的即时 bitblt 上屏；但解冻时 RedrawWindow(UPDATENOW)
        发出的 WM_PAINT 在 Tk 里并不同步绘制——Tk 的窗口过程只是
        BeginPaint/EndPaint 把区域 validate 掉、转成 Expose 事件排队，
        真正的像素绘制要回到 mainloop 后逐 widget 在 idle 阶段完成。
        因此解冻瞬间屏幕仍是定格的旧帧，新帧是随后逐块画上去的，
        旧像素与新位置卡片混杂的窗口期依旧存在 → 残影未消。

        幕布方案与绘制时序彻底解耦：切换前把客户区现有像素 BitBlt 进
        内存位图，创建一个原生 STATIC(SS_BITMAP) 弹窗原位盖住客户区
        （owner 为顶层 wrapper，天然压在本窗口之上；WS_EX_NOACTIVATE
        不抢焦点；STATIC 在 WM_PAINT 里同步绘制，UpdateWindow 立即
        上屏，与旧帧逐像素相同 → 盖上的瞬间无任何视觉变化）。DWM 下
        被遮挡的窗口照常把新帧画进自己的合成表面，等切换与全部重绘
        在幕布下做完再撤幕，露出的直接就是完整新帧。

        返回 (幕布 hwnd, HBITMAP) 交给 _hide_paint_curtain；已有幕布
        （嵌套）、窗口未映射或任何 Win32 调用失败时返回 None（调用方
        退化为仅冻结方案）。"""
        if self._curtain_active:
            return None
        # 本方法可能先于任何图标提取被调用（首次视图切换），argtypes
        # 未声明时 CreateWindowExW 的 style（高位置位）会溢出 c_int
        _init_win_apis()
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        hbm = None
        try:
            if not self.winfo_ismapped():
                return None
            hwnd = self.winfo_id()
            w, h = int(self.winfo_width()), int(self.winfo_height())
            x, y = int(self.winfo_rootx()), int(self.winfo_rooty())
            if w <= 1 or h <= 1:
                return None
            # 1) 客户区当前像素 → 内存位图（DWM 重定向表面不受遮挡影响）
            hdc = user32.GetDC(hwnd)
            if not hdc:
                return None
            ok = 0
            try:
                mdc = gdi32.CreateCompatibleDC(hdc)
                if not mdc:
                    return None
                try:
                    hbm = gdi32.CreateCompatibleBitmap(hdc, w, h)
                    if hbm:
                        old = gdi32.SelectObject(mdc, hbm)
                        ok = gdi32.BitBlt(mdc, 0, 0, w, h,
                                          hdc, 0, 0, self._SRCCOPY)
                        gdi32.SelectObject(mdc, old)
                finally:
                    gdi32.DeleteDC(mdc)
            finally:
                user32.ReleaseDC(hwnd, hdc)
            if not (hbm and ok):
                raise OSError("curtain capture failed")
            # 2) 原生位图弹窗原位盖住客户区并立即同步上屏
            owner = user32.GetParent(hwnd) or hwnd
            hinst = ctypes.windll.kernel32.GetModuleHandleW(None)
            cw = user32.CreateWindowExW(
                self._CURTAIN_EXSTYLE, "STATIC", None, self._CURTAIN_STYLE,
                x, y, w, h, owner, None, hinst, None)
            if not cw:
                raise OSError("curtain window failed")
            user32.SendMessageW(cw, self._STM_SETIMAGE, 0, hbm)
            user32.UpdateWindow(cw)
            self._curtain_active = True
            return (cw, hbm)
        except Exception as e:
            print(f"[QuickDeck] paint curtain fallback: {e!r}",
                  file=sys.stderr)
            if hbm:
                try:
                    gdi32.DeleteObject(hbm)
                except Exception:
                    pass
            return None

    def _hide_paint_curtain(self, curtain):
        """撤幕并释放截屏位图。curtain 为 None（嵌套/失败）时不做任何事。"""
        if not curtain:
            return
        self._curtain_active = False
        cw, hbm = curtain
        try:
            ctypes.windll.user32.DestroyWindow(cw)
        except Exception:
            pass
        try:
            ctypes.windll.gdi32.DeleteObject(hbm)
        except Exception:
            pass

    def _refresh_view(self):
        """按 self.view_mode 重建列表区显示。

        三层防残影：
        1. _show_paint_curtain（根治）——截屏幕布盖住旧帧，重建与全部
           重绘在幕布下完成，撤幕即完整新帧，与 Tk 异步绘制时序解耦。
        2. _freeze_paint（Win32 层兜底）——冻结屏幕更新，重建期间
           SetWindowPos 不上屏；幕布失败时仍消除布局中途的即时 bitblt。
        3. _view_switch_batch（Tcl 层兜底）——抑制 _reflow / _reflow_flat
           内部的 update_idletasks，整个切换只在末尾 flush 一次几何。
        经 _on_view_mode_change 进入时幕布/冻结已由外层挂好，此处的
        同名调用因嵌套标志直接跳过。"""
        curtain = self._show_paint_curtain()
        frozen = self._freeze_paint()
        try:
            self._view_switch_batch = True
            try:
                if self.view_mode == "cards":
                    try:
                        self.flat_view.pack_forget()
                    except Exception:
                        pass
                    # 全部卡片先从平铺容器解绑（含网页区卡片——它们不属于
                    # 任何 folder，解绑后即隐藏），文件夹区卡片由 _reflow 回收
                    for c in self.every_card:
                        try:
                            c.grid_forget()
                        except Exception:
                            pass
                    for f in self.folders:
                        f.pack(fill="x", padx=6, pady=(6, 0))
                        try:
                            f._reflow()
                        except Exception:
                            pass
                else:
                    for f in self.folders:
                        try:
                            f.pack_forget()
                        except Exception:
                            pass
                    self.flat_view.pack(fill="x", padx=6, pady=(6, 0))
                    self._reflow_flat(self._flat_card_list())
            finally:
                self._view_switch_batch = False
            try:
                self.update_idletasks()
            except Exception:
                pass
            # 视图切换大幅改变内容高度；window item 高度被 _update_scrollregion
            # 钉在旧视图的值时 inner_frame 的 <Configure> 不会触发（高度恒定），
            # 必须显式重新同步，否则切回内容更高的视图时下方卡片被钳制 unmap
            try:
                self._update_scrollregion()
            except Exception:
                pass
            # _update_scrollregion 改的 window item 高度要等 canvas 的
            # idle 重排才落到 inner_frame 上，趁冻结把它也 flush 掉
            try:
                self.update_idletasks()
            except Exception:
                pass
        finally:
            self._thaw_paint(frozen)
            if curtain:
                # 幕布之下把 Expose 逐 widget 绘制与排队事件全部做完
                try:
                    self.update()
                except Exception:
                    pass
            self._hide_paint_curtain(curtain)

    def _reflow_flat(self, cards):
        """把 cards 按 App.card_width 平铺 grid 进 flat_view。
        列数计算与 FolderFrame._reflow 同一套逻辑。"""
        self._flat_cards = list(cards)
        # 所有卡片先解绑（含不在本视图结果里的，例如 web 视图下
        # 文件夹区的 .lnk 卡片必须隐藏）
        for c in self.every_card:
            try:
                c.grid_forget()
            except Exception:
                pass
        try:
            self._flat_empty_label.grid_forget()
        except Exception:
            pass
        # 宽度：批处理中禁 update_idletasks（防中间布局上屏，见
        # _refresh_view），直接读 canvas 恒同步宽度的 inner_frame
        batch = getattr(self, "_view_switch_batch", False)
        w = 0
        if not batch:
            try:
                self.flat_view.update_idletasks()
            except Exception:
                pass
            w = self.flat_view.winfo_width()
        if w <= 1:
            try:
                iw = self.inner_frame.winfo_width()
                if iw > 24:
                    w = iw - 12
            except Exception:
                pass
        if w <= 1:
            w = max(1, self.winfo_width() - 40)
        cw = int(self.card_width)
        ncols = max(1, int(w) // (cw + 10))
        self._flat_ncols = ncols
        for col in range(ncols):
            self.flat_view.grid_columnconfigure(col, minsize=cw, weight=0)
        for col in range(ncols, ncols + 8):
            self.flat_view.grid_columnconfigure(col, minsize=0, weight=0)
        if not self._flat_cards:
            self._flat_empty_label.configure(
                text=self._FLAT_EMPTY_TEXT.get(
                    self.view_mode, self._FLAT_EMPTY_TEXT["usage"]))
            self._flat_empty_label.grid(row=0, column=0,
                                        padx=4, pady=4, sticky="w")
        for i, c in enumerate(self._flat_cards):
            c.grid(row=i // ncols, column=i % ncols, in_=self.flat_view,
                   padx=4, pady=4, sticky="ew")
            # 同 FolderFrame._reflow：防 stacking 覆盖
            try:
                c.tkraise()
            except Exception:
                pass
        if not batch:
            try:
                self.update_idletasks()
            except Exception:
                pass

    def _on_flat_configure(self, event):
        """窗口宽度变化时按新宽度重算平铺列数。"""
        if self.view_mode == "cards":
            return
        ncols = max(1, event.width // (int(self.card_width) + 10))
        if ncols != self._flat_ncols:
            self._reflow_flat(self._flat_cards)

    def _refresh_view_if_flat(self):
        """卡片集合变化（添加/删除/移动）后同步临时视图显示。"""
        if self.view_mode != "cards":
            self._refresh_view()

    # ============================================================
    # Canvas / 滚动
    # ============================================================
    def _update_scrollregion(self):
        """scrollregion 高度不小于画布可视高度。

        Tk Canvas 的滚动钳制在 scrollregion 比可视区还小时不完全生效：
        yview_scroll 仍能把内容整体推出可视区顶部并停住（内容不满一屏
        时向下滚出现顶部留白的根因）。把 region 高度兜底到画布高度后，
        内容不满一屏时 yview 恒为 (0,1)，滚动自然无从发生。"""
        # canvas 对 window item 的自动高度跟踪在"已滚动 + 内容收缩"
        # 场景下不可靠（实测 reqheight 已变、item 高度不收缩），
        # 显式把 item 高度同步为 inner_frame 的请求高度
        try:
            req_h = self.inner_frame.winfo_reqheight()
            self.canvas.itemconfigure(self.inner_window, height=req_h)
        except tk.TclError:
            return
        bbox = self.canvas.bbox("all")
        if bbox is None:
            bbox = (0, 0, 0, 0)
        x1, y1, x2, y2 = bbox
        ch = self.canvas.winfo_height()
        self.canvas.configure(
            scrollregion=(x1, min(0, y1), x2, max(y2, min(0, y1) + ch)))
        # 内容缩短（折叠文件夹/删卡片/切视图）后 Tk 不会主动把已有
        # 滚动偏移拉回新 region 的合法范围。把当前 lo 原样重设一遍：
        # yview_moveto 内部自带按新 region 的钳制，越界即回拉，
        # 避免残留"顶部露白"的越界状态
        try:
            lo = self.canvas.yview()[0]
            if lo > 0.0:
                self.canvas.yview_moveto(lo)
        except tk.TclError:
            pass

    def _on_inner_configure(self, event):
        self._update_scrollregion()

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self.inner_window, width=event.width)
        # 画布高度变化（拉大窗口）后 region 兜底值要跟着变，
        # 顺带把可能已产生的越界偏移拉回顶部
        self._update_scrollregion()

    def _on_mousewheel(self, event):
        if not self.folders:
            return
        rx, ry = event.x_root, event.y_root
        cx1 = self.canvas.winfo_rootx()
        cy1 = self.canvas.winfo_rooty()
        cx2 = cx1 + self.canvas.winfo_width()
        cy2 = cy1 + self.canvas.winfo_height()
        if not (cx1 <= rx <= cx2 and cy1 <= ry <= cy2):
            return
        # 内容整屏可见时不滚（双保险；主修复在 _update_scrollregion）
        try:
            lo, hi = self.canvas.yview()
            if lo <= 0.0 and hi >= 1.0:
                return
        except tk.TclError:
            pass
        self.canvas.yview_scroll(int(-event.delta / 120), "units")

    # ============================================================
    # 文件夹管理
    # ============================================================
    def _create_folder(self, folder_id, name):
        f = FolderFrame(self.inner_frame, self, folder_id, name)
        # 临时平铺视图下不显示 folder（切回卡片视图时 _refresh_view 统一 pack）
        if self.view_mode == "cards":
            f.pack(fill="x", padx=6, pady=(6, 0))
        self.folders.append(f)
        # 双重防御 stacking 陷阱：新 folder 默认在 inner_frame 里 stacking
        # 最上层，如果之后拖入的 card 是"更早创建"的，card 显示位置在 folder.body
        # 内但被 folder.body 的背景覆盖。让新 folder 沉底，配合 _reflow 里
        # 对 card tkraise，保证 card 永远画在 folder 之上。
        try:
            f.lower()
        except Exception:
            pass
        # 立即完成整轮布局（不只 idletasks），让新 folder 的 body 通过
        # pack fill 拿到真实宽度。否则用户马上把卡片拖进这个空文件夹时，
        # body.winfo_width() 仍是初始 1，_reflow 里 num_cols=1 且列 minsize=500
        # 会让 sticky="ew" 的卡片被 grid 到宽度不足的位置暂时不可见，
        # 需要等下次几何刷新才显示。
        try:
            self.update()
        except Exception:
            pass
        # inner_window 高度被 _update_scrollregion 钉死后，inner_frame 的
        # <Configure> 不会因内容增高自发触发；新 folder pack 进来若不显式
        # 同步，会落在钉住高度之外被裁剪（不可见），且 scrollregion 仍是
        # 旧值（yview 恒 (0,1)），滚轮守卫直接放弃滚动——必须主动同步
        try:
            self._update_scrollregion()
        except Exception:
            pass
        return f

    def _on_new_folder(self):
        fid = "f_" + uuid.uuid4().hex[:8]
        name = f"新文件夹 {len(self.folders) + 1}"
        self._create_folder(fid, name)
        self.save_state()

    def _on_open_app_dir(self):
        """打开 QuickDeck 本体（exe / 脚本）所在目录。"""
        try:
            os.startfile(APP_DIR)
        except Exception as e:
            messagebox.showerror("无法打开目录", f"{APP_DIR}\n\n{e}")

    def _ask_delete_folder_target(self, folder, remaining):
        """删除非空文件夹时的确认弹窗：可选卡片迁移的目标文件夹
        （默认最后一个剩余文件夹）。返回目标 FolderFrame；取消返回 None。"""
        th = self.theme
        dlg = tk.Toplevel(self)
        dlg.title("删除文件夹")
        dlg.configure(bg=th["app_bg"], padx=16, pady=12)
        dlg.resizable(False, False)
        dlg.transient(self)

        n = len(folder.cards)
        tk.Label(
            dlg, font=self.app_font, bg=th["app_bg"], fg=th["fg"],
            justify="left", anchor="w",
            text=(f"确定删除文件夹「{folder.name}」？\n\n"
                  f"其中的 {n} 张快捷方式卡片不会被删除，\n"
                  f"会移动到下方所选文件夹的末尾：")
        ).pack(anchor="w")

        # 目标选择：默认最后一个剩余文件夹（与旧行为一致）。
        # 文件夹允许重名，Combobox 按下标回查而不是按名字
        names = [f.name for f in remaining]
        target_var = tk.StringVar(value=names[-1])
        cb = ttk.Combobox(dlg, textvariable=target_var, values=names,
                          state="readonly", width=24)
        cb.current(len(names) - 1)
        cb.pack(anchor="w", pady=(8, 0))

        result = {"target": None}

        def _ok():
            idx = cb.current()
            result["target"] = remaining[idx if idx >= 0 else -1]
            dlg.destroy()

        def _cancel():
            dlg.destroy()

        btn_row = tk.Frame(dlg, bg=th["app_bg"])
        btn_row.pack(anchor="e", pady=(14, 0))
        for text, cmd, danger in (("删除", _ok, True),
                                  ("取消", _cancel, False)):
            tk.Button(
                btn_row, text=text, command=cmd, padx=14, pady=3,
                font=self.app_font,
                bg=th["btn_bg"],
                fg=th["danger_fg"] if danger else th["fg"],
                activebackground=(th["danger_active_bg"] if danger
                                  else th["btn_active_bg"]),
                activeforeground=th["danger_fg"] if danger else th["fg"],
            ).pack(side="left", padx=(8, 0))

        dlg.bind("<Return>", lambda e: _ok())
        dlg.bind("<Escape>", lambda e: _cancel())
        dlg.protocol("WM_DELETE_WINDOW", _cancel)

        # 居中到主窗口，模态等待
        dlg.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width()
                                  - dlg.winfo_reqwidth()) // 2
        y = self.winfo_rooty() + (self.winfo_height()
                                  - dlg.winfo_reqheight()) // 3
        dlg.geometry(f"+{max(0, x)}+{max(0, y)}")
        dlg.grab_set()
        cb.focus_set()
        self.wait_window(dlg)
        return result["target"]

    def delete_folder(self, folder):
        if len(self.folders) <= 1:
            messagebox.showinfo("提示", "至少保留一个文件夹。")
            return
        remaining = [f for f in self.folders if f is not folder]
        n = len(folder.cards)
        if n > 0:
            # 非空文件夹：弹窗内可自选卡片迁移目标（默认最后一个剩余文件夹）
            target = self._ask_delete_folder_target(folder, remaining)
            if target is None:
                return
        else:
            target = None
            if not messagebox.askyesno(
                    "删除文件夹", f"确定删除空文件夹「{folder.name}」？"):
                return
        moved = list(folder.cards)
        folder.cards = []  # 清空源文件夹，但不销毁卡片本身
        if target is not None:
            for c in moved:
                target.cards.append(c)
                c.folder = target
                # 让迁入卡片继承目标 folder 的锁定态
                try:
                    c.apply_lock_state(getattr(target, "locked", False))
                except Exception:
                    pass
            target._reflow()
        self.folders.remove(folder)
        try:
            folder.pack_forget()
            folder.destroy()
        except Exception:
            pass
        # 空文件夹删除不经过任何 _reflow，内容变矮后必须显式同步
        # 钉住的 window item 高度与 scrollregion（同 _create_folder 注释）
        try:
            self.update_idletasks()
            self._update_scrollregion()
        except Exception:
            pass
        self.save_state()

    # ============================================================
    # 添加 / 删除卡片
    # ============================================================
    def _on_add(self):
        path = filedialog.askopenfilename(
            title="选择快捷方式或程序",
            filetypes=[("快捷方式 / 程序", "*.lnk;*.exe;*.url"),
                       ("网页快捷方式", "*.url"),
                       ("所有文件", "*.*")]
        )
        if path:
            # 添加到最后一个文件夹的末尾（用户手动新增时的默认落点）
            target = self.folders[-1] if self.folders else None
            self._add_card(path, "", folder=target)
            self.save_state()

    def _on_multi_add(self):
        paths = filedialog.askopenfilenames(
            title="选择多个快捷方式或程序",
            filetypes=[("快捷方式 / 程序", "*.lnk;*.exe;*.url"),
                       ("网页快捷方式", "*.url"),
                       ("所有文件", "*.*")]
        )
        target = self.folders[-1] if self.folders else None
        for p in paths:
            self._add_card(p, "", folder=target)
        if paths:
            self.save_state()

    def _on_add_dir(self):
        """选择一个目录加入文件夹快捷方式独立存储区。"""
        path = filedialog.askdirectory(title="选择要添加的文件夹")
        if not path:
            return
        # askdirectory 返回正斜杠路径，统一成 Windows 风格
        path = os.path.normpath(path)
        if self._add_card(path, ""):
            self.save_state()

    def _pick_multiple_dirs(self):
        """系统 IFileOpenDialog（FOS_PICKFOLDERS + FOS_ALLOWMULTISELECT）
        多选目录。tkinter 的 askdirectory 不支持多选，而本机 pywin32
        的 shell 模块没有 IFileOpenDialog 包装，直接用 ctypes 走 COM
        vtable（与 imagefactory_icon 同一套调用方式）。
        返回路径列表；用户取消返回空列表；不可用时抛异常由调用方兜底。"""
        _ensure_com()
        ole32 = ctypes.windll.ole32

        def method(ptr, idx, *argtypes):
            """取 COM 对象 vtable 第 idx 个方法（返回 HRESULT）。"""
            vtbl = ctypes.cast(
                ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
            ).contents
            return ctypes.WINFUNCTYPE(
                ctypes.c_long, ctypes.c_void_p, *argtypes)(vtbl[idx])

        dlg = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(
            ctypes.byref(_iid("{DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7}")),
            None, 1,  # CLSCTX_INPROC_SERVER
            ctypes.byref(_iid("{D57C7288-D4AD-4768-BE02-9D969532D960}")),
            ctypes.byref(dlg))  # CLSID / IID_IFileOpenDialog
        if hr != 0 or not dlg.value:
            raise OSError(f"CoCreateInstance(FileOpenDialog) hr={hr:#010x}")
        items = ctypes.c_void_p()
        paths = []
        try:
            # IFileDialog::GetOptions(10) / SetOptions(9)：
            # FOS_PICKFOLDERS(0x20) | FOS_FORCEFILESYSTEM(0x40)
            # | FOS_ALLOWMULTISELECT(0x200)
            opts = ctypes.c_ulong()
            method(dlg, 10, ctypes.POINTER(ctypes.c_ulong))(
                dlg, ctypes.byref(opts))
            method(dlg, 9, ctypes.c_ulong)(
                dlg, opts.value | 0x20 | 0x40 | 0x200)
            # IFileDialog::SetTitle(17)
            method(dlg, 17, ctypes.c_wchar_p)(dlg, "选择多个要添加的文件夹")
            # IModalWindow::Show(3)：模态；用户取消返回
            # HRESULT_FROM_WIN32(ERROR_CANCELLED)，非 0 一律视为取消
            hr = method(dlg, 3, ctypes.c_void_p)(dlg, self.winfo_id())
            if hr != 0:
                return []
            # IFileOpenDialog::GetResults(27) → IShellItemArray
            hr = method(dlg, 27, ctypes.POINTER(ctypes.c_void_p))(
                dlg, ctypes.byref(items))
            if hr != 0 or not items.value:
                return []
            # IShellItemArray::GetCount(7) / GetItemAt(8)
            count = ctypes.c_ulong()
            method(items, 7, ctypes.POINTER(ctypes.c_ulong))(
                items, ctypes.byref(count))
            for i in range(count.value):
                item = ctypes.c_void_p()
                hr = method(items, 8, ctypes.c_ulong,
                            ctypes.POINTER(ctypes.c_void_p))(
                    items, i, ctypes.byref(item))
                if hr != 0 or not item.value:
                    continue
                try:
                    # IShellItem::GetDisplayName(5, SIGDN_FILESYSPATH)
                    pw = ctypes.c_wchar_p()
                    hr = method(item, 5, ctypes.c_ulong,
                                ctypes.POINTER(ctypes.c_wchar_p))(
                        item, 0x80058000, ctypes.byref(pw))
                    if hr == 0 and pw.value:
                        paths.append(os.path.normpath(pw.value))
                        ole32.CoTaskMemFree(pw)
                finally:
                    _com_release(item)
            return paths
        finally:
            _com_release(items)
            _com_release(dlg)

    def _on_multi_add_dir(self):
        """多选目录加入文件夹快捷方式独立存储区。"""
        try:
            paths = self._pick_multiple_dirs()
        except Exception as e:
            # COM 对话框不可用：退回单选 askdirectory
            print(f"[QuickDeck] multi dir dialog fallback: {e}",
                  file=sys.stderr)
            self._on_add_dir()
            return
        added = 0
        for p in paths:
            if self._add_card(p, ""):
                added += 1
        if added:
            self.save_state()

    @staticmethod
    def _normalize_path(p):
        if not p:
            return ""
        try:
            return os.path.normcase(os.path.abspath(os.path.expandvars(p)))
        except Exception:
            return p

    def _has_card_with_path(self, path):
        norm = self._normalize_path(path)
        return any(self._normalize_path(c.path) == norm
                   for c in self.every_card)

    def _add_card(self, path, description, folder=None,
                  custom_title="", custom_icon="",
                  launch_count=0, last_launch_ts=0.0):
        """添加卡片；重复路径安静跳过。
        目录自动进文件夹快捷方式独立存储区；
        .url 自动进网页快捷方式独立存储区（都不进文件夹分组）；
        其余默认加到最后一个文件夹的末尾。"""
        if self._has_card_with_path(path):
            return False
        if os.path.isdir(path):
            return self._add_standalone_card(
                self.dir_cards, path, description,
                custom_title=custom_title, custom_icon=custom_icon,
                launch_count=launch_count, last_launch_ts=last_launch_ts)
        if path.lower().endswith(".url"):
            return self._add_standalone_card(
                self.web_cards, path, description,
                custom_title=custom_title, custom_icon=custom_icon,
                launch_count=launch_count, last_launch_ts=last_launch_ts)
        if folder is None:
            if not self.folders:
                self._create_folder(self.DEFAULT_FOLDER_ID, "默认")
            folder = self.folders[-1]
        try:
            card = ShortcutCard(self.inner_frame, self, path, description,
                                custom_title=custom_title,
                                custom_icon=custom_icon,
                                launch_count=launch_count,
                                last_launch_ts=last_launch_ts)
        except Exception as e:
            print(f"[QuickDeck] add_card error: {e}", file=sys.stderr)
            return False
        folder.add_card(card)
        self._refresh_view_if_flat()
        return True

    def _add_standalone_card(self, area, path, description="",
                             custom_title="", custom_icon="",
                             launch_count=0, last_launch_ts=0.0):
        """把卡片加入独立存储区（web_cards / dir_cards）末尾
        （调用方已做去重）。"""
        try:
            card = ShortcutCard(self.inner_frame, self, path, description,
                                custom_title=custom_title,
                                custom_icon=custom_icon,
                                launch_count=launch_count,
                                last_launch_ts=last_launch_ts)
        except Exception as e:
            print(f"[QuickDeck] add_standalone_card error: {e}",
                  file=sys.stderr)
            return False
        # folder 保持 None：独立区卡片不属于任何文件夹，
        # ShortcutCard 内所有 locked 判断走 getattr 默认 False，天然可编辑
        area.append(card)
        self._refresh_view_if_flat()
        return True

    def move_card_to_folder(self, card, target_folder):
        """右键菜单"移动到文件夹"：追加到目标 folder 末尾。"""
        if card.folder is target_folder:
            return
        if getattr(card.folder, "locked", False) \
                or getattr(target_folder, "locked", False):
            return
        self._move_card_to(card, target_folder, len(target_folder.cards))
        self._refresh_view_if_flat()
        self.save_state()

    def remove_card(self, card):
        # 独立存储区卡片（网页区 / 文件夹区）：从对应列表移除
        # （不涉及 folder / 锁定）
        for area in (self.web_cards, self.dir_cards):
            if card in area:
                area.remove(card)
                try:
                    card.destroy()
                except Exception:
                    pass
                self._refresh_view_if_flat()
                self.save_state()
                return
        folder = card.folder
        # folder 上锁时，任何路径的删除都失效（含未来可能的键盘快捷键等）
        if folder is not None and getattr(folder, "locked", False):
            return
        if folder is not None:
            folder.remove_card(card)
        try:
            card.destroy()
        except Exception:
            pass
        self._refresh_view_if_flat()
        self.save_state()

    def launch_card(self, card):
        path = card.path
        try:
            if not os.path.exists(path):
                messagebox.showwarning(
                    "启动失败", f"目标不存在:\n{path}"
                )
                return
            os.startfile(path)
        except Exception as e:
            messagebox.showerror("启动失败", f"{path}\n\n{e}")
            return
        # 使用统计：只在成功启动后记账。当前正处于"按使用排序"视图时
        # 不立即重排——卡片在鼠标下瞬移体验很差，下次进入该视图时生效
        card.launch_count += 1
        card.last_launch_ts = time.time()
        self.save_state()

    # ============================================================
    # 加载配置
    # ============================================================
    def _load_from_config(self):
        folders = self.cfg.get("folders") or []
        if not folders:
            folders = [{"id": self.DEFAULT_FOLDER_ID,
                        "name": "默认", "order": 0}]
        folders = sorted(folders, key=lambda x: x.get("order", 0))
        for fd in folders:
            f = self._create_folder(
                fd.get("id") or ("f_" + uuid.uuid4().hex[:8]),
                fd.get("name") or "未命名"
            )
            # 恢复锁定态；卡片会在稍后 add_card 时通过 folder.locked 传播
            if fd.get("locked"):
                try:
                    f.set_locked(True)
                except Exception:
                    pass
            # 恢复折叠态（与锁定相互独立）
            if fd.get("collapsed"):
                try:
                    f.set_collapsed(True)
                except Exception:
                    pass

        items = self.cfg.get("shortcuts") or []
        items = sorted(
            items,
            key=lambda x: (x.get("folder", self.DEFAULT_FOLDER_ID),
                           x.get("order", 0))
        )
        for it in items:
            p = it.get("path")
            if not p:
                continue
            fid = it.get("folder") or self.DEFAULT_FOLDER_ID
            target = self.folder_by_id(fid) or self.folders[0]
            # 旧配置迁移：文件夹里的 .url 会被 _add_card 自动路由到
            # 网页区（追加到末尾），下次 save_state 起进入 web_shortcuts
            self._add_card(p, it.get("description", ""), folder=target,
                           custom_title=it.get("title", ""),
                           custom_icon=it.get("icon", ""),
                           launch_count=it.get("launch_count", 0),
                           last_launch_ts=it.get("last_launch_ts", 0.0))

        # 独立存储区：网页快捷方式 + 文件夹快捷方式
        for cfg_key, area in (("web_shortcuts", self.web_cards),
                              ("dir_shortcuts", self.dir_cards)):
            items = sorted(self.cfg.get(cfg_key) or [],
                           key=lambda x: x.get("order", 0))
            for it in items:
                p = it.get("path")
                if not p or self._has_card_with_path(p):
                    continue
                self._add_standalone_card(
                    area, p, it.get("description", ""),
                    custom_title=it.get("title", ""),
                    custom_icon=it.get("icon", ""),
                    launch_count=it.get("launch_count", 0),
                    last_launch_ts=it.get("last_launch_ts", 0.0))

    # ============================================================
    # 字体切换
    # ============================================================
    def _on_font_change(self, event=None):
        if self._font_apply_timer is not None:
            try:
                self.after_cancel(self._font_apply_timer)
            except Exception:
                pass
        self._font_apply_timer = self.after(120, self._apply_font_now)

    def _apply_font_now(self):
        self._font_apply_timer = None
        family = self.font_family_var.get().strip()
        try:
            size = int(self.font_size_var.get())
        except (ValueError, tk.TclError):
            return
        if not family:
            return
        size = max(8, min(36, size))
        if (family == self.app_font.cget("family")
                and size == int(self.app_font.cget("size"))):
            return
        self.app_font.configure(family=family, size=size)
        self._apply_style_font()
        # 字体变化时同步刷新 folder header 用的小号字
        for f in self.folders:
            try:
                f.refresh_header_font()
            except Exception:
                pass
        self.save_state()

    # ---- 卡片宽度 ----
    def _make_small_font(self):
        """给宽度调节小箭头按钮用的固定小号字。"""
        return tkFont.Font(family="Segoe UI", size=8)

    def _on_card_width_change(self, event=None):
        try:
            v = int(self.card_width_var.get())
        except (ValueError, tk.TclError):
            return
        v = max(200, min(1200, v))
        if v == self.card_width_var_int_last():
            return
        self._apply_card_width(v)

    def card_width_var_int_last(self):
        return int(self.card_width)

    def _apply_card_width(self, v):
        v = max(200, min(1200, int(v)))
        if v == self.card_width:
            return
        self.card_width = v
        # 回写 spinbox 显示（避免键盘越界后 UI 不同步）
        if self.card_width_var.get() != str(v):
            self.card_width_var.set(str(v))
        # 让所有已有卡片按新宽度重新排布
        for folder in self.folders:
            try:
                folder._reflow()
            except Exception:
                pass
        if self.view_mode != "cards":
            try:
                self._reflow_flat(self._flat_cards)
            except Exception:
                pass
        # 防抖保存
        if self._save_timer is not None:
            try:
                self.after_cancel(self._save_timer)
            except Exception:
                pass
        self._save_timer = self.after(500, self.save_state)

    def _cw_repeat_begin(self, direction):
        """按下自定义 ▲/▼ 按钮时开始连续 +1/-1。"""
        self._cw_repeat_dir = direction
        self._cw_repeat_step(first=True)

    def _cw_repeat_step(self, first=False):
        if self._cw_repeat_dir == 0:
            return
        new_v = self.card_width + self._cw_repeat_dir
        new_v = max(200, min(1200, new_v))
        if new_v != self.card_width:
            self._apply_card_width(new_v)
        # 第一次点击后 300ms 才开始连续，之后每 40ms 一步——手感接近系统 Spinbox
        delay = 300 if first else 40
        self._cw_repeat_after = self.after(delay, self._cw_repeat_step)

    def _cw_repeat_end(self):
        self._cw_repeat_dir = 0
        if self._cw_repeat_after is not None:
            try:
                self.after_cancel(self._cw_repeat_after)
            except Exception:
                pass
            self._cw_repeat_after = None

    # ============================================================
    # 窗口尺寸变化
    # ============================================================
    def _on_window_configure(self, event):
        if event.widget is not self:
            return
        if self._save_timer is not None:
            try:
                self.after_cancel(self._save_timer)
            except Exception:
                pass
        self._save_timer = self.after(500, self.save_state)

    # ============================================================
    # 卡片拖拽（可跨文件夹）
    # ============================================================
    def card_drag_start(self, card, event):
        # usage 视图为临时只读视图，禁止拖拽；
        # cards 视图只允许文件夹分组区卡片拖拽；
        # web / dirs 视图只允许各自独立区卡片排序
        if self.view_mode == "usage":
            return
        if self.view_mode == "web" and card not in self.web_cards:
            return
        if self.view_mode == "dirs" and card not in self.dir_cards:
            return
        if self.view_mode == "cards" and (card in self.web_cards
                                          or card in self.dir_cards):
            return
        self.dragging_card = card
        self.dragging_folder = None

    def card_drag_motion(self, card, event):
        if self.dragging_card is not card:
            return
        # 独立区排序：在对应列表内移动，不涉及 folder
        if self.view_mode == "web":
            self._area_drag_motion(card, event, "web_cards")
            return
        if self.view_mode == "dirs":
            self._area_drag_motion(card, event, "dir_cards")
            return
        x, y = event.x_root, event.y_root
        target_folder = self._folder_at_y(y)
        if target_folder is None:
            return
        # 折叠的文件夹卡片区不可见，不作为拖拽落点（避免卡片"拖进去就消失"）
        if getattr(target_folder, "collapsed", False) \
                and target_folder is not card.folder:
            return
        target_pos = self._insert_position_in_folder(target_folder, x, y, card)
        self._move_card_to(card, target_folder, target_pos)

    def _area_drag_motion(self, card, event, attr):
        """独立存储区视图（web / dirs）内拖拽排序：按鼠标位置找最近卡片
        决定插入点，与 _insert_position_in_folder 同一套判定逻辑。
        attr 为存储列表的属性名（"web_cards" / "dir_cards"）。"""
        cards = getattr(self, attr)
        others = [c for c in cards if c is not card]
        if not others:
            return
        x, y = event.x_root, event.y_root
        best_i, best_d = 0, float("inf")
        for i, c in enumerate(others):
            try:
                cx = c.winfo_rootx() + c.winfo_width() / 2
                cy = c.winfo_rooty() + c.winfo_height() / 2
            except tk.TclError:
                continue
            d = (cx - x) ** 2 + (cy - y) ** 2
            if d < best_d:
                best_d, best_i = d, i
        bc = others[best_i]
        ccx = bc.winfo_rootx() + bc.winfo_width() / 2
        ccy = bc.winfo_rooty() + bc.winfo_height() / 2
        if y < ccy - bc.winfo_height() / 3:
            pos = best_i
        elif y > ccy + bc.winfo_height() / 3:
            pos = best_i + 1
        else:
            pos = best_i if x < ccx else best_i + 1
        new_order = others[:pos] + [card] + others[pos:]
        if new_order == cards:
            return
        setattr(self, attr, new_order)
        self._reflow_flat(new_order)

    def card_drag_end(self, card, event):
        if self.dragging_card is card:
            self.dragging_card = None
            if self.view_mode in ("web", "dirs"):
                self.save_state()
                return
            # 拖拽过程中每次 motion 都做过局部 reflow，但如果最后落点是刚
            # 新建的空文件夹，body 尚未完成首次布局，卡片可能显示不出。
            # 收尾时对所有 folder 强制走一次完整 reflow + 顶层 update，
            # 保证卡片最终一定可见。
            for f in list(self.folders):
                try:
                    f._reflow()
                except Exception:
                    pass
            try:
                self.update()
            except Exception:
                pass
            self.save_state()

    def _folder_at_y(self, y_root):
        # 优先命中：鼠标落在某个 folder 的 y 范围内
        for f in self.folders:
            try:
                top = f.winfo_rooty()
                bot = top + f.winfo_height()
            except tk.TclError:
                continue
            if top <= y_root <= bot:
                return f
        # 没命中：按 y 距离最近的 folder 吸附
        best_f, best_d = None, float("inf")
        for f in self.folders:
            try:
                top = f.winfo_rooty()
                cy = top + f.winfo_height() / 2
            except tk.TclError:
                continue
            d = abs(y_root - cy)
            if d < best_d:
                best_d, best_f = d, f
        return best_f

    def _insert_position_in_folder(self, folder, x_root, y_root, dragging_card):
        others = [c for c in folder.cards if c is not dragging_card]
        if not others:
            return 0
        best_i, best_d = 0, float("inf")
        for i, c in enumerate(others):
            cx = c.winfo_rootx() + c.winfo_width() / 2
            cy = c.winfo_rooty() + c.winfo_height() / 2
            d = (cx - x_root) ** 2 + (cy - y_root) ** 2
            if d < best_d:
                best_d, best_i = d, i
        bc = others[best_i]
        ccx = bc.winfo_rootx() + bc.winfo_width() / 2
        ccy = bc.winfo_rooty() + bc.winfo_height() / 2
        # 跨行：以中心 y 为界；同一行内：以中心 x 为界
        if y_root < ccy - bc.winfo_height() / 3:
            return best_i
        if y_root > ccy + bc.winfo_height() / 3:
            return best_i + 1
        return best_i if x_root < ccx else best_i + 1

    def _move_card_to(self, card, target_folder, target_pos):
        src_folder = card.folder
        # 明确解除 card 现有的 grid 绑定，避免 in_ 从 src.body 换到
        # target.body 时 tk 遗留状态导致新位置不可见
        try:
            card.grid_forget()
        except Exception:
            pass

        if src_folder is target_folder:
            cur = src_folder.cards.index(card)
            # 同文件夹内：把 target_pos 修正为"移除 card 后的目标位置"
            if target_pos > cur:
                target_pos -= 1
            if cur == target_pos:
                # 顺序未变，也要把刚才 grid_forget 的 card 补回原位
                src_folder._reflow()
                return
            src_folder.cards.remove(card)
            src_folder.cards.insert(target_pos, card)
            src_folder._reflow()
        else:
            if src_folder is not None and card in src_folder.cards:
                src_folder.cards.remove(card)
                src_folder._reflow()
            target_folder.insert_card(card, target_pos)
            # 跨 folder 的首张卡片场景：target.body 可能刚 pack 完还没
            # 完成 fill 扩展。这里让 target 及其 body 完整走一次几何刷新，
            # 拿到真实宽度后再跑一次 _reflow，卡片就会立刻可见。
            try:
                target_folder.body.update_idletasks()
                target_folder.update_idletasks()
                target_folder._reflow()
            except Exception:
                pass
        # 全局强制刷新一次，确保新宿主的 grid 立即完成布局
        try:
            self.update_idletasks()
        except Exception:
            pass

    # ============================================================
    # 文件夹拖拽（换整个文件夹在列表里的顺序）
    # ============================================================
    def folder_drag_start(self, folder, event):
        self.dragging_folder = folder
        self.dragging_card = None

    def folder_drag_motion(self, folder, event):
        if self.dragging_folder is not folder:
            return
        if len(self.folders) <= 1:
            return
        y = event.y_root
        others = [f for f in self.folders if f is not folder]
        target_pos = 0
        for f in others:
            try:
                top = f.winfo_rooty()
                h = f.winfo_height()
            except tk.TclError:
                return
            if y > top + h / 2:
                target_pos += 1
            else:
                break
        new_order = others[:target_pos] + [folder] + others[target_pos:]
        if new_order == self.folders:
            return
        self.folders = new_order
        for f in self.folders:
            try:
                f.pack_forget()
            except Exception:
                pass
        for f in self.folders:
            f.pack(fill="x", padx=6, pady=(6, 0))
        try:
            self.inner_frame.update_idletasks()
        except Exception:
            pass

    def folder_drag_end(self, folder, event):
        if self.dragging_folder is folder:
            self.dragging_folder = None
            self.save_state()

    # ============================================================
    # 状态持久化
    # ============================================================
    def save_state(self):
        try:
            self.cfg["window"] = {
                "width": self.winfo_width(),
                "height": self.winfo_height(),
                "x": self.winfo_x(),
                "y": self.winfo_y()
            }
        except Exception:
            pass
        self.cfg["font"] = {
            "family": self.app_font.cget("family"),
            "size": int(self.app_font.cget("size"))
        }
        self.cfg["card_width"] = int(self.card_width)
        self.cfg["theme_mode"] = self.theme_mode
        self.cfg["folders"] = [
            {"id": f.id, "name": f.name, "order": i,
             "locked": bool(getattr(f, "locked", False)),
             "collapsed": bool(getattr(f, "collapsed", False))}
            for i, f in enumerate(self.folders)
        ]
        shortcuts = []
        for f in self.folders:
            for j, c in enumerate(f.cards):
                shortcuts.append({
                    "path": c.path,
                    "description": c.desc_var.get(),
                    "folder": f.id,
                    "order": j,
                    "title": getattr(c, "custom_title", "") or "",
                    "icon": getattr(c, "custom_icon", "") or "",
                    "launch_count": int(getattr(c, "launch_count", 0)),
                    "last_launch_ts": float(
                        getattr(c, "last_launch_ts", 0.0)),
                })
        self.cfg["shortcuts"] = shortcuts
        for cfg_key, cards in (("web_shortcuts", self.web_cards),
                               ("dir_shortcuts", self.dir_cards)):
            self.cfg[cfg_key] = [
                {
                    "path": c.path,
                    "description": c.desc_var.get(),
                    "order": j,
                    "title": getattr(c, "custom_title", "") or "",
                    "icon": getattr(c, "custom_icon", "") or "",
                    "launch_count": int(getattr(c, "launch_count", 0)),
                    "last_launch_ts": float(
                        getattr(c, "last_launch_ts", 0.0)),
                }
                for j, c in enumerate(cards)
            ]
        save_config(self.cfg)

    def _on_close(self):
        try:
            self.save_state()
        finally:
            self.destroy()


# ================================================================
# 程序入口
# ================================================================
# 单实例互斥句柄：必须保持进程级引用（进程退出时系统自动释放）。
# onefile exe 解压启动慢，用户双击两次导致双开很常见，而双开的两个
# 实例会在退出时互相覆盖 config.json，且用户完全无感知。
_SINGLE_MUTEX = None
_MUTEX_NAME = "QuickDeck_SingleInstance_B7A31F2C"


def acquire_single_instance():
    """CreateMutexW 命名互斥。已有实例在运行时激活旧窗口并返回 False；
    互斥 API 不可用时不阻止启动（宁可双开也不能打不开）。"""
    global _SINGLE_MUTEX
    if not sys.platform.startswith("win"):
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        _SINGLE_MUTEX = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
        ERROR_ALREADY_EXISTS = 183
        if kernel32.GetLastError() != ERROR_ALREADY_EXISTS:
            return True
        # 已有实例：找到旧窗口，还原最小化并前置
        # Tk 顶层 wrapper 的窗口类名固定为 TkTopLevel；按类名+标题匹配，
        # 找不到再放宽为仅标题（best-effort，找不到也照样退出，
        # 不能让第二个实例继续跑）
        hwnd = user32.FindWindowW("TkTopLevel", "QuickDeck") \
            or user32.FindWindowW(None, "QuickDeck")
        if hwnd:
            SW_RESTORE = 9
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, SW_RESTORE)
            user32.SetForegroundWindow(hwnd)
        return False
    except Exception:
        return True


def main():
    if not acquire_single_instance():
        return
    enable_dpi_awareness()
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
