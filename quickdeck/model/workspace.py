# -*- coding: utf-8 -*-
"""数据模型：Shortcut / Folder。

重构 P4 之前"widget 即模型"——path/custom_title/launch_count 等业务
字段直接挂在 tk widget 属性上。现在这些字段收敛到纯数据类：
- ShortcutCard 持有 Shortcut 实例（card.item），widget 属性退化为
  property 转发；
- FolderFrame 持有 Folder 实例（frame.meta），同理；
- save_state 的序列化逻辑收敛到 to_record()（与旧 config.json 字段
  严格同构，uid 为运行期标识不落盘）。

顺序（order）目前仍由 UI 列表（App.folders / folder.cards /
web_cards / dir_cards）承载，序列化时按列表下标写入——P7 拖拽重构
（松手才 commit）时顺序权威将进一步收敛到模型层。
"""
import uuid
from dataclasses import dataclass, field


def _new_uid():
    return uuid.uuid4().hex[:12]


@dataclass
class Shortcut:
    """一条快捷方式记录（文件夹区 / 网页区 / 目录区通用）。"""
    path: str
    description: str = ""
    title: str = ""      # 自定义标题（空 = 用文件名默认标题）
    icon: str = ""       # 自定义图标文件路径（空 = 自动提取）
    launch_count: int = 0
    last_launch_ts: float = 0.0
    uid: str = field(default_factory=_new_uid)  # 运行期标识，不落盘

    @classmethod
    def from_record(cls, rec):
        """从 config.json 的一条 shortcut 记录构建（记录已经过 sanitize）。"""
        return cls(
            path=rec.get("path", ""),
            description=rec.get("description", "") or "",
            title=rec.get("title", "") or "",
            icon=rec.get("icon", "") or "",
            launch_count=max(0, int(rec.get("launch_count", 0) or 0)),
            last_launch_ts=max(0.0, float(rec.get("last_launch_ts", 0.0)
                                          or 0.0)),
        )

    def to_record(self, order, folder_id=None):
        """序列化为 config.json 条目；folder_id 仅文件夹区卡片携带。
        字段名与键序保持与旧 save_state 一致。"""
        rec = {"path": self.path, "description": self.description}
        if folder_id is not None:
            rec["folder"] = folder_id
        rec.update({
            "order": order,
            "title": self.title or "",
            "icon": self.icon or "",
            "launch_count": int(self.launch_count),
            "last_launch_ts": float(self.last_launch_ts),
        })
        return rec


@dataclass
class Folder:
    """一个文件夹分组的元数据。"""
    id: str
    name: str
    locked: bool = False
    collapsed: bool = False

    def to_record(self, order):
        return {"id": self.id, "name": self.name, "order": order,
                "locked": bool(self.locked),
                "collapsed": bool(self.collapsed)}
