# CIMC Studio 0.8.0 串口 DMA 验收

## 原始固件

同一个 Keil ARM Compiler 5 的 DEMO4 HEX 用于新旧版对比。SHA-256 为 `c1924c74f0dd6d5f5decff70d376df2b70aa6e395badcf36695e7d1daa0bc0ee`。0.7.1 在 V1、V2 都停在 `0x08000A98`，报 `0x40026440` 读取未实现。

0.8.0 源码在两块板各通过 14 项真实固件串口验证。包括 63、64、65、127、128 字节、包含 `00` 和 `FF` 的满缓冲区、重挂后的重复接收、波特率和校验不匹配及恢复。V1 使用现有 H7 CH340 连接，V2 短接 H12.1–H12.3 与 H12.2–H12.4。CH340 由固件设置为 115200、8N1。

中断追踪观察到短帧和半缓冲区由 USART0 IRQ37 处理。满缓冲区的 NDTR 从 128 减为 0，DMA1 Channel 2 的 IRQ58 进入并处理完成，随后恢复 128 且通道重新使能。原始机代码实际读取 DMA 写入的 SRAM 并发送回显。

源码基线、串口逐字节对比和中断轨迹分别保存在 `artifacts/.dma-demo4/baseline.json`、`source.json` 和 `source-irq-trace.json`。DMA 回归另核对所有接收请求映射、W1C 标志、剩余计数、半字循环、时钟门控、复位和地址错误。

## 发布与安装证据

发布标签指向 `1cef9da88ff5072b277fa67d453f848f9827d045`。同一运行的 Windows、Linux 测试和打包四项任务通过。发行草稿用这次运行的五种分发文件创建，包体大小和 SHA-256 与 CI 逐项一致。 [选定 CI](https://github.com/Epiphany-Lucky/cimc-simulator/actions/runs/45371113672) · [0.8.0 发行页](https://github.com/Epiphany-Lucky/cimc-simulator/releases/tag/v0.8.0)

| 运行环境 | 验证 |
| --- | --- |
| Windows 便携版、HTML 本地包 | 各用原版 DEMO4 执行 V1/V2 共 28 项串口测试。Edge 页面触发发送，终端按字节显示实际回显。 |
| 本机 Windows 原生桌面 | 独立 AppId 安装、重装、卸载，WPF/WebView2 正常启动。隔离更新安装后自动打开同一路径的 0.8.0，验收工程文件保留。 |
| 同一 Linux 发布包 | WSL 用原版 DEMO4 在 V1/V2 共通过 28 项串口测试，并完成便携版生命周期及原有固件回归。CI 另覆盖了 Ubuntu 22.04 和 Debian 12 的安装、运行与卸载。 |
| PROJECT1 | 同一 Windows/Linux 发布包运行原始固件，V1 的 180 MHz 时钟及对应 LED 状态正常。 |

本机原生验收采用包含测试稳定性修订的 `7fc3c2f`，与选定发布提交仅有 `tests/test_self_update.py` 变更。该测试将仅依赖请求头的无效来源请求与使用请求体的无效令牌请求分开，避免 Windows 在关闭含未读取数据的连接时掩盖 403 结果。另一轮 Windows 打包复跑在暂停响应测试超时，发布使用上述四项均通过的完整运行。

正式安装包 SHA-256 为 `e9dea0eaaf3ebf14aa476dbfe23c7f93d6775bc13ad062bae3327258061b2d02`。旧安装目录仍有 14 个打开的引擎进程，正式 0.8.0 安装到 `D:\CIMC Studio 0.8.0`，Windows 注册项和训练目录的 CIMC Studio 快捷方式指向该版本。安装进程保留了 14 个旧进程，实际安装版在 V1、V2 各通过 14 项 DEMO4 测试。检查记录位于 `artifacts/v080-production-upgrade.json` 和 `artifacts/.dma-demo4/installed-v080.json`。

独立启动的已安装 0.7.1 冻结引擎通过真实在线接口发现 0.8.0，下载并校验了与上述摘要相同的官方 Windows 安装包。0.8.0 的冻结引擎检查后报告已是最新版。实际旧客户端下载、隔离更新重启与本机正式并行安装的记录分别见 `artifacts/v080-frozen-public-update-check.json`、`artifacts/update-restart-smoke-b40149332c45/result.json` 和前述本机安装记录。

两个 GHCR Packages 发布并回拉核对后，删除了 0.7.1 的 6 个旧发行附件与 2 个旧 Packages 版本。本地按预览清单删除 6 个标准目标、6 个摘要匹配的补充分发文件和 2 个空缓存目录。旧安装目录用于仍在运行的会话。 [Packages 验证](https://github.com/Epiphany-Lucky/cimc-simulator/actions/runs/45374644809) · [远端清理记录](releases/cleanup-v0.8.0.json)
