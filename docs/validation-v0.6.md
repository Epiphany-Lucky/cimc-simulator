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
| 暂停态输入顺序和立即反馈 | 30毫秒按下/松开、350毫秒按下请求延迟、鼠标拖出、失焦及弹窗内快捷键释放通过 | artifacts/key-ui-smoke.json、artifacts/v06-key-event-race-before.json、artifacts/v06-key-event-race-after.json |
| DEMO2按键扫描及LED响应时钟定位 | 同一HEX由1.947秒/152万条指令改善为21毫秒/1万条指令 | artifacts/v06-key-clock-diagnosis.json |
| DEMO2真实DOM按压与LED响应 | 23项通过，含鼠标/键盘50、100、200毫秒目标各3次 | artifacts/v06-key-ui-independent.json |
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

浏览器验收逐一切换六色并刷新，关闭并重新打开持久浏览器配置，再从独立上下文及另一localhost来源读取同一配置，均恢复预期颜色。键盘方向键选择、快速连续切换、旧版非法缓存回退及延迟初始状态返回检查通过。六种主按钮的文字对比度为4.697～5.906，激活导航为5.900～7.330。硬件连线的实际颜色保持一致，主题操作发送的仿真命令数为0，JavaScript错误列表为空。

1024×600及390×844的设置弹窗保持在视口内，页面无横向溢出。截图位于 `artifacts/theme-ui-1024.png` 和 `artifacts/theme-ui-390.png`。用户配置文件位于Windows的 `%LOCALAPPDATA%\CIMCStudio\preferences.json` 或Linux的 `$XDG_CONFIG_HOME/cimc-studio/preferences.json`，Linux未设置XDG目录时使用 `~/.config/cimc-studio/preferences.json`。同源JSON接口校验颜色固定集合，写入通过原子替换完成。验收服务使用独立配置目录。

## 按键响应

用户报告的固件为 `D:\desktop\CIMC_DEMO\DEMO2\CIMC_DEMO\MDK-ARM\build\CIMC_DEMO\CIMC_DEMO.hex`，本次时钟定位的SHA-256为 `e5990ebfef5fc8a8b81e45bfdeea35db623391d19d95892ff11ea5cd6781a030`，已与磁盘文件核对。V1原每条指令1个HCLK tick时，一次实际按键扫描及LED响应执行152万条指令、耗时1.946576秒。改为240后，实际响应执行1万条指令、耗时0.021035秒。DEMO2通过10毫秒调度扫描和KEY_Down边沿处理按键。CPU仍执行真实固件，按键通过实际GPIO网络输入。该测试主机的两次HAL tick分别由11→20和19→33，证据为 `artifacts/v06-key-clock-diagnosis.json`。

浏览器原先在按下请求延迟350毫秒时可重现松开后后端仍按下，报告为 `artifacts/v06-key-event-race-before.json`。按顺序提交后，相同延迟下后端最终释放，见 `artifacts/v06-key-event-race-after.json`。`tests/key_ui_smoke.py` 在暂停态进一步验证30毫秒按下/松开的输入顺序、立即反馈、鼠标捕获后在外释放及键盘失焦释放，全部通过且无JavaScript错误。记录为 `artifacts/key-ui-smoke.json`。

随后确认按住数字快捷键时打开设置或帮助弹窗，会因全局keyup的弹窗判断跳过释放。修正后，数字1按下、打开设置、松开的原生键盘回归通过，`numericShortcutModalRelease` 为true。该检查已加入 `tests/key_ui_smoke.py`，随包执行。

独立浏览器随后从文件界面导入同一DEMO2的12线工程，以真实原生鼠标和键盘事件分别执行50、100、200毫秒目标按压，每组各3次，18次均由固件翻转LED2。浏览器使用 `performance.now()` 定时释放，并记录实际DOM按下/松开，50毫秒目标实际为52.2～55.1毫秒，100毫秒为102.2～106.9毫秒，200毫秒为203.3～205.8毫秒。KEY2～KEY5另各执行100毫秒目标按压，分别翻转LED3～LED6。该固件为KEY1～KEY5配置LED动作，KEY6项检查释放及LED状态保持，合计23项通过。

每项HTTP按下/松开顺序正确，最终全部按键释放，无JavaScript错误，即时样式反馈最长8.1毫秒。18项主测试首次观察到GPIO结果的前台延迟为43.9～321.6毫秒，另有KEY2项为440.8毫秒，包含130毫秒轮询、HTTP和宿主调度时间。证据为 `artifacts/v06-key-ui-independent.json` 和截图。测试私有服务及配置均已清理。

## 原始DEMO与性能回归

原始用户DEMO按实际机器码在两板验证启动、复位、工程恢复和分块一致性，通过，用时16.116秒。V1/V2默认均为每条实际指令240个HCLK tick，每25万条指令读取一次真实HAL计数，两板均为362、719、1076、1434。LED输出仍符合原程序。证据为 `artifacts/v06-original-demo-regression.json`。

该回归使用此前保存的自包含工程，原始DEMO1的HEX SHA-256为 `6c4c6c6cb0cf775f128868702c071a97fcaf6cef17b1fc0d485a6c542f1d8ff2`，与当前磁盘HEX一致。V1/V2各执行100万条指令，六路LED均为亮、灭、亮、灭、亮、亮。最终比较包含CPU、SRAM、CCM、外设寄存器、SysTick、定时器及看门狗，三个指令分块方案的结果一致。

首轮热路径相关70项检查通过，用时8.099秒。无活动定时器的交错吞吐对比使用真实V2 Boot/App，为0.83696，约有16%的模型开销，见 `artifacts/v06-inactive-timer-profile.json`。极端V2 PWM测试中，CAR为1的1000条CPU指令约用时5.322秒，来自必须处理的外设事件数量。高频路径将宿主时间检查间隔缩小到8条指令，观察到单次短片约40毫秒。此记录属于功能模型吞吐和响应性，实际主机性能会影响耗时。

## 冻结包启动预算

源码 `03c814205c3d03110f699f7a501a1e8a5e1c3584` 的首轮本机原生安装验收在V2 Boot/App启动阶段达到240秒墙钟上限，执行52,518,016条指令，无诊断且仍在OLED软件I2C的 `iic_delay`。失败记录保存在 `artifacts/installer-smoke-827fc96c7c00/result.json`。

随后单独运行同一冻结内核的正常V2入口，首次观察到完整RS485启动帧时已执行60,871,552条指令、耗时160.957秒，向量表为 `0x08011000`，无诊断。记录见 `artifacts/v06-pre-keyfix-frozen-v2-startup.json`。该探针首次结束时遇到PyInstaller子进程句柄退出问题，已核实专属PID并清理，报告保留处理记录。完整CI的Linux和Windows冻结固件执行均已通过原240秒预算。

据实际指令需求，包验收将V2启动墙钟预算扩展到600秒，同时设置8000万条实际指令上限。Windows安装验收外层包执行预算为900秒。Linux工作流直接运行脚本，其外层未设置更短超时，启动预算由同一脚本控制。后续最终源码及原生安装结果另填入上表。

## 宿主待机中断及重验

第二轮本机原生安装验收 `installer-smoke-3d06d4de0df4` 已通过定时器、看门狗和相对吞吐检查，V2启动时在途 `/api/state` 请求超出10秒时限。同一时段冻结界面验收已有6项通过，随后V2原理图检查达到180秒子进程时限。原失败记录分别保存在 `artifacts/installer-smoke-3d06d4de0df4/result.json` 和 `artifacts/v06-standby-interrupted-frozen-ui-suite.json`。

Windows System日志确认10:18:31.5988607因Lid进入现代待机，10:27:29.5651274因Lid退出，期间还记录电量预算触发的待机转换。该时间段与工具60秒等待实际耗时约561秒相符。事件506/507及原始原因已归档 `artifacts/v06-host-standby-events.json`。本轮留存失败记录，软件及HTTP时限保持原值，最终验收在宿主恢复后原样重新执行。

## 功能时钟范围

当前验证使用确定性功能时钟。FWDGT配置与重装载在下一IRC32K边沿提交，跨时钟域延迟属于功能模型选择。14个TIMER按各自类型支持通道和模式。普通WFI中断等待属于本版功能模型，WFE事件等待和深度休眠电源域会给出明确诊断。完整DMA控制器、RTC日历、实板电气与逐周期时序需要独立实现及验收。
