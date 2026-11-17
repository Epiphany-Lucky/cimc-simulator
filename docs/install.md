# 安装、升级与卸载

本文对应版本0.6.0。安装包与在线发布验收状态见 [本版记录](validation-v0.6.md)，实际可下载版本以 [公开 Releases](https://github.com/Epiphany-Lucky/cimc-simulator/releases) 为准。本版提供 V1/V2 功能模型、多固件共同烧录与启动选择，以及14个 TIMER、SysTick和两种看门狗；安装程序不需要真实开发板、COM口、Keil或Python开发环境。

## Windows x64

下载 `CIMC-Studio-0.6.0-Setup-x64.exe`，双击后按向导安装。默认安装到当前用户的 `%LOCALAPPDATA%\Programs\CIMC Studio`，无需管理员权限。可修改安装位置和选择桌面快捷方式。

开始菜单提供 CIMC Studio 和 Web 入口。桌面入口使用WPF/WebView2，关闭窗口自动停止自己启动的内核；Web入口打开同一浏览器工作台，保持服务窗口运行。若没有WebView2 Runtime，桌面入口会使用系统浏览器。

后续运行同一应用ID的新版安装器，可沿用安装位置和快捷方式选择。更新前保存工程并关闭正在运行的工作台。0.4 的 v3 工程包含已烧录固件集合；旧版 v1/v2 工程没有这些固件字节，升级前也应保留原始 HEX/BIN。卸载在Windows“已安装的应用”中选择CIMC Studio；卸载仅删除安装器管理的文件，不清空用户导出的工程、固件或WebView2数据目录。

Windows ZIP和HTML ZIP仍是免安装选择，必须完整解压后运行，不能仅复制主EXE。

## Ubuntu / Debian amd64

目标系统：Ubuntu22.04及更新版本、Debian12及更新版本的amd64图形桌面。正式二进制在Ubuntu22.04构建；测试覆盖的具体环境以验收记录为准。此包不是ARM64或Alpine/musl版本。

在安装包所在目录执行：

```bash
sudo apt install ./cimc-studio_0.6.0_amd64.deb
```

安装后从应用菜单点击“CIMC Studio”，或在终端执行 `cimc-studio`。程序启动本地内核，并在系统默认图形浏览器中显示工作台。安装包携带Python、Unicorn及全部页面/原理图资源；系统需提供浏览器和xdg-utils。依赖缺失时由apt按系统仓库安装。

程序文件位于 `/opt/cimc-studio`，命令入口为 `/usr/bin/cimc-studio`，应用菜单文件在 `/usr/share/applications/cimc-studio.desktop`。运行时无需写入这些系统目录，也不要用sudo启动应用。

每个用户只复用自己的桌面会话。再次点击图标会打开当前工作台；点击网页右上角“退出应用”立即停止本次内核。关闭所有工作台页面后，180秒没有客户端活动也会退出。浏览器长时间冻结/丢弃所有标签页时同样会触发此规则。固件RAM及SPI Flash会话内容在退出后清空，工程应先下载保存。

安装新版同名 `.deb` 即可升级。升级前先退出工作台，避免旧进程继续占用旧内核。卸载：

```bash
sudo apt remove cimc-studio
```

浏览器中的偏好和用户导出文件不由包管理器删除。会话锁/记录/日志在本用户的XDG运行目录；没有可用运行目录时回退到 `~/.cache/cimc-studio/runtime`，不会扫描或终止其他进程。

## Linux 便携包

完整解压 `CIMC-Studio-0.6.0-linux-x64.tar.gz`，保留内部符号链接和执行权限，然后运行目录中的 `./cimc-studio`。同样使用本机默认浏览器和同一套桌面会话规则。不要用会丢失符号链接的Windows ZIP工具重打包Linux目录。

## 多固件和工程迁移

安装后仍可从固件卡直接导入单个 HEX/BIN。需要 Bootloader 和应用共同存在时，点“多固件”持续添加文件，为 BIN 填写编译时链接地址，选定启动项后“一次烧录”，再点“运行”。HEX 使用内置地址，不会自动把文件重定位到其他区域。

没有固定槽位数量；限制为 MCU 内部 Flash 实际写入总范围 512 KiB、每个原始文件 4 MiB、固件集合导出 JSON 8 MiB。HTTP 请求最多 16 MiB，用于容纳集合和工程外围字段。文件很大但有效 Flash 数据很少的 HEX 仍受文件/序列化上限约束。真实写入区间不能重叠，错误不应覆盖正在使用的固件集合。

三份示例位于 `firmware/`：`bootloader_probe`、`app_a_probe`、`app_b_probe` 的地址分别为 `0x08000000`、`0x08010000`、`0x08020000`。从 Bootloader 启动后在 CH340/USART0 终端发送字符 `1` 或 `2`，实际程序执行 MSP/VTOR/BX 跳转并运行所选应用的 SysTick。可直接选择 A/B 启动；查看 LED 需添加相应 PD10/PD11→LED1/LED2 跳线。详见 [固件说明](../firmware/BOOT_PROBES.md)。

v3 工程包含固件原始字节、地址、启动向量，以及接线、串口模式、ADC 电压。导入后从选定入口复位运行，不恢复暂停点、CPU 寄存器、RAM 或外置 SPI Flash 内容。v1/v2 工程仍可导入，但只恢复旧格式包含的设置，保留当前已装入固件；v3 中明确没有固件的工程会清空当前固件集合。保存的工程含固件内容，按本地文件自行保管。

这里的“烧录”指向仿真内部 Flash 装入镜像。V2 用户固件可通过既有 FMC 模型执行在线擦写与应用升级，具体协议和已验证路径见对应公告。系统 ROM Bootloader 和其他芯片功能按模型覆盖范围逐项验收。

## 检查更新与新版本提醒

在侧栏“设置”点击“检查更新”。窄屏可从右上角“C”打开“软件更新与设置”。默认在启动时检查，保持工作台打开期间每6小时再检查；开启提醒时，新版会显示应用内提示及设置入口圆点。可关闭“新版本提醒”，仍可手动检查。关闭应用后不会运行独立推送服务。

更新源固定为本项目公开的GitHub Releases，包含可下载的预览版。设置中可直接下载，查看进度并校验大小及SHA-256。保存工程后点击“安装并重启”，Windows沿用实际安装位置，退出应用后安装并重新启动。Linux系统安装请求系统授权，Linux便携包提供已校验文件夹入口。GitHub限流等查询错误会在更新设置中显示，可稍后重试。

## GitHub Packages

仓库关联两个 OCI 安装文件包，对应版本使用 `ghcr.io/epiphany-lucky/cimc-studio-windows:0.6.0` 与 `ghcr.io/epiphany-lucky/cimc-studio-linux:0.6.0`及`latest`；实际摘要和结果见本版验收记录。它们保存与 Releases 相同的安装文件及 SHA256 清单，供版本化拉取；普通安装请直接下载公开 Releases 中的 EXE/DEB。这些 OCI 包是文件容器，不是可运行的仿真服务镜像。

例如使用Docker提取Linux安装文件（不会启动容器）：

两个 GHCR 包当前仍为私有；公开仓库不会自动改变包的可见性，直接下载公开 Releases 不受影响。以下示例需要目标版本已上传且账户有读取权限，并已完成 `docker login ghcr.io`。只有包所有者将对应包设置为 Public 后，才能匿名拉取。

```bash
docker pull ghcr.io/epiphany-lucky/cimc-studio-linux:0.6.0
id=$(docker create ghcr.io/epiphany-lucky/cimc-studio-linux:0.6.0 /__extract_only__)
mkdir -p cimc-installers
docker cp "$id:/packages/." ./cimc-installers/
docker rm "$id"
cd cimc-installers
sha256sum --check SHA256SUMS.txt
```

## 旧版本分发文件

按项目所有者的更新规则，新版本构建、安装运行、文件摘要、Packages 回拉和在线更新识别全部通过后，才清理已枚举的旧安装包、便携包、旧 Release 附件及对应 Packages 版本。源码、提交、标签、Release 公告和验证报告保留；旧附件不保证长期下载，可据保留的源码和构建说明重建。此清理不扫描或删除用户的现有安装、导出工程、固件及个人文件。

## 常见检查

- 界面提示内核未连接：从安装后的应用入口重新打开，不要直接双击HTML文件。
- Linux无浏览器：先确认系统能通过 `xdg-open https://example.com` 打开默认图形浏览器，再启动应用；失败时查看用户会话目录中的 `desktop.log`。
- 退出后原网页不能继续操作：这是已结束的会话，关闭该页，再从应用菜单启动。
- 硬件不支持诊断：安装包没有扩展CPU/外设兼容范围；参见 `hardware-evidence.md` 与 `quick-start.md`。
- 发行包未进行商业代码签名。操作系统显示发布者提示时，应以本项目GitHub发行页和文件校验值核对来源。

## 应用内下载与安装

0.5 起可在设置中下载更新，检查大小及 SHA-256 后点击“安装并重启”。Windows 使用注册表中的实际安装位置，先退出自有内核与窗口，再运行安装器。失败提示会给出 update-helper.log 路径。Linux 系统版通过 pkexec 请求安装授权，便携版显示已校验包所在目录。下载失败可重试。安装前可直接点击“保存当前工程”。
