# V2 代码适配与应用内更新实施设计

日期 2026-11-16。用户已直接授权本次完整实现、GitHub 推送、软件发布、公告及旧版分发清理。依该授权继续实施。

## 复杂度判定

等级为大。预期涉及 engine/simulator.py、engine/adc.py、engine/updates.py、engine/server.py、engine/self_update.py、engine/fmc.py、engine/v2_devices.py、web/app.js、web/index.html、web/board-v2.json、desktop/App.cs、scripts/build.ps1、scripts/build-linux.sh、.github/workflows/ci.yml 及版本文档，至少 15 个文件。

| 条件 | 判定与依据 |
|---|---|
| H1 | 命中，上述文件跨内核、界面、宿主与构建 |
| H2 | 未命中，项目使用 JSON 工程文件 |
| H3 | 命中，扩展板卡选择和应用更新本地接口 |
| H4 | 命中，更新安装需要固定发行源、摘要和本地同源校验 |
| H5 | 未命中，无计费路径 |
| H6 | 命中，Simulator 为内核、HTTP、测试共同使用 |
| H7 | 未命中，沿用标准库、Unicorn、现有宿主与安装器 |
| H8 | 命中，界面与执行内核及桌面宿主共同实现 |
| H9 | 命中，双平台发布版本与构建验收更新 |
| H10 | 未命中，本次按提供的 V2 驱动证据适配，未知物理脚号标明证据范围 |

## 现状及能力核对

- `engine/simulator.py` 的 `_load_board` 固定读取 board-v1.json，`_write` 拒绝 USART 中断。`engine/updates.py` 的 UpdateChecker 仅返回发行元数据。
- `.ai-governance/capability-map.md` 已登记真实 ARM 执行、V1 固定网络、ADC/SPI、SysTick、多固件、工程 v3、更新检查、双平台安装与清理能力。
- 用户目录 `../27_0_BootLoader` 含 BootLoader 与 App 的 GD32F470VE 工程及实际 BIN。USART1 改为 PD5/PD6 AF7，RS485 DE 为 PE8，App LED 为 PE6。OLED 仍为 PB8/PB9。
- 复用现有 ARM 执行、固件集合、GPIO/I2C、串口面板、工程保存、安装器与发布工作流。扩展板卡配置、IRQ、ADC 输入及更新界面。新增 FMC 与 V2 DAC/SPI 功能模型和安装下载控制，现有模型尚不能执行这些访问。

## 实施方案

增加可选的 V2 驱动证据配置，记录已知信号与固定网络。板卡切换时清空当前执行环境，工程导入先验证全部输入，再切换对应板卡。提供用户 BIN 的导入说明与校验摘要。固件实际执行 USART RX/IDLE 中断、FMC 擦写、复位和 Bootloader 跳转，V2 ADC/DAC/SPI 显示实际 MMIO 产生的状态。

应用内更新复用固定 GitHub 发行源，异步下载对应系统安装文件，检查大小与 SHA-256，显示进度与可重试错误。用户点击安装后启动系统安装流程，Windows 由宿主安全退出释放文件，Linux 交给系统安装界面。安装前保留工程导出入口。

曾考虑直接给 V1 改标签并套用接线，但驱动中 USART、DE 和 LED 已有明确差异，会造成错误硬件行为，因此使用独立配置。曾考虑只增加下载链接，现有 0.4 已具备此能力，无法满足此次应用内更新要求。

## 验收与交付

- 回归 V1 与旧 v1/v2/v3 工程。验证 V2 配置、真实用户 BIN、串口收发及跳转、FMC 锁定/擦写/复位、ADC/DAC/SPI 交互，拒绝未知 MMIO。
- 验证更新源、摘要、失败重试、并发请求与启动安装，运行浏览器、冻结包及 Windows 原生安装验收。
- CI 构建 Windows 安装版/便携版/HTML 包及 Linux DEB/tar，核对同包 WSL 运行后发布 0.5.0 公告、GitHub 源码及 Packages。
- 发布验证成功后按现有脚本清理已枚举旧版安装分发文件，保留用户提供工程、Git 历史和验收证据。

风险为中断调度影响原 SysTick、FMC 改写后工程保存一致性，以及运行中安装的文件占用。通过专项回归、保存实际 Flash 状态与安装前退出处理。版本回滚可从保留源码标签重建安装文件，工程导出继续由用户保存。

## 用户补充与最终接线约束

用户要求“按照V1的形式实现嘞，不要直接放张图片上去”，并说明“我的代码中的接线仅供示例作为参考，不是绝对的连接，绝对连接的是原理图上的”。因此V2使用原创原理图接线视图，板载铜线按随后提供的五页原图锁定，示例外接跳线可以增删，新增跳线保留原板网络。原PDF SHA256为6289165231ed57c3dc1b15c1ebc0b90172f9b805d441accecb619a906aacc1ef，随软件提供原始下载与横版五页阅读。
