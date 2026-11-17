# CIMC Studio 0.6.0 验收记录

记录日期为2026-11-17。本文件逐项填写实际结果，待验项保留待验状态。

## 硬件依据

GD32F470xx数据手册Rev2.2第3.10节将定时器分为14个TIMER、24位SysTick及两种看门狗。TIMER0/7为16位高级，TIMER1/4为32位通用，TIMER2/3/8～13为16位通用，TIMER5/6为基本定时器。各通用类型具有不同通道数量。RTC日历属于第3.11节。

寄存器、时钟、连接和看门狗依据GD32F4xx User Manual Rev3.5相关章节及用户工程中的GD32F4xx固件库核对。原始资料和提取文本位于 `artifacts/timer-reference/`。[官方数据手册](https://www.gd32mcu.com/data/documents/datasheet/GD32F470xx_Datasheet_Rev2.2.pdf)

## 验收状态

最终产品源码固定为 `ca91cd9c7e80d5c245a5affe52aa2e99db593251`，选定完整发行构建为CI `44003765945`。后续结果按同一源码与对应发行产物填写。[产品源码](https://github.com/Epiphany-Lucky/cimc-simulator/commit/ca91cd9c7e80d5c245a5affe52aa2e99db593251)，[完整CI](https://github.com/Epiphany-Lucky/cimc-simulator/actions/runs/44003765945)

| 验收项 | 实际结果 | 证据 |
|---|---|---|
| TIMER0～TIMER13寄存器与边界 | 35项通过，2.861秒 | artifacts/v06-timer-validation-final.log |
| 14实例真实机器码与IRQ | Keil HEX/BIN及两板真实IRQ通过 | tests/test_timers.py、firmware/TIMER_PROBE.md |
| 时钟、预装载、更新、计数模式 | 35项定时器检查覆盖，通过 | artifacts/v06-timer-validation-final.log |
| PWM、互补、捕获、编码器、触发 | 定时器边界及3项ADC/DAC联动通过，后者0.109秒 | tests/test_timers.py、tests/test_timer_triggers.py |
| 优先级、共享向量、SysTick回归 | 6项NVIC与时钟检查通过，0.129秒 | artifacts/v06-interrupt-priority-final.log |
| FWDGT/WWDGT寄存器与时钟 | 9项通过，0.010秒 | tests/test_watchdogs.py |
| FWDGT/WWDGT真实IRQ与系统复位 | 3项通过，V1/V2均执行，含真实WFI等待，首轮联合12项检查0.475秒 | tests/test_watchdog_runtime.py、firmware/watchdog_probe.* |
| WFI、SLEEPONEXIT及SysTick精确边界 | 14项通过，0.301秒 | artifacts/v06-sleep-final.log |
| 原调度器与分块回归 | 12项通过，0.828秒 | artifacts/v06-scheduler-wfi-regression.log |
| 主题颜色保存与重启 | 用户配置5项、服务10项及六色浏览器交互通过 | tests/test_preferences.py、tests/test_server.py、artifacts/theme-ui-smoke.json |
| Windows全部源码检查 | 本机245项执行，235项通过、10项平台跳过，211.258秒；同源码CI为126.426秒，桌面构建通过 | artifacts/v06-final-windows-build.log、artifacts/v06-ci-windows-source.log |
| Ubuntu全部源码检查 | 245项全部通过，233.380秒 | artifacts/v06-ci-ubuntu-source.log |
| 浏览器定时器面板与适配 | 两板、14行状态、导出和窄屏通过，JavaScript错误为空 | artifacts/v06-timer-ui-smoke.json |
| 暂停态输入顺序和立即反馈 | 30毫秒按下/松开、350毫秒按下请求延迟、鼠标拖出、失焦及弹窗内快捷键释放通过 | artifacts/key-ui-smoke.json、artifacts/v06-key-event-race-before.json、artifacts/v06-key-event-race-after.json |
| DEMO2按键扫描及LED响应时钟定位 | 同一HEX由1.947秒/152万条指令改善为21毫秒/1万条指令 | artifacts/v06-key-clock-diagnosis.json |
| DEMO2真实DOM按压与LED响应 | 23项通过，含鼠标/键盘50、100、200毫秒目标各3次 | artifacts/v06-key-ui-independent.json |
| 最终冻结包全部界面与DEMO2 | 11项界面脚本及23项原DEMO2可信DOM输入全部通过，152文件核对提交、工作树和包 | artifacts/v06-frozen-ui-suite.json、artifacts/v06-frozen-ui/demo2-native-key-ui.json |
| Windows冻结包及原生安装 | 最终原生安装、WPF/WebView2、真实固件、重装、卸载及用户文件保留全部通过 | artifacts/installer-smoke-2cdda14a9b2f/result.json、artifacts/v06-final-installer-smoke.log |
| Ubuntu/Debian分发验收 | Ubuntu22.04 DEB、完整Chromium工作台、生命周期及卸载，Debian12安装、实际固件及卸载均通过 | CI 44003765945 package-linux、artifacts/v06-linux-ci-verification.json |
| 同一Linux发行包WSL补验 | 同一选定tar在WSL Ubuntu26.04通过全部包内固件、生命周期和原始DEMO三轮检查，111.241秒 | artifacts/v06-same-linux-wsl.json、artifacts/v06-frozen-linux-user-demo.json |
| 正式安装与软件内更新 | 实际0.5.1下载/SHA/安装器成功，新冻结内核自动重启失败；干净进程恢复0.6.0及当前DEMO2，后续由0.6.1修复 | artifacts/v06-production-upgrade.json、artifacts/v06-production-registry-audit.json |
| GitHub源码、标签与五种分发 | 固定ca91源码、注释标签及公开发行448041269完成，五软件及三验证/摘要附件共8项，公开五文件HEAD和摘要通过 | CI 44003765945、草稿44007328118、artifacts/v06-public-download-heads.json |
| 旧版更新识别和公开下载 | 匿名源码版本比较、四入口HEAD及五文件摘要通过，实际0.5.1下载0.6.0完成 | artifacts/v06-public-update-check.json、artifacts/v06-public-download-heads.json、artifacts/v06-production-upgrade.json |
| 两平台Packages推送与回拉 | Windows/Linux的0.6.0及latest均推送，按0.6.0回拉并核对全部文件摘要通过 | Packages工作流44007852329 |
| 旧版分发清理 | 远端8项通过，本地旧分发已随0.6.1完整验收后统一清理 | docs/releases/cleanup-v0.6.0.json、docs/validation-v0.6.1.md |

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

最终 `ca91cd9` 冻结包再次通过全部11项界面脚本，并通过同一冻结内核上的23项原DEMO2可信DOM输入检查。50毫秒目标实际为52.4～57.4毫秒，100毫秒为102.7～108.8毫秒，200毫秒为203.4～206.9毫秒，18次主测试均由固件翻转LED2。最终即时样式反馈最长8.3毫秒，GPIO前台首次观察为40.2～167.8毫秒，仍包含HTTP和130毫秒轮询。输入顺序、全部按键最终释放及JavaScript错误检查通过。

该冻结包152个运行及源码文件与提交Git blob、工作树和包内原始SHA-256逐一核对，验收前后包未变更。内核SHA-256为 `d564836b00ab367b86d0fdcf01f30cd6af69b1345e10bd97f474a63c4de2d1a7`。完整V2界面验收用时345.196秒，包含实际Boot/App、协议、ADC/DAC、工程恢复。主记录为 `artifacts/v06-frozen-ui-suite.json`，DEMO2记录为 `artifacts/v06-frozen-ui/demo2-native-key-ui.json`，私有服务及配置均清理完成。

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

宿主恢复后的最终原生验收 `installer-smoke-2cdda14a9b2f` 全部通过，`passed` 和 `desktopTest` 均为true，HKCU登记版本为0.6.0。实际安装后的内核完成14个定时器、两看门狗、三镜像Boot/App、V2真实Boot/CRC及ADC/DAC/SPI检查，相对SysTick吞吐比为0.917514。WPF/WebView2实际窗口、OLED和原理图检查通过，窗口处于显示器工作区内。覆盖重装、卸载及用户自存文件保留均通过，证据为该目录的 `result.json` 和 `artifacts/v06-final-installer-smoke.log`。

## 选定发行文件

注释标签 `v0.6.0` 的标签对象为 `2d71128e07a9b027da2d7eb85e12695f360b510e`，解引用到产品源码 `ca91cd9c7e80d5c245a5affe52aa2e99db593251`。草稿装配工作流 `44007328118` 成功，严格从选定完整CI复制五个软件附件并生成摘要清单和CI来源说明。

公开发行ID为 `448041269`，当前 `draft=false`、`prerelease=true`，沿用开发预览发布设计，共8附件。五软件、摘要清单及CI来源说明的ID、大小和SHA-256在公开及元数据复核期间逐项保持一致，本机验收说明单独更新。管理API实际快照为 `artifacts/v06-release-api.json`。[公开发行](https://github.com/Epiphany-Lucky/cimc-simulator/releases/tag/v0.6.0)

匿名直接访问五个公开分发文件的HEAD均返回200，公开 `SHA256SUMS-0.6.0.txt` 的五条记录与选定CI下载receipt完全一致，记录为 `artifacts/v06-public-download-heads.json`。更新客户端的匿名元数据发现及正式升级另列验收。

完整CI `44003765945` 的两个源码检查和两个打包验收job均成功。Windows CI隔离安装ID为 `9a8ac47abafc`，实际固件、重装和卸载通过；本机原生桌面验收另使用上文的最终记录。Ubuntu22.04完成DEB安装、实际固件、Chromium全部工作台、生命周期及卸载，Debian12容器完成安装、实际固件、生命周期及卸载。两平台验收artifact下载均已核对API摘要和CRC。

Windows原始CI artifact为 `14294326360`，232193831字节，外层ZIP SHA-256为 `5b7422702f8a482bc0f4b2e40f9e98f4edc6f3de4b6e021446c20de96ad01d2e`。全部附件名称集、版本和CRC均已核对，下载分片在完整验证后逐文件清除。

Linux原始CI artifact为 `14295110639`，100137202字节，外层ZIP SHA-256为 `21c6fa3aae845cc76039cb9dc6e7ab2df0a5b33a5b6e4de621afb1965b795453`。全部附件名称集、版本和CRC均已核对，下载分片在完整验证后逐文件清除。

| 分发文件 | SHA-256 |
|---|---|
| CIMC-Studio-0.6.0-Setup-x64.exe | 48cb8cf1f4cfbac91e345dfe6f92669982d1a33201f50ed2cc1b5957241be664 |
| CIMC-Studio-0.6.0-win-x64.zip | 266f97846e282c5b7366e2a68f1483cf55b26ddd1151fb35e0b7b0b92fe18f2e |
| CIMC-Studio-0.6.0-html-local.zip | 3bdbe866108135f90f1d074379ec0b855beddb315b4c57684990201d204b6465 |
| cimc-studio_0.6.0_amd64.deb | 74ae2e568dbd153071ce3ee195585ad44899e770d105156c5be3f342e61d0b29 |
| CIMC-Studio-0.6.0-linux-x64.tar.gz | 69598933e8be83b713f64fef70ab47a9ca0e12e85b9f34fa0fe0ce2f9e1eb51e |

## 同一Linux发行包WSL补验

对选定CI的实际Linux tar核对SHA-256 `69598933e8be83b713f64fef70ab47a9ca0e12e85b9f34fa0fe0ce2f9e1eb51e` 后，在WSL Ubuntu26.04自建临时目录解压，运行包内 `source/tests/package_smoke.py` 和 `source/tests/linux_install_smoke.py --portable` 全部通过。包含14个定时器真实IRQ、两看门狗超时复位和IRQ0、V2真实Boot/App及CRC、ADC/DAC/SPI、三镜像与工程恢复，以及便携会话生命周期。

再通过同一冻结内核公开HTTP接口载入保存的原始DEMO1工程，直接运行、复位、工程导出恢复三轮均执行超过100万条指令，LED状态为亮、灭、亮、灭、亮、亮，诊断为空。全部自建进程、临时目录和独立配置已清理，验收用时111.241秒。证据为 `artifacts/v06-same-linux-wsl.json` 及 `artifacts/v06-frozen-linux-user-demo.json`。

## Packages与远端旧分发清理

Packages工作流 `44007852329` 的两个平台发布和清理job均成功。Windows/Linux两个OCI包均推送0.6.0及latest标签，随后按0.6.0回拉，将安装文件提取后逐项检查SHA-256通过。

首轮清理在公开更新源检查门槛退出，日志为 `artifacts/v06-packages-prune-attempt1.log`，该轮没有执行删除。相同源码重跑该job后，真实公开检查及远端清理全部通过。首轮仅记录通用错误，具体HTTP原因无法从该日志复核。

清理artifact为 `14295741222`，外层ZIP SHA-256为 `5052a17c5b3d4e84a54e2e164c6437120e8187fc825aabe08165067462b58f2e`。下载后已核对摘要、CRC及唯一文件名，归档报告为 `docs/releases/cleanup-v0.6.0.json`，其SHA-256为 `e9d282c9386070057d49ee9f3e8548c093e52c43b97c74d3a8cbea7d9501027f`。报告 `executed=true`、`verified=true`，删除0.5.1的五个软件附件、一份摘要清单及两个旧Packages版本，合计8项。旧版源码、标签、公告及验证说明保留。

## 密集中断暂停的补充复核

标签自动触发的冗余CI `44007298699` 首轮Windows检查有一项 `pause_ms < 2000` 墙钟断言失败，其余定时器、看门狗和实际固件检查通过，原日志保留在 `artifacts/v06-tag-ci-windows-attempt1.log`。相同源码重跑后，两个源码检查及两个重复打包验收job全部成功。发行文件始终来自此前全部成功的选定CI `44003765945`。

随后保持原断言和每个子进程10秒时限，对同一密集SysTick、暂停、恢复和关闭场景连续复核30轮，30/30通过。暂停耗时最小2.379毫秒，中位32.717毫秒，最近秩P95为171.859毫秒，最大207.893毫秒。每轮至少执行1005条密集区间指令和233次ISR tick，最长单轮0.792秒，源码哈希前后一致。记录为 `artifacts/v06-dense-systick-pause-30.json` 和日志。首轮CI没有输出实际暂停时长或线程栈，其单次原因仍无法从该记录确定。

## 正式软件内更新发现的重启缺陷

实际已注册的0.5.1通过自己的更新HTTP API下载0.6.0安装器，完整接收85,675,415字节，SHA-256为 `48cb8cf1f4cfbac91e345dfe6f92669982d1a33201f50ed2cc1b5957241be664`，与选定CI一致。安装器退出码为0，实际软件文件已替换。随后的新冻结内核自动重启寻找旧PyInstaller临时目录中的 `python313.dll` 而失败，故本轮真实自动重启验收失败，报告为 `artifacts/v06-production-upgrade.json`。

干净Explorer进程重新启动同一0.6.0软件后，内核健康，用户当前DEMO2的 `e5990ebf…` 原HEX和12根连线已恢复运行。注册表初次读端仍见0.5.1及前日写入时间，与安装日志重新写键的记录存在作用域差异，原始只读证据保存在 `artifacts/v06-production-registry-audit.json`。

再次保存当前工程并正常关闭后，使用同一已核对SHA-256的官方0.6.0安装器从干净环境重装，退出码0，HKCU登记已为0.6.0，安装日期20261117，目录仍为 `D:\CIMC Studio`，证据为 `artifacts/v06-clean-reinstall-registration.json` 和对应日志。随后Explorer重新启动并恢复同一DEMO2及12根连线，运行健康。初次注册表作用域差异的原因仍未证实，版本宏保持原实现。该次重装建立了后续0.6.1真实升级的健康基线。

后续0.6.1已通过真实旧冻结环境重启、正式0.6.0到0.6.1自动升级及工程恢复，9文件与选定CI一致，旧分发完成统一清理。最终结果见 [0.6.1验收](validation-v0.6.1.md)。

## 功能时钟范围

当前验证使用确定性功能时钟。FWDGT配置与重装载在下一IRC32K边沿提交，跨时钟域延迟属于功能模型选择。14个TIMER按各自类型支持通道和模式。普通WFI中断等待属于本版功能模型，WFE事件等待和深度休眠电源域会给出明确诊断。完整DMA控制器、RTC日历、实板电气与逐周期时序需要独立实现及验收。
