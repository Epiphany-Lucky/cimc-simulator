# CIMC Studio 0.6.1 验收记录

记录日期为2026-11-17。本版修复源于0.6.0真实软件内升级验收，以下记录实际执行结果。

## 问题来源

0.5.1正式安装通过自己的更新API下载并校验0.6.0官方安装器，安装器成功替换 `D:\CIMC Studio` 中软件文件。随后辅助进程重新启动桌面时，冻结内核寻找旧PyInstaller临时目录中的 `python313.dll` 而失败。使用独立干净进程启动同一内核可正常进入0.6.0。

0.6.0初始失败及恢复记录保留在 `artifacts/v06-production-upgrade.json` 和 `docs/validation-v0.6.md`。0.6.1覆盖旧版辅助进程启动新桌面、桌面启动新内核以及新版辅助进程启动新版的运行环境交接。

使用同一官方0.6.0安装器从干净环境重装后，正式登记版本为0.6.0、目录仍为 `D:\CIMC Studio`，原DEMO2及12根连线已恢复运行，作为本版真实软件内升级的基线。记录为 `artifacts/v06-clean-reinstall-registration.json`。首轮登记作用域差异的原因仍未证实，安装器版本宏沿用既有实现。

负对照使用实际onefile父进程和原版0.5.1辅助脚本，安装替换同路径0.6.0内核，重现新桌面寻找旧临时目录Python DLL的错误，记录为 `artifacts/update-restart-smoke-f21b17049eb6/result.json`。新版正例使用同一交接检查继续验收。

## 验收状态

本版产品源码固定为 `240638c6792e5d84cb77be30d1501a7af1aa5657`，选定完整发行CI为 `44012209852`。[产品源码](https://github.com/Epiphany-Lucky/cimc-simulator/commit/240638c6792e5d84cb77be30d1501a7af1aa5657)，[完整CI](https://github.com/Epiphany-Lucky/cimc-simulator/actions/runs/44012209852)

| 验收项 | 实际结果 | 证据 |
|---|---|---|
| 冻结运行环境交接单元回归 | 14项更新器单元检查通过，包含新子环境标记及父环境保持 | tests/test_self_update.py |
| 实际冻结旧环境启动新版 | 真实onefile父进程、原0.5.1辅助脚本和安装器重启新WPF/内核全部通过，旧临时目录已删除 | artifacts/update-restart-smoke-f9fcaac91c27/result.json、artifacts/v061-restart-positive.log |
| Windows全部源码与构建 | 本机246项执行，236通过、10项平台跳过，273.392秒；同源码CI为239.293秒，桌面构建通过 | artifacts/v061-final-windows-build.log、artifacts/v061-ci-windows-source.log |
| Ubuntu全部源码与构建 | 246项全部通过，150.721秒 | artifacts/v061-ci-ubuntu-source.log |
| Windows冻结包、原生安装及界面 | 原生安装、WPF/WebView2、重装、卸载及用户文件保留全部通过，登记0.6.1 | artifacts/installer-smoke-19016559496b/result.json、artifacts/v061-final-installer-smoke.log |
| TIMER0～13、SysTick及两种看门狗 | 最终安装后的Keil HEX/BIN、14实例真实IRQ、两看门狗复位/IRQ0及SysTick分块通过 | artifacts/installer-smoke-19016559496b/result.json |
| DEMO2按键、主题颜色与工程恢复 | 最终冻结包11项界面脚本与23项原生DEMO2输入通过，156文件逐一核对提交、工作树及包 | artifacts/v061-frozen-ui-suite.json、artifacts/v061-frozen-ui/demo2-native-key-ui.json |
| Ubuntu/Debian安装、浏览器及卸载 | Ubuntu22.04 DEB、实际固件、全部Chromium工作台与卸载，Debian12安装、实际固件及卸载均通过 | CI 44012209852 package-linux、artifacts/v061-linux-ci-verification.json |
| 同一Linux发行包WSL补验 | 同一选定tar在WSL Ubuntu26.04完成全部实际固件、生命周期及原始DEMO三轮检查，125.826秒 | artifacts/v061-same-linux-wsl.json、artifacts/v061-frozen-linux-user-demo.json |
| GitHub源码、标签与五分发 | 固定240638c源码、注释标签、公开发行448117724及8附件完成，五分发摘要与选定CI一致 | CI 44012209852、草稿44015519549、artifacts/v061-final-release-receipt.json |
| 正式安装与实际软件内更新 | 实际0.6.0下载/SHA/安装/自动重启0.6.1通过，D目录、登记版本、9文件同CI和最新12线工程恢复均核对 | artifacts/v061-production-upgrade.json |
| 真实旧新版客户端匿名更新识别 | 真实0.5.1及0.6.0均发现0.6.1，真实0.6.1判断已最新，四入口HEAD和五文件清单通过 | artifacts/v061-public-update-check.json、artifacts/v061-frozen-public-update-check.json、artifacts/v061-frozen-v051-public-update-check.json |
| 两平台Packages推送与回拉摘要 | Windows/Linux均推送0.6.1及latest，按0.6.1回拉并逐文件核对摘要通过 | Packages工作流44015879369 |
| 旧版分发清理 | 远端8项，本地17项标准目标、15个补充旧文件及4个空组目录清理并复验通过 | docs/releases/cleanup-v0.6.1.json、artifacts/local-cleanup-0.6.1.json、artifacts/v061-extra-cleanup-result.json |

## 真实旧环境重启正例

隔离正例 `f9fcaac91c27` 使用实际onefile父进程及原版0.5.1更新辅助脚本，安装器覆盖同一路径中的旧内核。确认原 `_MEI` 解包目录已删除后，新WPF和实际内核自动启动，健康接口版本为0.6.1，窗口可见、处于正常工作区且未最小化，客户区为1582×933，示例固件按钮可操作。

验收后的TestId安装和登记均卸载，正式软件登记与测试前一致。正例结果为 `passed=true`，同一机制的0.6.0负对照重现DLL失败。记录分别为 `artifacts/update-restart-smoke-f9fcaac91c27/result.json` 与 `artifacts/update-restart-smoke-f21b17049eb6/result.json`。本项验证隔离旧环境交接，实际正式0.6.0到0.6.1的软件内升级另列结果。

独立只读审计核对辅助脚本与Git标签v0.5.1中的实际字符串一致，负例DLL路径对应已删除的原解包目录，正例WPF/内核二进制SHA-256与当前0.6.1包一致。两个TestId登记已实际不存在，窗口截图复核通过。结果为 `artifacts/v061-legacy-restart-independent-audit.json`。

## Windows原生安装验收

最终原生安装 `19016559496b` 的 `passed`、`desktopTest`、`reinstallPassed` 和 `uninstallPreservedUserFile` 均为true，HKCU登记版本为0.6.1。实际安装后的冻结内核完成14个定时器、两种看门狗、外设位带、三镜像Boot/App、V2真实Boot/CRC、ADC/DAC/SPI及工程恢复。WPF/WebView2、OLED、原理图和退出时内核所有权检查通过。

本轮使用独立TestId安装，实际正式安装的软件内升级另列验证。记录为 `artifacts/installer-smoke-19016559496b/result.json` 和 `artifacts/v061-final-installer-smoke.log`。

## 最终冻结界面与DEMO2

产品源码 `240638c` 的最终Windows包通过全部11项界面脚本，包含定时器、主题、按键、原理图、多固件和更新交互，并通过原始DEMO2的23项原生可信DOM输入检查。鼠标与键盘分别执行50、100、200毫秒目标按压，各重复3次，18次主测试均由原固件翻转LED2。实际按压分别为52.6～57.7、102.5～107.1和201.6～207.0毫秒，KEY2～KEY5另验证对应输出，KEY6检查释放和LED状态保持。

每项HTTP输入顺序及最终全部按键释放正确，JavaScript错误为空，即时样式反馈最长7.5毫秒。首次前台观察GPIO结果为35～243.9毫秒，包含HTTP及轮询时间。完整V2固件、协议和工程恢复界面验收用时474.885秒。

156个源码文件包含 `desktop/App.cs` 与工程版本文件，逐一核对提交Git blob、工作树及包内原始SHA-256，包验收前后保持一致。冻结内核SHA-256为 `d3aaea8e689e6e998b9fef9d3966083b6730e32c9df1b34168d3566250f88e2b`，桌面宿主为 `ecdf9bb334430dee06015c9f0e1e86d9987370b556a64d2bd49f2ba11521573b`。主记录为 `artifacts/v061-frozen-ui-suite.json`，DEMO2记录为 `artifacts/v061-frozen-ui/demo2-native-key-ui.json`，私有进程及配置均已清理，截图复核通过。

## 选定发行文件

注释标签 `v0.6.1` 的对象为 `cd486005ea6c7b688e12df3f0f1c034ae11e6d1a`，解引用到产品源码 `240638c6792e5d84cb77be30d1501a7af1aa5657`。草稿工作流 `44015519549` 成功，从选定CI复制五个软件并生成SHA清单和CI说明。

公开发行ID为 `448117724`，当前 `draft=false`、`prerelease=true`，五软件、SHA清单、CI说明及本机验收说明共8附件。五软件及SHA/CI说明的ID、大小和摘要在公开时逐项保持选定原值，本机验收说明单独更新。[公开发行](https://github.com/Epiphany-Lucky/cimc-simulator/releases/tag/v0.6.1)

完整CI `44012209852` 的两个源码检查及两个打包验收job均成功。Windows CI隔离安装ID为 `d73d099bc532`，实际固件、重装和卸载通过。Ubuntu22.04完成DEB安装、实际固件、Chromium全部工作台、生命周期及卸载，Debian12容器完成安装、实际固件、生命周期及卸载。两平台验收artifact已下载并核对API摘要和CRC。

Windows原始CI artifact为 `14298590224`，232243279字节，外层ZIP SHA-256为 `1d2ed10b61bc792ce5acc4016a4b4894e2d685856c51fbb5bb2a48513e7420ad`。名称集、版本和CRC均已核对，完整校验后的下载分片逐文件清除。

Linux原始CI artifact为 `14298630649`，100163011字节，外层ZIP SHA-256为 `9e23b3a8854fce246588e41c5fd65774ce404108c9d0943f5cda99d9d666e238`。名称集、版本和CRC均已核对，完整校验后的下载分片逐文件清除。

| 分发文件 | SHA-256 |
|---|---|
| CIMC-Studio-0.6.1-Setup-x64.exe | 4150bbfc1d1da9142490935231c433b29742a5971ad9ae368651119659310d5e |
| CIMC-Studio-0.6.1-win-x64.zip | 921307b313621bd767683d8e075bf8ad487379cfa7cd49e25301a84201b5e8a8 |
| CIMC-Studio-0.6.1-html-local.zip | ac396440f1f49c24ded48cfe723f5bf10abdfb8027e2dca5fb93b497bf4ca34a |
| cimc-studio_0.6.1_amd64.deb | 03ce4810879f1442bf63f8d53bcb3f14a812c2370e8d1b83c996516b11248d95 |
| CIMC-Studio-0.6.1-linux-x64.tar.gz | ffe305a92f51bb28a417cc53567b61efc47263e9c0c8c075923b2dfc1bf74052 |

## 同一Linux发行包WSL补验

实际选定Linux tar的SHA-256为 `ffe305a92f51bb28a417cc53567b61efc47263e9c0c8c075923b2dfc1bf74052`，在WSL Ubuntu26.04的自建临时目录解压。执行包内 `source/tests/package_smoke.py` 和 `source/tests/linux_install_smoke.py --portable` 通过，包含14实例真实IRQ、两看门狗复位/IRQ0、V2真实Boot/App与CRC、ADC/DAC/SPI、三镜像、工程恢复及便携生命周期。

通过同一冻结内核公开HTTP接口载入保存的原始DEMO1工程，直接运行、复位、工程导出恢复三轮均超过100万条指令，LED状态符合原固件，诊断为空。全部自建进程、临时目录和独立配置清理完成，用时125.826秒。记录为 `artifacts/v061-same-linux-wsl.json` 及 `artifacts/v061-frozen-linux-user-demo.json`。

## Packages与远端清理

Packages工作流 `44015879369` 的两平台发布和清理三个job首轮全部成功。两个OCI包分别推送0.6.1及latest，按0.6.1回拉后提取全部安装文件并逐项验证SHA-256。

清理artifact为 `14297484958`，外层ZIP SHA-256为 `3bebe70d8171fd8685cefe3e39d6ac93e814506205461ce9a21030231c76b4f8`。下载后已核对摘要、CRC及唯一文件名。报告 `executed=true`、`verified=true`，归档为 `docs/releases/cleanup-v0.6.1.json`，报告SHA-256为 `c9cc57787f94a51f42dff804cfda2dfc894da3775dd307db8fd5534f491737cb`。本轮删除0.6.0五个软件附件、一份摘要清单及两个旧Packages版本，共8项，源码、标签、公告及验证说明继续保留。

## 正式软件内升级与当前工程

实际已注册的0.6.0桌面通过自身更新HTTP API完成官方85,670,031字节安装器下载及SHA-256校验，摘要为 `4150bbfc1d1da9142490935231c433b29742a5971ad9ae368651119659310d5e`。安装、旧进程退出和新版自动重启通过，HKCU登记为0.6.1，实际目录仍为 `D:\CIMC Studio`。9个实际文件的SHA-256与选定CI Windows ZIP逐项一致，包含桌面、内核、界面、板卡、仿真器、更新器、桌面源码及定时器固件。

安装交接前从正在运行的软件导出最新工程，保存为报告所列的独立备份。新版恢复原固件集合、实际引脚端点与颜色后，原DEMO2的 `e5990ebfef5fc8a8b81e45bfdeea35db623391d19d95892ff11ea5cd6781a030` HEX及12根连线继续运行。首次完成记录为135,616条指令，结果 `passed=true`，见 `artifacts/v061-production-upgrade.json`。

后续2026-11-17 12:25本机持续运行复核为207,932,416条真实指令，状态running，14个定时器状态存在。诊断保留PA的0xFF0F及PC的0xFFCF浮空/不确定输入warning，共2条，error为空。初次及后续记录分别保留，后续记录为 `artifacts/v061-installed-runtime-followup.json`。

## 匿名公开更新识别

匿名 `UpdateChecker`、四个系统下载入口HEAD及公开SHA清单检查全部通过，清单五条摘要与选定CI receipt一致，见 `artifacts/v061-public-update-check.json`。

分别启动真实0.6.0及0.5.1冻结客户端，均返回 `latestVersion=0.6.1`、`available=true`。真实0.6.1冻结客户端返回同一最新版及 `available=false`。验证结束后所有自建进程树均退出，记录为 `artifacts/v061-frozen-public-update-check.json` 和 `artifacts/v061-frozen-v051-public-update-check.json`。

前轮匿名检查曾达到GitHub同公网IP额度，原失败报告已保留，额度恢复后使用真实匿名路径完成本轮检查。公开发行继续使用开发预览标记，客户端按有效发行列表选择版本。

## 本地旧分发清理

公开更新识别、真实正式升级及两平台Packages全部通过后，使用本版已验证的远端清理报告执行本地标准和补充清理。标准17项目标的执行结果 `executed=true`、`verified=true`，来源为 `artifacts/local-cleanup-0.6.1.json`。其中4个旧便携目录在删除前逐文件与相应完整ZIP核对名称集和内容SHA-256，记录为 `artifacts/v061-old-portable-preflight.json`。

补充清理覆盖标准清单遗漏的完整三段版本GitHub下载缓存、双平台旧CI外层ZIP以及两类smoke旧TestId安装器。15个补充旧文件及4个空组目录已完成删除，`executed=true`、`verified=true`、`status=complete`，记录为 `artifacts/v061-extra-cleanup-result.json`。独立复查全部17项标准路径、15个补充文件和4个组目录均已不存在。

清理覆盖0.5.1及0.6.0旧安装分发，当前0.6.1分发、实际安装、原工程、源码、日志及验证报告保留。后续每轮同时核对标准清单和补充清单的命名覆盖范围，已写入项目迭代约定。

## 既有功能依据

0.6.0已完成14个TIMER及SysTick/看门狗模型、真实Keil固件IRQ、两平台源码和安装验收，并在最终冻结Windows包完成11项界面及23项DEMO2可信DOM输入检查。历史事实及其限制保留在 [0.6.0验收](validation-v0.6.md)。本版软件文件保持单独的源码、选定CI、摘要和实际升级证据。

定时器使用GD32F470数据手册及GD32F4xx用户手册相应分类，RTC日历属于独立章节。虚拟时钟、滤波、死区及看门狗跨时钟域采用功能模型，实板及逐周期时序需要独立验收。
