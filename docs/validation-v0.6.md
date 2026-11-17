# CIMC Studio 0.6.0 验收记录

记录日期为2026-11-17。本文件逐项填写实际结果，待验项保留待验状态。

## 硬件依据

GD32F470xx数据手册Rev2.2第3.10节将定时器分为14个TIMER、24位SysTick及两种看门狗。TIMER0/7为16位高级，TIMER1/4为32位通用，TIMER2/3/8～13为16位通用，TIMER5/6为基本定时器。各通用类型具有不同通道数量。RTC日历属于第3.11节。

寄存器、时钟、连接和看门狗依据GD32F4xx User Manual Rev3.5相关章节及用户工程中的GD32F4xx固件库核对。原始资料和提取文本位于 `artifacts/timer-reference/`。[官方数据手册](https://www.gd32mcu.com/data/documents/datasheet/GD32F470xx_Datasheet_Rev2.2.pdf)

## 验收状态

| 验收项 | 实际结果 | 证据 |
|---|---|---|
| TIMER0～TIMER13寄存器与边界 | 35项通过，2.861秒 | artifacts/v06-timer-validation-final.log |
| 14实例真实机器码与IRQ | Keil HEX/BIN及两板真实IRQ通过 | tests/test_timers.py、firmware/TIMER_PROBE.md |
| 时钟、预装载、更新、计数模式 | 35项定时器检查覆盖，通过 | artifacts/v06-timer-validation-final.log |
| PWM、互补、捕获、编码器、触发 | 定时器边界及3项ADC/DAC联动通过，后者0.109秒 | tests/test_timers.py、tests/test_timer_triggers.py |
| 优先级、共享向量、SysTick回归 | 6项NVIC与时钟检查通过，0.129秒 | artifacts/v06-interrupt-priority-final.log |
| FWDGT/WWDGT寄存器与时钟 | 9项通过，0.010秒 | tests/test_watchdogs.py |
| FWDGT/WWDGT真实IRQ与系统复位 | 3项通过，V1/V2均执行，含真实WFI等待，最新联合12项检查0.475秒 | tests/test_watchdog_runtime.py、firmware/watchdog_probe.* |
| WFI、SLEEPONEXIT及SysTick精确边界 | 14项通过，0.301秒 | artifacts/v06-sleep-final.log |
| 原调度器与分块回归 | 12项通过，0.828秒 | artifacts/v06-scheduler-wfi-regression.log |
| 主题颜色保存与重启 | 用户配置5项、服务10项及六色浏览器交互通过 | tests/test_preferences.py、tests/test_server.py、artifacts/theme-ui-smoke.json |
| Windows全部源码检查 | 待验 | 待记录 |
| 浏览器定时器面板与适配 | 两板、14行状态、导出和窄屏通过，JavaScript错误为空 | artifacts/v06-timer-ui-smoke.json |
| Windows冻结包及原生安装 | 待验 | 待记录 |
| Ubuntu/Debian分发验收 | 待验 | 待记录 |
| 同一Linux发行包WSL补验 | 待验 | 待记录 |
| 正式安装与软件内更新 | 待验 | 待记录 |
| GitHub源码、标签与五种分发 | 待验 | 待记录 |
| 旧版更新识别和公开下载 | 待验 | 待记录 |
| 两平台Packages推送与回拉 | 待验 | 待记录 |
| 旧版分发清理 | 待验 | 待记录 |

## 看门狗实际固件

独立固件使用Keil Arm Compiler for Embedded 6.22编译。BIN摘要为 `a95469ee10d96370a33272de841f71a03ef196089610b67beadc2693c123a2e5`。通过正常CH340收发命令进入FWDGT、WWDGT和提前唤醒中断路径，启动后由真实WFI等待外设事件。

两板均实际超时复位，再由Reset_Handler读取RCU原因位并输出 `FWDGT RESET` 或 `WWDGT RESET`，分别点亮PD10或PD11连接的LED。发送 `C` 后由固件清除复位原因位。提前唤醒用真实IRQ0入口，处理器清EWIF、喂狗、打印 `W EWI` 并返回主循环，PD12连接的LED点亮。测试未向CPU/RAM注入结果。

寄存器测试覆盖全部FWDGT预分频编码、零和最大重装载边界、配置锁定、异步更新、IRC32K独立时钟、7周期重装载间隔、全部WWDGT预分频、EWIF读写、窗口相等与过早喂狗、时钟门控、外设复位、DBG保持和时钟变化下分块一致性。

## WFI与SysTick时序

`tests/test_sleep.py` 验证窄指令、宽指令及条件WFI、等待期间的零CPU指令增长、外部IRQ、PRIMASK唤醒和BASEPRI/FAULTMASK屏蔽、普通WFI期间的定时器及SysTick计时，以及SLEEPONEXIT返回线程时继续等待。无可唤醒事件时返回有界执行结果，界面仍可暂停或复位。

本版修正早期SysTick模型的启动和零重装载行为。VAL为0后的首个输入时钟只重装载，COUNTFLAG及中断在实际1→0转换时产生，LOAD为0且当前计数为0时保持停止。运行中更改LOAD只影响后续重装载。HCLK/8余相位、跨多周期推进和分块结果均由实际边界检查覆盖。原有密集中断调度回归改用LOAD为1来维持其验证目的。NVIC分组及外部SysTick时钟6项通过，0.129秒。

## 主题颜色

设置中的“主题颜色”提供蓝色、青色、绿色、紫色、玫红、琥珀六种强调色。选择保存在用户配置，并与当前浏览器偏好同步。六色交互、重新打开、窄屏和颜色可访问性检查通过，最低对比度为4.697。实际记录见 `artifacts/theme-ui-smoke.json`。

## 原始DEMO与性能回归

原始用户DEMO按实际机器码在两板验证启动、复位、工程恢复和分块一致性，通过，用时36.602秒。每25万条指令读取一次真实HAL计数，V1为1、2、4、5，V2为362、719、1076、1434，变化对应本版修正后的SysTick初始相位。LED输出仍符合原程序。证据为 `artifacts/v06-original-demo-regression.json`。

热路径相关70项检查通过，用时8.099秒。无活动定时器的交错吞吐对比为0.83696，约有16%的模型开销，见 `artifacts/v06-inactive-timer-profile.json`。极端V2 PWM测试中，CAR为1的1000条CPU指令约用时5.322秒，来自必须处理的外设事件数量。高频路径将宿主时间检查间隔缩小到8条指令，观察到单次短片约40毫秒。此记录属于功能模型吞吐和响应性，实际主机性能会影响耗时。

## 功能时钟范围

当前验证使用确定性功能时钟。FWDGT配置与重装载在下一IRC32K边沿提交，跨时钟域延迟属于功能模型选择。14个TIMER按各自类型支持通道和模式。普通WFI中断等待属于本版功能模型，WFE事件等待和深度休眠电源域会给出明确诊断。完整DMA控制器、RTC日历、实板电气与逐周期时序需要独立实现及验收。
