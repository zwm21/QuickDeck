# -*- coding: utf-8 -*-
"""P2 服务层冒烟：IconCache（命中/LRU/GC/兼容旧文件名）+ IconLoader
（纯数据队列、drain、哨兵退出）。全部在临时目录进行，不碰真实缓存。"""
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS_DIR))

from PIL import Image  # noqa: E402

from quickdeck.constants import ICON_SIZE  # noqa: E402
from quickdeck.services.icon_cache import IconCache  # noqa: E402
from quickdeck.services.icon_loader import IconLoader  # noqa: E402

ok = True


def check(name, cond):
    global ok
    print(f"[{'OK ' if cond else 'FAIL'}] {name}")
    ok = ok and bool(cond)


def img(color):
    return Image.new("RGBA", (ICON_SIZE, ICON_SIZE), color)


with tempfile.TemporaryDirectory() as td:
    cache_dir = os.path.join(td, "icon_cache")
    cache = IconCache(cache_dir, mem_limit=3)

    # 建一个真实文件作为 path（key 含 mtime）
    p1 = os.path.join(td, "a.exe")
    open(p1, "wb").write(b"x")

    # 未命中
    check("miss 返回 None", cache.get(p1) is None)
    # put + 内存命中
    cache.put(p1, img((255, 0, 0, 255)))
    check("put 后内存命中", cache.get(p1) is not None)
    # 磁盘命中（清内存后仍可读）
    cache._mem.clear()
    got = cache.get(p1)
    check("磁盘命中并回填", got is not None and got.size == (32, 32))
    # 默认尺寸文件名兼容旧格式（不含 size）
    key = cache._key(p1, ICON_SIZE)
    import hashlib
    old_name = hashlib.sha1(
        f"{key[0]}|{key[1]}".encode("utf-8", "replace")).hexdigest() + ".png"
    check("默认尺寸沿用旧文件名", os.path.exists(
        os.path.join(cache_dir, old_name)))
    # remove
    cache.remove(p1)
    check("remove 后 miss", cache.get(p1) is None)

    # LRU 上限
    paths = []
    for i in range(5):
        p = os.path.join(td, f"f{i}.exe")
        open(p, "wb").write(b"x")
        cache.put(p, img((i, i, i, 255)))
        paths.append(p)
    check("LRU 内存上限=3", len(cache._mem) == 3)
    # 最旧的被逐出内存（但磁盘仍在）
    check("被逐出者磁盘仍命中", cache.get(paths[0]) is not None)

    # GC：把上限压到 2 个文件，应删到 target(0.7*2=1)
    n = cache.gc(max_files=2, max_bytes=10**9, target_ratio=0.5)
    left = len([f for f in os.listdir(cache_dir) if f.endswith(".png")])
    check(f"GC 删除 {n} 个后剩 {left} <= 2", left <= 2 and n > 0)

    # ---- IconLoader ----
    calls = []

    def fake_extract(path, size):
        calls.append(path)
        if "bad" in path:
            return None
        return img((9, 9, 9, 255))

    cache2 = IconCache(os.path.join(td, "c2"))
    loader = IconLoader(fake_extract, cache2)
    pgood = os.path.join(td, "good.exe")
    pbad = os.path.join(td, "bad.exe")
    open(pgood, "wb").write(b"x")
    open(pbad, "wb").write(b"x")
    loader.submit(1, pgood, ICON_SIZE)
    loader.submit(2, pbad, ICON_SIZE)

    import time
    results = []
    for _ in range(50):
        results += loader.drain()
        if len(results) >= 1 and len(calls) >= 2:
            break
        time.sleep(0.05)
    check("提取成功者有结果", any(tid == 1 for tid, _ in results))
    check("提取失败者无结果", not any(tid == 2 for tid, _ in results))
    check("提取函数被调用 2 次", len(calls) == 2)
    # 缓存生效：再提交同一路径不再调用 extract
    loader.submit(3, pgood, ICON_SIZE)
    for _ in range(50):
        r = loader.drain()
        if r:
            results += r
            break
        time.sleep(0.05)
    check("二次提交走缓存（extract 不增加）", len(calls) == 2)
    # 哨兵退出
    loader.stop(timeout=2.0)
    check("worker 已退出", not loader._worker.is_alive())

print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
