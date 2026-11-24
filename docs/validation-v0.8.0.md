# CIMC Studio 0.8.0 串口 DMA 验收

## 原始固件

同一个 Keil ARM Compiler 5 的 DEMO4 HEX 用于新旧版对比。SHA-256 为 `c1924c74f0dd6d5f5decff70d376df2b70aa6e395badcf36695e7d1daa0bc0ee`。0.7.1 在 V1、V2 都停在 `0x08000A98`，报 `0x40026440` 读取未实现。

0.8.0 源码在两块板各通过 14 项真实固件串口验证。包括 63、64、65、127、128 字节、包含 `00` 和 `FF` 的满缓冲区、重挂后的重复接收、波特率和校验不匹配及恢复。V1 使用现有 H7 CH340 连接，V2 短接 H12.1–H12.3 与 H12.2–H12.4。CH340 由固件设置为 115200、8N1。

中断追踪观察到短帧和半缓冲区由 USART0 IRQ37 处理。满缓冲区的 NDTR 从 128 减为 0，DMA1 Channel 2 的 IRQ58 进入并处理完成，随后恢复 128 且通道重新使能。原始机代码实际读取 DMA 写入的 SRAM 并发送回显。

源码基线、串口逐字节对比和中断轨迹分别保存在 `artifacts/.dma-demo4/baseline.json`、`source.json` 和 `source-irq-trace.json`。DMA 回归另核对所有接收请求映射、W1C 标志、剩余计数、半字循环、时钟门控、复位和地址错误。

## 发布与安装证据

发行与分发可用性以 [0.8.0 发行页](https://github.com/Epiphany-Lucky/cimc-simulator/releases/tag/v0.8.0) 为准。
