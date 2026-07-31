# -*- coding: utf-8 -*-
"""Win32 图标提取：多通道兜底
(ExtractIconEx / PrivateExtractIconsW / SHGetFileInfoW /
 IShellItemImageFactory)，HICON/HBITMAP -> PIL。

从 main.py 原样迁移，保持行为等价。"""
import os
import sys
import ctypes
import threading

from quickdeck.constants import ICON_SIZE

try:
    import win32com.client
    import win32gui
    from PIL import Image, ImageDraw
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False


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
