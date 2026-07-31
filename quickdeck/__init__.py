# -*- coding: utf-8 -*-
"""QuickDeck 应用包。

单文件 main.py 正逐步重构为分层包结构：
- platform/  : 平台相关（Win32 图标提取、DPI、系统主题、字体）
- services/  : 图标缓存与异步加载
- config/    : 配置路径、校验、持久化
- model/     : 纯数据层（Shortcut/Folder/Workspace）
- ui/        : 主题、布局、控件、拖拽等视图层
"""
