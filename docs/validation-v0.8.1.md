# CIMC Studio 0.8.1 串口工作台验收

用当前 DEMO4 HEX 复现截图所示现象，SHA-256 为 f30214facec029419d601ee47144eb29532e598c307adde5e32878c4bc5f80cc。0.8.0 的 V2 独立复测产生两条 TX 日志，内容分别为「DMA data: Hel」和「lo」加换行。拼起来与固件发送的原始字节一致。

0.8.1 在工作台接续同一通道的 TX 片段。真实换行用于分行，同通道 RX 用于结束当前显示行。文本从原始字节解码，HEX 显示包含换行符在内的所有接收字节。很长的连续流分成有长度上限的显示行，UTF-8 字符可以跨显示行边界正确解码。

| 验收项 | 预期与结果 |
| --- | --- |
| 原版 DEMO4，V1 和 V2 | Edge 实际加载并运行原版 HEX，注入 Hello，完整回显保持一行。用两块板实测的 0.8.0 原始分段验证未完成行与下一次轮询追加。 |
| 字节、换行和清屏 | 受控浏览器测试验证 CRLF 跨分段、多行、UTF-8 跨分段、二进制 HEX、RX 与不同通道及清屏后的新内容。 |
| 日志导出 | 文本导出沿用 TX 分行，以完整字符输出。 |

证据位于 artifacts/.serial-fragment/source-edge.json 和 artifacts/.serial-log/edge-serial-log-regression.json。安装包及在线发行状态见 [0.8.1 更新公告](https://github.com/Epiphany-Lucky/cimc-simulator/releases/tag/v0.8.1)。

## 正式发行和应用内更新

发布标签指向 72ca646271dc7fe282b64c769938c3eac1f1c8ee。Windows 和 Linux 构建、验收均通过。发行草稿的五个分发文件与选定 CI 产物逐项核对了大小及 SHA-256。 [选定 CI](https://github.com/Epiphany-Lucky/cimc-simulator/actions/runs/45390701256)

同一份 Windows 便携分发和 HTML 本地包在 Edge 上复现了底层物理分段，工作台在 V1、V2 上把两次回显分别显示为两行，每条回复完整。Linux 的 Chromium 验收执行了串口分行回归。同一份 Linux 便携包在 WSL 中通过实际 DEMO4、PROJECT1 和打包固件及生命周期测试。原生 Windows 另验证安装、重装、卸载和 WebView2 工作台。

在本机真实 0.8.0 的应用内更新接口检测并下载 0.8.1。正式安装包 SHA-256 为 e985de0b8e288516c961c30d45dd540f418f5cd8d31018397ac3824e5745f20d。经安装交接后，Windows 注册版本为 0.8.1，重启的工作台成功应答。两版复用原安装位置，原有 14 个旧引擎进程在更新后复核仍运行。证据见 artifacts/v081-production-upgrade.json。

用实际安装版在独立端口再次运行原版 HEX。V1、V2 的初次回显各为一条 TX 日志，第二次回显分别新增一条。证据见 artifacts/v081-installed-ui.json。

Windows 和 Linux Packages 发布后重新拉取校验，通过公开更新和本机安装验收后，清理了 0.8.0 的 6 个旧发行附件、2 个旧 Packages 版本以及本地 12 个旧分发目标和 2 个空缓存目录。 [Packages 验证](https://github.com/Epiphany-Lucky/cimc-simulator/actions/runs/45394387639) · [远端清理记录](releases/cleanup-v0.8.1.json)
