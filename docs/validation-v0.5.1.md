# CIMC Studio 0.5.1 验收记录

记录日期为2026-11-16。此文件随实际验证补充，待验项目保留待验状态。

## 问题定位

用户工程位于 `D:\desktop\CIMC_DEMO\DEMO1\CIMC_DEMO`，复现使用其 `MDK-ARM\build\CIMC_DEMO\CIMC_DEMO.hex`。当前0.5.0内核在第764条指令、PC `0x08000BCA` 处诊断未映射访问 `0x42470060`，与用户截图一致。HAL 通过该外设位带别名写 RCC_CR 的 PLLON 位。

工程使用 STM32F427 的启动文件和 HAL。此次验证针对该 HEX 实际执行的时钟、SysTick 和 GPIO 路径。主循环只调度 `led_proc`，六路输出来自 `ucLed = {1,0,1,0,1,1}` 及 PD8～PD13。没有 OLED 初始化和串口任务。用户当前接线已按 PD8～PD13 连接 LED1～LED6，实际工作台状态保存在 `artifacts/v051-user-session-state.json`。

## 修复范围

扩展 `engine/simulator.py` 的字对齐外设位带别名访问，复用现有 RCC、GPIO 和未实现寄存器诊断。按 ARM 位带语义从别名映射底层位，读返回0或1，写只取最低位，以单个仿真访问完成读改写。

依据为 Arm Cortex-M4 Technical Reference Manual 第3.7节。支持范围为外设位带，SRAM 位带单独列入后续兼容性范围。[ARM 官方文档](https://documentation-service.arm.com/static/5fce431be167456a35b36ade)

## 验收状态

| 验收项 | 实际结果 | 证据 |
|---|---|---|
| 原始问题复现 | 第764条指令、PC 0x08000BCA、0x42470060未映射访问 | 本轮命令输出 |
| 用户原始 HEX 启动与 SysTick | V1/V2均执行100万条指令，SysTick递增，通过 | artifacts/v051-demo-source-check.json |
| 六路 LED 实际接线输出 | 两板均为1、0、1、0、1、1，PD_ODR为0x3500，通过 | artifacts/v051-demo-source-check.json |
| 独立位带机器码及非法访问回归 | 4项测试通过，用时0.104秒 | tests/test_bitband.py、firmware/BITBAND_PROBE.md |
| Windows 全套源码检查 | 待验 | 待记录 |
| Windows 冻结包与原生桌面 | 待验 | 待记录 |
| Windows 安装、升级、卸载 | 待验 | 待记录 |
| Ubuntu/Debian 安装分发 | 待验 | 待记录 |
| 同一 Linux 冻结包本机补验 | 待验 | 待记录 |
| GitHub 源码、标签和发行附件 | 待验 | 待记录 |
| 正式安装与软件内更新 | 待验 | 待记录 |
| 在线更新旧客户端识别 | 待验 | 待记录 |
| 两平台 Packages 发布及回拉摘要 | 待验 | 待记录 |
| 旧版分发文件清理 | 待验 | 待记录 |

## 用户原始 HEX 源码内核验收

`artifacts/v051-demo-source-check.py` 对原始 HEX 和保存的用户工程执行验证，结果 `passed=true`，总耗时14.038秒。原始 HEX 的 SHA-256 为 `6c4c6c6cb0cf775f128868702c071a97fcaf6cef17b1fc0d485a6c542f1d8ff2`，测试前后用户工程源文件、HEX及MAP哈希一致。

每25万条执行指令取样一次，由 MAP 定位 `uwTick` 的实际 RAM 地址 `0x20000024`。V1 的四次读数为3、4、6、7，V2为364、721、1078、1435。两板均得到 PD_ODR `0x3500` 和 LED1、LED3、LED5、LED6 点亮。复位、工程导出恢复以及100个1万指令块与3个不等长指令块的结果一致性检查均通过。测试只读取CPU/RAM证据，程序执行由原始机器码推进。

## 执行边界

此 DEMO 预期为静态 LED 输出。OLED 关闭和串口静默与工程内容一致。SysTick 为按执行指令推进的功能模型，主机墙钟耗时取决于仿真吞吐。完整 STM32F427 外设兼容性和实板时序需要独立验收。
