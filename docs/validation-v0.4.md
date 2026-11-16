# V0.4 多固件与 Bootloader 验收

日期：2026-11-16。本记录区分真实编译固件、源码内核、界面、冻结安装包和在线发布证据。**0.4.0已发布，安装、更新识别、Packages回拉与旧分发文件清理均完成。** 发布源码为`8221c1ff0fe2b6c5aee42b76fc9d62552092f90c`；后续验收记录提交只补充事实，不替换已测试版本标签或安装文件。

## 已完成：真实 Keil 验收固件

验证命令（项目根目录）：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File firmware\build-boot-probes.ps1
```

实际结果：退出码 0；MDK Plus 5.40 / Arm Compiler for Embedded 6.22，`armclang/armlink/fromelf` 全链路成功，`-Wall -Wextra -Werror` 通过。PowerShell 7 和 Windows PowerShell 5 两种执行环境均成功。

| 固件 | Flash 基址 | BIN 字节数 | 初始 MSP |
|---|---|---:|---|
| bootloader_probe | `0x08000000` | 612 | `0x20010000` |
| app_a_probe | `0x08010000` | 388 | `0x20018000` |
| app_b_probe | `0x08020000` | 388 | `0x20020000` |

每份 HEX/BIN 解析后的机器码与向量逐一一致，`boot-probes-manifest.json` 内源码、scatter、HEX、BIN、AXF、MAP 和构建脚本 SHA-256 均已独立重算一致。AXF 反汇编可见 Bootloader 的 `CPSID/DSB/ISB/MSR MSP/BX` 与应用入口的 `MRS MSP`，不是宿主替换 PC 或生成成功串口。

在新集合接口完成前，曾通过既有单镜像路径将三份独立 BIN 按原链接地址在内存中合成 FF 空洞图像，实际执行五种场景：两镜像选择 A、缺 B 拒跳、三镜像分别选择 A/B、直接 B 启动。串口、精确入口 MSP、VTOR、LED、SysTick 邮箱全部符合 [fixture 契约](../firmware/BOOT_PROBES.md)。这项初验只证明固件机器码可运行，不替代新接口和安装包验收。

## 已完成：多固件源码回归与独立审查

本次在当前 Windows 工作副本执行：

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -p test_multifirmware.py -v
```

实际结果：**17 项通过，0 失败，0 跳过，退出码 0**。这是本文建立时的专项结果；最终分支完整回归数量、提交号及 CI 结果见后续交付验收表。

该回归覆盖：

- 13 份非重叠文件共同装载，包含无需独立向量的数据镜像；不固定两个或三个槽位。
- 稀疏 HEX 空洞填充、完整 512 KiB 零地址别名一致、实际重叠拒绝。
- 向量与入口分属不同镜像、自定义向量偏移、启动索引、引用重排/移除及单文件入口替换。
- 坏 SP、偶数 Thumb 入口、入口第二字节未实际写入、越界、空集合、非法引用和原生分配失败的原子拒绝。
- 集合导出 JSON 8 MiB 限额覆盖单文件入口、集合入口、工程恢复和既有镜像引用增量。
- v3 完整固件/设置往返、损坏工程原子拒绝、v3 空集合清空、v1/v2 导入保留当前固件。
- ICSR SysTick pending 的写 1 置位/清除，写 0 无作用，清 pending 不误清 COUNTFLAG；未支持的 NMI/PendSV 请求明确诊断。
- 真实 HEX/BIN Bootloader 跳 A/B：入口 MSP、运行时 VTOR、应用 PC、串口、LED 和独立 SysTick 匹配；复位保留全部镜像；缺 B 拒跳后仍可选择 A；直接 B 启动无 Bootloader 输出。

独立只读审查同时检查了 `firmware_images.py` 的实际段/占用模型和 `simulator.py` 的预检、CPU 预分配、提交顺序；未发现本次多固件主链路阻断项。额外 inline Python 实测通过：

1. Flash 最后 128 字节对齐向量、最后两个字节中的 Thumb 自循环，以及主 SRAM 上界 `0x20030000` 作为初始栈。
2. ICSR 高字节写 1 置 pending、低字节写 0 不重放命令、高字节写 1 清 pending，COUNTFLAG 保持。
3. v3 工程含非 ASCII 非法 base64 时，CPU 对象、固件集合、状态、日志与诊断保持不变。

## SysTick 调度缺陷：修复与重复测量

用户截图中的问题已在0.3标签和本次修改前快照复现。每个负载使用独立进程、真实worker、初始化结束后测量2秒，交错顺序重复3次；真实`firmware/systick.hex`设置LOAD=999，ISR在SRAM递增计数。观测器只记录预算和时间，不改变调度。

| 负载 | 修复前计数/秒中位数 | 修复后计数/秒中位数 |
|---|---:|---:|
| SysTick真实中断 | 36,491 | 729,941 |
| 无中断NOP/branch对照 | 394,984 | 750,215 |
| 原有demo稳态 | 193,663 | 449,415 |

真实ISR平均频率由36.33次/秒增至751.64次/秒，LOAD=999下每次中断仍约对应1000条计数；未通过放大计数或伪造输出提速。修复前437次执行调用全部提前返回，仅消耗约5%预算；修复后异常进入/返回在同一预算内继续，并由hook每64条及异常边界检查宿主时间片。具体机器/Unicorn版本、每次试验、源码和固件哈希见[机器可读记录](benchmarks/systick-v0.4.json)。这些数值是本机实测，不是跨机器性能保证或硬件周期证明。

`tests/test_scheduler.py`独立12项通过：大块/小块/单步的完整CPU与SysTick状态一致；pending、PRIMASK、真实BX异常返回、栈恢复；故障和零进展停止；有/无中断的墙钟限制；密集中断暂停/恢复/关闭与临时时间片清理。未降低密集中断1000条/2秒的回归门槛。

新增冻结包交错三组相对吞吐回归，门槛为SysTick/无IRQ中位速率≥0.25。修改前的0.4冻结包已作为负对照实际失败（比值0.0743），因此该测试可识别旧问题。随后已重新构建最终引擎和安装包并完成下表验收，未用修复前安装结果替代。

## 最终交付验收表

以下均为本次实际执行结果。安装包来源、平台与图形界面证据分别列明；本地Windows构建与CI构建不声称字节相同，同包WSL校验则精确匹配发行tar。

| 验收项 | 当前证据状态 | 完成时需要记录 |
|---|---|---|
| 最终 Windows/Linux 全量源码回归 | 通过 | Windows118项，108通过、10项Linux专属跳过；Linux118项全部通过。最终源码`8221c1ff0fe2b6c5aee42b76fc9d62552092f90c`；[CI 43804681787](https://github.com/Epiphany-Lucky/cimc-simulator/actions/runs/43804681787)全部4个job成功 |
| 多固件对话框和工作台 | Windows源码服务已通过 | `multifirmware_ui_smoke.py`、`ui_smoke.py`、`laptop_smoke.py`、`schematic_smoke.py`；3BIN/8镜像、真实串口选A/B、错误草稿/取消/启动选择、v3工程往返、超过6MiB实际请求；1024×600与390px截图在artifacts/multifirmware-*.png；无JS异常 |
| Windows/HTML 冻结包 | 通过 | 重新构建真实新引擎；HTML多固件UI、所有外设及Bootloader HEX/BIN回归通过。SysTick/无IRQ吞吐比：HTML0.98861、实际安装后0.93300；日志artifacts/v04-final-html-package-smoke.log及v04-final-html-ui-smoke.log |
| Windows 安装/覆盖/卸载 | 通过 | 独立TestAppId `db5f3c6abc27`；原生WPF120DPI位于工作区，OLED/JEDEC/ADC/原图、关闭自有内核、重装与卸载保留用户文件均通过；artifacts/installer-smoke-db5f3c6abc27/result.json。云端另通过同提交安装/运行/升级/卸载（不冒称云端原生桌面验收） |
| Ubuntu 22.04 安装与冻结包 | 通过 | 最终CI同包apt安装、真实固件、全部Chromium工作台用例及退出、生命周期、卸载通过；SysTick比值1.00006 |
| Debian 12 安装与运行 | 通过 | 最终CI同DEB在Debian12容器安装、真实固件、生命周期、卸载通过；SysTick比值0.99999；Debian容器未做图形浏览器验收 |
| WSL 同一 Linux 发行包 | 通过 | artifact14198031656的API摘要核对一致，Linux tar SHA256为`440e9fcfad0cdf2d32bed76f4a2b9c69c62da9b3ac8c47444e0fcd1ed5cd9355`；WSL Ubuntu26.04运行同tar真实固件与便携生命周期通过，SysTick比值0.99824；artifacts/v04-final-linux-verification.json |
| GitHub CI 与 Release | 通过，已发布 | `v0.4.0`指向最终CI提交；[发行组装43805352121](https://github.com/Epiphany-Lucky/cimc-simulator/actions/runs/43805352121)核对CI与tag并附五包、SHA256SUMS及独立验收记录；[公开Release](https://github.com/Epiphany-Lucky/cimc-simulator/releases/tag/v0.4.0) |
| GHCR Packages | 通过 | [发布和清理43805602944](https://github.com/Epiphany-Lucky/cimc-simulator/actions/runs/43805602944)两平台push/pull、逐文件对原始Release摘要检查通过；保留0.4.0/latest。包当前仍私有，公开下载用Release |
| 在线更新识别 | 通过 | 实际冻结0.3.0客户端返回latestVersion=0.4.0/available=true；0.4.0返回available=false；Windows安装器、DEB、Linux tar、HTML四个匿名下载入口均HTTP200。artifacts/v04-public-update-check.json |
| 旧版分发文件清理 | 已完成，最后执行 | 0.1/0.2旧安装ZIP及清单已删除；自动流程删除0.3五包+清单及两个旧GHCR版本；本地18个旧分发文件/目录随后删除。Git标签、公告及0.3验收附件保留；[清理记录](releases/cleanup-v0.4.0.json) |

## 容量、证据与运行边界

- GD32F470VET6 内部 Flash 为 512 KiB；容量按实际写入地址计算。每个原始文件最多 4 MiB，集合可移植导出 JSON 最多 8 MiB，HTTP 请求最多 16 MiB；无固定镜像数量上限。
- “烧录”是向仿真 Flash 共同装载文件；尚未实现 FMC 在线擦写、完整 IAP/OTA、系统 ROM Bootloader 或选项字节。
- v3 工程保存镜像和设置，重新导入时复位；不是 CPU/RAM/SPI Flash 运行现场快照。
- fixture 使用特权 Thread/MSP、轮询 USART0 和基础 SysTick，不代表外设 NVIC 中断、DMA、PSP/RTOS 或任意 Keil 工程已兼容。
- 内核功能模型和机器码验收不是逐周期、电气或实板验证。原板固定网络保持只读；LED/KEY 只能通过真实端点加跳线。
- GitHub 仓库及 Releases 公开不等于 GHCR Packages 公开；当前两份包仍为私有，最终可见性须按实际检查更新。
- 只有新版本安装、发布、摘要、Packages 回拉及在线更新检查全部完成后才清理旧版分发附件。保留源码/提交/标签、Release 公告、验证报告，不删除用户安装或导出文件。
