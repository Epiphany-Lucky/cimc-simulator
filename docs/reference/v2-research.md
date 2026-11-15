# CIMC V2.0 硬件证据与模型边界

核验日期：2026-11-15。此文件对应 `web/board-v2.json`。当前状态为**局部核验**，不是完整 V2.0 电气数字孪生验收。

## 已获得的直接证据

1. 2026 官方《初赛 硬件设计题目说明》物理第 1 页右侧 V2.0 实拍图，原始提取文件为 `D:/desktop/网页开发/CIMC2026-research/images/official-hardware-photo-2.jpeg`。软件中的 `web/assets/board-v2.jpg` 是该文件的原样复制，保留官方图中的供电标注红框，不重画底板。
2. [官方商城](https://www.siemenscup-cimc.org.cn/store/index)的 [GD32F470VET6 v2.0 产品海报原图](http://www.siemenscup-cimc.org.cn/Public/ProductMainImage/2026/3/be67f84eaed54436a777dc151bf169ba.png)。原图 3200×3200，板卡排针丝印可放大阅读。
3. 本机存在用户 2026 固件：`D:/desktop/CIMC2026/2026343469/2026343469-code/APP/Driver/`。代码证明该工程的配置，但其路径没有明确声明所用底板版本，不能独立证明 V2.0 铜线。
4. 本机存在完整 **V1.0** 原理图：`D:/desktop/CIMC2026/CIMC_V1/GD32F470 Development Kit V1.0 原理图.pdf`，4 页，图签创建 2025-03-01、更新至 2025-03-22，图名 `CIMC-IHD-v04`。已经查看图页。仅历史对照，**禁止作为 V2.0 原理图使用**。

官方公开赛项资料页：[工业嵌入式系统开发](https://www.siemenscup-cimc.org.cn/Project/PorjectResourceDetail?id=18)。本轮仍未取得完整 V2.0 原理图。

## V2.0 实拍可确认的端点

板卡左侧 MCU 排针为 U3，右侧为 U2。下表以正面照片的“自上向下、每行左/右”表示，**不冒充厂商连接器针号**。JSON 的 `rowFromTop`、`column` 采用同一约定。

| 行 | U3 左/右 | U2 左/右 |
|---|---|---|
| 1 | PB12 / PB13 | 3V3 / DGND |
| 2 | PB14 / PB15 | 3V3 / DGND |
| 3 | PD8 / PD9 | 3V3 / DGND |
| 4 | PD10 / PD11 | NC / NC |
| 5 | PD12 / PD13 | NC / PB11 |
| 6 | PD14 / PD15 | PB10 / PE15 |
| 7 | PC6 / PC7 | PE14 / PE13 |
| 8 | PC8 / PC9 | PE12 / PE11 |
| 9 | PA8 / PA11 | PE10 / PE9 |
| 10 | PA12 / PA15 | PE8 / PE7 |
| 11 | PC10 / PC11 | PB1 / PB0 |
| 12 | PC12 / PD0 | PC5 / PC4 |
| 13 | PD1 / PD2 | PA7 / PA6 |
| 14 | PD3 / PD4 | PA5 / PA4 |
| 15 | PD5 / PD6 | PA1 / PA0 |
| 16 | PD7 / PB3 | PC3 / PC2 |
| 17 | PB4 / PB5 | PC1 / PC0 |
| 18 | PB6 / PB7 | PC13 / PE6 |
| 19 | PB8 / PB9 | PE5 / PE4 |
| 20 | PE0 / PE1 | PE3 / PE2 |

H4 是 LED 区 6 个独立端点，H3 是 KEY 区 6 个独立端点；照片上没有把它们跳接到某一组 GPIO 的导线。产品海报 H4 第 2 行丝印存在 LED2/LED3 的印刷或可读性问题，端点按实际自上而下的 6 个 LED 顺序编号，不据此声称两只 LED 共网。

OLED 模组 4 针自上而下可见 SDA、SCL、VCC、GND。照片能确认端口存在，不能单独确认 MCU 侧的内层走线。

V2.0 USART2 区的跳线端丝印明确出现 **PD8、PD9**；V1.0 图纸 USART2 则为 **PB10、PB11**。这是版本不能混用的直接例子。照片中的 C_R/C_T、T_R/T_T 涉及信号源选择，完整默认跳帽位置/跳帽接通关系仍需 V2 图纸或实板导通核验。

## 软件配置证据与尚未确认项

| 模型行为 | 证据 | 结论 |
|---|---|---|
| OLED SCL=PB8，SDA=PB9 | `APP/Driver/OLED/OLED.h` 第 15–18 行 | 用户代码配置已确认；V2 铜线尚未独立确认 |
| OLED 7 位地址 0x3C，128×32 | `OLED.c` 第 133 行写地址 0x78，169/193 行和初始化配置 | 模型可按该驱动处理；不是实测屏幕验收 |
| LED1–6 由 PD10–PD15 高电平点亮 | `APP/Driver/LED/LED.c` 第 7–25 行 | 这是用户跳线方案的代码，不是板载固定 GPIO 接线 |
| KEY1–5 从 PE7–PE11 低电平读取 | `APP/Driver/KEY/key.c` 第 9–14、22、38 行 | 这是用户跳线方案；第 6 路另有 PA0 唤醒处理 |
| LED 端高有效、KEY 端低有效 | 上述代码与 V1.0 原理图第 2 页一致 | V2 独立极性/上拉/公共地尚未通过图纸或实板确认，JSON `polarityVerified=false` |
| USB CH340 使用 USART0 PA9/PA10 | `APP/Driver/USART/USART.c` 第 39–48 行，照片 USB 区有 PA9/PA10 丝印 | 照片及代码支持；跳帽完整通断关系待核验 |
| RS485 使用 USART1 PA2/PA3，PA1 方向 | `APP/Driver/USART/USART.h` 第 28–30 行、`.c` 第 152–162 行 | 代码配置已确认；V2 选择器铜线尚未完整核验 |
| RS232 与 RS485 的共享/选择关系 | V1 有选择跳帽，V2 照片有选择区 | V2 默认连通不能沿用 V1 推定，保留未知 |
| 板上电位器输入 PC0 | `APP/Driver/ADC/ADC.c` 第 18 行；V1 同网 | V2 模型候选，不能宣称已验证 V2 铜线 |

## 接线约束

- `fixedNets` 只记录照片丝印确认的 MCU 到引出排针关系，全部只读。照片/该列表不等于完整底板网表。
- `provisionalFixedNets` 单独记录 OLED 代码支持的 SCL/SDA 模型假定及 3V3/DGND 供电模型；界面必须显示其证据等级，不能将其称为已核验 V2 固定铜线。启用这些模型时，OLED 端点和 GPIO 必须共用相同连通图；端点新增接地线不能被仿真器忽略。
- 用户只能在已确认存在的排针端点之间添加跳线；禁止移动、删除或改接原板网络。NC 不可接线；3V3/DGND 不是可编程 GPIO。
- `defaultAddedWires` 是演示工程额外添加的 12 条可见跳线：PD10–PD15 到 LED1–6、PE7–PE12 到 KEY1–6。它们不属于底板原始铜线。前 5 个 KEY 与用户工程一致，第 6 个 PE12 是演示选择，不声称与其 PA0 唤醒方案一致。
- 禁止静默把所有 LED、KEY 默认固定到 GPIO。没有用户跳线或明确演示跳线时，GPIO 改变不应自动驱动这些独立端点。
- GPIO 共网、输出冲突、电源短路应在新增导线层检查；不能为让示例“正常运行”而更改板载连线。

## 图像坐标

`viewBox=[0,0,1000,650]`；背景图原生为 640×428。端点位置按实拍图近似投影，位于其真实连接器区域；它们不是 PCB 制造尺寸。UI 应按同一比例映射背景及端点。主排针上下顺序来自高分辨率实拍，端点不按示意布局重新排列。

## MCU 型号与存储空间（已核验）

精确型号为 **GD32F470VET6**。[兆易创新该型号官方页面](https://www.gigadevice.com.cn/product/mcu/mcus-product-selector/gd32f470vet6)给出 240 MHz、512K Flash、256K SRAM。不能把同系列 VG/VI 的更大容量套用到 VE。

本机 `D:/desktop/CIMC2026/2026343469/2026343469-code/APP/project/CIMC_GD32_LED_driver.uvprojx` 第 18 行指定 `GD32F470VE`；第 22 行设备声明为：

```text
IRAM(0x20000000,0x030000) IRAM2(0x10000000,0x010000) IROM(0x08000000,0x080000)
```

| 空间 | 起始地址 | 大小 | 最后有效字节地址 |
|---|---|---|---|
| 内部 Flash | 0x08000000 | 512 KiB | 0x0807FFFF |
| 主 SRAM | 0x20000000 | 192 KiB | 0x2002FFFF |
| TCM SRAM | 0x10000000 | 64 KiB | 0x1000FFFF |

256 KiB SRAM **不是从 0x20000000 开始的连续 256 KiB**。仿真器应分别映射两个 RAM 地址段，并拒绝超界固件与内存访问。向下增长堆栈的初始 SP 可指向相应 RAM 末尾的下一个地址（例如 0x20030000），但该地址不是一个可读写字节。用户工程 `.uvprojx` 第 280–281 行的 APP `0x08011000 + 0x20000` 只是该工程分区，不能把它误当整颗芯片 Flash 容量。

另已直接读取[官方 GD32F470xx Datasheet Rev2.1](https://www.gd32mcu.com/data/documents/datasheet/GD32F470xx%20Datasheet_Rev2.1.pdf)：物理第 64 页（印刷页 63）说明 TCM 仅供 Cortex-M4 **数据总线**访问，应禁止从 TCM 取指；该页及物理第 15 页列有额外 4 KiB BKP SRAM，地址 `0x40024000–0x40024FFF`，应作为独立备份域功能处理，不能混入主 SRAM。普通写指令也不应直接改写内部 Flash，编程/擦除必须由已实现的闪存控制器模型完成，否则应报告未支持。

## 检索范围与未完成证据

本轮检索了 `D:/desktop/CIMC2026`、`D:/desktop/2027年CIMC培训` 的相关图纸/驱动文件，以及 `C:/Users/admin/Documents/LCEDA-Pro/online-projects-backup` 中 CIMC、2026cimc国赛、米醋·西门子2026硬件题最新 ZIP 的目录和 EPRU 文档头。这些备份主要是扩展板项目；未发现 GD32F470 主控原理图标识。没有修改这些原始资料。

仍须补齐完整 V2.0 原理图或用实板测量确认：OLED 与 MCU 的固定连接、LED/KEY 极性及公共网络、全部 UART 跳帽默认状态、SPI Flash/TF/以太网/ADC/DAC 固定路由及电源网络。当前软件只能称为“按官方 V2.0 外观和已确认端点构建、部分固定外设采用代码支持模型的训练仿真”。
