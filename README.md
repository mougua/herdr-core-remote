# Herdr Core Remote

通过浏览器操作 Windows 上的 `herdr-core`。项目与旧版 Herdr Remote 独立。
仅使用 Python 标准库，无须安装第三方 Python 包。

## 环境准备

- Windows 11 和 Python 3.10 或更高版本。
- 已安装 `hc`，并在同一 Windows 用户下运行 Herdr App。
- 外网访问需要 `cloudflared` 和可用的网络出口。

## 启动和停止

在 PowerShell 中执行：

```powershell
cd D:\mylab\my-herdr\herdr-core-remote
.\service.ps1 start
.\service.ps1 status
.\service.ps1 restart
.\service.ps1 stop
```

启动脚本退出后，后台进程继续运行。关闭 PowerShell 窗口也不会停止服务。
这是当前用户的后台进程，支持窗口关闭；不保证注销、重启或睡眠后可用。
停止服务只停止网页和它启动的隧道，保留 Herdr core 和现有终端。

如果系统拦截脚本，可单次执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\service.ps1 start
```

## 打开网页

```powershell
.\service.ps1 url
```

该命令显示带令牌的私有链接。在浏览器中打开它。
令牌放在 URL 片段中，网页读取后会清除地址栏中的片段。
网页仅在当前标签页的会话存储中保留令牌。

页面支持终端列表、当前屏幕、消息发送和常用按键。
当前屏幕每 1.8 秒刷新，导航每 5 秒同步。
保留 core 原始状态，不猜测 Agent 状态。
当前版本显示屏幕快照，不提供完整终端仿真和历史滚动。
发送失败或超时后，请先查看终端，再决定是否重发。
权限弹窗请用方向键和 Enter 操作；消息接口不添加 `--force`。

## 在家访问

首次运行会生成 `config.json`。默认仅监听本机 `127.0.0.1:8375`。
修改配置后执行 `restart`。

复用原来的命名隧道时，将配置中的字段改为：

```json
{
  "port": 8375,
  "hc": "hc",
  "tunnel": "named",
  "tunnel_name": "herdr",
  "tunnel_config": "~/.cloudflared/config-herdr.yml",
  "public_url": "https://你的隧道域名"
}
```

确认隧道配置的 `service` 指向 `http://localhost:8375`。
旧 Relay 需要先停止，避免端口冲突。
本项目不会停止其他项目的进程，也不会修改原隧道配置。
启动后，运行 `url` 获取外网链接，在家里的浏览器打开。
`status` 表示本机进程存活，公网连通性仍需实际访问验证。

原域名启用了 Cloudflare Access。浏览器会先显示登录页。
完成登录后，再打开 `url` 输出的私有链接。
Access 认证和本项目的连接令牌都需要保留。

临时测试可将 `tunnel` 改为 `temp`。
等待隧道分配地址后，用 `status` 和 `url` 查看。
临时域名会变化；长期使用建议复用命名隧道。

## 日志和验证

`.runtime/service.log` 记录网页服务运行情况。
`.runtime/launcher.log` 记录后台启动错误。
`.runtime/tunnel.log` 记录隧道连接情况。
`.runtime/token` 保存连接令牌。
Windows 启动时会限制该目录的访问权限。
请妥善保存私有链接；持有令牌的人可以操作这些终端。

```powershell
.\service.ps1 test
```

单元测试使用模拟 core，不向已有 Agent 发送内容。

服务启动后，可执行 `python tests\smoke.py` 进行真实收发验证。
脚本会新建专用测试终端，并在结束时清理该终端。

## 接口依据

- [herdr-core 官方项目](https://github.com/herdrdev/herdr-core)
- 本机 `hc --skill`、`hc send --help`、`hc read --help` 和 `hc keys --help`。

## 导航和切换

- **Spaces**：读取 Herdr App 的真实工作区、标签页和分屏终端。
- **Agents**：汇总运行中的终端。需要处理的状态排在前面。
- 搜索支持 Agent、路径、名称、终端地址和中文状态。
- 切换工作区时，恢复上次选中的终端。
- 每个终端分别保留草稿和滚动位置，保留至当前页面关闭。
- `Alt + ↑ / ↓` 切换终端，`Ctrl / ⌘ + Enter` 发送消息。
- 手机使用侧栏抽屉。所有设备的屏幕均自动折行，不显示横向滚动条。

网页导航有独立的选择状态，不改变公司桌面的焦点。
Herdr App 窗口不可用时，Agents 仍可操作 core 中的终端。
侧栏支持新建工作区。关闭和重命名暂未提供。

切换先显示内存中的屏幕，再立即读取最新内容。
后台用两个并发请求，预取最多 8 个其他终端。
屏幕缓存最多保留 40 个终端；退出登录时清除。
页面隐藏后暂停周期刷新。后台预取失败不干扰当前终端。

## 浏览器回归验证

已安装 Playwright 和 Chrome 时，可执行：

```powershell
python tests\ui-smoke.py
```

测试模拟所有 API，不会向真实终端发送任务。
覆盖工作区、Agent 排序、草稿、搜索、快速切换和移动布局。
测试还模拟 600 毫秒读取延迟，检查缓存是否立即显示。
截图保存在 `.runtime/ui-desktop.png` 和 `.runtime/ui-mobile.png`。

## 字体和颜色

终端使用项目内置的 Hack Nerd Font，补齐 Powerline 和 Nerd Font 图标。
字体沿用上游项目的许可，见 `web/HackNerdFont-LICENSE.txt`。
Emoji 优先使用设备的系统彩色字体，不加载第三方字体服务。
具体图形取决于操作系统，部分组合 Emoji 可能显示不同。

`hc read` 只返回纯文本，当前页面无法恢复原始前景色和背景色。
Powerline 的字形可以显示，彩色背景色块仍受这个限制。
已在源终端中替换成方框的字符，也无法通过网页字体还原。
当前模式侧重轻量屏幕快照，尚未接入原始字节流终端渲染器。

## 新建 Space

点击侧栏的“＋ 新建 Space”，填写名称和公司电脑上的现有绝对目录。
创建后会在公司 Herdr App 中同步出现，并自动选中新工作区。
Herdr 默认打开普通 PowerShell 终端，不会自动启动 Agent。
可在下方输入 `codex`、`claude` 等命令，再继续使用。
普通 Shell 单独列出，不计入 Agents 数量。

完全没有终端的工作区会显示空状态，并禁用发送和按键。
刷新导航时会保留该工作区的选择状态。

`python tests\space-smoke.py` 验证真实创建流程和空状态。
测试会短暂显示专用工作区，完成后仅清理该测试工作区。

## 在 Space 中新建终端

选中 Space 后，点击该工作区下的“＋ 新建终端”。
新终端作为该 Space 的新标签页打开，使用工作区目录。
默认启动普通 Shell，不启动 Agent。网页会自动切换到新终端。
空 Space 同样提供新建入口。创建期间会禁用按钮，避免重复点击。

## 屏幕排版和连接提示

实时屏幕保留缩进，并按可用宽度自动折行。
长路径、URL 和连续字符也会换行，无须横向滚动。

Space 使用工作区标题栏，终端以缩进层级显示。
标题显示名称；同名终端用“终端 1、终端 2”区分。
内部终端编号仅在悬停说明中保留，供排查问题使用。

屏幕和导航的连接错误分别跟踪，恢复后自动清除对应提示。
发送失败等操作错误会保留，避免被后台刷新覆盖。
`python tests/layout-recovery.py` 验证自动恢复和三种屏幕宽度。
