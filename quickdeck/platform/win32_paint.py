# -*- coding: utf-8 -*-
"""Win32 绘制辅助：防闪三层机制 + 类背景刷 + 深色标题栏。

从 main.py 的 App 方法收口而来（重构 P5b），机制与注释见各方法。
三层防残影（视图/主题切换）：
1. 截屏幕布（根治）：客户区像素 BitBlt 进内存位图，用原生
   STATIC(SS_BITMAP) 弹窗原位盖住；切换与全部重绘在幕布下完成，
   撤幕即完整新帧，与 Tk 异步绘制时序彻底解耦。
2. WM_SETREDRAW 冻结（兜底）：冻结期间 SetWindowPos 只改几何不上屏。
3. Tcl 层批处理标志（App._view_switch_batch，另行保留）。

类背景刷：Tk 窗口类 hbrBackground=NULL，Win11 最小化恢复时 DWM 表面
全黑先露出（黑闪）；挂主题色实心刷后擦除阶段先填主题色。
深色标题栏：DWMWA_USE_IMMERSIVE_DARK_MODE，仅在目标值变化时写入
（浅色启动完全不碰该属性，避免走深浅色感知合成路径引入黑边）。
"""
import sys
import ctypes
from contextlib import contextmanager

from quickdeck.platform.win32_icons import _init_win_apis

_WM_SETREDRAW = 0x000B
# INVALIDATE|ERASE|ALLCHILDREN|UPDATENOW
_RDW_REPAINT = 0x0001 | 0x0004 | 0x0080 | 0x0100
# WS_POPUP|WS_VISIBLE|SS_BITMAP
_CURTAIN_STYLE = 0x80000000 | 0x10000000 | 0x0000000E
# WS_EX_NOACTIVATE|WS_EX_TOOLWINDOW
_CURTAIN_EXSTYLE = 0x08000000 | 0x00000080
_STM_SETIMAGE = 0x0172
_SRCCOPY = 0x00CC0020
_GCLP_HBRBACKGROUND = -10


class PaintGuard:
    """持有 tk 顶层（root）的绘制辅助。所有方法 best-effort：
    失败时静默退化，不影响功能路径。"""

    def __init__(self, root):
        self.root = root
        self._frozen = False
        self._curtain_active = False
        self._bg_brush = None
        self._titlebar_dark_val = 0

    # ---- 冻结 ----
    def freeze(self):
        """WM_SETREDRAW(FALSE)。返回冻结的 hwnd；嵌套/失败返回 None
        （WM_SETREDRAW 无引用计数，嵌套必须由外层统一解冻）。"""
        if self._frozen:
            return None
        try:
            hwnd = self.root.winfo_id()
            ctypes.windll.user32.SendMessageW(hwnd, _WM_SETREDRAW, 0, 0)
        except Exception:
            return None
        self._frozen = True
        return hwnd

    def thaw(self, hwnd):
        """WM_SETREDRAW(TRUE) + RedrawWindow(ALLCHILDREN) 整树重绘。"""
        if not hwnd:
            return
        self._frozen = False
        try:
            user32 = ctypes.windll.user32
            user32.SendMessageW(hwnd, _WM_SETREDRAW, 1, 0)
            user32.RedrawWindow(hwnd, None, None, _RDW_REPAINT)
        except Exception:
            pass

    # ---- 幕布 ----
    def show_curtain(self):
        """截屏客户区并用原生 STATIC 位图弹窗原位盖住。
        返回 (hwnd, HBITMAP)；嵌套/未映射/失败返回 None。"""
        if self._curtain_active:
            return None
        _init_win_apis()  # 首次调用可能早于任何图标提取，argtypes 必须就绪
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        hbm = None
        try:
            root = self.root
            if not root.winfo_ismapped():
                return None
            hwnd = root.winfo_id()
            w, h = int(root.winfo_width()), int(root.winfo_height())
            x, y = int(root.winfo_rootx()), int(root.winfo_rooty())
            if w <= 1 or h <= 1:
                return None
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
                                          hdc, 0, 0, _SRCCOPY)
                        gdi32.SelectObject(mdc, old)
                finally:
                    gdi32.DeleteDC(mdc)
            finally:
                user32.ReleaseDC(hwnd, hdc)
            if not (hbm and ok):
                raise OSError("curtain capture failed")
            owner = user32.GetParent(hwnd) or hwnd
            hinst = ctypes.windll.kernel32.GetModuleHandleW(None)
            cw = user32.CreateWindowExW(
                _CURTAIN_EXSTYLE, "STATIC", None, _CURTAIN_STYLE,
                x, y, w, h, owner, None, hinst, None)
            if not cw:
                raise OSError("curtain window failed")
            user32.SendMessageW(cw, _STM_SETIMAGE, 0, hbm)
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

    def hide_curtain(self, curtain):
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

    @contextmanager
    def guard(self, freeze=True):
        """幕布 + （可选）冻结包住一段几何/配色重建：
        进入时挂幕布、冻结；退出时解冻、在幕布下 update() 完成全部
        重绘、撤幕。嵌套进入时内层自动退化为 no-op。"""
        curtain = self.show_curtain()
        frozen = self.freeze() if freeze else None
        try:
            yield
        finally:
            self.thaw(frozen)
            if curtain:
                try:
                    self.root.update()
                except Exception:
                    pass
            self.hide_curtain(curtain)

    # ---- 类背景刷 ----
    def apply_class_brush(self, color_hex):
        """把 Tk 窗口类背景刷设为主题底色（防最小化恢复黑闪）。"""
        try:
            colorref = (int(color_hex[1:3], 16)
                        | int(color_hex[3:5], 16) << 8
                        | int(color_hex[5:7], 16) << 16)
            gdi32 = ctypes.windll.gdi32
            user32 = ctypes.windll.user32
            new_brush = gdi32.CreateSolidBrush(colorref)
            if not new_brush:
                return
            set_cls = getattr(user32, "SetClassLongPtrW", None) \
                or user32.SetClassLongW
            set_cls.restype = ctypes.c_ssize_t
            set_cls.argtypes = [ctypes.c_ssize_t, ctypes.c_int,
                                ctypes.c_ssize_t]
            self.root.update_idletasks()
            child = self.root.winfo_id()
            top = user32.GetParent(child)
            for hwnd in {child, top}:
                if hwnd:
                    set_cls(hwnd, _GCLP_HBRBACKGROUND, new_brush)
            if self._bg_brush:
                gdi32.DeleteObject(self._bg_brush)
            self._bg_brush = new_brush
        except Exception:
            pass

    # ---- 深色标题栏 ----
    def set_titlebar_dark(self, want_dark):
        """仅在目标值变化时写 DWMWA_USE_IMMERSIVE_DARK_MODE。"""
        want = 1 if want_dark else 0
        if want == self._titlebar_dark_val:
            return
        try:
            self.root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            val = ctypes.c_int(want)
            for attr in (20, 19):  # 20=IMMERSIVE_DARK_MODE，旧 build 19
                r = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(val), ctypes.sizeof(val))
                if r == 0:
                    self._titlebar_dark_val = want
                    break
        except Exception:
            pass
