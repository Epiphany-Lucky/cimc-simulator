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

独立设置 RS485 自定义 31250 bps、7E1.5 后，CH340 仍保留自身参数。错误输入未写入状态。工程导出重开保留手动参数、12 条跳线和固件，缺少参数字段的旧工程恢复自动模式。1024×600、390×844 与常用桌面尺寸的弹窗通过浏览器操作检查。记录为 `artifacts/demo3-serial-source-attempt1-v070.json`。

在内置三镜像 Keil 真实固件上，通过界面设为 9600 bps 后发送 `2`，诊断记录不匹配且仍在 Bootloader 向量表。改为匹配的 115200 bps 后发送 `1`，实际机器码切换 App A 向量表、发出启动消息并点亮对应 LED。该场景随 `tests/multifirmware_ui_smoke.py` 在发行验收运行。
