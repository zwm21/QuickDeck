# -*- coding: utf-8 -*-
"""快捷方式卡片控件（重构 P5c 自 main.py 迁出）。

依赖注入约定：通过 app 引用获取运行时服务——
app.theme / app.tm（主题）、app.app_font、app.card_width、
app.icon_cache、app.has_win32、app.default_icon_img、
app.request_icon、app.mark_dirty、拖拽回调等。
"""
import os
import sys
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

from PIL import Image, ImageTk

from quickdeck.constants import ICON_SIZE
from quickdeck.platform.win32_icons import (
    get_icon_for_file, get_title_for_file,
)


class ShortcutCard(tk.Frame):
    """一张快捷方式卡片，宽度由 App.card_width 动态决定（默认 500px）。
    可拖拽（换顺序 / 跨文件夹）、可双击启动。
    """

    # 兼容旧引用；实际生效值走 App.card_width（可由 UI 实时调整）
    CARD_WIDTH = 500

    def __init__(self, master, app, item):
        """item: quickdeck.model.workspace.Shortcut——卡片的业务数据
        全部存于纯数据对象（重构 P4），widget 属性仅作 property 转发。"""
        th = app.theme
        # P8 视觉：描边用 highlight 系（可主题化），替代 relief="solid"
        super().__init__(master, bd=0, padx=8, pady=6, bg=th["card_bg"],
                         highlightthickness=1,
                         highlightbackground=th["border"],
                         highlightcolor=th["border"])
        self.app = app
        self.item = item
        self.folder = None  # 由 FolderFrame.add_card / insert_card 设置
        self._hovered = False
        self._flash_job = None
        path = item.path
        description = item.description

        # 图标：
        #   1) 自定义图标文件 → 同步加载（本地图像，开销小）
        #   2) (path, mtime) 缓存命中 → 同步用缓存（含磁盘 PNG，重启后有效）
        #   3) 未命中 → 先贴默认占位图标，交给 App 的 worker 线程异步提取，
        #      避免几十张卡片启动时把 UI 卡住
        pil = None
        pending_async = False
        if self.custom_icon:
            pil = self._load_icon_file(self.custom_icon)
        if pil is None and self.app.has_win32:
            pil = self.app.icon_cache.get(path)
        if pil is None:
            pil = app.default_icon_img
            pending_async = self.app.has_win32
        self.icon_pil = pil
        self.icon_photo = ImageTk.PhotoImage(pil)

        self.icon_label = tk.Label(self, image=self.icon_photo,
                                   bg=th["card_bg"], cursor="fleur")
        self.icon_label.pack(side="left", padx=(0, 8))

        mid = tk.Frame(self, bg=th["card_bg"])
        mid.pack(side="left", fill="both", expand=True)
        self.mid = mid

        title_text = self.custom_title or get_title_for_file(path)
        # P8 字号层级：标题加粗放大一号
        self.title_label = tk.Label(mid, text=title_text, anchor="w",
                                    font=app.font_title, bg=th["card_bg"],
                                    fg=th["fg"], cursor="fleur")
        self.title_label.pack(fill="x")

        self.desc_var = tk.StringVar(value=description)
        # P8 字号层级：描述缩小一号 + 次级文字色
        self.desc_entry = tk.Entry(mid, textvariable=self.desc_var,
                                   font=app.font_desc, relief="flat",
                                   bg=th["desc_bg"], fg=th["fg_secondary"],
                                   insertbackground=th["fg"],
                                   readonlybackground=th["desc_bg"])
        self.desc_entry.pack(fill="x", pady=(3, 0))
        self.desc_entry.bind("<FocusOut>", lambda e: self._sync_desc())
        self.desc_entry.bind("<Return>", lambda e: self._sync_desc())

        self.del_btn = tk.Button(self, text="\u2715",  # ✕（较 ❌ 更利落）
                                 width=3, font=app.font_desc, relief="flat",
                                 bd=0, cursor="hand2",
                                 bg=th["card_bg"], fg=th["fg_secondary"],
                                 activebackground=th["danger_active_bg"],
                                 activeforeground=th["danger_fg"],
                                 command=self._on_delete)
        self.del_btn.pack(side="right", padx=(8, 0))
        self.del_btn.bind("<Enter>", self._on_del_enter, add="+")
        self.del_btn.bind("<Leave>", self._on_del_leave, add="+")

        # P8 hover：整卡悬停高亮（进入子控件不算离开）
        self.bind("<Enter>", lambda e: self._set_hover(True), add="+")
        self.bind("<Leave>", self._on_pointer_leave, add="+")

        # 拖拽 & 双击（不绑 Entry / 删除按钮，避免影响文本编辑与点击）
        for w in (self, mid, self.icon_label, self.title_label):
            w.bind("<ButtonPress-1>", self._on_drag_start)
            w.bind("<B1-Motion>", self._on_drag_motion)
            w.bind("<ButtonRelease-1>", self._on_drag_end)
            w.bind("<Double-Button-1>", self._on_double_click)
            w.bind("<Button-3>", self._on_right_click)

        # 主题注册（重构 P5：切主题时由 ThemeManager 统一刷新）
        tm = app.tm
        tm.register(self, bg="card_bg", highlightbackground="border",
                    highlightcolor="border")
        tm.register(self.icon_label, bg="card_bg")
        tm.register(mid, bg="card_bg")
        tm.register(self.title_label, bg="card_bg", fg="fg")
        tm.register(self.desc_entry, bg="desc_bg", fg="fg_secondary",
                    insertbackground="fg", readonlybackground="desc_bg")
        tm.register(self.del_btn, bg="card_bg", fg="fg_secondary",
                    activebackground="danger_active_bg",
                    activeforeground="danger_fg")

        # widget 就绪后再入队异步提取（结果经主线程轮询回填）
        if pending_async:
            app.request_icon(self)

    # ---- hover / 启动反馈（P8 视觉升级） ----
    def _set_hover(self, on):
        self._hovered = bool(on)
        th = self.app.theme
        bg = th["card_hover_bg"] if on else th["card_bg"]
        border = th["border_strong"] if on else th["border"]
        try:
            self.configure(bg=bg, highlightbackground=border,
                           highlightcolor=border)
            for w in (self.icon_label, self.mid, self.title_label):
                w.configure(bg=bg)
            self.del_btn.configure(bg=bg)
        except tk.TclError:
            pass

    def _on_pointer_leave(self, _e):
        """离开事件也会在进入子控件时触发（NotifyInferior），
        指针仍在卡片矩形内则维持 hover。"""
        try:
            x, y = self.winfo_pointerxy()
            rx, ry = self.winfo_rootx(), self.winfo_rooty()
            if (rx <= x < rx + self.winfo_width()
                    and ry <= y < ry + self.winfo_height()):
                return
        except tk.TclError:
            pass
        self._set_hover(False)

    def _on_del_enter(self, _e):
        th = self.app.theme
        try:
            self.del_btn.configure(bg=th["danger_hover_bg"],
                                   fg=th["danger_fg"])
        except tk.TclError:
            pass

    def _on_del_leave(self, _e):
        th = self.app.theme
        bg = th["card_hover_bg"] if self._hovered else th["card_bg"]
        try:
            self.del_btn.configure(bg=bg, fg=th["fg_secondary"])
        except tk.TclError:
            pass

    def flash_launch(self):
        """双击启动成功的视觉确认：描边闪两下 accent 色。"""
        th = self.app.theme
        seq = [th["accent"], th["border"], th["accent"], th["border"]]

        def step(i=0):
            if i >= len(seq):
                self._flash_job = None
                # 收尾按当前 hover 状态恢复
                self._set_hover(self._hovered)
                return
            try:
                self.configure(highlightbackground=seq[i],
                               highlightcolor=seq[i])
            except tk.TclError:
                return
            self._flash_job = self.after(110, lambda: step(i + 1))

        if self._flash_job is None:
            step()

    # ---- 数据转发（重构 P4：业务字段的唯一真源是 self.item） ----
    @property
    def path(self):
        return self.item.path

    @property
    def custom_title(self):
        return self.item.title

    @custom_title.setter
    def custom_title(self, v):
        self.item.title = v or ""

    @property
    def custom_icon(self):
        return self.item.icon

    @custom_icon.setter
    def custom_icon(self, v):
        self.item.icon = v or ""

    @property
    def launch_count(self):
        return self.item.launch_count

    @launch_count.setter
    def launch_count(self, v):
        self.item.launch_count = max(0, int(v or 0))

    @property
    def last_launch_ts(self):
        return self.item.last_launch_ts

    @last_launch_ts.setter
    def last_launch_ts(self, v):
        self.item.last_launch_ts = max(0.0, float(v or 0.0))

    def _sync_desc(self):
        """描述输入框内容同步进数据模型并请求保存。"""
        self.item.description = self.desc_var.get()
        self.app.mark_dirty("desc")

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
        if pil is None and self.app.has_win32:
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
            state="disabled" if (self.custom_icon or not self.app.has_win32)
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
        self.app.mark_dirty()

    def _menu_change_icon(self):
        p = filedialog.askopenfilename(
            title="选择图标图像",
            filetypes=[("图像文件", "*.ico;*.png;*.jpg;*.jpeg;*.bmp;*.gif"),
                       ("所有文件", "*.*")],
            parent=self.app)
        if not p:
            return
        if self.set_custom_icon(p):
            self.app.mark_dirty()

    def _menu_refresh_icon(self):
        """删除该卡片的图标缓存条目并重新入队异步提取。
        解决"目标应用升级后卡片仍显示旧图标"（缓存 key 的 mtime 盲区）。"""
        if self.custom_icon or not self.app.has_win32:
            return
        self.app.icon_cache.remove(self.path)
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
        self.app.mark_dirty()

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

