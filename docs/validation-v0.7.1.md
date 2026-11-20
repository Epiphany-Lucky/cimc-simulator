# CIMC Studio 0.7.1 验收记录

## PROJECT1 停机与修复范围

用户报告 V1 小灯全灭并指出 PC `0x08000E50`。原版 0.7.0 正式会话确认正在使用 `MDK-ARM/build/PROJECT0/PROJECT0.hex`，SHA-256 为 `1a12c1d631a3327cbb6091570bfb8ba950f855ea1e002100f80adaa1ca95dcec`。六条跳线为 PD8～PD13 到 LED1～LED6。

ARMCC 反汇编显示，`0x08000E48` 调用 `HAL_PWREx_EnableOverDrive()`，`0x08000E4C` 检查返回值，失败后关中断并进入 `0x08000E50` 自循环。独立执行同一份 HEX，50,000 条指令时读取状态寄存器 `0x40007004` 为零，100,000 条时进入停机点，PD 模式、输出和任务数均为零。

GD32 PMU 高驱动使能及切换控制位与就绪状态对应。原实现仅为 V2 响应状态。0.7.1 复用该功能映射，让 V1 和 V2 都按实际控制位给出就绪状态。保留已有 PMU 控制寄存器、位带、时钟、GPIO 路径。依据为芯片手册和实际 HAL 实现。[GD32F4xx 用户手册](https://www.gd32mcu.com/data/documents/userManual/GD32F4xx_User_Manual_Rev2.7.pdf) · [STM32F427 RM0090](https://www.st.com/resource/en/reference_manual/rm0090-stm32f405-415-stm32f407-417-stm32f427-437-and-stm32f429-439-advanced-armbased-32bit-mcus-stmicroelectronics.pdf)

## 本机源码与真实固件

- 四个原位带用例和新增 PMU 就绪用例全部通过。新增用例核对两个板型的复位、使能、切换、清除及保留其他状态位。
- 同一份原 HEX 执行 1,000,000 条 ARM 指令后 HCLK 为 180 MHz，APB1 为 45 MHz，APB2 为 90 MHz。PWR 状态 `0x00030000`，GPIOD 输出 `0x3500`，LED1、LED3、LED5、LED6 点亮，诊断为空。原源码和 HEX 保留。
- 隔离复现的前态与修复后证据分别在 `artifacts/v071-before-project1-state.json`、`artifacts/v071-project1-source-positive.json`。用户固件与工程备份仅用于本机验收。
