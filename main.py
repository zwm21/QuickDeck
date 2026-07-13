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
import uuid
import ctypes
import tkinter as tk
from tkinter import ttk, font as tkFont, filedialog, messagebox

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
LOCAL_FONT_FILE = _resource_path("HYWenHei-65W.ttf")

# 内置字体家族名（TTF 文件内 name table 记录的家族名，
# 通常与去掉扩展名的文件名一致）
BUILTIN_FONT_FAMILY = "HYWenHei-65W"

ICON_SIZE = 32  # 卡片上显示的图标像素尺寸

DEFAULT_CONFIG = {
    "window": {"width": 900, "height": 650, "x": 200, "y": 100},
    "font": {"family": BUILTIN_FONT_FAMILY, "size": 12},
    "card_width": 500,
    "shortcuts": []
}


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
def _merge_dict(base, override):
    """把 override 的字段递归合并到 base，保证 base 拥有完整结构。"""
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = _merge_dict(base[k], v)
        else:
            base[k] = v
    return base


def load_config():
    """从 config.json 加载配置；缺失或损坏时使用默认值。"""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            cfg = _merge_dict(cfg, loaded)
        except Exception as e:
            print(f"[QuickDeck] load_config error: {e}", file=sys.stderr)
    return cfg


def save_config(cfg):
    """把配置字典写回 config.json（UTF-8 + 缩进）。"""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[QuickDeck] save_config error: {e}", file=sys.stderr)


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

        _APIS_INITED = True
    except Exception as e:
        print(f"[QuickDeck] _init_win_apis error: {e}", file=sys.stderr)


# ---- COM 辅助 ---------------------------------------------------
_COM_INITED = False


def _iid(s):
    _init_win_apis()
    g = _GUID()
    ctypes.windll.ole32.CLSIDFromString(s, ctypes.byref(g))
    return g


def _ensure_com():
    global _COM_INITED
    if _COM_INITED:
        return
    _init_win_apis()
    try:
        # 0x2 = COINIT_APARTMENTTHREADED，tk 主线程用 STA
        ctypes.windll.ole32.CoInitializeEx(None, 0x2)
    except Exception:
        pass
    _COM_INITED = True


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
      其他:
        1) ExtractIconEx
        2) IShellItemImageFactory
        3) SHGetFileInfoW
    """
    if not HAS_WIN32:
        return None
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
    """默认标题：文件名（不含扩展名）。"""
    return os.path.splitext(os.path.basename(path))[0]


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
# 快捷方式卡片
# ================================================================
class ShortcutCard(tk.Frame):
    """一张快捷方式卡片，宽度由 App.card_width 动态决定（默认 500px）。
    可拖拽（换顺序 / 跨文件夹）、可双击启动。
    """

    # 兼容旧引用；实际生效值走 App.card_width（可由 UI 实时调整）
    CARD_WIDTH = 500

    def __init__(self, master, app, path, description=""):
        super().__init__(master, bd=1, relief="solid",
                         padx=8, pady=6, bg="#FFFFFF")
        self.app = app
        self.path = path
        self.folder = None  # 由 FolderFrame.add_card / insert_card 设置

        # 图标
        pil = get_icon_for_file(path) if HAS_WIN32 else None
        if pil is None:
            pil = app.default_icon_img
        self.icon_pil = pil
        self.icon_photo = ImageTk.PhotoImage(pil)

        self.icon_label = tk.Label(self, image=self.icon_photo,
                                   bg="#FFFFFF", cursor="fleur")
        self.icon_label.pack(side="left", padx=(0, 8))

        mid = tk.Frame(self, bg="#FFFFFF")
        mid.pack(side="left", fill="both", expand=True)

        title_text = get_title_for_file(path)
        self.title_label = tk.Label(mid, text=title_text, anchor="w",
                                    font=app.app_font, bg="#FFFFFF",
                                    cursor="fleur")
        self.title_label.pack(fill="x")

        self.desc_var = tk.StringVar(value=description)
        self.desc_entry = tk.Entry(mid, textvariable=self.desc_var,
                                   font=app.app_font, relief="flat",
                                   bg="#F4F4F4")
        self.desc_entry.pack(fill="x", pady=(3, 0))
        self.desc_entry.bind("<FocusOut>",
                             lambda e: self.app.save_state())
        self.desc_entry.bind("<Return>",
                             lambda e: self.app.save_state())

        self.del_btn = tk.Button(self, text="\u274C",  # ❌
                                 width=3, font=app.app_font, relief="flat",
                                 bg="#FFFFFF", fg="#B22222",
                                 activebackground="#FADBD8",
                                 command=self._on_delete)
        self.del_btn.pack(side="right", padx=(8, 0))

        # 拖拽 & 双击（不绑 Entry / 删除按钮，避免影响文本编辑与点击）
        for w in (self, mid, self.icon_label, self.title_label):
            w.bind("<ButtonPress-1>", self._on_drag_start)
            w.bind("<B1-Motion>", self._on_drag_motion)
            w.bind("<ButtonRelease-1>", self._on_drag_end)
            w.bind("<Double-Button-1>", self._on_double_click)

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
        super().__init__(master, bd=1, relief="solid", bg="#F5F5F5")
        self.app = app
        self.id = folder_id
        self.name = name
        self.cards = []
        self._num_cols = 1
        self.locked = False  # 上锁时禁用名字编辑 / 卡片编辑 / 卡片拖拽 / 删除

        # ---- header（紧凑：小 padding，无冗余空间） ----
        header = tk.Frame(self, bg="#E0E0E0", padx=4, pady=1)
        header.pack(fill="x")
        self.header = header

        # 用小号字（约为 app 字体的 0.9 倍）让 header 更矮
        self._header_font = tkFont.Font(
            family=app.app_font.cget("family"),
            size=max(8, int(app.app_font.cget("size")) - 1)
        )

        self.drag_handle = tk.Label(
            header, text="\u2630", font=self._header_font,  # ☰
            bg="#E0E0E0", cursor="fleur", padx=2
        )
        self.drag_handle.pack(side="left")

        self.name_var = tk.StringVar(value=name)
        self.name_entry = tk.Entry(
            header, textvariable=self.name_var,
            font=self._header_font, bd=0, bg="#E0E0E0",
            highlightthickness=0
        )
        self.name_entry.pack(side="left", fill="x", expand=True, padx=(2, 4))
        self.name_entry.bind("<FocusOut>", lambda e: self._on_rename())
        self.name_entry.bind("<Return>", lambda e: self._on_rename())

        # 上锁按钮：🔓/🔒 切换；点击调 toggle_lock
        self.lock_btn = tk.Button(
            header, text="\U0001F513",  # 🔓
            font=self._header_font, relief="flat", bd=0,
            bg="#E0E0E0", fg="#333333",
            activebackground="#D0D0D0",
            padx=4, pady=0,
            command=self._on_toggle_lock
        )
        self.lock_btn.pack(side="right", padx=(0, 2))

        # 用小号 ✕ 按钮替代原来的"删除文件夹"文本按钮，
        # 让 header 高度显著变矮；保留同样的悬停危险色反馈
        self.del_btn = tk.Button(
            header, text="\u2716",  # ✖
            font=self._header_font, relief="flat", bd=0,
            bg="#E0E0E0", fg="#B22222",
            activebackground="#FADBD8",
            padx=4, pady=0,
            command=self._on_delete
        )
        self.del_btn.pack(side="right")

        # ---- body（卡片 grid 容器；padding 也收紧） ----
        self.body = tk.Frame(self, bg="#F5F5F5", padx=4, pady=3)
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
        # 强制立即完成布局
        try:
            self.update_idletasks()
        except Exception:
            pass


# ================================================================
# 主应用窗口
# ================================================================
class App(tk.Tk):
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

        self.cfg = load_config()
        load_local_font(LOCAL_FONT_FILE)

        wcfg = self.cfg["window"]
        self.geometry(
            f"{int(wcfg.get('width', 900))}x{int(wcfg.get('height', 650))}"
            f"+{int(wcfg.get('x', 200))}+{int(wcfg.get('y', 100))}"
        )
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

        self._build_ui()
        self._apply_style_font()

        if not HAS_WIN32:
            messagebox.showwarning(
                "缺少依赖",
                "未检测到 pywin32 / Pillow，图标提取与卡片功能已禁用。\n\n"
                "请执行：\n  pip install pywin32 Pillow\n\n"
                f"错误详情：{_IMPORT_ERR}"
            )
            self.add_btn.configure(state="disabled")
            self.multi_add_btn.configure(state="disabled")
            self.new_folder_btn.configure(state="disabled")
        else:
            self._load_from_config()

        self.bind("<Configure>", self._on_window_configure)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ============================================================
    # 便捷 accessors
    # ============================================================
    @property
    def all_cards(self):
        return [c for f in self.folders for c in f.cards]

    def folder_by_id(self, fid):
        for f in self.folders:
            if f.id == fid:
                return f
        return None

    # ============================================================
    # UI 构建
    # ============================================================
    def _build_ui(self):
        bottom = tk.Frame(self)
        bottom.pack(side="bottom", fill="x")

        # 全局字体设置卡片
        font_card = tk.Frame(bottom, bd=1, relief="solid",
                             padx=8, pady=6, bg="#F8F9FA")
        font_card.pack(side="bottom", fill="x", padx=8, pady=(0, 8))

        tk.Label(font_card, text="全局字体：",
                 font=self.app_font, bg="#F8F9FA"
                 ).pack(side="left")
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

        tk.Label(font_card, text="字号：",
                 font=self.app_font, bg="#F8F9FA"
                 ).pack(side="left")
        self.font_size_var = tk.StringVar(
            value=str(int(self.app_font.cget("size"))))
        self.font_size_spin = tk.Spinbox(
            font_card, from_=8, to=36, width=5,
            textvariable=self.font_size_var,
            font=self.app_font, command=self._on_font_change
        )
        self.font_size_spin.pack(side="left", padx=4)
        self.font_size_spin.bind("<KeyRelease>", self._on_font_change)
        self.font_size_spin.bind("<FocusOut>", self._on_font_change)

        # 卡片宽度调节
        tk.Label(font_card, text="卡片宽度：",
                 font=self.app_font, bg="#F8F9FA"
                 ).pack(side="left", padx=(12, 0))
        self.card_width_var = tk.StringVar(value=str(int(self.card_width)))
        # tk.Spinbox 的箭头默认只在按下瞬间触发一次，长按不连续；
        # 这里保留 Spinbox 作为可键盘输入/单击的入口，但另外把两个自定义
        # 小箭头贴在旁边，用 ButtonPress/ButtonRelease + after 实现按住连续变化
        self.card_width_spin = tk.Spinbox(
            font_card, from_=200, to=1200, width=6,
            textvariable=self.card_width_var,
            font=self.app_font, command=self._on_card_width_change,
            increment=1
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
            padx=2, pady=0, width=2, takefocus=0
        )
        arrow_up.pack(side="left", padx=(2, 0))
        arrow_dn = tk.Button(
            font_card, text="\u25BC",  # ▼
            font=self._make_small_font(), relief="flat", bd=1,
            padx=2, pady=0, width=2, takefocus=0
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

        # 工具栏
        toolbar = tk.Frame(bottom)
        toolbar.pack(side="bottom", fill="x", padx=8, pady=(6, 0))

        self.add_btn = tk.Button(
            toolbar, text="添加快捷方式",
            font=self.app_font, command=self._on_add,
            padx=10, pady=4
        )
        self.add_btn.pack(side="left")

        self.multi_add_btn = tk.Button(
            toolbar, text="多选添加快捷方式",
            font=self.app_font, command=self._on_multi_add,
            padx=10, pady=4
        )
        self.multi_add_btn.pack(side="left", padx=(8, 0))

        self.new_folder_btn = tk.Button(
            toolbar, text="新建文件夹",
            font=self.app_font, command=self._on_new_folder,
            padx=10, pady=4
        )
        self.new_folder_btn.pack(side="left", padx=(8, 0))

        # 可滚动列表
        list_wrap = tk.Frame(self)
        list_wrap.pack(fill="both", expand=True, padx=8, pady=(8, 0))

        self.canvas = tk.Canvas(list_wrap, highlightthickness=0, bg="#F0F0F0")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.scrollbar = ttk.Scrollbar(
            list_wrap, orient="vertical", command=self.canvas.yview
        )
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.inner_frame = tk.Frame(self.canvas, bg="#F0F0F0")
        self.inner_window = self.canvas.create_window(
            (0, 0), window=self.inner_frame, anchor="nw"
        )
        self.inner_frame.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

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
    # Canvas / 滚动
    # ============================================================
    def _on_inner_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self.inner_window, width=event.width)

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
        self.canvas.yview_scroll(int(-event.delta / 120), "units")

    # ============================================================
    # 文件夹管理
    # ============================================================
    def _create_folder(self, folder_id, name):
        f = FolderFrame(self.inner_frame, self, folder_id, name)
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
        return f

    def _on_new_folder(self):
        fid = "f_" + uuid.uuid4().hex[:8]
        name = f"新文件夹 {len(self.folders) + 1}"
        self._create_folder(fid, name)
        self.save_state()

    def delete_folder(self, folder):
        if len(self.folders) <= 1:
            messagebox.showinfo("提示", "至少保留一个文件夹。")
            return
        # 卡片转移到最后一个剩余文件夹的末尾（"所有卡片队列末尾"）
        remaining = [f for f in self.folders if f is not folder]
        target = remaining[-1] if remaining else None
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
        self.save_state()

    # ============================================================
    # 添加 / 删除卡片
    # ============================================================
    def _on_add(self):
        path = filedialog.askopenfilename(
            title="选择快捷方式或程序",
            filetypes=[("快捷方式 / 程序", "*.lnk;*.exe"),
                       ("所有文件", "*.*")]
        )
        if path:
            self._add_card(path, "")
            self.save_state()

    def _on_multi_add(self):
        paths = filedialog.askopenfilenames(
            title="选择多个快捷方式或程序",
            filetypes=[("快捷方式 / 程序", "*.lnk;*.exe"),
                       ("所有文件", "*.*")]
        )
        for p in paths:
            self._add_card(p, "")
        if paths:
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
        return any(self._normalize_path(c.path) == norm for c in self.all_cards)

    def _add_card(self, path, description, folder=None):
        """添加卡片；重复路径安静跳过。默认加到第一个文件夹的末尾。"""
        if self._has_card_with_path(path):
            return False
        if folder is None:
            if not self.folders:
                self._create_folder(self.DEFAULT_FOLDER_ID, "默认")
            folder = self.folders[0]
        try:
            card = ShortcutCard(self.inner_frame, self, path, description)
        except Exception as e:
            print(f"[QuickDeck] add_card error: {e}", file=sys.stderr)
            return False
        folder.add_card(card)
        return True

    def remove_card(self, card):
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
        self.save_state()

    def launch_card(self, card):
        path = card.path
        try:
            if not os.path.exists(path):
                messagebox.showwarning(
                    "启动失败", f"文件不存在:\n{path}"
                )
                return
            os.startfile(path)
        except Exception as e:
            messagebox.showerror("启动失败", f"{path}\n\n{e}")

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
            self._add_card(p, it.get("description", ""), folder=target)

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
        self.dragging_card = card
        self.dragging_folder = None

    def card_drag_motion(self, card, event):
        if self.dragging_card is not card:
            return
        x, y = event.x_root, event.y_root
        target_folder = self._folder_at_y(y)
        if target_folder is None:
            return
        target_pos = self._insert_position_in_folder(target_folder, x, y, card)
        self._move_card_to(card, target_folder, target_pos)

    def card_drag_end(self, card, event):
        if self.dragging_card is card:
            self.dragging_card = None
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
        self.cfg["folders"] = [
            {"id": f.id, "name": f.name, "order": i,
             "locked": bool(getattr(f, "locked", False))}
            for i, f in enumerate(self.folders)
        ]
        shortcuts = []
        for f in self.folders:
            for j, c in enumerate(f.cards):
                shortcuts.append({
                    "path": c.path,
                    "description": c.desc_var.get(),
                    "folder": f.id,
                    "order": j
                })
        self.cfg["shortcuts"] = shortcuts
        save_config(self.cfg)

    def _on_close(self):
        try:
            self.save_state()
        finally:
            self.destroy()


# ================================================================
# 程序入口
# ================================================================
def main():
    enable_dpi_awareness()
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
