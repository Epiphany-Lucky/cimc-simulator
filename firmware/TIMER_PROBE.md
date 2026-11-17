# GD32F470 定时器验证固件

2026-11-17

`timer_probe.c` 是独立编写的裸机验收程序。Keil Arm Compiler for Embedded 6.22 编译生成 HEX、BIN、AXF 和 MAP，CPU 通过真实寄存器访问、中断入栈和返回推进程序。运行完成消息由 USART0 / PA9 的机器码发送。

## 构建与源码验收

在项目根目录运行以下命令。

```powershell
./firmware/build.ps1 -Target timer_probe
./.venv/Scripts/python.exe -m unittest discover -s tests -p test_timers.py -v
```

探针入口向量位于 `0x08000000`，初始 MSP 为 `0x20020000`。测试以 SRAM `0x2000007C` 的模式字选择独立场景，该模式字由验收工具在复位执行前设置。软件的“载入定时器示例”使用模式0。其余场景可以按源码中的寄存器配置在自己的固件中复现。

| 模式 | 真实固件操作 | 验收输出 |
|---|---|---|
| 0 | 逐个使能 TIMER0～TIMER13，以实际更新中断处理器停止并计数，检查 TIMER1/4 的32位计数器 | `ALL14 TIMER IRQ OK`，LED1、3、5、6点亮 |
| 1 | TIMER3_CH0 从 PD12 / AF2 输出周期60000 HCLK、占空比25%的 PWM，PA5 / AF1 的 TIMER1_CH0 捕获并产生实际捕获中断 | `PWM CAPTURE OK`，三次以上捕获、相邻捕获值差60000 |
| 2 | CPU 用 PD8、PD9 产生16个真实GPIO边沿，经 PA6、PA7 / AF2 输入 TIMER2 正交解码器 | `ENCODER16 OK`，计数值16 |
| 3 | TIMER1 更新 TRGO 经 TIMER2 的 ITI1 输入作为外部计数时钟 | `TIMER CHAIN OK`，从定时器计数大于0 |
| 4 | BASEPRI 阻塞低优先级 TIMER1，解除后在其处理器中启动高优先级 TIMER2，实现真实嵌套抢占 | `NESTED TIMER IRQ OK`，处理顺序轨迹 `0x123` |
| 5 | TIMER0 软件事件同时请求刹车、更新、触发、换相、捕获比较中断，验证四个硬件向量及共享触发/换相向量 | `ADVANCED TIMER IRQ OK`，五个事件各处理一次 |

模式0的六根参考跳线按 PD8～PD13 顺序连接 LED1～LED6。模式1使用 PD12→PA5，模式2使用 PD8→PA6 和 PD9→PA7。上述跳线作为可编辑外接连线保存。PA5 的选择适用于两个板卡的可连接排针，沿用原板固定网络。

## 定时器实例与差异

| TIMER | 地址 | 位宽 | 通道 | 更新IRQ | APB/使能与复位位 |
|---|---|---|---|---|---|
| 0 | 0x40010000 | 16 | 4 | 25 | APB2 bit0 |
| 1 | 0x40000000 | 32 | 4 | 28 | APB1 bit0 |
| 2 | 0x40000400 | 16 | 4 | 29 | APB1 bit1 |
| 3 | 0x40000800 | 16 | 4 | 30 | APB1 bit2 |
| 4 | 0x40000C00 | 32 | 4 | 50 | APB1 bit3 |
| 5 | 0x40001000 | 16 | 0 | 54 | APB1 bit4 |
| 6 | 0x40001400 | 16 | 0 | 55 | APB1 bit5 |
| 7 | 0x40010400 | 16 | 4 | 44 | APB2 bit1 |
| 8 | 0x40014000 | 16 | 2 | 24 | APB2 bit16 |
| 9 | 0x40014400 | 16 | 1 | 25 | APB2 bit17 |
| 10 | 0x40014800 | 16 | 1 | 26 | APB2 bit18 |
| 11 | 0x40001800 | 16 | 2 | 43 | APB1 bit6 |
| 12 | 0x40001C00 | 16 | 1 | 44 | APB1 bit7 |
| 13 | 0x40002000 | 16 | 1 | 45 | APB1 bit8 |

高级 TIMER0/7 提供互补输出、死区、刹车、换相和重复计数。TIMER1～4 为完整通用定时器。TIMER8/11 提供双通道与主从管理。单通道 TIMER9/10/12/13 采用向上计数。基础 TIMER5/6 用于时间基准与 TRGO。实例和功能差异依据官方用户手册第18章以及数据手册定时器章节录入。[GD32F4xx User Manual Rev3.5](https://www.gd32mcu.com/data/documents/userManual/GD32F4xx_User_Manual_Rev3.5.pdf) [GD32F470 数据手册 Rev2.2](https://www.gd32mcu.com/data/documents/datasheet/GD32F470xx_Datasheet_Rev2.2.pdf)

## 寄存器边界回归

`tests/test_timers.py` 同时覆盖全部实例的门控、复位、位宽和独立状态，PSC/ARR/比较值的影子装载，向上、向下、中心对齐、单脉冲、重复计数，UPDIS/UPS 与 rc_w0 标志，拆分和共享中断，八种比较/PWM模式，输入捕获、过捕获、读取清标志、数字滤波及输入预分频，外部时钟、编码器和主从触发，互补输出死区、刹车、保护锁、换相影子更新，以及 APB 分频、TIMERSEL 倍频和调试冻结。

实际固件场景在 V1/V2 均执行，模式0分别使用 HEX 与 BIN。冻结包验收脚本使用正常载入、接线、运行和串口接口观察模式0，随后执行看门狗固件场景。原始 SRAM 邮箱用于源码验收，冻结包的通过条件来自固件串口消息、LED 和公开定时器状态。

该模型使用确定性的 HCLK tick 推进时间，完整 DMA 控制器、以太网 PTP、USB SOF 和 RTC 专用输入源分别需要对应外设实现。验收记录按实际连接和诊断说明这些依赖。

## 摘要

| 文件 | SHA-256 |
|---|---|
| timer_probe.c | fdef91b2a18dabb150d1bcbad9022eb171baa8bef840cc596c5bfabeea03259f |
| timer_probe.bin | 0a125efc36f1585f5ee807908b9eb499903c9b2a5d570f1c547568834ff18f12 |
| timer_probe.hex | 6cae5c5ce106fb5d2280d11f984f60ee1cb03152cf67826aaa26cf01bfea6faf |
