# V0.4 多固件与 Bootloader 验收

日期：2026-11-16。本记录区分真实编译固件、源码内核、界面、冻结安装包和在线发布证据。**当前是待补齐的验收记录；未在下文记录的 0.4 安装包、CI 或发布结果不得视为通过。** V0.3 的既有报告不能替代本版安装验收。

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

实际结果：**17 项通过，0 失败，0 跳过，退出码 0**。这是本文建立时的专项结果；最终分支完整回归数量、提交号及 CI 结果仍需在后续表中补齐。

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

## 待补齐：最终界面、安装与发布证据

以下为验收项，不是已完成声明。由主发布流程填入实际命令、报告路径、提交号、摘要和运行链接；未通过的项目保留失败原因。

| 验收项 | 当前证据状态 | 完成时需要记录 |
|---|---|---|
| 最终 Windows/Linux 全量源码回归 | Windows已通过，Linux待CI | `python -m unittest discover -s tests -v`：106项，96通过、10项Linux专属跳过；包括清理流程14项与HTTP边界8项 |
| 多固件对话框和工作台 | Windows源码服务已通过 | `multifirmware_ui_smoke.py`、`ui_smoke.py`、`laptop_smoke.py`、`schematic_smoke.py`；3BIN/8镜像、真实串口选A/B、错误草稿/取消/启动选择、v3工程往返、超过6MiB实际请求；1024×600与390px截图在artifacts/multifirmware-*.png；无JS异常 |
| Windows/HTML 冻结包 | 待补 | 构建命令；安装后及便携包真实多镜像/MSP/VTOR/SysTick结果；文件摘要 |
| Windows 安装/覆盖/卸载 | 待补 | 隔离 TestAppId、原生 WPF、用户文件保留、报告路径 |
| Ubuntu 22.04 安装与冻结包 | 待补 | apt 安装、真实多固件、浏览器、生命周期、卸载、CI链接 |
| Debian 12 安装与运行 | 待补 | 同一 DEB 安装、真实固件、生命周期、卸载 |
| WSL 同一 Linux 发行包 | 待补 | 包 SHA-256、实际多固件执行与退出结果 |
| GitHub CI 与 Release | 待补 | 最终提交/标签/工作流；发布文件与 SHA256SUMS；匿名下载核对 |
| GHCR Packages | 待补 | Windows/Linux推送及回拉摘要匹配；可见性实际状态（当前仍私有） |
| 在线更新识别 | 待补 | 公开更新源返回0.4.0、旧客户端可识别及下载链接验证 |
| 旧版分发文件清理 | 待补，必须最后执行 | 已枚举目标及删除结果；确认源码/标签/Release公告/验证报告保留 |

## 容量、证据与运行边界

- GD32F470VET6 内部 Flash 为 512 KiB；容量按实际写入地址计算。每个原始文件最多 4 MiB，集合可移植导出 JSON 最多 8 MiB，HTTP 请求最多 16 MiB；无固定镜像数量上限。
- “烧录”是向仿真 Flash 共同装载文件；尚未实现 FMC 在线擦写、完整 IAP/OTA、系统 ROM Bootloader 或选项字节。
- v3 工程保存镜像和设置，重新导入时复位；不是 CPU/RAM/SPI Flash 运行现场快照。
- fixture 使用特权 Thread/MSP、轮询 USART0 和基础 SysTick，不代表外设 NVIC 中断、DMA、PSP/RTOS 或任意 Keil 工程已兼容。
- 内核功能模型和机器码验收不是逐周期、电气或实板验证。原板固定网络保持只读；LED/KEY 只能通过真实端点加跳线。
- GitHub 仓库及 Releases 公开不等于 GHCR Packages 公开；当前两份包仍为私有，最终可见性须按实际检查更新。
- 只有新版本安装、发布、摘要、Packages 回拉及在线更新检查全部完成后才清理旧版分发附件。保留源码/提交/标签、Release 公告、验证报告，不删除用户安装或导出文件。
