# CIMC V2 用户工程固件

这组机器码来自用户于 2026-11-16 提供的 `27_0_BootLoader` 工程，目标为 CIMC V2 板，MCU 为 GD32F470VE。文件与原件逐字节一致，摘要见 `v2-manifest.json`。

| 文件 | 烧录或使用方式 |
|---|---|
| v2-bootloader.bin | Flash 0x08000000，启动向量 0x08000000 |
| v2-app.bin | Flash 0x08011000，支持直接从该向量启动 |
| v2-app-update.bin | 8 字节升级包头加 App；在 BootLoader 0502 命令后通过 RS485 发送 |

软件选择 V2 后点击“载入 V2 工程”可装入 BootLoader 与 App。它们运行真实 ARM 指令，OLED 初始化含大量软件 I2C 延时循环，启动过程需要等待。V2 的功能时钟按每条指令推进 240 个核心时钟计数，SysTick 经真实中断执行。该比例用于可交互的功能验证，实际墙钟速度依计算机性能变化。

BootLoader 默认在自身完成 OLED 初始化后等待 5 秒仿真时间并跳入 App。App 会重做 OLED 初始化，再输出协议心跳。升级流程发送 ASCII HEX 0502 命令、原始 v2-app-update.bin、等待完成回应、再发 ASCII HEX 0503 命令。协议为 A5 B6、设备 ID、类型、命令、数据长度、02、数据、CRC16/MODBUS 高字节在前、B6 A5。

工程实际使用 USART1 PD5/PD6 AF7、RS485 DE PE8、OLED PB8/PB9、LED PE6、ADC PC0/PC1、DAC PA4、SPI0 PA5/PA6/PA7 与 CS PB10。源码中的未启用旧驱动或注释地址与运行路径可能不同，固定铜线以随包五页 V2 原理图为准，代码外接连接作为可删除示例跳线。

Flash 页擦除和编程会改变当前机器的实际 Flash。工程导出在发生改写后使用 v3 的 internalFlashData 字段保存完整 Flash 快照，重新导入保留这些字节。擦除启动区后仍能导出和恢复现场，复位会报告启动向量无效并进入故障状态。合法启动区复位会保留改写字节，并同步更新 Flash 快照元数据。硬件复位不会抹除 Flash。单层 SysTick 与 USART RX/IDLE 中断、FMC 同步操作用于该固件，嵌套中断与电气时序仍超出功能模型。

第三方 GigaDevice 库的版权许可随 `licenses/V2-GigaDevice-LICENSE.txt` 分发。用户业务固件的来源与作者署名见原工程，原工程继续保留在用户目录。

板载 GD25Q40E 按原图接 SPI0 PB3/PB4/PB5、PA15 片选。v2_spiflash_probe.c/HEX/BIN 使用真实机器码验证 JEDEC、页编程和扇区擦除。PC0 固定接 VR1/ADC_IN10，PC2 经 H7 跳帽可接基准；PC1 外接输入 与 DAC 观察端的示例跳线可自行增删。
