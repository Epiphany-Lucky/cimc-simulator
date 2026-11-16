# Cortex-M4 外设位带验收固件

`bitband_probe.c` 是独立编写的 freestanding 固件。实际 Cortex-M4 `LDR/STR` 指令访问外设位带别名，结果通过 SRAM 邮箱与 GPIOD 输出记录。

## 构建

从项目根目录运行以下命令。

```powershell
powershell -NoProfile -File firmware\build.ps1 -Target bitband_probe
```

2026-11-16 实际使用 MDK Plus 5.40 / Arm Compiler for Embedded 6.22，链接布局复用 `keil.sct`。初始 MSP 为 `0x20010000`，向量表位于 `0x08000000`。保留 `.axf/.map/.hex/.bin` 以核对编译结果。

| 文件 | SHA-256 |
|---|---|
| `bitband_probe.c` | `25e1d245512b644cf84ff99b142da5264aa7ed525c780b7c16adc0968bef50a7` |
| `bitband_probe.hex` | `dfdc196044e364c3ca56f7ea1b956fe780a474cfaa5c4bafae71671875505b45` |
| `bitband_probe.bin` | `c9282ead38f3b1ea55ceaf37ff6b918ebd9ef00b9252cef00b7d7969fe7fc51f` |

## 正常运行结果

SRAM 邮箱基址为 `0x20000000`，每项为 32 位小端整数。索引 15 在复位入口读取，用于选择测试模式，默认值 0 执行完整正常流程。

| 索引 | 含义 | 预期值 |
|---|---|---|
| 0 | 所有实际访问执行完毕 | `0x42424F4B` |
| 1、2 | RCC_CR.PLLON 别名先清除再置位后的读取 | `0`、`1` |
| 3 | PLL、HSE、HSI 启用及 ready 状态 | `0x03030003` |
| 4 | 先通过 BSRR 更新后的 GPIOD ODR | `0x0000A5C5` |
| 5、6 | ODR 位带置位 bit9、清除 bit8 | `0x0000A7C5`、`0x0000A6C5` |
| 7、8 | bit9、bit8 别名读取 | `1`、`0` |
| 9、10 | RCC_PLLCFGR bit31 先置位再清除 | `0x8055A5A5`、`0x0055A5A5` |

使用 `0xFFFFFFFF`、`0xFFFFFFFE`、`2` 检查写值仅最低位参与目标位更新。BSRR 写入后的 ODR 检查要求别名操作读取当前外设状态，并保留其他位。高位别名检查覆盖寄存器高字节的寻址。

连接 PD8…PD13 至 LED1…LED6 后，稳定状态为 `[灭,亮,亮,灭,灭,亮]`。冻结安装包验收通过普通固件装载与接线接口核对此状态，并要求持续执行超过 1000 条指令。源码测试还检查全部 SRAM 结果。

## 诊断模式与功能边界

| 索引 15 的值 | 实际访问 | 预期结果 |
|---|---|---|
| 1 | 从 DMA 未实现寄存器的别名读取 | 诊断 `0x40026000`，终止运行 |
| 2 | 向同一未实现寄存器的别名写入 | 终止运行，原寄存器未写入 |
| 3、4 | 未按字对齐的别名读取、写入 | 终止运行并显示对齐诊断 |
| 5、6 | 字节读取、半字写入 | 终止运行并显示当前访问宽度限制 |

当前模拟器实现外设区的字对齐 32 位位带访问，复用已有寄存器行为。ARM 硬件还支持字节、半字传输及 SRAM 位带，后续兼容范围可据实际固件需求扩展。未对齐访问在 Unicorn 分拆 MMIO 前检查，避免原始非法传输被拆分后通过校验。

架构公式和传输语义依据 ARM Cortex-M4 Devices Generic User Guide 的 §2.2.5，以及 Cortex-M4 Technical Reference Manual 的 §3.7。用户 STM32 HAL 工程中的 `RCC_CR_PLLON_BB` 按同一公式访问 RCC_CR bit24。固件源码独立编写。[ARM Generic User Guide](https://www.keil.com/dd/docs/datashts/arm/cortex_m4/r0p1/dui0553a_cortex_m4_dgug.pdf)

运行源码回归使用以下命令。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_bitband.py -v
```
