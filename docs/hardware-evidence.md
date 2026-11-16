# V1.0 硬件连接证据

2026-11-15，用户将第一版目标改为 **V1.0**。V2.0 的照片和早期调查只作历史资料，不参与当前默认网络模型。

## 原始资料

- 原理图：[GD32F470 Development Kit V1.0](reference/GD32F470-V1.0-schematic.pdf)，4 页；标题栏 CoreBoard / CIMC-IHD-Project / CIMC-IHD-v04，作者 Lingyu Meng，版本 V1.0，更新至 2025-03-22。
- 来源：用户本地 `D:\desktop\CIMC2026\CIMC_V1\GD32F470 Development Kit V1.0 原理图.pdf`，原文件保持不变。
- SHA-256：`74C365AEA16DDB43FC74B3F3B43707DB5C079B9C07A3F8674321DF9F1597E6ED`。
- 左侧“原理图”入口的 PDF 位于 `web/assets/schematics/GD32F470-V1.0-schematic.pdf`，与上述原件 SHA-256 相同。四张只读预览由 Poppler 命令 `pdftoppm -scale-to 3200 -png docs/reference/GD32F470-V1.0-schematic.pdf web/assets/schematics/v1-page` 生成，均为 3200×2257；已查看四页完整图面，没有修改原图网络或重绘资料。
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
| ADC 电位器 | PC0→ADC→VR1 滑动端；VR1=10 kΩ，两端分别接 3V3、DGND | 第 1 页 MCU、第 2 页 ADC |
| SPI Flash | U4 GD25Q40E；PB12→FLASH_CS→CS#，PB13→SPI_SCK→CLK，PB14→SPI_MISO→SO，PB15→SPI_MOSI→SI；CS# 经 R8 10 kΩ 上拉，WP#/HOLD# 接 3V3 | 第 1 页 MCU、第 2 页 FLASH |

原图的 `485_RX` 接收发器 DI，`485_TX` 接 RO。模型保留原图网络名称，并按照真实信号方向连接；不会因网络名称看似相反而自行换线。

## 排针规则

原板铜线、器件接线和固定网络只读。LED/KEY 排针没有默认接到某个 GPIO。所有用户新增导线保存到工程的 `wires`；删除操作只删除这些导线。

H6/H7 是真实跳帽排针，原图没有把相邻端点画成铜线短接。V0.2 按用户确认的产品规则，将 H7 接通及 H6 串口模式所需跳帽作为**系统管理连接**显示，不能任意改接；这些连接不冒充原板铜线。示例加载 12 条用户跳线：6 条 LED、6 条 KEY。H6 默认 RS485，可通过 RS232/RS485 模式开关切换。

| 用途 | 连接及管理方式 |
|---|---|
| 示例 LED1–6 | PD10–PD15 → H2 的 LED1–6 |
| 示例 KEY1–6 | PE7–PE12 → H3 的 KEY1–6 |
| CH340 | 系统管理 H7.1↔H7.3；H7.2↔H7.4 |
| RS485 | 模式开关管理 H6.1↔H6.3；H6.2↔H6.4 |
| RS232 | 模式开关管理 H6.3↔H6.5；H6.4↔H6.6，与 RS485 接法互斥 |

串口终端页签选择查看/发送通道；独立模式开关负责 H6 的上述接法。USART 模式、复用或实际所选通道不符时，不生成成功的固件回复。RS485 还检查 PA1 方向。OLED、ADC、SPI、串口等固定网络的专用引脚不能作为用户跳线端点，LED/KEY 仍通过允许的空闲 GPIO 排针手动连接。

## ADC 与 SPI Flash 的器件依据

- [GD32F470xx Datasheet Rev1.3](https://gd32mcu.com/data/documents/datasheet/GD32F470xx_Datasheet_Rev1.3.pdf)：PC0 的附加模拟功能为 ADC012_IN10。原图固定 PC0 后，ADC0/ADC1/ADC2 的通道 10 均对应此物理输入。
- [GD32F4xx User Manual Rev3.4](https://www.gd32mcu.com/data/documents/userManual/GD32F4xx_User_Manual_Rev3.4.pdf)：印刷页 293 为 ADC 状态和 EOC/ROVF 语义，294–297 为控制与分辨率，302 为 RDATA 对齐。V0.2 使用这些寄存器语义，旋钮只改变输入电压，固件转换后才更新采样结果。
- [GD32F470xx Datasheet Rev1.7](https://www.gd32mcu.com/data/documents/datasheet/GD32F470xx_Datasheet_Rev1.7.pdf)：印刷页 54（PDF 第 55 页）Port B 复用表，经原始表格图面核对，PB13/PB14/PB15 的 SPI1_SCK/MISO/MOSI 均为 AF5。PB12 在本模型中使用 GPIO 输出控制片选。
- [GD32F4xx User Manual Rev3.3](https://www.gd32mcu.com/data/documents/userManual/GD32F4xx_User_Manual_Rev3.3.pdf) 第 21 章 SPI，结合本地官方标准外设库 `gd32f4xx_spi.h`、`gd32f4xx_rcu.h`：SPI1 基址 `0x40003800`；CTL0/CTL1/STAT/DATA 偏移为 `0x00/0x04/0x08/0x0C`；RCU_APB1EN/SPI1RST 位均为 bit 14。SPI 控制器复位不改变 GPIO 片选线，MCU 复位后片选由板上上拉回到未选中状态。
- [GD25Q40E/20E Datasheet Rev1.1](https://download.gigadevice.com/Datasheet/DS-00538-GD25Q40E-Rev1.1.pdf)：第 18 页确认 GD25Q40E 的 JEDEC 为 `C8 40 13`，90H/ABH 设备 ID 为 `12`；第 19 页 WEL/WIP；第 21 页普通/快速读；第 26–30 页页编程及擦除。GD25Q40E 容量 4 Mbit（512 KiB），页 256 B，扇区 4 KiB。页编程越过页尾会回绕到同页，超过 256 B 的输入以最后一次页缓冲值为准；存储单元编程只允许 1→0，恢复为 1 必须擦除。

### V0.2 实现范围

ADC 支持软件触发、单次单通道轮询、12/10/8/6 位分辨率、左/右对齐、EOC 清除与 EOCM 溢出语义，以及功能级即时校准。模型检查 ADC/GPIOC 时钟和 PC0 模拟模式。连续、扫描、插入转换、看门狗、DMA、中断、外部触发、过采样、多 ADC 同步尚未实现，会明确诊断；没有噪声、采样电容、转换延迟或真实校准误差模型。

SPI1 支持主机、软件 NSS、8 位、MSB 优先、全双工、mode 0/3 轮询收发，检查 GPIOB/SPI1 时钟、PB13–15 AF5 与片选条件。GD25Q40E 支持 `06/04` 写使能/禁止、`05/35` 状态读取、`03/0B` 读/快速读、`9F/90/AB` 标识及唤醒、`02` 页编程、`20/52/D8/C7/60` 扇区/块/整片擦除、`B9` 深掉电、`66/99` 软件复位。保留接收标志、溢出清除顺序、WEL、忙时忽略命令、CS 上升沿提交、页回绕和 NOR 编程语义。

SPI 字节传输是原子的功能模型。Flash 忙时间按仿真执行指令数推进：页编程 256、扇区擦除 2048、块擦除 4096、整片擦除 8192 条指令；这些确定性延迟用于验证轮询流程，**不是器件数据手册中的耗时或性能测量**。暂停仿真时不推进。Flash 内容和未完成的内部操作跨 MCU 复位保留，保存在当前内核会话内，关闭内核后不自动保存。Flash 软件复位若打断忙操作，本功能模型丢弃待提交数据，不模拟真实器件可能发生的部分编程/擦除结果。

未实现 SPI DMA、中断、CRC、I2S、16 位帧、Dual/Quad、状态/保护寄存器写入、SFDP、安全寄存器及挂起/恢复，相关访问明确诊断。`firmware/spiflash_probe.hex` 和 `.bin` 为 Keil 编译的真实 MCU 测试固件，通过 SPI 读取 ID、编程及回读并擦除；这些验证不等于任意现有固件或完整器件功能均受支持。

## 证据边界

- 原图连接核对不等于所有硬件都已仿真。`verified:false` 保留为整板完整仿真尚未完成的标志；已核对端点各自标为 `verified:true`。
- 128×32 OLED、0x3C 地址和 SSD1306 兼容命令子集还依据本地 OLED 驱动。未实现整个显示控制器的全部命令。
- MCU 内部 512 KiB Flash、192 KiB 主 SRAM、64 KiB TCM 分段映射；TCM 不可取指。外部 GD25Q40E 另外提供 512 KiB SPI 存储。未模拟外部晶振的真实时间、电流和电容暂态；ADC 电压使用理想量化模型。
- SD、SWD、BOOT 等原固定信号关系保留，当前未实现完整相关外设；ADC、SPI Flash 已有上述限定子集。没有移走或重新分配这些引脚。
- GPIO 电平为数字功能模型；强驱动冲突会停止仿真并报告。悬空输入报告警告，采用确定性 0，不能据此判断真实硬件输入电平。

`scripts/generate-board-v1.py` 是可审查的连接表生成脚本，输出 `web/board-v1.json` 和原创矢量接线图。

## 0.5 CIMC V2 驱动证据

用户于2026-11-16确认新增的27_0_BootLoader代码对应CIMC V2板卡。保留原有官方板照、排针标注和资料来源，按Driver/USART补入USART1 PD5/PD6 AF7及PE8方向控制，按OLED驱动补齐PB8/PB9。App LED驱动使用PE6，示例通过可删除的PE6→LED1跳线连接独立端子。其他LED/KEY继续沿用端子与用户跳线。

App Function.c使用PC0/PC1 ADC、PA4 DAC0、PA5/PA6/PA7 SPI0及PB10片选。PT100转换按该驱动公式和SPI配置字0x404B建立功能模型。该SPI接口对应GD30AD3344资料中的子集，未将I²C型号GD30AD3340写为SPI芯片。完整V2五页原理图已接入并核对，实板验证仍需独立完成。

firmware/v2-manifest.json记录3份用户实际BIN的来源、SHA-256和地址。模拟器执行这些BIN本身，串口帧、内部Flash编程、系统复位和App跳转由机器码产生。V2板卡每条指令推进240个SysTick输入tick，该设置为功能模拟时间约定。
