# V1.0 硬件连接证据

2026-11-15，用户将第一版目标改为 **V1.0**。V2.0 的照片和早期调查只作历史资料，不参与当前默认网络模型。

## 原始资料

- 原理图：[GD32F470 Development Kit V1.0](reference/GD32F470-V1.0-schematic.pdf)，4 页；标题栏 CoreBoard / CIMC-IHD-Project / CIMC-IHD-v04，作者 Lingyu Meng，版本 V1.0，更新至 2025-03-22。
- 来源：用户本地 `D:\desktop\CIMC2026\CIMC_V1\GD32F470 Development Kit V1.0 原理图.pdf`，原文件保持不变。
- SHA-256：`74C365AEA16DDB43FC74B3F3B43707DB5C079B9C07A3F8674321DF9F1597E6ED`。
- 已逐页提取文本并查看原始图面；脚号以图面为准，不以 PDF 的文本抽取顺序决定。
- 目前没有确认与这份 V1.0 图完全一致的实物照片。工作台使用自行绘制的**原理图接线视图**，没有以 V2 或 V1.3 照片冒充 V1.0，也不声称图中的坐标是 PCB 实物坐标。

## 已核对的连接

| 对象 | V1.0 原图连接 | 证据 |
|---|---|---|
| MCU | U1 GD32F470VET6 | 第 1 页 |
| GPIO 排针 | U2、U3，各 2×20；109 个当前可见端点的详细脚号写入 board-v1.json | 第 1 页 Pin Out |
| LED | **H2**，1→LED6、2→LED5、…、6→LED1；每路 2 kΩ 串联电阻，LED 阴极接 DGND，高电平点亮 | 第 2 页 LED |
| KEY | H3，1→FUN_KEY6、…、6→FUN_KEY1；每路 10 kΩ 上拉，按下接 DGND，低有效 | 第 2 页 KEY |
| OLED | PB8→OLED_CLK→OLED1.3；PB9→OLED_DAT→OLED1.4；OLED1.1=DGND、.2=3V3 | 第 1、2 页 |
| USB/CH340C | USART0 PA9 TX、PA10 RX；H7 1=USB_RX、2=USB_TX、3=USART0_TX、4=USART0_RX | 第 1、4 页 |
| RS485 | USART1 PA2 TX、PA3 RX；PA1→485_CS→MAX3485 的 DE/RE#；H6 1=485_RX、2=485_TX、3=USART1_TX、4=USART1_RX | 第 1、4 页 |
| RS232 | SP3232；H6 5=232_RX、6=232_TX，与 RS485 共用 H6 中间的 USART1 TX/RX | 第 4 页 |
| TTL 调试口 | CN1.1=DGND、.2=USART2_TX(PB10)、.3=USART2_RX(PB11) | 第 1、4 页 |

原图的 `485_RX` 接收发器 DI，`485_TX` 接 RO。模型保留原图网络名称，并按照真实信号方向连接；不会因网络名称看似相反而自行换线。

## 排针规则

原板铜线、器件接线和固定网络只读。LED/KEY 排针没有默认接到某个 GPIO。所有用户新增导线保存到工程的 `wires`；删除操作只删除这些导线。

H6/H7 是真实跳帽排针，原图没有把相邻端点画成短接，因此它们也使用可见的新增跳线表示。空白工程不擅自假定跳帽已插上。示例明确加载 16 条新增跳线：6 条 LED、6 条 KEY、2 条 H7、2 条 H6。

| 用途 | 新增跳线 |
|---|---|
| 示例 LED1–6 | PD10–PD15 → H2 的 LED1–6 |
| 示例 KEY1–6 | PE7–PE12 → H3 的 KEY1–6 |
| CH340 | H7.1↔H7.3；H7.2↔H7.4 |
| RS485 | H6.1↔H6.3；H6.2↔H6.4 |
| RS232 | 删除上述两条 H6 跳线，再连接 H6.3↔H6.5、H6.4↔H6.6 |

串口终端的页签只选择查看/发送通道，**不会替用户重接 H6**。USART 模式、复用和跳线未接通时，不生成成功的固件回复。RS485 还检查 PA1 方向。

## 证据边界

- 原图连接核对不等于所有硬件都已仿真。`verified:false` 保留为整板完整仿真尚未完成的标志；已核对端点各自标为 `verified:true`。
- 128×32 OLED、0x3C 地址和 SSD1306 兼容命令子集还依据本地 OLED 驱动。未实现整个显示控制器的全部命令。
- 512 KiB Flash、192 KiB 主 SRAM、64 KiB TCM 分段映射；TCM 不可取指。未模拟外部晶振的真实时间、模拟电压、电流和电容暂态。
- SD、SPI Flash、ADC、SWD、BOOT 等原固定信号关系保留，当前没有实现相关完整外设。没有移走或重新分配这些引脚。
- GPIO 电平为数字功能模型；强驱动冲突会停止仿真并报告。悬空输入报告警告，采用确定性 0，不能据此判断真实硬件输入电平。

`scripts/generate-board-v1.py` 是可审查的连接表生成脚本，输出 `web/board-v1.json` 和原创矢量接线图。
