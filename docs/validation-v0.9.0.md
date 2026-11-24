# CIMC Studio 0.9.0 SDIO 验收

验收探针以 ARM Compiler 5.06 update 7 编译，复用 081501 工程原有的 TF、SDIO、GD32 外设库和 FatFs 源码。探针从 0x08011000 启动，固件 SHA-256 为 22d2a7dbeb2cd0043603c10160c530ca587c43f083cee8fe4bcdde8d34746e8d。0.8.0 内核在两版板卡上均于读取 SDIO CLKCTL（0x40012C04）时报告外设未实现。0.9.0 运行同一份探针检查以下行为。

| 验收项 | V1 和 V2 的结果 |
| --- | --- |
| 初始化和 FAT32 挂载 | 真实 ARM 指令初始化 SDIO，协商 4 位总线，挂载 64 MiB 的 FAT32 镜像。 |
| 文件读写 | 读取预置二进制文件，创建 RESULT.BIN，关闭后重新打开并逐字节验证 777 字节。独立解码导出镜像，再次核对文件内容及两份 FAT 表。 |
| MCU 复位 | 镜像继续挂载，探针读取先前写入的文件。读回过程无数据写命令，导出镜像保持字节一致。 |
| 只读和无卡 | 只读挂载可发起读取，固件获得写入失败，镜像保持字节一致。未挂载时，固件报告 FAT32 挂载失败。 |
| 工作台 | Edge 验证原始二进制上传和导出、带中文及空格的镜像名、可写及只读状态、错误镜像拒绝、弹出和更换确认，以及 390 像素布局。 |

源码验收证据在 artifacts/.sdio/acceptance.json、artifacts/.sdio/sd-probe-build.json 和 artifacts/v090-sd-card-source-win-x64.json。真实 ARM 指令的验收覆盖独立 SDIO 探针。081501 整机固件还依赖其他外设，其整机启动和实板时序未纳入这次验证。

## 功能范围

控制器通过 SDIO FIFO 读写 512 字节扇区，模拟 V1、V2 原理图的固定接线和 PE2 卡检测。虚拟 SDSC 卡使用字节寻址。长度须可由 SDSC CSD 精确表示，最大 128 MiB。MCU 复位保留镜像和计数，未完成的写入扇区丢弃。工作台导出原始镜像，文件系统由固件处理。

当前覆盖 SDIO 1 位和 4 位轮询。SDHC、SDXC、SDIO DMA 和 SDIO 中断需要独立实现及验收。

官方在线分发与 SHA-256 清单见 [0.9.0 发行页](https://github.com/Epiphany-Lucky/cimc-simulator/releases/tag/v0.9.0)。

## 发行与安装验证

标签 v0.9.0 指向 6f766a843c871270a2dacc1f4a705252039d63d5。Windows 安装版、便携版、HTML 本地包、Ubuntu/Debian 安装版及 Linux 便携版均来自同一次构建。发行草稿和公开版的五个文件、SHA-256 清单与 CI 产物逐项核对通过。[构建 45399344258](https://github.com/Epiphany-Lucky/cimc-simulator/actions/runs/45399344258)

使用所选 Windows 包验证了原生 WPF/WebView2 启动、原有固件、重装和卸载。Windows 便携版和 HTML 本地包均通过 Edge 的 TF 卡操作及 V1、V2 的 64 MiB FAT32 读写。所选 Linux 便携包在 WSL 通过同样的 V1、V2 FAT32 实测及便携应用生命周期验证。证据分别见 artifacts/v090-ci-wpf-baseline.json、artifacts/v090-sd-firmware-http-ci-win-x64.json、artifacts/v090-sd-firmware-http-ci-html-local.json、artifacts/v090-sd-firmware-http-ci-linux-x64.json 和 artifacts/v090-same-linux-wsl.json。

同一 Windows 安装包的原生 WebView2 工作台通过 1 MiB 文件上传、64 MiB FAT32 挂载和 V1 原驱动读写。用实际固件生成 RESULT.BIN 后校验导出内容，随后验证了弹出的取消与确认。证据见 artifacts/v090-ci-wpf-sd.json。

本机正式安装的 0.8.1 从公开接口发现 0.9.0，下载 SHA-256 为 ea42f46fea1517eae236ca57b706065a3b6ea84ed53409f4833512a54a8805cb 的安装器，成功在原安装位置升级并重启。升级前的 14 个旧引擎进程均保留。升级后用已安装的冻结内核在独立端口再次通过两板 FAT32 验收。证据见 artifacts/v090-production-upgrade.json 和 artifacts/v090-sd-firmware-http-installed-win-x64.json。

Windows、Linux 的 GHCR Packages 发布并重新拉取校验通过。随后清理了 0.8.1 的 6 个旧发行附件、2 个旧 Packages 版本，以及本地 13 个旧分发目标和 2 个空缓存目录。源码标签、历史公告和验收证据保留。[Packages 验证](https://github.com/Epiphany-Lucky/cimc-simulator/actions/runs/45404965353) · [清理报告](releases/cleanup-v0.9.0.json)
