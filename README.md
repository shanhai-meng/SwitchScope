# SwitchScope — 单显示器下 Mac ↔ Windows 一键切屏

一台显示器接两台电脑：**按一下 F12，画面立刻切到另一台**。

两台机器都装同一个小工具、注册同一个快捷键，谁正在被你使用，谁就响应这次按键——
于是「切过去」和「切回来」用的是同一个键，不用再伸手去够显示器背面的信号源按钮。

![信号源数量示意](https://img.shields.io/badge/inputs-HDMI1%20%2F%20HDMI2%20%2F%20USB--C%20%2F%20DP-blue)

---

## 它解决什么问题

一台显示器、两台电脑（Mac + Windows）时，每次切换要做三件事：
伸手摸显示器边框 → 点几下 OSD 按钮 → 在菜单里选信号源。

SwitchScope 把这件事压缩成一次按键，语义等同于「按信号源键」，
而且**在 Mac 端和 Windows 端方向相反、体验一致**：

```
  在 Mac 上按 F12  →  显示器切到 Windows 的输入源
  在 Windows 上按 F12  →  显示器切回 Mac 的输入源
```

键鼠不需要在这台工具里处理（蓝牙/物理切换各自解决），它只管「画面切到哪台机器」。

---

## 下载即用（推荐）

到 [Releases](https://github.com/shanhai-meng/SwitchScope/releases) 下载对应平台的成品包，
**不需要安装 Python**：

| 平台 | 文件 | 安装方式 |
|---|---|---|
| macOS（Apple Silicon / Intel） | `SwitchScope-macOS.zip` | 解压后把 `SwitchScope.app` 拖进「应用程序」 |
| Windows 10 / 11 | `SwitchScope-Windows.exe` | 双击运行即可，托盘图标在右下角（可能在 `^` 折叠区里） |

> **macOS 首次打开**：应用未经苹果签名公证，系统会拦一下。
> 右键 App 选「打开」点一次即可；或在终端执行：
> `xattr -dr com.apple.quarantine /Applications/SwitchScope.app`

### 三步配起来

1. **授权辅助功能**（只有热键需要，点菜单切换不受影响）
   - macOS：`系统设置 → 隐私与安全性 → 辅助功能`，把 SwitchScope 勾上。
     菜单栏图标旁的「授权全局热键…」可以直接跳过去。
   - Windows：无需授权。
2. **接通显示器**
   菜单栏 / 托盘首次启动会自动扫描局域网找到显示器，并把地址写进配置文件。
   找不到就手动填：菜单 → 「打开配置文件」→ `hyperos_host`。
3. **填好两台机器各自的输入源编号**（只做一次，见下一节）

---

## 配置

配置文件位置：

| 平台 | 路径 |
|---|---|
| macOS | `~/Library/Application Support/SwitchScope/config.yaml` |
| Windows | `%APPDATA%\SwitchScope\config.yaml` |

菜单栏 / 托盘里点「打开配置文件」即可编辑。两台机器各一份，**只有 `self` 不同**：

```yaml
self: mac                    # Windows 那份改成 windows

display:
  hyperos_host: "192.168.88.128"   # 留空则每次自动扫描发现
  auto_discover: true
  ddc_display_index: 1

machines:
  mac:
    label: "Mac"
    hyperos: 30      # Mac 插在 USB-C
    ddc: 27          # 备用通道的 VCP 0x60 值
  windows:
    label: "Windows"
    hyperos: 23      # Windows 插在 HDMI1
    ddc: 17

channels: [hyperos, ddc]

hotkey: "<f12>"      # 默认 F12；也支持组合键 "<ctrl>+<alt>+s"
```

### 怎么知道两台机器各插在哪个输入源

澎湃 OS 的固件不提供「查询当前信号源」接口，所以第一次要人工确认一次，两种方式：

- **看一眼显示器菜单**：按显示器背面的摇杆/按键，OSD 里显示的当前信号源就是此刻 Mac 正在用的口。
  同理，切到 Windows 后看到的就是 Windows 的口。
- **逐个试**：命令行执行 `python main.py --try 30`，看画面是不是另一台机器了，
  换 23 / 24 / 29 再试。**切错没有副作用**——总有某个编号能切回来。

常见编号（不同型号可能不同，以 `--probe` 列出的为准）：

| 编号 | 输入源 |
|---|---|
| 23 | HDMI1 |
| 24 | HDMI2 |
| 29 | DP |
| 30 | USB-C |

**热键写法**：`<f12>` 是单键；组合键写成 `<ctrl>+<alt>+s`；
支持 `cmd/ctrl/alt/shift` 组合 + 字母或 `f1`~`f12`、方向键等。留空则不注册热键。

---

## 为什么不用现成的方案

| 方案 | 结论 |
|---|---|
| DDC/CI 工具（`m1ddc`、`MonitorControl`、`BetterDisplay`、`Lunar`） | ✗ **走不通**。REDMI / 小米显示器（含实测的 G Pro 27U）不支持 DDC/CI，`m1ddc get luminance` 直接报 `DDC communication failure`。这也是网上大多数教程对你没用的原因 |
| SimpleKVM / display-switch | 需要额外买 USB 切换器硬件，靠 USB 设备插拔触发 |
| MonitorBar（开源 Go 项目） | 思路相同，但功能堆得重（场景/分辨率/屏幕时间……），换型号要改 Go 源码 |
| EasyKVM 等商业软件 | 收费、闭源 |

SwitchScope 只做「切屏」这一件事，并把路走窄而稳：

**显示器开机后会在局域网开一个 HTTP 遥控接口（`6095` 端口）**，
给它一个信号源编号就能切源，与视频线怎么接无关，Mac 和 Windows 用起来完全一样。
万一碰到没有这个接口的显示器，自动降级到 DDC/CI。

### 两条控制通道

| 通道 | 适用 | 条件 |
|---|---|---|
| **澎湃 OS 局域网**（默认） | 小米/REDMI 带澎湃 OS 的显示器 | 显示器和电脑在同一个局域网 |
| **DDC/CI**（备用） | 大多数其他显示器 | macOS 走 IOKit 直写 I2C（必要时回退调用 `m1ddc`）；Windows 走系统 `dxva2` 的 `SetVCPFeature` |

启动时按顺序自检，谁真能用就用谁，用 `--probe` 可以看到每条通道的实测结果。

---

## 从源码运行

需要 Python 3.10+。

```bash
# macOS
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-mac.txt
.venv/bin/python main.py --discover   # 扫描并写入显示器地址
.venv/bin/python main.py              # 启动菜单栏 App

# Windows
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt -r requirements-win.txt
.venv\Scripts\python main.py
```

打包成品（依赖 `pyinstaller` + `pillow`）：

```bash
pip install pyinstaller pillow
python build_app.py          # macOS 出 dist/SwitchScope.app，Windows 出 dist/SwitchScope.exe
```

## 命令行

```bash
python main.py                    # 启动菜单栏 / 托盘
python main.py --probe            # 打印诊断：每条通道是否可用、输入源清单
python main.py --discover         # 扫描局域网找显示器并写回配置
python main.py --toggle           # 立即切到另一台
python main.py --to windows       # 立即切到指定机器
python main.py --try 23           # 试切某个输入源编号（确认插口用）
python main.py --autostart on     # 开机自启（Mac: LaunchAgent / Win: 启动目录）
```

## 开机自启

两种方式任选：

- **图形**：菜单栏 / 托盘菜单里直接勾选「开机自启」（推荐，成品 App 也能用）
- **命令行**：`python main.py --autostart on` / `off`

macOS 写的是 `~/Library/LaunchAgents/com.switchscope.app.plist`，
Windows 写的是「启动」目录里的 `.bat`。

## 目录结构

```
switchscope/
├── settings.py            配置模型（两台机器共用同一份格式）
├── controller.py          通道选择 + 切换编排 + 诊断输出
├── discover.py            局域网扫描（并发探测 6095 端口）
├── autostart.py           开机自启（支持成品 App 与源码两种形态）
├── channels/
│   ├── hyperos.py         澎湃 OS 局域网遥控：isalive / getsources / changesource2
│   ├── ddc_macos.py       macOS DDC/CI：ctypes 直写 IOKit I2C，回退调用 m1ddc
│   └── ddc_windows.py     Windows DDC/CI：dxva2 SetVCPFeature
└── ui/
    ├── hotkey.py          跨平台全局热键（pynput，支持单键与组合键）
    ├── mac_menu.py        macOS 菜单栏（rumps）
    └── win_tray.py        Windows 托盘（pystray）
```

## 常见问题

| 现象 | 原因和处理 |
|---|---|
| 按 F12 没反应 | 没授权「辅助功能」（macOS）；或 `hotkey` 被写成空；或该键被系统/其他软件占用（Mac 上试试 `fn+F12`） |
| 「局域网内没有找到澎湃 OS 显示器」 | 显示器没联网或不在同一网段、处于关机状态；手动填 `hyperos_host` |
| DDC/CI 显示不可用 | 正常现象：小米/REDMI 不支持 DDC/CI，主力是局域网通道；其他显示器记得在 OSD 菜单里打开 DDC/CI 开关 |
| Mac 走 HDMI 且 DDC/CI 不通 | Apple Silicon 的部分 HDMI 口不转发 DDC/CI，换 USB-C→DP 线即可 |
| 换显示器后不生效 | 新显示器没有局域网接口时，把 `channels` 改成 `[ddc, hyperos]`，并确认 DDC/CI 已开启 |
| 两台机器都切了、但画面没变 | 两台机器填的输入源编号填反了或填错了，用 `--try` 逐个确认 |

## 许可

MIT
