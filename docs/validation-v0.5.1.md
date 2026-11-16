# CIMC Studio 0.5.1 验收记录

记录日期为2026-11-16，涵盖原始问题复现、源码与冻结包执行、双平台发布、正式软件内升级和旧分发清理。

## 问题定位

用户工程位于 `D:\desktop\CIMC_DEMO\DEMO1\CIMC_DEMO`，复现使用其 `MDK-ARM\build\CIMC_DEMO\CIMC_DEMO.hex`。当前0.5.0内核在第764条指令、PC `0x08000BCA` 处诊断未映射访问 `0x42470060`，与用户截图一致。HAL 通过该外设位带别名写 RCC_CR 的 PLLON 位。

工程使用 STM32F427 的启动文件和 HAL。此次验证针对该 HEX 实际执行的时钟、SysTick 和 GPIO 路径。主循环只调度 `led_proc`，六路输出来自 `ucLed = {1,0,1,0,1,1}` 及 PD8～PD13。没有 OLED 初始化和串口任务。用户当前接线已按 PD8～PD13 连接 LED1～LED6，实际工作台状态保存在 `artifacts/v051-user-session-state.json`。

## 修复范围

扩展 `engine/simulator.py` 的字对齐外设位带别名访问，复用现有 RCC、GPIO 和未实现寄存器诊断。按 ARM 位带语义从别名映射底层位，读返回0或1，写只取最低位，以单个仿真访问完成读改写。

依据为 Arm Cortex-M4 Technical Reference Manual 第3.7节。支持范围为外设位带，SRAM 位带单独列入后续兼容性范围。[ARM 官方文档](https://documentation-service.arm.com/static/5fce431be167456a35b36ade)

## 验收状态

| 验收项 | 实际结果 | 证据 |
|---|---|---|
| 原始问题复现 | 第764条指令、PC 0x08000BCA、0x42470060未映射访问 | 本轮命令输出 |
| 用户原始 HEX 启动与 SysTick | V1/V2均执行100万条指令，SysTick递增，通过 | artifacts/v051-demo-source-check.json |
| 六路 LED 实际接线输出 | 两板均为1、0、1、0、1、1，PD_ODR为0x3500，通过 | artifacts/v051-demo-source-check.json |
| 独立位带机器码及非法访问回归 | 4项测试通过，用时0.104秒 | tests/test_bitband.py、firmware/BITBAND_PROBE.md |
| Windows 全套源码检查 | 167项运行，157通过，10项Linux专用跳过，177.680秒 | artifacts/v051-windows-build.log |
| Windows 冻结包与原生桌面 | 原始用户HEX、独立HEX/BIN位带探针及WPF验收通过 | artifacts/v051-demo-package-check.json、artifacts/installer-smoke-cc5c256f6347/result.json |
| Windows 安装、升级、卸载 | 隔离安装、重复安装通过，卸载保留用户文件 | artifacts/installer-smoke-cc5c256f6347/result.json |
| Ubuntu/Debian 安装分发 | Ubuntu22.04 DEB、浏览器、生命周期和卸载，以及Debian12容器安装/实际固件/生命周期/卸载通过 | CI 43871906368 package-linux |
| 同一 Linux 冻结包本机补验 | WSL Ubuntu26.04，包内固件、生命周期和原始用户HEX三轮验收通过，124.311秒 | artifacts/v051-same-linux-wsl.json、artifacts/v051-frozen-linux-user-demo.json |
| GitHub 源码、标签和发行附件 | 公开发行已发布，五个软件包、摘要清单和两份验证说明共8个附件 | CI 43871906368、草稿工作流43874484339、Release447066739 |
| 正式安装与软件内更新 | 实际0.5.0桌面更新API完成下载、校验、安装交接与0.5.1重启，恢复原固件和六根跳线后运行通过 | artifacts/v051-production-upgrade.json |
| 在线更新旧客户端识别 | 真实0.5.0冻结客户端发现0.5.1，正式安装0.5.1判断已最新，四个下载入口和摘要校验通过 | artifacts/v051-frozen-public-update-check.json、artifacts/v051-public-update-check.json |
| 两平台 Packages 发布及回拉摘要 | 双平台0.5.1及latest发布，按0.5.1回拉并校验全部文件，通过 | Packages工作流43875336284 |
| 旧版分发文件清理 | 远端8项、本地10个旧分发目标及24个旧CI分片删除并复验通过 | docs/releases/cleanup-v0.5.1.json、artifacts/local-cleanup-0.5.1.json、artifacts/v051-extra-cleanup-result.json |

## 用户原始 HEX 源码内核验收

`artifacts/v051-demo-source-check.py` 对原始 HEX 和保存的用户工程执行验证，结果 `passed=true`，总耗时14.038秒。原始 HEX 的 SHA-256 为 `6c4c6c6cb0cf775f128868702c071a97fcaf6cef17b1fc0d485a6c542f1d8ff2`，测试前后用户工程源文件、HEX及MAP哈希一致。

每25万条执行指令取样一次，由 MAP 定位 `uwTick` 的实际 RAM 地址 `0x20000024`。V1 的四次读数为3、4、6、7，V2为364、721、1078、1435。两板均得到 PD_ODR `0x3500` 和 LED1、LED3、LED5、LED6 点亮。复位、工程导出恢复以及100个1万指令块与3个不等长指令块的结果一致性检查均通过。测试只读取CPU/RAM证据，程序执行由原始机器码推进。

## Windows 冻结包与原生安装

`artifacts/v051-demo-package-check.json` 记录通过浏览器正常工程导入和运行入口，冻结内核执行原始用户 HEX 至1038752条指令，六条既有 LED 跳线得到预期状态，JavaScript错误列表为空。打包内核源文件摘要与已验证源码一致。

隔离安装验收ID为 `cc5c256f6347`，结果 `passed=true`、`desktopTest=true`。安装后执行独立 Keil 位带 HEX/BIN、V1内置示例、OLED、串口、ADC、SPI Flash、三镜像Bootloader、工程恢复及V2 Bootloader/App。SysTick与无中断吞吐比为1.0866651141136934。WPF窗口在120 DPI下完整处于显示器工作区内。重复安装和卸载保留用户文件均通过。

`artifacts/v051-self-update-ui-smoke.json` 使用冻结内核和浏览器实际点击验证下载进度、校验失败重试、工程导出、取消安装确认、安装失败重试、退出交接和便携包打开文件夹，JavaScript错误列表为空。本项的安装响应由测试夹具提供，真实安装器执行另列正式升级验收。

## 发行来源

- 固定产品源码为 `ee3b20a0026f52a00d48834f399703306d70463e`。
- 注释标签 `v0.5.1` 的标签对象为 `c9be75607f2ea602461cfeff8e45b2b87df32936`，解引用到该源码提交。
- 完整CI运行 `43871906368` 的两个源码检查和两个打包验收job均成功。
- 发行草稿工作流 `43874484339` 成功，严格从该CI选取五个软件分发文件，并生成摘要清单和CI来源说明。草稿ID为 `447066739`。
- Windows原始CI artifact为 `14228891933`，231713957字节，外层ZIP SHA-256为 `9e448bf30ec37ab21adbf19f9bba2604fb46ff529d0a704bca9bb51f1d1d1c08`。
- Linux原始CI artifact为 `14229521136`，99848594字节，外层ZIP SHA-256为 `7981bfa52e876952b5adb9df5f2c1e195df192de3a1f0bfe10dac4cfec822cb0`。
- 两份下载的外层摘要和CRC均已检查，附件文件名集与版本严格匹配。已完成的下载分片逐文件清除。
- 公开发行ID为 `447066739`，标题为 `CIMC Studio 0.5.1 · DEMO 启动修复`，包含五个软件包、摘要清单、CI来源说明及本机Windows/WSL验收说明，共8个附件。[公开发行](https://github.com/Epiphany-Lucky/cimc-simulator/releases/tag/v0.5.1)

| 分发文件 | SHA-256 |
|---|---|
| CIMC-Studio-0.5.1-Setup-x64.exe | 8644f6acdd0390339e6d1bb7c3fc9775e7bd445851a101f008774f4a75217b12 |
| CIMC-Studio-0.5.1-win-x64.zip | 3d71f307557b40ce49d50e2802059577269202825313b622d6944d93bd2f3fd3 |
| CIMC-Studio-0.5.1-html-local.zip | b45d36ea900c2962e0460f810be43b5f0cd552bf1ce323210c3ca9bb477d291f |
| cimc-studio_0.5.1_amd64.deb | e8d1d3a04d41e32877bdf4857965ec6f5a59e95853cf4910419559ef3dce6f6e |
| CIMC-Studio-0.5.1-linux-x64.tar.gz | 50f753ae8bcdadff27c3e42c6bf322cb4e17193abaeb86db5fddd0e9c97e1ec5 |

## 同一 Linux 发行包本机补验

已校验的实际发行 tar 在本机 WSL Ubuntu26.04 中解压到自建临时目录。运行包内 `source/tests/package_smoke.py` 和 `source/tests/linux_install_smoke.py --portable` 通过，覆盖独立位带HEX/BIN、V1/V2实际固件、SPI/ADC/DAC、工程恢复、便携启动、重复启动、授权退出、空闲清理和异常恢复。SysTick与无中断吞吐比为0.9404545976467131。

再通过冻结内核公开HTTP接口载入保存的原始用户工程，三轮分别执行1053984、1069920和1021568条指令，覆盖直接运行、复位、工程导出恢复。每轮LED均为亮、灭、亮、灭、亮、亮，诊断为空。全部自建进程已结束，临时目录已清除，未修改系统安装包。验收总用时124.311秒，结果见 `artifacts/v051-same-linux-wsl.json` 和 `artifacts/v051-frozen-linux-user-demo.json`。

## Packages 与远端清理

Packages工作流 `43875336284` 的Windows、Linux发布和清理三个job均成功。两个OCI包分别推送 `0.5.1` 和 `latest`，随后按 `0.5.1` 回拉并核对全部分发文件摘要。

清理报告artifact `14230580206` 的外层ZIP摘要为 `9462027aec00744e7118cd38398e39dd4dde0c5f0463b4e89c73fc90b40590b2`，下载后已检查摘要、CRC及唯一文件名。报告 `executed=true`、`verified=true`，已归档至 `docs/releases/cleanup-v0.5.1.json`。共删除0.5.0的五个安装分发附件、一份摘要清单和两个旧Packages版本，合计8项。0.5.0源码、标签、公告与验证说明保留。

## 正式软件内升级与用户工程恢复

`artifacts/v051-production-upgrade.json` 的结果为 `passed=true`。实际已注册的0.5.0桌面通过自身更新HTTP API完成官方85,561,313字节安装器下载、大小与SHA-256校验、安装交接、退出和重新启动。下载的安装器摘要与所选CI分发文件一致。Windows注册表确认版本从0.5.0变为0.5.1，实际安装目录仍为 `D:\CIMC Studio`。

升级前检测到原工作台已关闭，验收脚本启动原已注册的0.5.0应用，并从此前保存的工程恢复同一份HEX和六根跳线后执行真实软件内升级。新版重启后恢复原始固件集合、引脚连接和颜色，运行超过100万条指令，LED为亮、灭、亮、灭、亮、亮，诊断为空，正式WPF窗口标题显示0.5.1。

首次恢复校验使用临时连线ID比较而触发断言。工程导入会重新生成这些ID，续验改为核对实际端点、颜色和固件集合后通过。初始记录 `artifacts/v051-production-upgrade-initial-check.json` 及续验日志 `artifacts/v051-production-upgrade-resume.log` 均保留。

匿名公开更新检查通过，四个下载入口HEAD均返回200，内容长度和公开摘要清单与发行资产一致。真实0.5.0冻结客户端返回 `latestVersion=0.5.1`、`available=true`，正式安装的0.5.1冻结客户端返回 `latestVersion=0.5.1`、`available=false`。验证自建的8884、8885端口进程树已结束。证据见 `artifacts/v051-public-update-check.json` 和 `artifacts/v051-frozen-public-update-check.json`。

## 本地旧分发清理

在0.5.1公开发行、更新识别和双平台Packages验收成功后，使用已验证的同版远端清理报告运行 `scripts/prune-local-installers.ps1`，先预览再执行。本次删除10个已枚举的旧目标，包括0.5.0Windows/HTML分发目录及ZIP、安装器、Linux DEB及tar、两个旧隔离安装器和旧CI下载ZIP。结果为 `executed=true`、`verified=true`，见 `artifacts/local-cleanup-0.5.1.json`、`artifacts/v051-local-cleanup-preview.log` 和 `artifacts/v051-local-cleanup.log`。

另核对旧0.5.0Linux CI下载缓存的24个分片，逐文件删除后移除空目录，结果 `executed=true`、`verified=true`，见 `artifacts/v051-extra-cleanup-result.json`。本轮新版本下载分片在完整ZIP摘要、CRC及文件集核验后也已逐文件清除。当前版本的分发文件、用户原始DEMO、正式安装与工程数据继续保留。

## 执行边界

此 DEMO 预期为静态 LED 输出。OLED 关闭和串口静默与工程内容一致。SysTick 为按执行指令推进的功能模型，主机墙钟耗时取决于仿真吞吐。完整 STM32F427 外设兼容性和实板时序需要独立验收。
