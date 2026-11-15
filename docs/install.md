# 安装、升级与卸载

版本0.3.0。仿真范围沿用V1.0功能模型；安装程序不需要真实开发板、COM口、Keil或Python开发环境。

## Windows x64

下载 `CIMC-Studio-0.3.0-Setup-x64.exe`，双击后按向导安装。默认安装到当前用户的 `%LOCALAPPDATA%\Programs\CIMC Studio`，无需管理员权限。可修改安装位置和选择桌面快捷方式。

开始菜单提供 CIMC Studio 和 Web 入口。桌面入口使用WPF/WebView2，关闭窗口自动停止自己启动的内核；Web入口打开同一浏览器工作台，保持服务窗口运行。若没有WebView2 Runtime，桌面入口会使用系统浏览器。

后续运行同一应用ID的新版安装器，可沿用安装位置和快捷方式选择。更新前保存接线工程并关闭正在运行的工作台。卸载在Windows“已安装的应用”中选择CIMC Studio；卸载仅删除安装器管理的文件，不清空用户导出的工程、固件或WebView2数据目录。

Windows ZIP和HTML ZIP仍是免安装选择，必须完整解压后运行，不能仅复制主EXE。

## Ubuntu / Debian amd64

目标系统：Ubuntu22.04及更新版本、Debian12及更新版本的amd64图形桌面。正式二进制在Ubuntu22.04构建；测试覆盖的具体环境以验收记录为准。此包不是ARM64或Alpine/musl版本。

在安装包所在目录执行：

```bash
sudo apt install ./cimc-studio_0.3.0_amd64.deb
```

安装后从应用菜单点击“CIMC Studio”，或在终端执行 `cimc-studio`。程序启动本地内核，并在系统默认图形浏览器中显示工作台。安装包携带Python、Unicorn及全部页面/原理图资源；系统需提供浏览器和xdg-utils。依赖缺失时由apt按系统仓库安装。

程序文件位于 `/opt/cimc-studio`，命令入口为 `/usr/bin/cimc-studio`，应用菜单文件在 `/usr/share/applications/cimc-studio.desktop`。运行时无需写入这些系统目录，也不要用sudo启动应用。

每个用户只复用自己的桌面会话。再次点击图标会打开当前工作台；点击网页右上角“退出应用”立即停止本次内核。关闭所有工作台页面后，180秒没有客户端活动也会退出。浏览器长时间冻结/丢弃所有标签页时同样会触发此规则。固件RAM及SPI Flash会话内容在退出后清空，接线工程应先下载保存。

安装新版同名 `.deb` 即可升级。升级前先退出工作台，避免旧进程继续占用旧内核。卸载：

```bash
sudo apt remove cimc-studio
```

浏览器中的偏好和用户导出文件不由包管理器删除。会话锁/记录/日志在本用户的XDG运行目录；没有可用运行目录时回退到 `~/.cache/cimc-studio/runtime`，不会扫描或终止其他进程。

## Linux 便携包

完整解压 `CIMC-Studio-0.3.0-linux-x64.tar.gz`，保留内部符号链接和执行权限，然后运行目录中的 `./cimc-studio`。同样使用本机默认浏览器和同一套桌面会话规则。不要用会丢失符号链接的Windows ZIP工具重打包Linux目录。

## 检查更新与新版本提醒

在侧栏“设置”点击“检查更新”。窄屏可从右上角“C”打开“软件更新与设置”。默认在启动时检查，保持工作台打开期间每6小时再检查；开启提醒时，新版会显示应用内提示及设置入口圆点。可关闭“新版本提醒”，仍可手动检查。关闭应用后不会运行独立推送服务。

更新源固定为本项目公开的GitHub Releases，包含可下载的预览版；不会读取或发送固件、接线工程、串口数据。断网或GitHub限流只影响更新查询，不影响本地仿真。点击对应系统的下载链接后，保存工程并退出应用，再运行安装包升级；程序不静默覆盖当前安装。

## GitHub Packages

仓库侧边栏Packages对应两个OCI安装文件包：`ghcr.io/epiphany-lucky/cimc-studio-windows:0.3.0` 与 `ghcr.io/epiphany-lucky/cimc-studio-linux:0.3.0`。它们保存与Releases相同的安装文件及SHA256清单，供版本化拉取；普通安装请直接下载Releases中的EXE/DEB。这些OCI包是文件容器，不是可运行的仿真服务镜像。

例如使用Docker提取Linux安装文件（不会启动容器）：

当前两份Packages已上传，但包本身尚为私有；直接下载公开Releases不受影响。仓库所有者在各包的Package settings中设置Public后，下面的匿名拉取命令即可使用。

```bash
docker pull ghcr.io/epiphany-lucky/cimc-studio-linux:0.3.0
id=$(docker create ghcr.io/epiphany-lucky/cimc-studio-linux:0.3.0 /__extract_only__)
mkdir -p cimc-installers
docker cp "$id:/packages/." ./cimc-installers/
docker rm "$id"
cd cimc-installers
sha256sum --check SHA256SUMS.txt
```

## 常见检查

- 界面提示内核未连接：从安装后的应用入口重新打开，不要直接双击HTML文件。
- Linux无浏览器：先确认系统能通过 `xdg-open https://example.com` 打开默认图形浏览器，再启动应用；失败时查看用户会话目录中的 `desktop.log`。
- 退出后原网页不能继续操作：这是已结束的会话，关闭该页，再从应用菜单启动。
- 硬件不支持诊断：安装包没有扩展CPU/外设兼容范围；参见 `hardware-evidence.md` 与 `quick-start.md`。
- 发行包未进行商业代码签名。操作系统显示发布者提示时，应以本项目GitHub发行页和文件校验值核对来源。
