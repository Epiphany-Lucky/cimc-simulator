# V0.1 验收记录

日期：2026-11-15。目标：CIMC GD32F470VET6 **V1.0**。实际验证环境：Windows 11 x64、Python 3.13.13、Unicorn 2.1.4、.NET 10.0.8 / SDK 10.0.300、Keil Arm Compiler 6、Microsoft Edge。

## 已通过的检查

1. `python -m unittest discover -s tests -v`：**21 项全部通过**。
2. `tests/ui_smoke.py`：真实浏览器交互通过，未捕获 JavaScript 异常。
3. `dotnet publish`：Windows 自包含宿主构建成功。

内核测试实际运行交付的 Keil 机器码，覆盖 HEX/BIN 一致性、校验和/向量/容量、OLED 像素、KEY→LED、删除跳线、接线工程原子导入、NC 禁接、电平冲突、UART 未启用/断线、CH340/RS485/RS232/TTL 固件回复、基础 SysTick 异常进入与返回、UART 中断和未知外设明确停止。

浏览器测试覆盖示例运行、按键、OLED、串口 `ACK L`、点击真实排针新增导线、删除和保存/恢复接线、BIN 文件选择导入、单步/复位、减少动画、390 px 布局无横向溢出。截图为 `docs/ui-preview.png`。

## 发行包验证

首次 PyInstaller 打包在执行 ARM 时触发 `0xc0000409`，已定位为官方文档列出的 Unicorn 与 CFG bootloader 兼容问题。构建脚本新增 `setup-packager.ps1`，仅为本项目按官方 `--no-cfg` 选项重新编译 bootloader，不修改系统设置。

依据：[PyInstaller 官方说明](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#windows-executables-and-control-flow-guard-cfg)、[Unicorn 上游问题 #2281](https://github.com/unicorn-engine/unicorn/issues/2281)。

重新构建后已通过以下检查：

- `tests/package_smoke.py artifacts/CIMC-Studio-0.1.0-html-local`：独立 EXE 启动、真实 Keil 执行、OLED 像素和串口回复全部通过。使用随包内核，不调用开发虚拟环境作为运行内核。
- `tests/ui_smoke.py http://127.0.0.1:8767`：对 HTML 发行包执行完整浏览器交互检查，通过。
- 直接启动发行包 `CIMC-Studio.exe`，在实际 WPF WebView2 页面中载入/运行 Keil 示例，OLED 与串口启动输出通过。
- 正常关闭桌面窗口后，其启动的内核端口停止监听；另一份独立运行的测试服务不受影响。
- GitHub Actions 的 Windows `verify` 作业通过同一套 21 项测试和 .NET 宿主构建。

发行包为 Windows x64，未对全新操作系统、所有 Edge 版本或杀毒软件策略进行矩阵验证。桌面依赖系统 WebView2 Runtime；缺少时的浏览器回退路径有实现，但本机已有运行时，未实际卸载后测试。

## 支持范围与限制

| 能力 | 第一版范围 |
|---|---|
| CPU | Cortex-M4 ARM 机器码功能执行；非逐周期 |
| 固件 | Intel HEX、BIN；测试样本为交付 Keil AC6 固件，不保证任意工程 |
| GPIO | 输入/输出、上拉/下拉、开漏、手动跳线、NC、强驱动冲突 |
| OLED | PB8/PB9 软件 I²C，128×32，SSD1306 兼容指令子集 |
| 串口 | 轮询，GPIO 复用与 H6/H7 连接检查；RS485 方向控制；无物理 COM |
| SysTick | 基础单层异常；计数基于解释执行进度，不是 MCU 时钟精确计时 |
| UART IRQ / DMA | 未实现，明确报错 |
| NVIC / RTOS / FPU | 未完成完整兼容性验收 |
| 硬件 I²C / SPI / ADC / SD / 定时器 | 未实现完整器件行为，原固定信号关系保留 |
| 电源与模拟电路 | 理想供电和数字逻辑模型；无电流、电容、RS232/485 波形仿真 |
| HTML | 需要发行包内本地 ARM 内核；不是独立浏览器 WASM 版 |
| 视图 | 按 V1 原理图绘制的接线图；不是精确实物 PCB 布局 |

该版本是第一版开发预览，适合先验证受支持范围内的基础固件和接线流程；不作为赛事官方评测或真实硬件验收证明。
