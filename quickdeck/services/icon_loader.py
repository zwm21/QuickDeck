# -*- coding: utf-8 -*-
"""图标异步加载器。

改进（相对旧版 App 内嵌 worker）：
- 队列元素为 (task_id, path, size) 纯数据，不再持有 widget 引用
  （旧实现队列持卡片对象，已删除的卡片无法被回收）。
- stop() 投递 None 哨兵并 join，退出路径明确（旧 worker 永不退出）。
- pending() 暴露积压量，主线程可据此自适应轮询节奏。
"""
import sys
import queue
import threading


class IconLoader:
    def __init__(self, extract_fn, cache, prepare=None):
        """extract_fn(path, size) -> PIL.Image | None；
        cache: IconCache；prepare: worker 线程启动时调用（如 COM 初始化）。"""
        self._extract = extract_fn
        self._cache = cache
        self._prepare = prepare
        self._tasks = queue.Queue()
        self._results = queue.Queue()
        self._worker = threading.Thread(
            target=self._worker_main, daemon=True,
            name="QuickDeckIconWorker")
        self._worker.start()

    def submit(self, task_id, path, size):
        self._tasks.put((task_id, path, size))

    def drain(self):
        """取出全部已完成结果，返回 [(task_id, pil), ...]。主线程调用。"""
        out = []
        try:
            while True:
                out.append(self._results.get_nowait())
        except queue.Empty:
            pass
        return out

    def pending(self):
        return self._tasks.qsize()

    def stop(self, timeout=1.0):
        self._tasks.put(None)
        self._worker.join(timeout)

    def _worker_main(self):
        if self._prepare is not None:
            try:
                self._prepare()
            except Exception as e:
                print(f"[QuickDeck] icon worker prepare error: {e}",
                      file=sys.stderr)
        while True:
            task = self._tasks.get()
            if task is None:
                break
            task_id, path, size = task
            try:
                pil = self._cache.get(path, size)
                if pil is None:
                    pil = self._extract(path, size)
                    if pil is not None:
                        self._cache.put(path, pil, size)
                if pil is not None:
                    self._results.put((task_id, pil))
            except Exception as e:
                print(f"[QuickDeck] icon worker error: {e}",
                      file=sys.stderr)
