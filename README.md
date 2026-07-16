# QuickDeck

Windows 桌面快捷方式管理器。以卡片形式管理 `.lnk` / `.exe` / `.url` 快捷方式，支持文件夹分组、拖拽排序、拖放添加与全局字体调节。基于 Python 标准库 tkinter 开发，单文件源码（`main.py`），可用 PyInstaller 打包为独立 exe。

## 功能

### 卡片管理
- 添加快捷方式：单选、多选文件对话框（支持 `.lnk` / `.exe` / `.url`），或直接从资源管理器**拖放文件到窗口**（需要 `tkinterdnd2`，缺失时该功能自动禁用，其余功能不受影响）
- 新添加的卡片落在最后一个文件夹的末尾；重复路径自动去重（按规范化绝对路径判断）
- 双击卡片启动对应程序 / 网页快捷方式；成功启动会记录启动次数与最近启动时间（供"按使用排序"视图使用）
- 卡片显示自动提取的程序图标与文件名标题，附带一行可编辑的描述
- 右键菜单：重命名标题（留空恢复默认）、替换图标（ico/png/jpg/bmp/gif）、刷新图标（删除缓存条目重新提取，解决目标程序升级后图标陈旧）、编辑描述、移动到指定文件夹、打开文件所在位置、复制路径、删除卡片

### 视图切换
底部"视图"下拉框三选项：
- **卡片视图**（默认）：文件夹分组的 `.lnk` / `.exe` 卡片，可编辑/拖拽
- **按使用排序**：文件夹区与网页区的全部卡片按启动次数降序、同次数按最近启动时间降序平铺显示。临时只读视图：不改动存储顺序，禁止拖拽
- **网页快捷方式**：`.url` 卡片的**独立存储区**——添加的 `.url` 不进文件夹，单独存放在该视图中，可拖拽排序、编辑、删除，顺序独立持久化（`config.json` 的 `web_shortcuts` 字段）

添加入口（文件对话框 / 拖放）会按扩展名自动路由：`.url` 进网页区，其余进最后一个文件夹。旧配置中已在文件夹里的 `.url` 启动时自动迁移到网页区。视图选择不持久化，重启后恢复卡片视图

### 单实例
通过命名互斥体（`CreateMutex`）保证同时只有一个 QuickDeck 在运行；重复启动时自动激活已有窗口（还原最小化并前置）后退出，避免双开实例互相覆盖配置

### 文件夹
- 卡片按文件夹分组；文件夹可新建、重命名（直接编辑名字）、删除（删除前弹确认框，其中的卡片会移动到最后一个剩余文件夹的末尾，至少保留一个文件夹）
- 拖拽文件夹头部（☰）调整文件夹顺序
- 拖拽卡片在文件夹内排序，或跨文件夹移动
- 文件夹上锁（🔓/🔒 按钮）：锁定后文件夹名不可编辑、其中卡片不可编辑/拖动/删除，仅保留双击启动；文件夹之间仍可拖动排序；解锁后恢复
- 文件夹折叠（▾/▸ 按钮）：收起后隐藏整个卡片区、仅保留文件夹标题栏；与上锁相互独立，可同时或分别生效；折叠状态持久化

### 布局与外观
- 卡片宽度可调（200–1200px，底部控件支持长按 ▲/▼ 连续调节），窗口足够宽时自动多列排布
- 全局字体家族与字号（8–36）实时调节
- **深色模式**：底部"主题"下拉框三选项——浅色 / 深色 / 跟随系统（默认）。跟随系统模式下每 5 秒检测注册表 `AppsUseLightTheme`，系统切换即实时跟随；手动指定浅色/深色后不再受系统影响。切换时整套配色实时重刷，标题栏同步（DWM）
- 内置汉仪文黑字体（`HYWenHei-65W.ttf`），通过 `AddFontResourceExW` 以进程私有方式加载，无需系统安装
- 高 DPI 感知（`SetProcessDpiAwareness`）
- 工具栏"打开程序目录"按钮：一键打开 QuickDeck 本体所在目录

### 图标提取
针对 `.lnk` 与 `.exe` 采用多层兜底链提取图标：解析快捷方式目标（`WScript.Shell`）→ `ExtractIconEx` → `PrivateExtractIconsW` → `IShellItemImageFactory`（COM，经 ctypes vtable 调用）→ `SHGetFileInfoW` → 占位图标。像素转换使用 `CreateDIBSection`（显式 32 位 BGRA），并对无 alpha 通道的老式图标做 alpha 重建。

`.url` 网页快捷方式：解析 INI 的 `IconFile=` / `IconIndex=` 字段（编码按 BOM → UTF-8 → 本机 ANSI 依次尝试）——指向图像文件（favicon 缓存的 .ico/.png 等）直接加载，指向 exe/dll 走 `ExtractIconEx`，兜底对 `.url` 本身走 shell 提取（通常得到默认浏览器图标）。

**异步加载与缓存**：图标提取在后台 worker 线程执行，启动时卡片先显示占位图标再逐个回填，避免大量卡片阻塞 UI；提取结果以 `(路径, mtime)` 为键做内存 + 磁盘双层缓存（`icon_cache/` 目录存 PNG），重启后直接命中磁盘缓存、不重复提取。

### 状态持久化
- 窗口尺寸/位置、字体、卡片宽度、文件夹结构（含锁定状态）、卡片顺序/描述/自定义标题/自定义图标/使用统计均保存到 `config.json`
- **原子写入**：先写 `.tmp` 并 fsync，再 `os.replace` 原子替换；旧版本轮转为 `config.json.bak`
- **损坏恢复**：主文件解析失败时隔离为 `config.json.corrupt` 并尝试从 `.bak` 恢复，两者都不可用时弹窗让用户选择"重置继续"或"退出检查"
- **双路径**：优先使用 exe 同目录的 `config.json`（Portable 语义）；目录不可写（如安装在 `Program Files`）时自动降级到 `%APPDATA%\QuickDeck\config.json`
- 配置加载后逐字段做类型/范围校验；记忆的窗口坐标若已不在当前屏幕可见范围（如显示器被拔掉），自动重置到主屏居中

## 运行环境

- Windows（大量使用 Win32 API：pywin32、ctypes 调用 shell32/gdi32/user32）
- Python 3.x（开发环境为 3.10）
- 依赖：

| 包 | 用途 | 必需性 |
|---|---|---|
| tkinter | GUI（标准库自带） | 必需 |
| pywin32 | 解析 .lnk、提取图标 | 缺失时可启动，但图标提取与添加功能禁用 |
| Pillow | 图标位图处理与显示 | 同上 |
| tkinterdnd2 | 文件拖放进窗口 | 可选，缺失时仅禁用拖放添加 |

```bash
pip install pywin32 Pillow tkinterdnd2
```

## 运行

```bash
python main.py
```

## 打包为 exe

```bash
build.bat
```

脚本会检查并按需安装 PyInstaller 及各依赖，然后以 `--onefile --windowed` 打包，内嵌字体文件并收集 tkinterdnd2 的 tkdnd 扩展，产物为 `dist\QuickDeck.exe`，构建结束后自动清理中间 `build/` 目录。

## 配置文件

`config.json`（UTF-8，程序自动维护，一般无需手改）：

```json
{
  "window":  { "width": 900, "height": 650, "x": 200, "y": 100 },
  "font":    { "family": "HYWenHei-65W", "size": 12 },
  "card_width": 500,
  "theme_mode": "system",
  "folders": [
    { "id": "default", "name": "默认", "order": 0,
      "locked": false, "collapsed": false }
  ],
  "shortcuts": [
    {
      "path": "C:\\path\\to\\app.lnk",
      "description": "一行描述",
      "folder": "default",
      "order": 0,
      "title": "",
      "icon": "",
      "launch_count": 0,
      "last_launch_ts": 0.0
    }
  ],
  "web_shortcuts": [
    {
      "path": "C:\\path\\to\\site.url",
      "description": "",
      "order": 0,
      "title": "",
      "icon": "",
      "launch_count": 0,
      "last_launch_ts": 0.0
    }
  ]
}
```

- `title` / `icon` 为空表示使用文件名默认标题 / 自动提取的图标
- `launch_count` / `last_launch_ts` 为双击成功启动时累计的使用统计，"按使用排序"视图的排序依据
- `icon` 记录的是自定义图标的图像文件路径；该文件被移动或删除后会自动回落到自动提取
- 伴生文件：`config.json.bak`（上次成功保存的备份）、`config.json.corrupt`（被隔离的损坏文件，可手动检查后删除）、`icon_cache/`（图标磁盘缓存，删除后下次启动自动重建）

## 项目结构

```
QuickDeck/
├── main.py            # 全部源码（约 2500 行）
├── build.bat          # PyInstaller 打包脚本
├── HYWenHei-65W.ttf   # 内置字体
├── config.json        # 运行时生成的配置
├── todo.md            # 开发过程的阶段性任务清单
└── dist/QuickDeck.exe # 打包产物
```

## 已知限制

- 仅支持 Windows；图标提取、快捷方式解析、字体加载均依赖 Win32 API
- 拖放添加只接受文件，拖入目录会被跳过
- 卡片以路径去重，同一目标的两个不同 `.lnk` 会被视为两张不同卡片
- 自定义图标以文件路径引用而非内嵌存储，源图像文件删除后自定义失效
- "按使用排序"视图在启动某卡片后不会立即重排（避免卡片在鼠标下移位），排序在下次进入该视图时生效
- 使用统计只统计在 QuickDeck 内双击启动的次数，不感知程序在系统其他入口的启动
