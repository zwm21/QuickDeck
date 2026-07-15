# QuickDeck

Windows 桌面快捷方式管理器。以卡片形式管理 `.lnk` / `.exe` 快捷方式，支持文件夹分组、拖拽排序、拖放添加与全局字体调节。基于 Python 标准库 tkinter 开发，单文件源码（`main.py`），可用 PyInstaller 打包为独立 exe。

## 功能

### 卡片管理
- 添加快捷方式：单选、多选文件对话框，或直接从资源管理器**拖放文件到窗口**（需要 `tkinterdnd2`，缺失时该功能自动禁用，其余功能不受影响）
- 新添加的卡片落在最后一个文件夹的末尾；重复路径自动去重（按规范化绝对路径判断）
- 双击卡片启动对应程序
- 卡片显示自动提取的程序图标与文件名标题，附带一行可编辑的描述
- 右键菜单：重命名标题（留空恢复默认）、替换图标（ico/png/jpg/bmp/gif）、编辑描述、移动到指定文件夹、打开文件所在位置、复制路径、删除卡片

### 文件夹
- 卡片按文件夹分组；文件夹可新建、重命名（直接编辑名字）、删除（删除前弹确认框，其中的卡片会移动到最后一个剩余文件夹的末尾，至少保留一个文件夹）
- 拖拽文件夹头部（☰）调整文件夹顺序
- 拖拽卡片在文件夹内排序，或跨文件夹移动
- 文件夹上锁（🔓/🔒 按钮）：锁定后文件夹名不可编辑、其中卡片不可编辑/拖动/删除，仅保留双击启动；文件夹之间仍可拖动排序；解锁后恢复

### 布局与外观
- 卡片宽度可调（200–1200px，底部控件支持长按 ▲/▼ 连续调节），窗口足够宽时自动多列排布
- 全局字体家族与字号（8–36）实时调节
- 内置汉仪文黑字体（`HYWenHei-65W.ttf`），通过 `AddFontResourceExW` 以进程私有方式加载，无需系统安装
- 高 DPI 感知（`SetProcessDpiAwareness`）

### 图标提取
针对 `.lnk` 与 `.exe` 采用多层兜底链提取图标：解析快捷方式目标（`WScript.Shell`）→ `ExtractIconEx` → `PrivateExtractIconsW` → `IShellItemImageFactory`（COM，经 ctypes vtable 调用）→ `SHGetFileInfoW` → 占位图标。像素转换使用 `CreateDIBSection`（显式 32 位 BGRA），并对无 alpha 通道的老式图标做 alpha 重建。

### 状态持久化
- 窗口尺寸/位置、字体、卡片宽度、文件夹结构（含锁定状态）、卡片顺序/描述/自定义标题/自定义图标均保存到 `config.json`
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
  "folders": [
    { "id": "default", "name": "默认", "order": 0, "locked": false }
  ],
  "shortcuts": [
    {
      "path": "C:\\path\\to\\app.lnk",
      "description": "一行描述",
      "folder": "default",
      "order": 0,
      "title": "",
      "icon": ""
    }
  ]
}
```

- `title` / `icon` 为空表示使用文件名默认标题 / 自动提取的图标
- `icon` 记录的是自定义图标的图像文件路径；该文件被移动或删除后会自动回落到自动提取
- 伴生文件：`config.json.bak`（上次成功保存的备份）、`config.json.corrupt`（被隔离的损坏文件，可手动检查后删除）

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
