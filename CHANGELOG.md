# Changelog

## 0.1.0 — 2026-11-15

第一版开发预览，目标板按用户最新选择采用 V1.0。

- Windows EXE 与 HTML 本地网页版共用 Apple 风格工作台。
- 实际执行 Keil 编译 HEX/BIN，提供运行、暂停、单步、复位和诊断。
- V1 原理图排针、固定网络、LED/KEY 手动跳线、H6/H7 跳帽。
- GPIO 软件 I²C OLED、基础 SysTick、轮询 CH340 / RS485 / RS232 / TTL 通道。
- 接线工程保存/恢复、串口日志导出、OLED PNG 导出、键盘操作与减少动画。
- 21 项内核/HTTP 检查和浏览器交互验收；发行包包含内核、源码与第三方许可。

边界：外设子集、数字功能仿真、非逐周期；UART 中断/DMA/硬件 I²C/ADC/SD/SPI Flash 等尚未实现。HTML 需随包本地内核。不是任意 Keil 工程兼容证明。详见 docs/validation-v0.1.md。
