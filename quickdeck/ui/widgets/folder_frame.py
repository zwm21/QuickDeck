# -*- coding: utf-8 -*-
"""文件夹分组控件（重构 P5c 自 main.py 迁出）。

卡片的 tk parent 是 App.inner_frame，通过 grid(in_=body) 显示在
文件夹内，跨文件夹移动不销毁重建（不重复提取图标）。
"""
import tkinter as tk
from tkinter import font as tkFont

from quickdeck.ui.layout import CARD_GAP, compute_cols, grid_signature


class FolderFrame(tk.Frame):
    """一个文件夹 section：header（拖拽把手 + 名字 + 删除）+ 卡片 grid 容器。

    卡片的 tk parent 是 App.inner_frame，通过 grid(in_=body) 显示在这里；
    这样跨文件夹移动卡片时不用销毁 / 重建，也就不用重新提取图标。
    """


    def __init__(self, master, app, meta):
        """meta: quickdeck.model.workspace.Folder——文件夹元数据
        （id/name/locked/collapsed）的唯一真源（重构 P4）。"""
        th = app.theme
        super().__init__(master, bd=0, bg=th["folder_bg"],
                 highlightthickness=1,
                 highlightbackground=th["border"],
                 highlightcolor=th["border"])
        self.app = app
        self.meta = meta
        self.cards = []
        self._num_cols = 1
        self._last_grid_sig = None  # 增量重排签名（重构 P6）

        # ---- header（紧凑：小 padding，无冗余空间） ----
        header = tk.Frame(self, bg=th["header_bg"], padx=4, pady=0)
        header.pack(fill="x")
        self.header = header

        # 用小号字（约为 app 字体的 0.9 倍）让 header 更矮
        self._header_font = tkFont.Font(
            family=app.app_font.cget("family"),
            size=max(8, int(app.app_font.cget("size")) - 1)
        )
        # P8 字号层级：文件夹名加粗（保持紧凑字号）
        self._name_font = tkFont.Font(
            family=app.app_font.cget("family"),
            size=max(8, int(app.app_font.cget("size"))),
            weight="bold"
        )

        self.drag_handle = tk.Label(
            header, text="\u2630", font=self._header_font,  # ☰
            bg=th["header_bg"], fg=th["fg"], cursor="fleur", padx=2
        )
        self.drag_handle.pack(side="left")

        self.name_var = tk.StringVar(value=meta.name)
        self.name_entry = tk.Entry(
            header, textvariable=self.name_var,
            font=self._name_font, bd=0, bg=th["header_bg"],
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
            padx=4, pady=0, cursor="hand2",
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
            padx=4, pady=0, cursor="hand2",
            command=self._on_toggle_collapse
        )
        self.collapse_btn.pack(side="right", padx=(0, 2))

        # 用小号 ✕ 按钮替代原来的"删除文件夹"文本按钮，
        # 让 header 高度显著变矮；保留同样的悬停危险色反馈
        self.del_btn = tk.Button(
            header, text="\u2716",  # ✖
            font=self._header_font, relief="flat", bd=0,
            bg=th["header_bg"], fg=th["header_fg"],
            activebackground=th["danger_active_bg"],
            padx=4, pady=0, cursor="hand2",
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

        # 主题注册（重构 P5）
        tm = app.tm
        tm.register(self, bg="folder_bg", highlightbackground="border",
                    highlightcolor="border")
        tm.register(header, bg="header_bg")
        tm.register(self.drag_handle, bg="header_bg", fg="fg")
        tm.register(self.name_entry, bg="header_bg", fg="fg",
                    insertbackground="fg", readonlybackground="header_bg")
        tm.register(self.lock_btn, bg="header_bg", fg="header_fg",
                    activebackground="header_active_bg")
        tm.register(self.collapse_btn, bg="header_bg", fg="header_fg",
                    activebackground="header_active_bg")
        tm.register(self.del_btn, bg="header_bg", fg="header_fg",
                    activebackground="danger_active_bg")
        tm.register(self.body, bg="folder_bg")

        # P8 hover：header 图标按钮
        from quickdeck.ui.widgets.hover import bind_hover
        bind_hover(app, self.lock_btn, "header_bg", "header_active_bg")
        bind_hover(app, self.collapse_btn, "header_bg", "header_active_bg")
        bind_hover(app, self.del_btn, "header_bg", "danger_hover_bg",
                   also_fg=("header_fg", "danger_fg"))

    # ---- 数据转发（重构 P4：元数据唯一真源是 self.meta） ----
    @property
    def id(self):
        return self.meta.id

    @property
    def name(self):
        return self.meta.name

    @name.setter
    def name(self, v):
        self.meta.name = v

    @property
    def locked(self):
        return self.meta.locked

    @locked.setter
    def locked(self, v):
        self.meta.locked = bool(v)

    @property
    def collapsed(self):
        return self.meta.collapsed

    @collapsed.setter
    def collapsed(self, v):
        self.meta.collapsed = bool(v)

    def refresh_header_font(self):
        """app 字体变化时，让 header 内部小号字跟着刷新。"""
        try:
            self._name_font.configure(
                family=self.app.app_font.cget("family"),
                size=max(8, int(self.app.app_font.cget("size"))))
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
            self.app.mark_dirty()

    def _on_delete(self):
        if self.locked:
            return
        self.app.delete_folder(self)

    def _on_toggle_lock(self):
        self.set_locked(not self.locked)
        self.app.mark_dirty()

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
        self.app.mark_dirty()

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
        return compute_cols(body_width, self.app.card_width)

    def invalidate_grid(self):
        """外部（视图切换等）把卡片 grid_forget 后调用，
        强制下次 _reflow 全量重排（跳过增量短路）。"""
        self._last_grid_sig = None

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

        # 增量短路（重构 P6）：列数/卡宽/卡片序列全部未变时跳过重排。
        # 拖拽 motion、长按调宽循环等高频路径大多命中此分支，
        # 避免旧实现每次全量 grid_forget + 重排的开销与闪烁。
        cw = int(self.app.card_width)
        sig = grid_signature(self.cards, self._num_cols, cw)
        if sig == getattr(self, "_last_grid_sig", None):
            return
        self._last_grid_sig = sig

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
        # 列宽恒为 cw + CARD_GAP（= 卡片墨迹宽 + padx 两侧），weight=0：
        # 卡宽只由卡宽控件决定，窗口变宽只增列数、余量留白在右侧。
        # 用过 weight=1 铺满整行，副作用是卡片被拉伸、卡宽控件失效。
        for col in range(self._num_cols):
            self.body.grid_columnconfigure(col, minsize=cw + CARD_GAP,
                                           weight=0)
        # 收敛：清掉多余列的最小宽度配置
        for col in range(self._num_cols, self._num_cols + 8):
            self.body.grid_columnconfigure(col, minsize=0, weight=0)
        for i, c in enumerate(self.cards):
            r, col = i // self._num_cols, i % self._num_cols
            c.grid(row=r, column=col, in_=self.body,
                   padx=3, pady=3, sticky="ew")
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

