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
