# 0.5 验收记录

日期 2026-11-16。当前为开发验证阶段，发布结果将在实际验收后补充。

| 项目 | 验证方式 | 结果 |
|---|---|---|
| 源码内核与旧版兼容 | unittest discover | 待最终全量运行 |
| V2 真实用户固件 | Bootloader/App、UART IRQ、FMC、复位、ADC/DAC/SPI | 待集成验收 |
| V2 界面 | 浏览器板卡切换、固件、协议、信号输入、工程、窄屏 | 待执行 |
| 自更新 | 下载、摘要、错误、并发、安装交接、应用退出 | 专项测试已执行，最终回归待补 |
| Windows 冻结包与原生安装 | build.ps1、windows_installer_smoke.py | 待执行 |
| Linux 安装与同包 WSL | CI apt/dpkg、便携生命周期、实际发行 tar | 待执行 |
| 发布与清理 | GitHub、Packages、在线更新检查及清理报告 | 待执行 |

本轮软件升级目标是现有正式安装 `D:\CIMC Studio`。升级前检查运行实例并保留用户工程。
