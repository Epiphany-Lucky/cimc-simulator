# Bootloader 与双应用验收固件

这组三个固件用于验证真实 Cortex-M4 取指、跨镜像跳转与向量表切换。它们是本项目新写的独立最小程序，不包含用户完整固件工程，不在线擦写 Flash，也不实现系统 ROM Bootloader。

| 产物前缀 | 源码 | Flash/向量表基址 | 初始 MSP | 成功串口输出 | GPIO 输出 |
|---|---|---|---|---|---|
| `bootloader_probe` | `boot_probe.c` | `0x08000000` | `0x20010000` | `BOOT READY`、`SELECT 1 OR 2` | 无 |
| `app_a_probe` | `app_probe.c`，`APP_ID=1` | `0x08010000` | `0x20018000` | `APP A READY` | PD10 高，PD11…15 低 |
| `app_b_probe` | `app_probe.c`，`APP_ID=2` | `0x08020000` | `0x20020000` | `APP B READY` | PD11 高，PD10/12…15 低 |

每个前缀有独立 `.sct/.axf/.map/.hex/.bin`。三个链接区域各为 64 KiB，实际固件远小于该上限。GD32F470VET6 的内部 Flash 范围为 `0x08000000…0x0807FFFF`；主 SRAM 为 `0x20000000…0x2002FFFF`，另有不连续的 64 KiB TCM SRAM。所有 fixture 的栈位于主 SRAM，且按 8 字节对齐。

## 编译与产物证据

从项目根目录运行：

```powershell
powershell -NoProfile -File firmware\build-boot-probes.ps1
```

工具链位置可通过 `-KeilBin` 参数覆盖，默认使用 `D:\keil\Keil_V5\ARM\ARMCLANG\bin`。脚本要求真实 Keil `armclang/armlink/fromelf`，启用 `-Wall -Wextra -Werror`，检查每一步退出码和生成向量表。它不修改 `demo.c` 或现有 `build.ps1`。

`boot-probes-manifest.json` 记录本次编译器/链接器/导出工具的实际版本、构建时间、每个产物的地址/MSP/入口/长度，以及源码、scatter、HEX、BIN、AXF、MAP 和构建脚本的 SHA-256。HEX 自带绝对地址；装入 BIN 时必须填写表中的链接地址，不能将链接后的应用随意平移。

2026-11-16 本地实际编译结果：MDK Plus 5.40 / Arm Compiler for Embedded 6.22；Bootloader 612 字节，A/B 各 388 字节。HEX 与 BIN 解析得到的机器码及向量表逐一一致，构建摘要中全部文件哈希均已核对。反汇编可见 Bootloader 的 `CPSID/DSB/ISB/MSR MSP/BX` 和应用入口的 `MRS MSP`。

## 连接与操作

- 串口使用 V1 原板固定 CH340 → USART0（PA9/PA10、AF7）路径，不改原板线路。固件按复位 IRC16M 时钟设置 115200 baud，8N1，轮询收发。
- 查看 LED 时，在真实可连接端点添加 PD10→LED1、PD11→LED2（或沿用六条示例 LED 跳线）。LED 跳线是可删除外接线，不是原板固定网。
- 一起装入 Bootloader 和所需应用，选择 `0x08000000` 向量启动；收到 `BOOT READY` 后从 CH340 发送 ASCII `1` 或 `2`。Bootloader 输出 `JUMP APP A/B` 后执行目标应用。缺失或不合法的应用向量会输出 `APP MISSING OR INVALID`，并继续等待选择。
- 直接启动 B 时，选择 `0x08020000` 作为启动向量。此时应只收到 `APP B READY`，不出现 `BOOT READY`。
- 应用不实现返回 Bootloader 命令；通过仿真复位回到配置的启动向量，再选择应用。

Bootloader 验证目标栈和 Thumb 入口，关闭可屏蔽中断、停止 SysTick、清 `ICSR.PENDSTCLR`，写入 VTOR，执行 `DSB/ISB`，最后在无栈汇编尾跳中设置 MSP 并 `BX` 到应用复位入口。应用入口在 C 函数栈帧建立之前记录实际 MSP 和 VTOR；应用**不会自行补写 VTOR**，以便暴露 Bootloader 重定位错误。

Fixture 从复位后的特权 Thread/MSP 环境执行，不启用 PSP、FPU、RTOS 或外设 NVIC 中断。这里只清 SysTick pending，不以空操作伪造完整 NVIC 复位。应用启动自己的 SysTick，第 15 项向量必须指向当前应用的 `Tick_Handler`。计数证明中断路由与返回，不证明周期精度或板上运行。

## SRAM 邮箱契约

以下均为 32 位小端无符号整数，基址 `0x20000000`。固定邮箱不依赖 C 初始化数据/BSS 启动。

| 地址 | 含义 | 预期值 |
|---|---|---|
| `0x20000000` | Bootloader 已执行 | `0x424F4F54`；直接应用启动时为 0 |
| `0x20000004` | 最近选择 | 1 或 2 |
| `0x20000008` | 最近目标 | `0x08010000` 或 `0x08020000` |
| `0x2000000C` | 选择尝试次数 | 每次输入 1/2 递增 |
| `0x20000010` | 应用标识 | A=`0x41505041`，B=`0x41505042` |
| `0x20000014` | 应用入口精确 MSP | A=`0x20018000`，B=`0x20020000` |
| `0x20000018` | 应用入口读出的 VTOR | A=`0x08010000`，B=`0x08020000` |
| `0x2000001C` | 应用 SysTick 次数 | 持续递增 |
| `0x20000020` | 当前中断处理器标识 | A=`0x54494341`，B=`0x54494342` |
| `0x20000024` | 中断处理器读出的 VTOR | 与对应应用地址相同 |
| `0x20000028` | 应用初始化完成 | `0x52454144` |
| `0x2000002C` | 误执行 Bootloader SysTick | 正常为 0；错误路由写 `0xBAD0000F` |

## 验收范围

本次 fixture 初验使用既有单镜像装载器，将多个独立 BIN 按原链接地址在内存中合成为包含 FF 空洞的 Flash 图像，未修改固件机器码：

1. Bootloader+A，选择 1：A 的串口/MSP/VTOR/LED/SysTick 全部匹配。
2. Bootloader+A，选择 2：实际机器码报告缺失应用，留在 Bootloader，应用邮箱保持 0。
3. Bootloader+A+B，选择 1：执行 A，B 未被误选。
4. Bootloader+A+B，选择 2：执行 B，入口 MSP=`0x20020000`、VTOR=`0x08020000`。
5. 直接启动 B：无 Bootloader 串口，B 标识、LED 与 SysTick 匹配。

上述 5 项实际运行通过；它们验证 fixture 的机器码行为。新 `load_set` 接口、工程保存恢复、GUI、安装包另由对应回归验证，不能由这次初验替代。

架构依据：[Arm 核心寄存器语义](https://arm-software.github.io/CMSIS_6/main/Core/group__Core__Register__gr.html)、[Arm 向量表/VTOR](https://arm-software.github.io/CMSIS_6/main/Core/group__NVIC__gr.html)、[GigaDevice GD32F470 数据手册](https://www.gd32mcu.com/data/documents/datasheet/GD32F470xx%20Datasheet_Rev2.1.pdf)。
