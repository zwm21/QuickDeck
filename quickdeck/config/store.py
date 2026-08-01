# -*- coding: utf-8 -*-
"""配置持久化：路径选择（Portable 优先，APPDATA 兜底）、原子写、
损坏恢复。

相对旧版 main.py 的修正：
- bak/tmp/corrupt 伴生路径全部由 active_file **动态派生**（旧版
  CONFIG_BAK_FILE 等模块级常量在 save 降级切换路径后不跟随更新）。
- 不弹窗、不 sys.exit：load() 返回 (cfg | None, notices)，
  由 UI 层决定如何提示用户；cfg 为 None 表示主文件与备份都不可用，
  调用方选择 isolate_corrupt()+默认值继续，或退出。
- 可写探测不再在 import 期执行（旧版模块导入即在磁盘写探测文件）。
"""
import copy
import json
import os
import sys

from quickdeck.config.schema import (
    DEFAULT_CONFIG, merge_dict, sanitize_config, default_config,
)


def dir_writable(d):
    """探测目录是否真的可写（Program Files 下 os.access 不可靠）。"""
    try:
        probe = os.path.join(d, ".qd_write_test")
        with open(probe, "w") as f:
            f.write("x")
        os.remove(probe)
        return True
    except OSError:
        return False


class ConfigStore:
    """单个配置文件的加载/保存，含 Portable→APPDATA 自动降级。"""

    def __init__(self, portable_file, appdata_file):
        self.portable_file = portable_file
        self.appdata_file = appdata_file
        self.active_file = self._select_file()

    # ---- 路径 ----
    def _select_file(self):
        """Portable 优先：exe 目录存在 config.json 或目录可写 → 用之；
        否则降级到 APPDATA。"""
        if os.path.exists(self.portable_file):
            return self.portable_file
        if os.path.exists(self.appdata_file):
            # exe 目录没有配置但 APPDATA 有 → 曾经降级过，继续用 APPDATA
            return self.appdata_file
        if dir_writable(os.path.dirname(self.portable_file)):
            return self.portable_file
        try:
            os.makedirs(os.path.dirname(self.appdata_file), exist_ok=True)
        except OSError:
            pass
        return self.appdata_file

    @property
    def bak_file(self):
        return self.active_file + ".bak"

    @property
    def tmp_file(self):
        return self.active_file + ".tmp"

    @property
    def corrupt_file(self):
        return self.active_file + ".corrupt"

    # ---- 读 ----
    @staticmethod
    def _read_file(path):
        """读取并合并到默认结构；失败时抛异常。"""
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        with open(path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if not isinstance(loaded, dict):
            raise ValueError("config root is not a JSON object")
        return sanitize_config(merge_dict(cfg, loaded))

    def load(self):
        """返回 (cfg | None, notices)。

        notices 为事件列表，每项是 dict(kind=..., ...)：
        - restored_from_bak：主文件损坏，已隔离为 .corrupt 并用 .bak 恢复
        - unrecoverable：主文件与 .bak 都不可用（此时 cfg 为 None，
          调用方决定 isolate_corrupt()+default_config() 继续，或退出）
        """
        notices = []
        if not os.path.exists(self.active_file):
            # 主文件缺失但有 .bak，尝试恢复（静默，与旧行为一致）
            if os.path.exists(self.bak_file):
                try:
                    return self._read_file(self.bak_file), notices
                except Exception as e:
                    print(f"[QuickDeck] load bak fallback failed: {e}",
                          file=sys.stderr)
            return default_config(), notices

        try:
            return self._read_file(self.active_file), notices
        except Exception as primary_err:
            print(f"[QuickDeck] load_config primary error: {primary_err}",
                  file=sys.stderr)

            bak_err = None
            if os.path.exists(self.bak_file):
                try:
                    bak_cfg = self._read_file(self.bak_file)
                except Exception as e:
                    bak_err = e
                    print(f"[QuickDeck] load_config bak error: {e}",
                          file=sys.stderr)
                else:
                    # 有可用 .bak：隔离损坏主文件 → 使用 .bak
                    self.isolate_corrupt()
                    notices.append({"kind": "restored_from_bak",
                                    "primary_err": primary_err})
                    return bak_cfg, notices

            notices.append({"kind": "unrecoverable",
                            "primary_err": primary_err,
                            "bak_err": bak_err})
            return None, notices

    def isolate_corrupt(self):
        """把损坏的主文件挪到 .corrupt（避免下次 save 无声覆盖坏数据）。"""
        try:
            os.replace(self.active_file, self.corrupt_file)
        except OSError:
            pass

    # ---- 写 ----
    def _write_to(self, cfg, cfg_file):
        """原子写到 cfg_file（tmp + fsync + os.replace + bak 轮转）。
        失败时抛异常（由 save 决定是否降级重试）。"""
        bak_file = cfg_file + ".bak"
        tmp_file = cfg_file + ".tmp"
        d = os.path.dirname(cfg_file)
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
            try:
                f.flush()
                os.fsync(f.fileno())
            except (OSError, AttributeError):
                pass
        if os.path.exists(cfg_file):
            try:
                os.replace(cfg_file, bak_file)
            except OSError as e:
                print(f"[QuickDeck] backup rotate failed: {e}",
                      file=sys.stderr)
        os.replace(tmp_file, cfg_file)

    def save(self, cfg):
        """原子写回。写失败自动降级到 APPDATA 并切换 active_file
        （伴生路径动态派生，随之切换）。"""
        try:
            self._write_to(cfg, self.active_file)
            return True
        except Exception as e:
            print(f"[QuickDeck] save_config error at "
                  f"{self.active_file}: {e}", file=sys.stderr)
            try:
                if os.path.exists(self.tmp_file):
                    os.remove(self.tmp_file)
            except OSError:
                pass

        # 已经在 APPDATA 还失败：没有更低的降级层，放弃本次保存
        if os.path.normcase(self.active_file) == \
                os.path.normcase(self.appdata_file):
            return False

        try:
            self._write_to(cfg, self.appdata_file)
            self.active_file = self.appdata_file
            print(f"[QuickDeck] config fell back to {self.appdata_file}",
                  file=sys.stderr)
            return True
        except Exception as e:
            print(f"[QuickDeck] save_config appdata fallback error: {e}",
                  file=sys.stderr)
            return False
