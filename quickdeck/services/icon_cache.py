# -*- coding: utf-8 -*-
"""图标缓存：内存 LRU + 磁盘 PNG。

- key = (规范化绝对路径, mtime_ns, size)；mtime 进 key 保证目标文件
  更新后缓存自动失效；size 进 key 为图标分档（32/40/48）做准备。
- 内存层：OrderedDict LRU，默认上限 512 张（旧实现无上限）。
- 磁盘层：cache_dir 下按 key 哈希存 PNG。默认尺寸沿用旧文件名格式
  （不含 size），保证升级后已有磁盘缓存继续命中、不整体重提取。
- gc()：磁盘缓存超限时按 mtime 淘汰（旧实现只增不减）。
"""
import os
import sys
import hashlib
import threading
from collections import OrderedDict

from PIL import Image

from quickdeck.constants import ICON_SIZE

_GC_MAX_FILES = 2000
_GC_MAX_BYTES = 100 * 1024 * 1024
_GC_TARGET_RATIO = 0.7


class IconCache:
    def __init__(self, cache_dir, mem_limit=512):
        self.cache_dir = cache_dir
        self.mem_limit = int(mem_limit)
        self._mem = OrderedDict()
        self._lock = threading.Lock()

    # ---- key / 路径 ----
    @staticmethod
    def _key(path, size):
        p = os.path.normcase(os.path.abspath(path))
        try:
            mtime = os.stat(p).st_mtime_ns
        except OSError:
            mtime = 0
        return p, mtime, size

    def _file(self, key):
        p, mtime, size = key
        if size == ICON_SIZE:
            # 与旧版磁盘缓存文件名兼容（旧 key 不含 size）
            raw = f"{p}|{mtime}"
        else:
            raw = f"{p}|{mtime}|{size}"
        name = hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()
        return os.path.join(self.cache_dir, name + ".png")

    # ---- 读写 ----
    def get(self, path, size=ICON_SIZE):
        """先查内存（LRU 触达置新），再查磁盘 PNG（命中回填内存）。"""
        key = self._key(path, size)
        with self._lock:
            pil = self._mem.get(key)
            if pil is not None:
                self._mem.move_to_end(key)
                return pil
        fp = self._file(key)
        try:
            if os.path.exists(fp):
                img = Image.open(fp)
                img.load()
                if img.mode != "RGBA":
                    img = img.convert("RGBA")
                self._remember(key, img)
                return img
        except Exception as e:
            print(f"[QuickDeck] icon cache read failed: {e}",
                  file=sys.stderr)
        return None

    def put(self, path, pil, size=ICON_SIZE):
        """写内存 + 磁盘。磁盘失败只打日志（缓存是加速手段，非功能依赖）。"""
        key = self._key(path, size)
        self._remember(key, pil)
        fp = self._file(key)
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            pil.save(fp, "PNG")
        except Exception as e:
            print(f"[QuickDeck] icon cache write failed: {e}",
                  file=sys.stderr)

    def remove(self, path, sizes=(32, 40, 48)):
        """删除该路径全部尺寸档的内存 + 磁盘条目（右键"刷新图标"用）。

        覆盖缓存盲区：key 含 mtime，但 .lnk 指向的目标 exe 升级换图标时
        .lnk 本身 mtime 不变、key 相同导致永远命中陈旧图标。"""
        for size in sizes:
            key = self._key(path, size)
            with self._lock:
                self._mem.pop(key, None)
            fp = self._file(key)
            try:
                if os.path.exists(fp):
                    os.remove(fp)
            except OSError as e:
                print(f"[QuickDeck] icon cache remove failed: {e}",
                      file=sys.stderr)

    def _remember(self, key, pil):
        with self._lock:
            self._mem[key] = pil
            self._mem.move_to_end(key)
            while len(self._mem) > self.mem_limit:
                self._mem.popitem(last=False)

    # ---- 磁盘 GC ----
    def start_gc(self):
        """后台线程执行磁盘 GC，不阻塞启动。"""
        threading.Thread(target=self.gc, daemon=True,
                         name="QuickDeckIconCacheGC").start()

    def gc(self, max_files=_GC_MAX_FILES, max_bytes=_GC_MAX_BYTES,
           target_ratio=_GC_TARGET_RATIO):
        """磁盘条目超过数量/体积上限时，按 mtime 从旧到新删至上限的
        target_ratio。返回删除的文件数。"""
        try:
            with os.scandir(self.cache_dir) as it:
                entries = []
                for e in it:
                    if e.is_file() and e.name.endswith(".png"):
                        st = e.stat()
                        entries.append((st.st_mtime, st.st_size, e.path))
        except OSError:
            return 0
        total_bytes = sum(s for _m, s, _p in entries)
        if len(entries) <= max_files and total_bytes <= max_bytes:
            return 0
        entries.sort()  # mtime 升序：先删最旧
        want_files = int(max_files * target_ratio)
        want_bytes = int(max_bytes * target_ratio)
        removed = 0
        for _mtime, fsize, fpath in entries:
            if len(entries) - removed <= want_files \
                    and total_bytes <= want_bytes:
                break
            try:
                os.remove(fpath)
                removed += 1
                total_bytes -= fsize
            except OSError:
                pass
        if removed:
            print(f"[QuickDeck] icon cache gc removed {removed} files",
                  file=sys.stderr)
        return removed
