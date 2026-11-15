# CIMC Studio

面向 CIMC 工业嵌入式训练的本地固件仿真工作台。第一版按用户最新选择使用 **GD32F470 V1.0**；Windows EXE 与 HTML 网页共用界面和本地执行内核。

当前版本：**0.1.0，第一版开发预览**。确切支持范围、硬件证据及验证结果分别见 [硬件证据](docs/hardware-evidence.md) 和 [验收记录](docs/validation-v0.1.md)。不能将开发预览视为全部 Keil 工程或官方评测的兼容证明。

![V1.0 工作台](docs/ui-preview.png)

## 使用 Windows 版

1. 从仓库 Releases 下载 Windows 压缩包并完整解压。
2. 双击 `CIMC-Studio.exe`。程序会在本机启动仿真服务，关闭窗口时停止自己启动的服务。
3. 先载入“示例固件”验证环境，再导入自己的 HEX 或 BIN。
4. 按实际排针添加虚拟跳线，运行固件，操作 KEY，观察 LED/OLED，并使用内置串口面板收发数据。

EXE 使用系统 Edge WebView2 Runtime；若没有该运行时，会打开相同的浏览器版本。不要只复制主 EXE，必须保留内核、web 与 firmware 目录。

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
- 打包：`powershell -File scripts/build.ps1`。

Windows 打包还需 Visual Studio C++ 构建工具。脚本会按 PyInstaller 官方说明为 Unicorn 重新编译本项目的 bootloader（`--no-cfg`），不修改系统安全设置。发行包另有真实运行检查：`.venv/Scripts/python.exe tests/package_smoke.py artifacts/CIMC-Studio-0.1.0-html-local`。

示例固件源代码及实际构建信息保存在 `firmware/`。示例输出也必须经过 ARM 机器码执行路径，界面不生成预设成功回复。

## 固定电路约束

原板固定网络与用户新增跳线分开保存。用户只可增删自己的跳线；不能拆改底板线路或重映射 MCU。网络映射必须有原图、板卡丝印或驱动证据，未知信息保持明确标记。所有硬件资料的证据范围见 `docs/hardware-evidence.md`。

V1 的 RS232 和 RS485 通过 H6 选择，共用 USART1。切换终端页签不改变接线。CH340 还需连接 H7 跳帽。详细步骤见 [使用说明](docs/quick-start.md)。当前界面为原理图接线视图，未冒用其他版本的实物图。

已验证范围：Keil HEX/BIN、GPIO、LED/KEY、软件 I²C OLED、轮询串口、基础 SysTick。UART 中断、DMA、硬件 I²C、定时器、ADC、SD、SPI Flash 和 RTOS 尚未通过兼容性验收；不是逐周期或电气仿真。

## 版本迭代

- `main`：通过已有检查的版本。
- `feature/...`：后续功能分支，经验证后合并。
- `v0.x.y`：对应 Releases 的版本标签。
- [CHANGELOG](CHANGELOG.md)：记录新增、修复及已知限制。
- [实施设计](docs/implementation-v0.1.md)：本次开发依据。
- GitHub Actions 在推送与 PR 时执行测试并构建 Windows 宿主。

不提交虚拟环境、密钥、生成日志或无关个人资料。大体积发行文件放在 Releases，不塞进 Git 历史。
