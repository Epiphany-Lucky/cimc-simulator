# CIMC Studio 0.7.0 验收记录

本轮验收覆盖独立串口通道设置、真实固件收发、工程兼容、分发及应用内更新。DEMO3 原工程和固件留在本机，发布包使用仓库已有的公开验证固件。

## DEMO3 代码与旧固件对照

两份同名 HEX 在相同 V1 板卡配置和 12 条接线下独立运行。较新的 `MDK-ARM/build/CIMC_DEMO/CIMC_DEMO.hex` 在按 KEY1 后翻转 LED2，USB · CH340 记录 7 个字节 `48 45 4C 4C 4F 0D 0A`。较旧的 `MDK-ARM/CIMC_DEMO/CIMC_DEMO.hex` 同样翻转 LED2，串口记录为空，旧链接映射确认发送函数已被移除。

| HEX | SHA-256 |
| --- | --- |
| 新 `build/CIMC_DEMO/CIMC_DEMO.hex` | `ac7e4b3c1077261e3cdc5fa2827337b25e11784357fbc105062d7be8a5f966b7` |
| 旧 `CIMC_DEMO/CIMC_DEMO.hex` | `07d440e10c05e8b61252e5d120901e66c122af82616c277bc7cda730b9c215ca` |

已安装 0.6.1 的隔离浏览器实测也得到相同结果。两次真实 KEY1 按下均触发新版输出。RS485 视图没有对应消息，切回 USB · CH340 可见 `HELLO`。终端发送 `Z` 只记录输入，当前 DEMO3 无回显逻辑。证据为 `artifacts/demo3-serial-baseline-v061.json`。

## 串口参数验收

源码界面验收使用未改动的 DEMO3 原始 HEX。固件参数显示为 115226 bps、8N1，手动设置 115200 bps、8N1 时，真实 KEY1 按下两次各得到 7 字节 `HELLO\r\n`。单独调错波特率、数据位、奇偶校验或停止位均拦截输出，LED2 仍随实际按键翻转。

独立设置 RS485 自定义 31250 bps、7E1.5 后，CH340 仍保留自身参数。错误输入未写入状态。工程导出重开保留手动参数、12 条跳线和固件，缺少参数字段的旧工程恢复自动模式。1440×1000、1024×600 和 390×844 的弹窗通过浏览器操作检查。源码和本机冻结包记录分别为 `artifacts/demo3-serial-source-6ccc491-v070.json`、`artifacts/demo3-serial-frozen-win-v070.json`。7 个相关源码文件核对到产品提交 `6ccc49148945adadca79c9fd90a2f2bda30a8402`，冻结包验证期间内核文件摘要一致。

在内置三镜像 Keil 真实固件上，通过界面设为 9600 bps 后发送 `2`，诊断记录不匹配且仍在 Bootloader 向量表。改为匹配的 115200 bps 后发送 `1`，实际机器码切换 App A 向量表、发出启动消息并点亮对应 LED。该场景随 `tests/multifirmware_ui_smoke.py` 在发行验收运行。

串口参数功能的原稿提交执行了 252 项检查。Windows 通过 242 项，10 项 Linux 专用检查跳过。Ubuntu 通过全部 252 项。新发现的接收中断修复进入后续单独选定的最终构建。

## 21:11 DEMO3 接收中断版本

正式 0.6.1 会话的运行诊断与用户截图对应。当前 HEX 的 SHA-256 为 `365eb7dea0d47386c0447501d4a3028c29d0d3a7db788773dbca39c5b79beb3b`。故障点为 PC `0x080019AC`，累计 7102 条指令。`Core/Src/usart.c:54` 启动 HAL 接收中断，链接映射把该 PC 对应到 `UART_Start_Receive_IT`。日志记录 `USART0 中断模式尚未实现`。前一节串口参数验收使用 20:23 只含发送功能的 DEMO3 构建。

接入共用 RXNE/IDLE 路径后，同一 HEX 在 V1 和原 12 条接线下继续执行。手动 `115200 8N1` 的 KEY1 按下产生 `HELLO`。输入 `DEMO3 RX IRQ` 后，固件中断回调将 12 字节写入实际缓冲区，主任务随后发出 `uart data: DEMO3 RX IRQ`。测试使用短帧。原工程的接收下标和 16 位超时变量仍由固件代码管理。

| 检查 | 结果 | 本机证据 |
| --- | --- | --- |
| 0.6.1 隔离复现 | 同一 HEX 与接线复现 7102 指令后中止 | `artifacts/demo3-rx-interrupt-baseline-v061.json` |
| 最终源码和 Windows 本机冻结包 | 自动模式回显 `IRQ42`，手动 115200/8N1 两次回显 `MATCH71`、`REARM26`。9600 拦截输入，KEY1 仍输出 `HELLO` | `artifacts/demo3-rx-interrupt-source-4bfa681-v070.json`、`artifacts/demo3-rx-interrupt-frozen-win-v070.json` |
| 真实异常测试 | V1 的 Cortex-M4 处理程序接收 RXNE 字节并清除 IDLE。TXE/TC 中断及 DMA 仍报告未支持 | `tests/test_engine.py`、`tests/test_serial_settings.py` |
| 最终本机 Windows 源码及原生安装 | 253 项中 243 项通过，10 项 Linux 专用检查跳过。隔离安装、原生窗口、固件、重装、卸载和用户文件保留通过 | `artifacts/v070-final-windows-build.log`、`artifacts/installer-smoke-473db80779a3/result.json` |

## 最终分发构建

产品提交 `4bfa681b17619401587b4c145846cafcb423cb57` 的 [选定 CI 44312504894](https://github.com/Epiphany-Lucky/cimc-simulator/actions/runs/44312504894) 四个作业通过。Windows 和 Ubuntu 源码检查分别通过 243 项和 253 项。Windows 安装后的真实固件、重装和卸载通过。Ubuntu 22.04 与 Debian 12 通过安装、固件、生命周期与卸载，Ubuntu 安装版工作台还执行了串口配置、多固件等 Chromium 验收。

从选定 CI 的 Windows ZIP 提取 407 个文件。在该冻结内核再现同一 DEMO3 的短帧回显、波特率失配拦截和 KEY1 输出，CPU 累计执行 1,590,208 条指令。原 12 条跳线、测试固件及内核摘要保持一致。报告为 `artifacts/demo3-rx-interrupt-frozen-ci-win-44312504894.json`，归档与源码对应关系见同名前缀的 `-provenance.json`。

同一选定 Linux tar 在 Ubuntu WSL 用 117.697 秒完成完整固件、便携生命周期与原 DEMO1 恢复。实际 DEMO3 同 HEX 在 9600 下不回显，切到 115200/8N1 后连续收到 `uart data: ABC` 和 `uart data: XYZ`。报告为 `artifacts/v070-same-linux-wsl.json` 和 `artifacts/v070-frozen-linux-demo3-rx.json`。

普通 main 推送 CI `44312409798` 首次 Windows 检查在密集 SysTick 暂停时间的 2 秒断言失败。同一提交重新运行后通过。额外本机运行同一有界场景 30 次全部通过，最大暂停耗时 70.218 ms。首次 CI 日志没有暂停时长与线程栈，无法确定当次原因。记录分别为 `artifacts/v070-main-push-windows-attempt1.log`、`artifacts/v070-dense-systick-pause-30.json`。
