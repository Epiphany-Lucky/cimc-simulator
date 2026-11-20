# CIMC Studio 0.7.1 验收记录

## PROJECT1 停机与修复范围

用户报告 V1 小灯全灭并指出 PC `0x08000E50`。原版 0.7.0 正式会话确认正在使用 `MDK-ARM/build/PROJECT0/PROJECT0.hex`，SHA-256 为 `1a12c1d631a3327cbb6091570bfb8ba950f855ea1e002100f80adaa1ca95dcec`。六条跳线为 PD8～PD13 到 LED1～LED6。

ARMCC 反汇编显示，`0x08000E48` 调用 `HAL_PWREx_EnableOverDrive()`，`0x08000E4C` 检查返回值，失败后关中断并进入 `0x08000E50` 自循环。独立执行同一份 HEX，50,000 条指令时读取状态寄存器 `0x40007004` 为零，100,000 条时进入停机点，PD 模式、输出和任务数均为零。

GD32 PMU 高驱动使能及切换控制位与就绪状态对应。原实现仅为 V2 响应状态。0.7.1 复用该功能映射，让 V1 和 V2 都按实际控制位给出就绪状态。保留已有 PMU 控制寄存器、位带、时钟、GPIO 路径。依据为芯片手册和实际 HAL 实现。[GD32F4xx 用户手册](https://www.gd32mcu.com/data/documents/userManual/GD32F4xx_User_Manual_Rev2.7.pdf) · [STM32F427 RM0090](https://www.st.com/resource/en/reference_manual/rm0090-stm32f405-415-stm32f407-417-stm32f427-437-and-stm32f429-439-advanced-armbased-32bit-mcus-stmicroelectronics.pdf)

## 本机源码与真实固件

- 四个原位带用例和新增 PMU 就绪用例全部通过。新增用例核对两个板型的复位、使能、切换、清除及保留其他状态位。
- 同一份原 HEX 执行 1,000,000 条 ARM 指令后 HCLK 为 180 MHz，APB1 为 45 MHz，APB2 为 90 MHz。PWR 状态 `0x00030000`，GPIOD 输出 `0x3500`，LED1、LED3、LED5、LED6 点亮，诊断为空。原源码和 HEX 保留。
- 隔离复现的前态与修复后证据分别在 `artifacts/v071-before-project1-state.json`、`artifacts/v071-project1-source-positive.json`。用户固件与工程备份仅用于本机验收。

## Windows 本机验收

完整源码套件共 254 项，244 项通过，10 项 Linux 专用检查跳过。使用本机实际冻结包，在 Edge 导入原六线工程并点击运行，累计执行 64,192 条指令时读到 180 MHz 和正确的六灯状态。截图及记录见 `artifacts/v071-local-windows-project1.png` 与 `artifacts/v071-local-windows-project1.json`。

本机原生隔离安装、注册、固件运行、WPF 窗口、重装、卸载及用户文件保留均通过。执行记录在 `artifacts/installer-smoke-a97f93cb3609/result.json`。

## GitHub 构建

产品源码 `f18e70cabdc9e5a5d7a94df1e72ea648057bf74f`。选定 [CI 44696920571](https://github.com/Epiphany-Lucky/cimc-simulator/actions/runs/44696920571) 分别在 Windows 和 Ubuntu 执行 254 项源码检查，Windows 244 项通过及 10 项平台检查跳过，Ubuntu 254 项通过。

选定 Windows 安装器通过 CI 实际安装、固件运行、重装和卸载。所选 Windows 便携 ZIP 核对摘要与 CRC 后，使用原 PROJECT1 HEX 和六条接线在 Edge 实际运行。94,208 条指令时达到 180 MHz，LED1、LED3、LED5、LED6 亮，其余两盏熄灭。报告为 `artifacts/v071-frozen-windows-project1.json`。

Ubuntu 22.04 安装版通过完整 Chromium 工作台测试，Ubuntu 与 Debian 12 均通过安装、固件运行、生命周期与卸载。选定的同一个 Linux tar 在本机 Ubuntu WSL 上执行原 PROJECT1、完整固件和便携生命周期，三项均通过，耗时 124.690 秒。原 PROJECT1 执行 64,736 条指令时读到 180 MHz 及相同的六灯状态。记录为 `artifacts/v071-same-linux-wsl.json`、`artifacts/v071-frozen-linux-project1.json`。

## 公开发布、本机更新与清理

`v0.7.1` 注释标签解引用到产品提交。草稿由 CI `44700111675` 从选定的 Windows 和 Linux 产物装配。五个分发文件、校验清单与 CI 说明在发布时保留原编号和摘要。[公开发行](https://github.com/Epiphany-Lucky/cimc-simulator/releases/tag/v0.7.1)

本机 0.7.0 应用内查询遇到 GitHub 匿名限流。使用与公开安装包 SHA-256 一致的官方安装器，在原位置 `D:\CIMC Studio` 就地升级，退出码 0，Windows 与应用内核均确认 0.7.1。10 个安装文件与选定 Windows ZIP 逐项摘要相同。重开后恢复原 PROJECT1 的 HEX 和 6 条接线，127,792 条指令时仍在 180 MHz 正常运行，LED1、LED3、LED5、LED6 亮。记录见 `artifacts/v071-production-upgrade.json`，限流前态单独保留在 `artifacts/v071-in-app-attempt-rate-limited.json`。

GitHub 托管的 Packages 工作流 `44700695231` 通过公开更新接口检查，并发布及回拉校验两个平台的 Packages。另使用正式发行元数据验证 0.7.0 识别新版、0.7.1 判断已最新，并匿名下载并核对五文件 SHA 清单。本机自动下载和重启因匿名限流改用上述安装流程。证据为 `artifacts/v071-public-metadata-check.json`。

远端清理 6 项旧分发附件及 2 项旧 Packages 版本。使用同版远端证明并核对实际安装恢复后，本地删除 11 项标准目标、23 个补充文件、6 个旧便携目录和 6 个空缓存目录。源项目、验收报告和识别出的旧测试缓存保留。依据为 `docs/releases/cleanup-v0.7.1.json` 与本机三份执行结果。
