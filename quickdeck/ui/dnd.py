# -*- coding: utf-8 -*-
"""拖拽控制器（重构 P7）。

旧实现的问题：B1-Motion 每次事件都真实重排数据结构 + grid（无预览、
布局跟随鼠标跳动、高频全量 reflow）。新实现：

- motion 期间只做三件事：移动半透明幽灵卡（Toplevel）、命中测试、
  放置 accent 色插入指示线——数据与布局完全不动；
- ButtonRelease 才一次性 commit（移动数据 + 一次 reflow + mark_dirty）；
- 卡片与文件夹拖拽共用同一套幽灵/指示线基础设施；
- 命中测试合并了旧版 _insert_position_in_folder 与 _area_drag_motion
  两份近乎重复的实现。

对 App 的依赖（鸭子类型）：folders / web_cards / dir_cards /
view_mode / theme / app_font / _move_card_to / _reflow_flat /
mark_dirty / inner_frame。
"""
import tkinter as tk

DRAG_THRESHOLD = 8       # 超过该位移才认定为拖拽（防双击误触发幽灵）
INDICATOR_WIDTH = 3      # 插入指示线宽度（px）


class DragController:
    def __init__(self, app):
        self.app = app
        self.card = None            # 正在拖的卡片
        self.folder = None          # 正在拖的文件夹
        self._start_xy = (0, 0)
        self._active = False        # 已越过阈值、幽灵已挂
        self._ghost = None
        self._indicator = None
        self._target = None         # 卡片落点 ("folder", f, pos) / ("area", attr, pos)
        self._folder_target = None  # 文件夹落点 pos

    # ================= 卡片拖拽 =================
    def card_start(self, card, event):
        app = self.app
        # usage 视图只读；cards 视图只拖文件夹区卡片；web/dirs 只拖各自区
        if app.view_mode == "usage":
            return
        if app.view_mode == "web" and card not in app.web_cards:
            return
        if app.view_mode == "dirs" and card not in app.dir_cards:
            return
        if app.view_mode == "cards" and (card in app.web_cards
                                         or card in app.dir_cards):
            return
        self.card = card
        self.folder = None
        self._start_xy = (event.x_root, event.y_root)
        self._active = False
        self._target = None

    def card_motion(self, card, event):
        if self.card is not card:
            return
        x, y = event.x_root, event.y_root
        if not self._active:
            dx, dy = x - self._start_xy[0], y - self._start_xy[1]
            if dx * dx + dy * dy < DRAG_THRESHOLD ** 2:
                return
            self._active = True
            self._make_ghost(card)
        self._move_ghost(x, y)

        app = self.app
        if app.view_mode in ("web", "dirs"):
            attr = "web_cards" if app.view_mode == "web" else "dir_cards"
            cards = getattr(app, attr)
            others = [c for c in cards if c is not card]
            pos = self._pos_among(others, x, y)
            self._target = ("area", attr, pos)
            self._show_indicator_at(others, pos, app.flat_view)
            return

        target_folder = self._folder_at_y(y)
        if target_folder is None:
            self._hide_indicator()
            self._target = None
            return
        # 折叠的文件夹卡片区不可见，不作为落点（拖进去就"消失"）
        if target_folder.collapsed and target_folder is not card.folder:
            self._hide_indicator()
            self._target = None
            return
        others = [c for c in target_folder.cards if c is not card]
        pos = self._pos_among(others, x, y)
        self._target = ("folder", target_folder, pos)
        self._show_indicator_at(others, pos, target_folder.body)

    def card_end(self, card, event):
        if self.card is not card:
            return
        target, active = self._target, self._active
        self._cleanup()
        if not active or target is None:
            return
        app = self.app
        kind, dest, pos = target
        if kind == "area":
            cards = getattr(app, dest)
            others = [c for c in cards if c is not card]
            new_order = others[:pos] + [card] + others[pos:]
            if new_order != cards:
                setattr(app, dest, new_order)
                app._reflow_flat(new_order)
            app.mark_dirty("area drag")
        else:
            app._move_card_to(card, dest, pos)
            app.mark_dirty("card drag")

    # ================= 文件夹拖拽 =================
    def folder_start(self, folder, event):
        self.folder = folder
        self.card = None
        self._start_xy = (event.x_root, event.y_root)
        self._active = False
        self._folder_target = None

    def folder_motion(self, folder, event):
        if self.folder is not folder:
            return
        app = self.app
        if len(app.folders) <= 1:
            return
        x, y = event.x_root, event.y_root
        if not self._active:
            dy = y - self._start_xy[1]
            dx = x - self._start_xy[0]
            if dx * dx + dy * dy < DRAG_THRESHOLD ** 2:
                return
            self._active = True
            self._make_ghost(folder, is_folder=True)
        self._move_ghost(x, y)

        others = [f for f in app.folders if f is not folder]
        pos = 0
        for f in others:
            try:
                if y > f.winfo_rooty() + f.winfo_height() / 2:
                    pos += 1
                else:
                    break
            except tk.TclError:
                return
        self._folder_target = pos
        self._show_folder_indicator(others, pos)

    def folder_end(self, folder, event):
        if self.folder is not folder:
            return
        pos, active = self._folder_target, self._active
        self._cleanup()
        if not active or pos is None:
            return
        app = self.app
        others = [f for f in app.folders if f is not folder]
        new_order = others[:pos] + [folder] + others[pos:]
        if new_order != app.folders:
            app.folders = new_order
            for f in app.folders:
                try:
                    f.pack_forget()
                except Exception:
                    pass
            for f in app.folders:
                f.pack(fill="x", padx=6, pady=(6, 0))
            try:
                app.inner_frame.update_idletasks()
            except Exception:
                pass
        app.mark_dirty("folder drag")

    # ================= 命中测试 =================
    def _folder_at_y(self, y_root):
        """优先命中 y 范围；未命中按中心距吸附最近文件夹。"""
        best_f, best_d = None, float("inf")
        for f in self.app.folders:
            try:
                top = f.winfo_rooty()
                h = f.winfo_height()
            except tk.TclError:
                continue
            if top <= y_root <= top + h:
                return f
            d = abs(y_root - (top + h / 2))
            if d < best_d:
                best_d, best_f = d, f
        return best_f

    @staticmethod
    def _pos_among(others, x_root, y_root):
        """在网格排列的 others 中求插入下标：先找最近卡片，
        跨行以中心 y ± 1/3 高度为界，同行内以中心 x 为界。
        （合并旧版两份重复实现）"""
        if not others:
            return 0
        best_i, best_d = 0, float("inf")
        for i, c in enumerate(others):
            try:
                cx = c.winfo_rootx() + c.winfo_width() / 2
                cy = c.winfo_rooty() + c.winfo_height() / 2
            except tk.TclError:
                continue
            d = (cx - x_root) ** 2 + (cy - y_root) ** 2
            if d < best_d:
                best_d, best_i = d, i
        bc = others[best_i]
        try:
            ccx = bc.winfo_rootx() + bc.winfo_width() / 2
            ccy = bc.winfo_rooty() + bc.winfo_height() / 2
            h3 = bc.winfo_height() / 3
        except tk.TclError:
            return best_i
        if y_root < ccy - h3:
            return best_i
        if y_root > ccy + h3:
            return best_i + 1
        return best_i if x_root < ccx else best_i + 1

    # ================= 幽灵卡片 =================
    def _make_ghost(self, widget, is_folder=False):
        app = self.app
        th = app.theme
        try:
            g = tk.Toplevel(app)
            g.overrideredirect(True)
            g.attributes("-alpha", 0.75)
            g.attributes("-topmost", True)
            body = tk.Frame(g, bg=th["card_bg"],
                            highlightthickness=1,
                            highlightbackground=th["accent"])
            body.pack(fill="both", expand=True)
            if is_folder:
                text = "\u2630  " + widget.name
                tk.Label(body, text=text, font=app.app_font,
                         bg=th["card_bg"], fg=th["fg"],
                         padx=10, pady=4).pack()
            else:
                row = tk.Frame(body, bg=th["card_bg"], padx=8, pady=5)
                row.pack()
                icon = getattr(widget, "icon_photo", None)
                if icon is not None:
                    tk.Label(row, image=icon,
                             bg=th["card_bg"]).pack(side="left",
                                                    padx=(0, 6))
                tk.Label(row, text=widget.title_label.cget("text"),
                         font=app.app_font, bg=th["card_bg"],
                         fg=th["fg"]).pack(side="left")
            self._ghost = g
        except Exception:
            self._ghost = None  # 幽灵失败不影响拖拽本身

    def _move_ghost(self, x_root, y_root):
        if self._ghost is None:
            return
        try:
            self._ghost.geometry(f"+{x_root + 12}+{y_root + 12}")
        except Exception:
            pass

    # ================= 插入指示线 =================
    def _ensure_indicator(self):
        if self._indicator is None or not self._indicator.winfo_exists():
            self._indicator = tk.Frame(self.app.inner_frame,
                                       bg=self.app.theme["accent"],
                                       width=INDICATOR_WIDTH)
        else:
            self._indicator.configure(bg=self.app.theme["accent"])
        return self._indicator

    def _place_indicator(self, x_root, y_root, w, h):
        """按屏幕坐标在 inner_frame 中放置指示条。"""
        ind = self._ensure_indicator()
        try:
            base_x = self.app.inner_frame.winfo_rootx()
            base_y = self.app.inner_frame.winfo_rooty()
            ind.place(x=x_root - base_x, y=y_root - base_y,
                      width=w, height=h)
            ind.tkraise()
        except Exception:
            pass

    def _show_indicator_at(self, others, pos, container):
        """竖线放在插入下标对应卡片的左缘；末尾则放在最后一张右缘；
        空容器时放在容器内容区左上。"""
        try:
            if others:
                if pos < len(others):
                    c = others[pos]
                    x = c.winfo_rootx() - 4
                    y = c.winfo_rooty()
                    h = c.winfo_height()
                else:
                    c = others[-1]
                    x = c.winfo_rootx() + c.winfo_width() + 1
                    y = c.winfo_rooty()
                    h = c.winfo_height()
            else:
                x = container.winfo_rootx() + 4
                y = container.winfo_rooty() + 4
                h = max(24, container.winfo_height() - 8)
            self._place_indicator(x, y, INDICATOR_WIDTH, h)
        except tk.TclError:
            pass

    def _show_folder_indicator(self, others, pos):
        """横线放在插入位置的文件夹上缘（末尾放最后一个下缘）。"""
        try:
            if not others:
                return
            if pos < len(others):
                f = others[pos]
                y = f.winfo_rooty() - 4
            else:
                f = others[-1]
                y = f.winfo_rooty() + f.winfo_height() + 1
            x = f.winfo_rootx()
            w = f.winfo_width()
            self._place_indicator(x, y, w, INDICATOR_WIDTH)
        except tk.TclError:
            pass

    def _hide_indicator(self):
        if self._indicator is not None:
            try:
                self._indicator.place_forget()
            except Exception:
                pass

    # ================= 清理 =================
    def _cleanup(self):
        self.card = None
        self.folder = None
        if self._ghost is not None:
            try:
                self._ghost.destroy()
            except Exception:
                pass
            self._ghost = None
        self._hide_indicator()
