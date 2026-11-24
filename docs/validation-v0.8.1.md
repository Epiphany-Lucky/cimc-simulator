# CIMC Studio 0.8.1 串口工作台验收

用当前 DEMO4 HEX 复现截图所示现象，SHA-256 为 f30214facec029419d601ee47144eb29532e598c307adde5e32878c4bc5f80cc。0.8.0 的 V2 独立复测产生两条 TX 日志，内容分别为「DMA data: Hel」和「lo」加换行。拼起来与固件发送的原始字节一致。

0.8.1 在工作台接续同一通道的 TX 片段。真实换行用于分行，同通道 RX 用于结束当前显示行。文本从原始字节解码，HEX 显示包含换行符在内的所有接收字节。很长的连续流分成有长度上限的显示行，UTF-8 字符可以跨显示行边界正确解码。

| 验收项 | 预期与结果 |
| --- | --- |
| 原版 DEMO4，V1 和 V2 | Edge 实际加载并运行原版 HEX，注入 Hello，完整回显保持一行。用两块板实测的 0.8.0 原始分段验证未完成行与下一次轮询追加。 |
| 字节、换行和清屏 | 受控浏览器测试验证 CRLF 跨分段、多行、UTF-8 跨分段、二进制 HEX、RX 与不同通道及清屏后的新内容。 |
| 日志导出 | 文本导出沿用 TX 分行，以完整字符输出。 |

证据位于 artifacts/.serial-fragment/source-edge.json 和 artifacts/.serial-log/edge-serial-log-regression.json。安装包及在线发行状态见 [0.8.1 更新公告](https://github.com/Epiphany-Lucky/cimc-simulator/releases/tag/v0.8.1)。
