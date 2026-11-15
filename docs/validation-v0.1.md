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

重新构建后的独立 EXE 运行、WebView2 与 HTML 发行包检查正在进行，结果将于发布前更新。构建成功不能替代发行包运行验收。

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
