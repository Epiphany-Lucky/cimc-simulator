# 0.5 发布与验收记录

2026-11-16。0.5.0 已公开发布，正式安装已升级，源码、公告与 Packages 已同步，旧版分发清理完成。

## 版本与来源

- 构建源码与标签 v0.5.0 对应 `3f68dbf8083daa6797e2a7a2c4b503a1ce720380`。后续文档与验收工具提交继续记录结果，发行标签及安装附件指向该已验证源码。
- [最终四任务 CI](https://github.com/Epiphany-Lucky/cimc-simulator/actions/runs/43819333532) 全部成功。
- [发行组装](https://github.com/Epiphany-Lucky/cimc-simulator/actions/runs/43821875890) 核对标签、源码和两平台安装产物，生成五包及 SHA-256 清单。
- [公开发行页](https://github.com/Epiphany-Lucky/cimc-simulator/releases/tag/v0.5.0)。
- [Packages 发布和远端清理](https://github.com/Epiphany-Lucky/cimc-simulator/actions/runs/43822474667) 成功，两平台安装文件重新拉取后摘要一致。GHCR Packages 当前为私有，公开下载使用 Releases。

## 原理图与最终范围

工作台采用与 V1 一致的原创接线视图。V2 的119端点、116固定网络与8条用户参考线分开保存，U2/U3、H3/H4、OLED、H10/H11/H12采用原图脚号。固定铜线以用户提供的五页 V2 原理图为准，代码外接示例线可增删。

原 PDF SHA-256 为 `6289165231ed57c3dc1b15c1ebc0b90172f9b805d441accecb619a906aacc1ef`。软件提供同字节原始 PDF 下载与五页横向阅读。PT100 软件部分已移除，DAC 使用固件寄存器和实际 PA4 引脚，界面通过引脚提示显示实际输出。

## 验收结果

| 项目 | 实际验证及结果 |
|---|---|
| Windows 全量源码 | 163项，153通过，10项Linux专属跳过，退出码0。日志 artifacts/v05-production-windows-build.log |
| 两平台 CI | Windows/Ubuntu verify、Windows package、Linux package全部success。Ubuntu22.04安装运行与Chromium工作台、Debian12容器安装运行和卸载均通过 |
| 真实 V2 用户固件 | 原始Bootloader/App BIN摘要匹配。实际RX/IDLE中断接收升级包、0503擦写、系统复位、再次Boot跳App并输出真实心跳通过 |
| 固定网络和接线 | H10拔线影响真实收发，重新连接恢复。参考线可删、跨板工程原子导入、GPIO复用和原图端点约束通过 |
| 内部 Flash | 锁定、位翻转、页擦写、双地址别名、故障回滚、全擦空快照、启动向量改变后恢复通过 |
| 板载 SPI0 Flash | Keil HEX/BIN实际执行JEDEC C84013、两次编程/两次擦除及CIMC FLASH字节读回，V1 SPI1回归通过 |
| Windows 冻结与安装 | TestAppId 443bbbca6b06，安装、真实固件、WPF、覆盖安装、卸载和用户文件留存通过。源码/冻结包web资源逐字节一致 |
| 本机冻结浏览器 | V1、短屏/手机、原图、多固件、更新检查、应用内更新、V2五页原图与V2运行覆盖完成，零JS错误，记录 artifacts/v05-frozen-ui-suite.json |
| V2 两轮工程恢复 | 实际协议CRC、PC0/PC1及DAC3072→2048→3072参数保存和PA4提示验证完成。主机启动超过原240秒预算后，沿用同一真实CPU现场接续完成，正式工具改为600秒并等待真实心跳。记录明确保留超时与接续过程 |
| 同一 Linux 包 WSL | 最终artifact14204661870完整ZIP摘要核对，Ubuntu26.04 WSL运行同一发行tar真实固件和便携生命周期通过。SysTick/无IRQ吞吐比0.93198。日志 artifacts/v05-same-linux-wsl.log |
| 正式0.4→0.5更新 | 实际SelfUpdater下载公开安装器，校验后helper退出交接、保留D盘安装位置、成功安装并实际重启。HKCU DisplayVersion=0.5.0，安装位置D:/CIMC Studio。记录 artifacts/v05-production-upgrade.json |
| 正式安装原生复验 | D盘实际安装程序通过WPF工作区/DPI、真实OLED/JEDEC、原图和关闭自有内核验收，日志 artifacts/v05-installed-native.log。安装资源与源码同字节 |
| 公开更新 | 真实旧0.4冻结引擎识别0.5且available=true，正式新0.5冻结引擎available=false。四个下载入口匿名HEAD200，长度、API摘要与SHA256SUMS一致，记录 artifacts/v05-public-update-check.json及v05-frozen-public-update-check.json |
| 清理 | 远端删除8项旧附件/包版本。本地标准规则首次删除10目标，逐文件补清理46个已核验旧下载/测试安装文件。再次执行旧目标为0。远端报告见 docs/releases/cleanup-v0.5.0.json |

实际安装器 SHA-256 为 `8936acd4be1a22ed6b6178201834263e346bf73c415e2118b2530f9b45be95de`。

最终 Linux artifact ZIP SHA-256 为 `9faea07deb941a7303469c70ceeae0dc9131e468e776b2ea86887807ce291d54`，发行 tar SHA-256 为 `07fb2f8543d56f091caf1383be7170097e22956f9866b80ff40d7c4ca3ca50fd`。

首次正式更新检查曾触发GitHub匿名接口60次配额，按服务返回时间等待重置后，真实下载、安装和新旧客户端公开检查均通过。该失败日志与成功记录分别保留。

## 验证范围

本次为机器码、功能模型、安装、浏览器与发布验收。V2每条指令推进240个SysTick输入tick，OLED软件延时循环完整执行，示例初始化可能需数分钟。逐周期、实板电气、复杂中断嵌套、DMA、完整Ethernet/SD及RTOS仍需后续专项。Linux系统更新的polkit图形授权窗口尚未在真实图形桌面演练，便携Linux更新通过校验包解压完成。
