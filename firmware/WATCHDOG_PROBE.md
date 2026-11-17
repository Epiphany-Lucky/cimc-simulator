# 看门狗验收固件

`watchdog_probe.c` 为独立编写的裸机C固件，由Keil Arm Compiler for Embedded 6.22编译为HEX/BIN。BIN SHA-256为 `a95469ee10d96370a33272de841f71a03ef196089610b67beadc2693c123a2e5`。

## 运行

V1和V2均使用USART0 PA9/PA10 AF7，经真实CH340连接收发。V1的H7由板卡固定连接定义，V2接通H12.1–H12.3、H12.2–H12.4。添加PD10→LED1、PD11→LED2、PD12→LED3跳线，导入 `watchdog_probe.hex` 或 `.bin` 后点击运行。

固件先输出 `WDGT SELECT F W E`。在CH340终端发送ASCII字符。启动看门狗后，主循环执行真实WFI进入中断等待，虚拟外设时钟继续运行，超时复位或提前唤醒中断由模型触发。

| 字符 | 真实执行路径 | 预期结果 |
|---|---|---|
| F | 配置并启动FWDGT，等待超时系统复位 | 重新启动后读取RCU原因位29，输出 `FWDGT RESET`，LED1亮 |
| W | 配置并启动WWDGT，等待超时系统复位 | 重新启动后读取RCU原因位30，输出 `WWDGT RESET`，LED2亮 |
| E | 启用IRQ0，提前唤醒处理中清EWIF并重装载 | 输出 `W EWI`，LED3亮，返回主循环继续运行 |
| C | 固件写RCU_RSTFC | 输出 `FLAGS CLEAR`，复位原因位清零 |

选择新的看门狗场景前，发送C清除此前原因位，再重新载入固件。系统复位后固件会根据实际原因位直接进入结果分支。

## 邮箱和编译

SRAM地址 `0x20001000` 的4个32位字依次保存阶段、收到的命令、真实EWI次数和启动读取的复位原因。`0x57414954`为等待命令，`0x46574F4B`为FWDGT复位后的FWOK，`0x57574F4B`为WWDGT复位后的WWOK。

在项目目录运行 `powershell -File firmware/build.ps1 -Target watchdog_probe` 可重新编译。实际中断和系统复位回归命令为 `.venv/Scripts/python.exe -m unittest discover -s tests -p test_watchdog_runtime.py -v`。

硬件寄存器依据GD32F4xx User Manual Rev3.5第16章。功能模型在下一IRC32K边沿完成配置及重装载提交，异步延迟与实际芯片周期需单独校验。
