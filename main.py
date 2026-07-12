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
def resolve_shortcut(lnk_path):
    """解析 .lnk 得到 (target, icon_path, icon_index)。"""
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
        # 展开 %SystemRoot% 之类的环境变量，否则 os.path.exists 会假失败
        if target:
            target = os.path.expandvars(target)
        if icon_path:
            icon_path = os.path.expandvars(icon_path)
        return target, icon_path, icon_index
    except Exception as e:
        print(f"[QuickDeck] resolve_shortcut error: {e}", file=sys.stderr)
        return "", "", 0


def _hicon_to_pil(hicon, size=ICON_SIZE):
    """
    把 HICON 绘制到 32bit 兼容位图并转成 PIL.Image (RGBA)。
    调用后 **一定** 会 DestroyIcon(hicon)，失败返回 None。
    """
    hdc_handle = None
    hdc = None
    memdc = None
    try:
        hdc_handle = win32gui.GetDC(0)
        hdc = win32ui.CreateDCFromHandle(hdc_handle)
        hbmp = win32ui.CreateBitmap()
        hbmp.CreateCompatibleBitmap(hdc, size, size)
        memdc = hdc.CreateCompatibleDC()
        old = memdc.SelectObject(hbmp)
        # DrawIconEx 支持任意尺寸缩放绘制
        win32gui.DrawIconEx(
            memdc.GetSafeHdc(), 0, 0, hicon,
            size, size, 0, 0, win32con.DI_NORMAL
        )
        memdc.SelectObject(old)
        # 位图字节按 BGRA 排列，用 Pillow 读回 RGBA
        bmp_bits = hbmp.GetBitmapBits(True)
        img = Image.frombuffer(
            "RGBA", (size, size),
            bmp_bits, "raw", "BGRA", 0, 1
        )
        return img
    except Exception as e:
        print(f"[QuickDeck] _hicon_to_pil error: {e}", file=sys.stderr)
        return None
    finally:
        # 严格顺序释放：memdc → hdc → GetDC 得到的句柄 → hicon
        try:
            if memdc:
                memdc.DeleteDC()
        except Exception:
            pass
        try:
            if hdc:
                hdc.DeleteDC()
        except Exception:
            pass
        try:
            if hdc_handle:
                win32gui.ReleaseDC(0, hdc_handle)
        except Exception:
            pass
        try:
            win32gui.DestroyIcon(hicon)
        except Exception:
            pass


def extract_icon_image(path, index=0, size=ICON_SIZE):
    """
    ExtractIconEx 从 exe/dll/ico 抽取图标 → PIL.Image。
    对普通 PE 文件效果最好；对 UWP、shell 命名空间、
    某些自定义资源可能拿不到，此时应走 shget_icon_image 兜底。
    """
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
        try:
            win32gui.DestroyIcon(h)
        except Exception:
            pass
    return _hicon_to_pil(hicon, size)


# ---- SHGetFileInfoW 兜底 ---------------------------------------
# 通过 ctypes 直接调用 shell32，避免依赖 pywin32 的 shell 子模块
_SHGFI_ICON = 0x00000100
_SHGFI_LARGEICON = 0x00000000
_SHGFI_USEFILEATTRIBUTES = 0x00000010


class _SHFILEINFOW(ctypes.Structure):
    _fields_ = [
        ("hIcon", ctypes.c_void_p),
        ("iIcon", ctypes.c_int),
        ("dwAttributes", ctypes.c_ulong),
        ("szDisplayName", ctypes.c_wchar * 260),
        ("szTypeName", ctypes.c_wchar * 80),
    ]


def shget_icon_image(path, size=ICON_SIZE):
    """
    用 shell32.SHGetFileInfoW 取"Explorer 里显示的那张图标"，覆盖：
      - UWP / AppX / shell 命名空间目标 (ExtractIconEx 拿不到)
      - lnk 本身：Windows 会自动解析目标并叠加左下角小箭头
      - 图标资源不在常规 icon table 里的 exe
    失败返回 None。
    """
    if not path:
        return None
    try:
        info = _SHFILEINFOW()
        # 目标若不存在，加 SHGFI_USEFILEATTRIBUTES 让 shell 只按扩展名给通用图标；
        # 存在则不加，能拿到"真图标"。
        flags = _SHGFI_ICON | _SHGFI_LARGEICON
        if not os.path.exists(path):
            flags |= _SHGFI_USEFILEATTRIBUTES
        ret = ctypes.windll.shell32.SHGetFileInfoW(
            ctypes.c_wchar_p(path),
            0,
            ctypes.byref(info),
            ctypes.sizeof(info),
            flags
        )
        if ret == 0 or not info.hIcon:
            return None
        return _hicon_to_pil(info.hIcon, size)
    except Exception as e:
        print(f"[QuickDeck] shget_icon_image error: {e}", file=sys.stderr)
        return None


# ---- IShellItemImageFactory 兜底 -------------------------------
# Windows Vista+ 官方 API，Explorer 里显示大图标 / 缩略图用的路径。
# 对 .NET 内嵌资源、UWP、以及 ExtractIconEx / SHGetFileInfoW 都拿不到
# 或返回"通用图标"的场景效果最好。
# 走 ctypes 手写 COM vtable 调用，避免依赖 pywin32 的 shell 子模块。

class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_byte * 8),
    ]


def _iid(s):
    g = _GUID()
    ctypes.windll.ole32.CLSIDFromString(ctypes.c_wchar_p(s), ctypes.byref(g))
    return g


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


_IID_IShellItem_STR = "{43826D1E-E718-42EE-BC55-A1E261C37BFE}"
_IID_IShellItemImageFactory_STR = "{BCC18B79-BA16-442F-80C4-8A59C30C463B}"

# IShellItemImageFactory::GetImage 的 SIIGBF 标志
_SIIGBF_BIGGERSIZEOK = 0x00000001  # 允许返回比请求更大的图标（再让我们缩）
_SIIGBF_ICONONLY = 0x00000004      # 只要图标，不要缩略图

_COM_INITED = False


def _ensure_com():
    global _COM_INITED
    if not _COM_INITED:
        try:
            # 0x2 = COINIT_APARTMENTTHREADED，tk 主线程用 STA
            ctypes.windll.ole32.CoInitializeEx(None, 0x2)
        except Exception:
            pass
        _COM_INITED = True


def _com_release(obj_ptr):
    """调用 IUnknown::Release (vtable[2])。"""
    if not obj_ptr:
        return
    try:
        vtbl = ctypes.cast(obj_ptr,
                           ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        rel_ft = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
        ctypes.cast(vtbl[2], rel_ft)(obj_ptr)
    except Exception:
        pass


def _hbitmap_to_pil(hbmp, size):
    """把 HBITMAP 转成 PIL.Image。调用方负责 DeleteObject(hbmp)。"""
    bm = _BITMAP()
    if ctypes.windll.gdi32.GetObjectW(hbmp, ctypes.sizeof(bm),
                                      ctypes.byref(bm)) == 0:
        return None
    w, h = int(bm.bmWidth), int(bm.bmHeight)
    if w <= 0 or h <= 0:
        return None

    bi = _BITMAPINFO()
    bi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
    bi.bmiHeader.biWidth = w
    bi.bmiHeader.biHeight = -h  # 顶到底，与 PIL 一致
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32
    bi.bmiHeader.biCompression = 0  # BI_RGB

    buf = (ctypes.c_ubyte * (w * h * 4))()
    hdc = ctypes.windll.user32.GetDC(0)
    try:
        got = ctypes.windll.gdi32.GetDIBits(
            hdc, hbmp, 0, h,
            ctypes.byref(buf), ctypes.byref(bi), 0  # DIB_RGB_COLORS
        )
        if got == 0:
            return None
    finally:
        ctypes.windll.user32.ReleaseDC(0, hdc)

    img = Image.frombuffer("RGBA", (w, h), bytes(buf), "raw", "BGRA", 0, 1)
    if (w, h) != (size, size):
        img = img.resize((size, size), Image.LANCZOS)
    return img


def imagefactory_icon(path, size=ICON_SIZE):
    """
    通过 IShellItemImageFactory::GetImage 拿图标。
    对 .NET 内嵌资源 / UWP / 其他 API 拿不到的场景效果最好。
    请求 2x 尺寸 + BIGGERSIZEOK，能拿到更清晰的 jumbo 版本再缩放。
    """
    if not path:
        return None
    _ensure_com()

    item_ptr = ctypes.c_void_p()
    factory_ptr = ctypes.c_void_p()
    hbmp = ctypes.c_void_p()
    try:
        iid_item = _iid(_IID_IShellItem_STR)
        iid_factory = _iid(_IID_IShellItemImageFactory_STR)

        # HRESULT SHCreateItemFromParsingName(pszPath, pbc, riid, ppv)
        hr = ctypes.windll.shell32.SHCreateItemFromParsingName(
            ctypes.c_wchar_p(path), None,
            ctypes.byref(iid_item), ctypes.byref(item_ptr)
        )
        if hr != 0 or not item_ptr.value:
            return None

        # item->QueryInterface(IID_IShellItemImageFactory, &factory)
        vtbl_item = ctypes.cast(
            item_ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
        )[0]
        qi_ft = ctypes.WINFUNCTYPE(
            ctypes.HRESULT, ctypes.c_void_p,
            ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)
        )
        hr = ctypes.cast(vtbl_item[0], qi_ft)(
            item_ptr, ctypes.byref(iid_factory), ctypes.byref(factory_ptr)
        )
        if hr != 0 or not factory_ptr.value:
            return None

        # factory->GetImage((cx, cy), flags, &hbmp)  (vtable[3])
        sz = _SIZE(size * 2, size * 2)
        vtbl_fac = ctypes.cast(
            factory_ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
        )[0]
        gi_ft = ctypes.WINFUNCTYPE(
            ctypes.HRESULT, ctypes.c_void_p,
            _SIZE, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)
        )
        hr = ctypes.cast(vtbl_fac[3], gi_ft)(
            factory_ptr, sz,
            _SIIGBF_BIGGERSIZEOK | _SIIGBF_ICONONLY,
            ctypes.byref(hbmp)
        )
        if hr != 0 or not hbmp.value:
            return None

        return _hbitmap_to_pil(hbmp.value, size)
    except Exception as e:
        print(f"[QuickDeck] imagefactory_icon error: {e}", file=sys.stderr)
        return None
    finally:
        if hbmp and hbmp.value:
            try:
                ctypes.windll.gdi32.DeleteObject(hbmp)
            except Exception:
                pass
        _com_release(factory_ptr)
        _com_release(item_ptr)


def get_icon_for_file(path, size=ICON_SIZE):
    """
    多层兜底图标提取：
      .lnk:
        1) IconLocation 指定的图标（若有）
        2) TargetPath 的 ExtractIconEx
        3) IShellItemImageFactory 对 lnk 本身  ← 对 .NET / 特殊资源最强
        4) IShellItemImageFactory 对 TargetPath
        5) SHGetFileInfoW 对 lnk 本身
        6) SHGetFileInfoW 对 TargetPath
      其他文件:
        1) ExtractIconEx
        2) IShellItemImageFactory
        3) SHGetFileInfoW
    """
    if not HAS_WIN32:
        return None
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

        # IShellItemImageFactory 对 lnk 本身
        img = imagefactory_icon(path, size)
        if img is not None:
            return img

        if target:
            img = imagefactory_icon(target, size)
            if img is not None:
                return img

        # 最后 SHGetFileInfoW 兜底
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
    """
    单张快捷方式卡片：
      [图标] [标题 / 描述输入框]                     [删除]
    整卡（除 Entry / 删除按钮外的区域）都能作为拖拽把手。
    """

    def __init__(self, master, app, path, description=""):
        super().__init__(master, bd=1, relief="solid",
                         padx=8, pady=6, bg="#FFFFFF")
        self.app = app
        self.path = path

        # ---- 图标 ---------------------------------------------
        pil = get_icon_for_file(path) if HAS_WIN32 else None
        if pil is None:
            pil = app.default_icon_img
        # 引用必须保留，否则 PhotoImage 会被 GC，图片消失
        self.icon_pil = pil
        self.icon_photo = ImageTk.PhotoImage(pil)

        self.icon_label = tk.Label(self, image=self.icon_photo,
                                   bg="#FFFFFF", cursor="fleur")
        self.icon_label.pack(side="left", padx=(0, 8))

        # ---- 中间：标题 + 描述 --------------------------------
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
        # 编辑完描述后保存
        self.desc_entry.bind("<FocusOut>",
                             lambda e: self.app.save_state())
        self.desc_entry.bind("<Return>",
                             lambda e: self.app.save_state())

        # ---- 删除按钮 -----------------------------------------
        self.del_btn = tk.Button(self, text="\u274C",  # ❌
                                 width=3,
                                 font=app.app_font, relief="flat",
                                 bg="#FFFFFF", fg="#B22222",
                                 activebackground="#FADBD8",
                                 command=self._on_delete)
        self.del_btn.pack(side="right", padx=(8, 0))

        # ---- 拖拽 & 双击绑定 -----------------------------------
        # 仅绑到非交互控件上，避免影响 Entry 选择与删除按钮点击
        for w in (self, mid, self.icon_label, self.title_label):
            w.bind("<ButtonPress-1>", self._on_drag_start)
            w.bind("<B1-Motion>", self._on_drag_motion)
            w.bind("<ButtonRelease-1>", self._on_drag_end)
            # 双击卡片区域 = 启动对应程序
            w.bind("<Double-Button-1>", self._on_double_click)

    # ---- 事件回调 ---------------------------------------------
    def _on_delete(self):
        self.app.remove_card(self)

    def _on_drag_start(self, e):
        self.app.drag_start(self, e)

    def _on_drag_motion(self, e):
        self.app.drag_motion(self, e)

    def _on_drag_end(self, e):
        self.app.drag_end(self, e)

    def _on_double_click(self, e):
        self.app.launch_card(self)


# ================================================================
# 主应用窗口
# ================================================================
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("QuickDeck")

        # 加载配置与本地字体
        self.cfg = load_config()
        load_local_font(LOCAL_FONT_FILE)

        # 还原窗口尺寸/位置
        wcfg = self.cfg["window"]
        w = int(wcfg.get("width", 900))
        h = int(wcfg.get("height", 650))
        x = int(wcfg.get("x", 200))
        y = int(wcfg.get("y", 100))
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(560, 380)

        # 全局字体对象：所有 tk 控件用 font=self.app_font
        # 修改 configure 后，控件会自动跟随（tkFont.Font 的机制）
        self.app_font = tkFont.Font(
            family=self.cfg["font"].get("family", BUILTIN_FONT_FAMILY),
            size=int(self.cfg["font"].get("size", 12))
        )

        # ttk 主题与字体
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass

        # 默认图标（PIL 层，卡片按需转 PhotoImage）
        self.default_icon_img = make_default_icon() if HAS_WIN32 else None

        # 运行时状态
        self.cards = []
        self.dragging_card = None
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
            # 无依赖时禁用添加按钮
            self.add_btn.configure(state="disabled")
            self.multi_add_btn.configure(state="disabled")
        else:
            self._load_shortcuts_from_config()

        self.bind("<Configure>", self._on_window_configure)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ============================================================
    # UI 构建
    # ============================================================
    def _build_ui(self):
        # ---------- 底部区域 ----------
        bottom = tk.Frame(self)
        bottom.pack(side="bottom", fill="x")

        # 全局字体设置卡片（固定，不可删除、不可拖动）
        font_card = tk.Frame(bottom, bd=1, relief="solid",
                             padx=8, pady=6, bg="#F8F9FA")
        font_card.pack(side="bottom", fill="x", padx=8, pady=(0, 8))

        tk.Label(font_card, text="全局字体：",
                 font=self.app_font, bg="#F8F9FA"
                 ).pack(side="left")

        self.font_family_var = tk.StringVar(
            value=self.app_font.cget("family"))
        families = sorted({f for f in tkFont.families() if f.strip()})
        # 保证内置字体与当前使用字体一定出现在下拉列表里
        # （tk 的字体枚举有时看不到 AddFontResourceEx 私有加载的字体）
        for extra in (BUILTIN_FONT_FAMILY, self.app_font.cget("family")):
            if extra and extra not in families:
                families.append(extra)
        families.sort()
        self.font_family_cb = ttk.Combobox(
            font_card, textvariable=self.font_family_var,
            values=families, width=26
        )
        self.font_family_cb.pack(side="left", padx=(4, 12))
        self.font_family_cb.bind(
            "<<ComboboxSelected>>", self._on_font_change)
        self.font_family_cb.bind("<Return>", self._on_font_change)
        self.font_family_cb.bind("<FocusOut>", self._on_font_change)

        tk.Label(font_card, text="字号：",
                 font=self.app_font, bg="#F8F9FA"
                 ).pack(side="left")
        # 用 StringVar 而非 IntVar，避免用户输错时抛 TclError
        self.font_size_var = tk.StringVar(
            value=str(int(self.app_font.cget("size"))))
        self.font_size_spin = tk.Spinbox(
            font_card, from_=8, to=36, width=5,
            textvariable=self.font_size_var,
            font=self.app_font,
            command=self._on_font_change
        )
        self.font_size_spin.pack(side="left", padx=4)
        self.font_size_spin.bind("<KeyRelease>", self._on_font_change)
        self.font_size_spin.bind("<FocusOut>", self._on_font_change)

        # 按钮工具栏
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

        # ---------- 中间可滚动列表 ----------
        list_wrap = tk.Frame(self)
        list_wrap.pack(fill="both", expand=True, padx=8, pady=(8, 0))

        self.canvas = tk.Canvas(list_wrap,
                                highlightthickness=0,
                                bg="#F0F0F0")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.scrollbar = ttk.Scrollbar(
            list_wrap, orient="vertical",
            command=self.canvas.yview
        )
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        # 用 Canvas.create_window 承载 Frame，Frame 尺寸变化时更新 scrollregion
        self.inner_frame = tk.Frame(self.canvas, bg="#F0F0F0")
        self.inner_window = self.canvas.create_window(
            (0, 0), window=self.inner_frame, anchor="nw"
        )
        self.inner_frame.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # 全局鼠标滚轮
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    # ============================================================
    # 样式 / 字体
    # ============================================================
    def _apply_style_font(self):
        """把当前字体同步到 ttk 控件、Combobox 下拉列表。"""
        fam = self.app_font.cget("family")
        sz = int(self.app_font.cget("size"))
        tup = (fam, sz)
        for name in ("TCombobox", "TButton", "TLabel",
                     "TEntry", "TSpinbox"):
            try:
                self.style.configure(name, font=tup)
            except tk.TclError:
                pass
        # Combobox 下拉列表用 option database 指定字体
        self.option_add("*TCombobox*Listbox.font", tup)
        # 已实例化的 Combobox 直接改字体，让效果立即可见
        if hasattr(self, "font_family_cb"):
            try:
                self.font_family_cb.configure(font=tup)
            except tk.TclError:
                pass

    # ============================================================
    # Canvas 滚动
    # ============================================================
    def _on_inner_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        # 让内部 frame 宽度跟随 canvas
        self.canvas.itemconfigure(self.inner_window, width=event.width)

    def _on_mousewheel(self, event):
        if not self.cards:
            return
        # 只在鼠标位于 canvas 内时滚动
        rx, ry = event.x_root, event.y_root
        cx1 = self.canvas.winfo_rootx()
        cy1 = self.canvas.winfo_rooty()
        cx2 = cx1 + self.canvas.winfo_width()
        cy2 = cy1 + self.canvas.winfo_height()
        if not (cx1 <= rx <= cx2 and cy1 <= ry <= cy2):
            return
        # Windows 上 event.delta 是 120 的倍数
        self.canvas.yview_scroll(int(-event.delta / 120), "units")

    # ============================================================
    # 添加 / 删除
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
        """规范化路径用于去重（大小写不敏感 + 展开环境变量 + 绝对路径）。"""
        if not p:
            return ""
        try:
            return os.path.normcase(os.path.abspath(os.path.expandvars(p)))
        except Exception:
            return p

    def _has_card_with_path(self, path):
        norm = self._normalize_path(path)
        return any(self._normalize_path(c.path) == norm for c in self.cards)

    def _add_card(self, path, description):
        """添加卡片；若路径已存在则安静跳过，返回是否真的添加了。"""
        if self._has_card_with_path(path):
            return False
        try:
            card = ShortcutCard(self.inner_frame, self, path, description)
        except Exception as e:
            print(f"[QuickDeck] add_card error: {e}", file=sys.stderr)
            return False
        card.pack(fill="x", pady=3, padx=2)
        self.cards.append(card)
        return True

    def launch_card(self, card):
        """双击卡片时启动对应的快捷方式/程序。"""
        path = card.path
        try:
            if not os.path.exists(path):
                messagebox.showwarning(
                    "启动失败", f"文件不存在:\n{path}"
                )
                return
            # os.startfile 在 Windows 上等价于双击资源管理器：
            # .lnk 会被解析并启动、.exe 会直接运行
            os.startfile(path)
        except Exception as e:
            messagebox.showerror("启动失败", f"{path}\n\n{e}")

    def _load_shortcuts_from_config(self):
        items = self.cfg.get("shortcuts", [])
        items = sorted(items, key=lambda x: x.get("order", 0))
        for it in items:
            p = it.get("path")
            if not p:
                continue
            self._add_card(p, it.get("description", ""))

    def remove_card(self, card):
        try:
            card.pack_forget()
            card.destroy()
        except Exception:
            pass
        if card in self.cards:
            self.cards.remove(card)
        self.save_state()

    # ============================================================
    # 字体切换（延时应用，防止输入中间态被应用）
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
        # 无变化则跳过，避免多余保存
        if (family == self.app_font.cget("family")
                and size == int(self.app_font.cget("size"))):
            return
        # 修改 tkFont.Font 后，所有引用它的控件自动重绘
        self.app_font.configure(family=family, size=size)
        self._apply_style_font()
        self.save_state()

    # ============================================================
    # 窗口尺寸/位置变化：延时保存，避免拉伸时反复写盘
    # ============================================================
    def _on_window_configure(self, event):
        # <Configure> 会从各层子控件冒泡上来，只关心主窗口自己
        if event.widget is not self:
            return
        if self._save_timer is not None:
            try:
                self.after_cancel(self._save_timer)
            except Exception:
                pass
        self._save_timer = self.after(500, self.save_state)

    # ============================================================
    # 拖拽排序
    #   - 使用屏幕坐标（event.y_root / winfo_rooty）比较
    #     因此滚动偏移不影响算法
    # ============================================================
    def drag_start(self, card, event):
        self.dragging_card = card

    def drag_motion(self, card, event):
        if self.dragging_card is not card:
            return
        if len(self.cards) <= 1:
            return

        mouse_y = event.y_root
        others = [c for c in self.cards if c is not card]

        # 在 others 中扫描：鼠标已经越过某个卡片中心线，则插入点 +1
        target_pos = 0
        for c in others:
            try:
                top = c.winfo_rooty()
                h = c.winfo_height()
            except tk.TclError:
                return
            if mouse_y > top + h / 2:
                target_pos += 1
            else:
                break

        new_order = others[:target_pos] + [card] + others[target_pos:]
        if new_order == self.cards:
            return

        # 仅当顺序确实变化时才重排，减少闪烁
        self.cards = new_order
        for c in self.cards:
            c.pack_forget()
        for c in self.cards:
            c.pack(fill="x", pady=3, padx=2)
        # 立即完成布局，让下一次 motion 拿到最新 winfo_rooty
        try:
            self.inner_frame.update_idletasks()
        except Exception:
            pass

    def drag_end(self, card, event):
        if self.dragging_card is card:
            self.dragging_card = None
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
        self.cfg["shortcuts"] = [
            {
                "path": c.path,
                "description": c.desc_var.get(),
                "order": i
            }
            for i, c in enumerate(self.cards)
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
def main():
    enable_dpi_awareness()
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
