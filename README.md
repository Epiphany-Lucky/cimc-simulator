# CIMC Studio

面向 CIMC 工业嵌入式训练的本地固件仿真工作台。第一版按用户最新选择使用 **GD32F470 V1.0**；Windows 安装版、Ubuntu/Debian 安装版与 HTML 网页共用界面和本地执行内核。

当前版本：**0.3.0，开发预览**。确切支持范围、硬件证据及验证结果分别见 [硬件证据](docs/hardware-evidence.md) 和 [验收记录](docs/validation-v0.3.md)。不能将开发预览视为全部 Keil 工程或官方评测的兼容证明。

![V1.0 工作台](docs/ui-preview.png)

## 使用 Windows 版

1. 从 Releases 下载 `CIMC-Studio-0.3.0-Setup-x64.exe`，运行安装向导（当前用户安装）。
2. 从开始菜单或可选桌面快捷方式启动 CIMC Studio；关闭窗口时停止自己启动的仿真服务。仍可使用完整解压的 Windows 便携 ZIP。
3. 先载入“示例固件”验证环境，再导入自己的 HEX 或 BIN。
4. 按实际排针添加虚拟跳线，运行固件，操作 KEY，观察 LED/OLED，并使用内置串口面板收发数据。

EXE 使用系统 Edge WebView2 Runtime；若没有该运行时，会打开相同的浏览器版本。不要只复制主 EXE，必须保留内核、web 与 firmware 目录。

## 使用 Ubuntu / Debian 版

下载 `cimc-studio_0.3.0_amd64.deb`，在下载目录运行：

```bash
sudo apt install ./cimc-studio_0.3.0_amd64.deb
```

安装后从应用菜单打开 **CIMC Studio**，同一工作台显示在系统默认浏览器中。随包已带 Python/Unicorn，不需要安装开发环境。目标为 Ubuntu 22.04+ / Debian 12+ 的 amd64 图形桌面；需有可用的图形浏览器。提供同版本 Linux tar.gz 便携目录。

重复启动复用本次工作台；点右上角“退出应用”立即结束会话，关闭全部页面后约180秒无客户端活动也会退出。卸载使用 `sudo apt remove cimc-studio`。详细安装、升级、卸载和数据规则见 [安装说明](docs/install.md)。

## 使用 HTML 网页版

下载 `html-local.zip`，完整解压后双击 `Open-Web.cmd`，浏览器会打开本地工作台。HTML 专用包已含本地内核，不需要安装 Python、.NET SDK 或 Keil。保持启动窗口开启。Windows 完整包也可用 `Open-Web.cmd` 或 `CIMC-Studio.exe --web` 打开浏览器版。

HTML 源码位于 `web/index.html`，不依赖 CDN。**浏览器与桌面版运行固件都需要随包提供的本地内核**；直接双击 HTML 只会打开界面和内核连接提示，不会在没有引擎时伪装固件运行。第一版不包含浏览器 WebAssembly CPU 内核，也不需要真实 COM、CH340 驱动或开发板。

## 开发环境

- Windows 10/11 x64，.NET SDK 10，Python 3.13。
- 开发界面使用 HTML/CSS/JavaScript；桌面宿主为 WPF＋WebView2；CPU 内核为 Unicorn。
- 源码安装：`powershell -File scripts/setup.ps1 -Testing`。
- 网页运行：`powershell -File scripts/start-web.ps1`，打开 `http://127.0.0.1:8765`。
- 桌面运行：`dotnet run --project desktop/CimcLab.csproj`。
- 测试：`.venv/Scripts/python.exe -m unittest discover -s tests -v`。
- Windows目录打包：`powershell -File scripts/build.ps1`；安装器：`powershell -File scripts/build-windows-installer.ps1`。
- Linux打包：在Ubuntu22.04的Python3.13构建环境中先安装 `engine/requirements.txt` 和 `requirements-dev.txt`，再执行 `bash scripts/build-linux.sh 0.3.0`，不可用Windows PyInstaller交叉生成Linux内核。

Windows 打包还需 Visual Studio C++ 构建工具。脚本会按 PyInstaller 官方说明为 Unicorn 重新编译本项目的 bootloader（`--no-cfg`），不修改系统安全设置。发行包另有真实运行检查：`.venv/Scripts/python.exe tests/package_smoke.py artifacts/CIMC-Studio-0.3.0-html-local`。

示例固件源代码及实际构建信息保存在 `firmware/`。示例输出也必须经过 ARM 机器码执行路径，界面不生成预设成功回复。

## 固定电路约束

原板固定网络与用户新增跳线分开保存。用户只可增删自己的跳线；不能拆改底板线路或重映射 MCU。网络映射必须有原图、板卡丝印或驱动证据，未知信息保持明确标记。所有硬件资料的证据范围见 `docs/hardware-evidence.md`。

V1 的 RS232 和 RS485 通过模式开关自动按原图切换 H6，共用 USART1。切换终端页签不改变接线。CH340 的 H7 由系统固定连接。OLED、ADC、SPI Flash 及串口等固定端点在界面与内核均禁止改接；LED/KEY 仍通过空闲 GPIO 手动添加跳线。详细步骤见 [使用说明](docs/quick-start.md)。当前界面为原理图接线视图，未冒用其他版本的实物图。

已验证范围：Keil HEX/BIN、GPIO、LED/KEY、软件 I²C OLED、轮询串口、基础 SysTick、PC0 软件触发单通道 ADC，以及 SPI1 上 GD25Q40E 的轮询读写/擦除子集。新增 ADC 旋钮可调 0–3.3 V，采样值只在固件实际转换后更新。Flash 为 512 KiB，MCU 复位保留内容，关闭服务后清空。UART/ADC/SPI 中断、DMA、硬件 I²C、定时器、SD 和 RTOS 尚未通过兼容性验收；不是逐周期或电气仿真。

Windows 窗口根据显示器工作区与 DPI 自动限制尺寸，网页适配短屏笔记本；核心操作、OLED 和 ADC 在小尺寸视口保持可见。

左侧“原理图”可查看 V1.0 原始四页图面，支持翻页、缩放及下载原 PDF。OLED 的 SCL/SDA/3V3/GND 四条原板固定线在接线视图中直接显示，并保持只读。

## 版本迭代

- `main`：通过已有检查的版本。
- `feature/...`：后续功能分支，经验证后合并。
- `v0.x.y`：对应 Releases 的版本标签。
- [CHANGELOG](CHANGELOG.md)：记录新增、修复及已知限制。
- [实施设计](docs/implementation-v0.3.md)：本次开发依据。
- GitHub Actions 在 Windows/Ubuntu 上执行测试；标签和手动打包工作流生成并验收两种系统安装包。

不提交虚拟环境、密钥、生成日志或无关个人资料。大体积发行文件放在 Releases，不塞进 Git 历史。
