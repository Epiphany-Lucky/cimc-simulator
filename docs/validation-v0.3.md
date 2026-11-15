# V0.3 安装版验收

日期：2026-11-15。V0.3新增安装方式和Linux会话管理，CIMC V1外设模型沿用V0.2。

## 已完成的源码与构建预检

- Windows11 / Python3.13：`python -m unittest discover -s tests -v`，73项中63项通过，10项Linux专用测试按平台跳过。
- WSL Ubuntu26.04 / Python3.14.4：73项全部通过，无跳过。Unicorn wheel仅解包至项目临时目录并通过PYTHONPATH加载，没有改动WSL系统包。该结果是Linux源码执行证据，不替代冻结包验收。
- Windows `scripts/build.ps1 -Version 0.3.0`：本地内核、WPF自包含宿主、Windows/HTML目录构建完成。
- Inno Setup6.7.4官方安装程序已通过固定SHA256及Authenticode发布者Pyrsys B.V.校验；中文翻译采用官方固定commit和SHA256。
- 更新查询的13项离线测试通过；Edge界面验收覆盖自动提示、手动检查、关闭提醒后重载、断网状态、安全下载链接和390px设置入口。
- 运行固件后退出的原始Linux关闭路径在10次复现中出现5次native崩溃；改为等待有界执行线程结束后，10次全部正常退出且stderr为空。新增重复真实固件退出回归，不接受非零退出码。

## 安装器验收程序

Windows使用 `tests/windows_installer_smoke.py`，每次编译随机TestAppId、测试开始菜单组和独立安装目录，验证当前用户安装、HKCU卸载项、桌面/菜单快捷方式、已安装目录真实HEX/BIN/ADC/SPI/OLED执行、WPF原图阅读、重复安装、卸载及用户文件保留。不会试装正式应用ID或删除用户现有程序。

Linux在GitHub Ubuntu22.04构建PyInstaller onedir，再由dpkg生成amd64包。验收依次执行：

```bash
sudo apt-get install -y --no-install-recommends ./artifacts/cimc-studio_0.3.0_amd64.deb
python tests/package_smoke.py /opt/cimc-studio
python tests/linux_browser_smoke.py /opt/cimc-studio
python tests/linux_install_smoke.py /opt/cimc-studio
sudo dpkg --remove cimc-studio
```

测试覆盖安装后的真实机器码、Chromium界面、四页原图/下载、笔记本布局、ADC/Flash、单实例复用、同源/实例标识校验、主动退出、无活动退出、异常进程退出后的锁恢复，以及安装目录不写入。测试只结束自身创建的进程。

## 最终发行结果

- Windows11本机隔离安装验收通过，报告 `artifacts/installer-smoke-74c50dc0d587/result.json`。已安装的WPF窗口在125% DPI下位于工作区内，原理图阅读、真实固件运行、快捷方式、覆盖安装、卸载及用户文件保留均通过。
- GitHub工作流 `43714112725` 的Windows安装、固件执行、覆盖安装和卸载通过；Ubuntu22.04与Windows源码测试通过。
- Ubuntu22.04首次构建、apt安装和安装后HEX/BIN/OLED/UART/ADC/H6/SPI测试通过。首次浏览器验收中的原图测试遇到测试同步问题：前一组已有12条跳线，计数不能证明异步加载完成；现已改为等待本次加载响应后再比较接线ID，继续执行完整验收。
- GitHub工作流 `43714913743` 已通过Ubuntu冻结包的完整浏览器验收（含OLED/ADC/SPI/原图/退出界面）。该轮运行固件后退出的native错误已在源码中修复，具体复现与回归见上文。
- 最终冻结安装包以[本版本构建验收工作流](https://github.com/Epiphany-Lucky/cimc-simulator/actions/workflows/ci.yml)及发行页附带的验收记录为准。发布门槛包含Windows安装/升级/卸载、Ubuntu实际安装/浏览器/生命周期/卸载、Debian12容器实际安装/固件/生命周期/卸载，以及同一Linux便携包在WSL中的执行；全部通过后才发布成品。GitHub保存安装日志、报告与界面截图。

## 最终候选成品验收（提交1e3b7dd）

- [GitHub完整验收43716184712](https://github.com/Epiphany-Lucky/cimc-simulator/actions/runs/43716184712)：两个源码任务、Windows安装任务和Linux安装任务全部成功。
- Ubuntu22.04：实际apt安装、冻结HEX/BIN/OLED/UART/ADC/SPI、全部Chromium界面/原图/笔记本/更新检查验收、会话退出及恢复、dpkg卸载通过。
- Debian12官方容器：实际安装同一个DEB、真实固件、会话生命周期与卸载通过，`linux-debian12-verification.json`为passed。
- WSL Ubuntu26.04：从同一个CI便携包完整解压后，固件与生命周期验收通过；tar.gz SHA256为 `e23d30ce86286df0cdf38f162d72742b9188350effb78a3823e6ca94d46ff90d`。没有安装或修改WSL系统组件。
- Windows11本机最新版：`installer-smoke-dbb506ebff2c/result.json`全部通过，包含原生WPF、真实固件、125%DPI、原图、覆盖安装和卸载保留用户文件。两ZIP CRC及源码/许可证/文档一致性通过；没有残留测试进程。本机与云端分别构建，安装器文件摘要以各自对应清单为准。
- 公开前只读扫描：8个可达提交、2个旧标签、164个历史blob及当前跟踪文件未发现明显密钥/私钥/已跟踪env。当前硬件研究文档已去除非必要本机路径与参赛编号，保留原作者及官方资料来源；未改写历史。

## 发布与匿名访问检查

版本v0.3.0已发布，仓库已切换PUBLIC，匿名GitHub API和安装包校验清单下载通过。实际公开版本源返回0.3.0；当前版本不重复提示，0.2.0客户端识别更新且获得四种有效下载链接。

[Packages发布运行43717406799](https://github.com/Epiphany-Lucky/cimc-simulator/actions/runs/43717406799)两个任务通过，推送后重新拉取并校验全部5个安装文件。GHCR内容摘要：Windows `sha256:8f612261dd8ff1002fc73d50f817f5161aeda7f642d3e5ac997003d4720dd662`；Linux `sha256:34c8354d815210020e8ca8e63e4b1bf634ee506fda0851cf1af49f176f8b628c`。

待处理的外部设置：两个GHCR包仍拒绝匿名拉取（401）。仓库公开不自动公开包；官方方式为包页面Package settings → Change visibility → Public。当前桌面页面控制工具在初始化时报告 `failed to write kernel assets`，重置重试仍失败，因此没有执行这项独立可见性修改。源码和Releases安装文件已经公开，不受该设置影响。

## 边界

- Linux构建基线Ubuntu22.04/glibc2.35，目标Ubuntu22.04+/Debian12+ amd64。没有验证所有发行版、ARM64或musl系统。
- Linux使用系统图形浏览器；无浏览器时给出失败并停止本次服务。CI的界面证据为无头Chromium，不是物理Ubuntu桌面矩阵测试。
- Windows本机实测包含WebView2；CI安装测试可跳过交互桌面部分，仅验证安装后内核和卸载。
- 两种安装包没有商业代码签名；下载源与摘要可在GitHub发行页核对。
- 安装不会增加未实现的ADC/SPI/RTOS功能。Flash及MCU内存仅保留在当前内核会话中；退出前应导出需要保留的接线工程。
