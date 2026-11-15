# V0.3 安装版验收

日期：2026-11-15。V0.3新增安装方式和Linux会话管理，CIMC V1外设模型沿用V0.2。

## 已完成的源码与构建预检

- Windows11 / Python3.13：`python -m unittest discover -s tests -v`，59项中50项通过，9项Linux专用测试按平台跳过。
- WSL Ubuntu26.04 / Python3.14.4：59项全部通过，无跳过。Unicorn wheel仅解包至项目临时目录并通过PYTHONPATH加载，没有改动WSL系统包。该结果是Linux源码执行证据，不替代冻结包验收。
- Windows `scripts/build.ps1 -Version 0.3.0`：本地内核、WPF自包含宿主、Windows/HTML目录构建完成。
- Inno Setup6.7.4官方安装程序已通过固定SHA256及Authenticode发布者Pyrsys B.V.校验；中文翻译采用官方固定commit和SHA256。

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

Windows隔离安装、Ubuntu冻结包、卸载与本机WSL冻结包的实际结果在本次发布前回填。GitHub工作流保留对应安装测试日志与报告，不将“成功生成安装文件”视为安装后可运行的证明。

## 边界

- Linux构建基线Ubuntu22.04/glibc2.35，目标Ubuntu22.04+/Debian12+ amd64。没有验证所有发行版、ARM64或musl系统。
- Linux使用系统图形浏览器；无浏览器时给出失败并停止本次服务。CI的界面证据为无头Chromium，不是物理Ubuntu桌面矩阵测试。
- Windows本机实测包含WebView2；CI安装测试可跳过交互桌面部分，仅验证安装后内核和卸载。
- 两种安装包没有商业代码签名；下载源与摘要可在GitHub发行页核对。
- 安装不会增加未实现的ADC/SPI/RTOS功能。Flash及MCU内存仅保留在当前内核会话中；退出前应导出需要保留的接线工程。
