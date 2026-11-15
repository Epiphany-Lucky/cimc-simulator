# V0.3 实现前设计：Windows 与 Ubuntu/Debian 安装包

日期：2026-11-15。授权：用户“我想要实现一个包来完成安装，win和Linux两个版本”，随后确认“Ubuntu / Debian”。沿用此前 GitHub 版本迭代授权。本文件在实现前完成；用户已直接要求实施，不重复请求同一范围许可。

## G1 复杂度判定

具体文件：packaging/windows/cimc-studio.iss、scripts/setup-inno.ps1、scripts/build-windows-installer.ps1、tests/windows_installer_smoke.py、packaging/linux/cimc-studio.desktop、packaging/linux/cimc-studio.svg、scripts/build-linux.sh、engine/desktop_session.py、engine/server.py、tests/test_desktop_session.py、tests/linux_install_smoke.py、tests/package_smoke.py、tests/ui_smoke.py、tests/laptop_smoke.py、tests/schematic_smoke.py、scripts/build.ps1、.github/workflows/ci.yml、desktop/App.cs、desktop/CimcLab.csproj、engine/simulator.py、web/app.js、web/index.html、web/styles.css、README.md、CHANGELOG.md、THIRD_PARTY_NOTICES.md、docs/install.md、docs/validation-v0.3.md、docs/releases/v0.3.0.md、.ai-governance/capability-map.md。

| 条件 | 命中 | 依据 |
|---|---|---|
| H1 文件≥5 | 是 | 上列30个具体文件 |
| H2 数据库 | 否 | 无数据库变更 |
| H3 对外接口 | 是 | Linux桌面会话状态、同源退出接口；现有仿真命令不改 |
| H4 权限/鉴权 | 是 | 新增退出控制需检查本机同源和会话标识；用户级运行目录权限 |
| H5 金额交易 | 否 | 无交易 |
| H6 公共模块 | 是 | server由源码启动、WPF启动、冻结发行包、API验收等路径调用 |
| H7 新依赖 | 是 | Inno Setup仅为构建依赖；Linux运行复用Python标准库与Unicorn |
| H8 跨端 | 是 | Linux会话与网页退出入口配合，Windows保持原宿主生命周期 |
| H9 构建CI | 是 | 两种系统安装包、Linux构建与安装卸载验收 |
| H10 业务口径 | 否 | 用户已确认Ubuntu/Debian；现有x64目标沿用 |

[复杂度判定]
- 涉及文件数：30，依据上列清单。
- 硬条件命中：H1 H3 H4 H6 H7 H8 H9。
- 未命中项：H2 H5 H10。
- 判定结果：大，无降级。进入G2。

## G2 调查与能力地图

- `scripts/build.ps1:1` 当前0.2.0，只生成Windows和HTML ZIP。`desktop/CimcLab.csproj:4` 为net10.0-windows/WPF，不能直接在Linux运行。
- `engine/server.py:16` 已区分冻结/源码资源根；`server.py:74` 仅监听127.0.0.1，已有Host/Origin检查；`--open-browser` 已复用HTML但尚无Linux应用会话管理。
- `desktop/App.cs:194` 一带的 StopEngine负责关闭WPF自己的子进程；WebView2用户目录在LocalAppData，不在程序目录。
- `.github/workflows/ci.yml` 现有Windows verify/package作业，`tests/package_smoke.py:19` 硬编码CIMC-Engine.exe。UI验收使用Edge，需要适配Linux Chromium。
- 运行 `rg -n 'installer|安装包|Inno|deb|Linux' scripts desktop .github engine README.md`，除debug路径误命中以外，没有已有安装器实现。`.ai-governance/capability-map.md` 已读取。
- Windows安装工具调查来自windows_installer子代理：本机常见位置无ISCC/NSIS；官方Inno Setup6.7.4可固定版本下载，SHA256 `a549929319f9120716677c685535ca4671e4b937b5fdc87e2585f32d8eb30e8c`，简体中文采用官方翻译文件，固定版本随构建准备（实际6.7.4安装目录未内置该文件）。
- Linux环境调查来自linux_packaging子代理：WSL Ubuntu26.04 x86_64、glibc2.43、dpkg-deb可用，但不适合旧系统兼容构建。采用GitHub ubuntu-22.04构建，随后在WSL验证同一冻结二进制，不安装/改造用户WSL发行版。

| 能力 | 处理 | 边界 |
|---|---|---|
| 原HTML界面及全部仿真外设 | 复用 | 不改硬件网络或机器码语义 |
| Windows宿主和自包含内核 | 复用 | 外加安装、快捷方式、升级和卸载 |
| 安装器 | 新增 | ZIP缺少安装注册/卸载；用Inno封装现有目录 |
| Linux宿主 | 新增 | WPF为Windows专用；复用浏览器界面与冻结内核，避免重新实现整个UI |
| 服务安全与生命周期 | 扩展 | 新行为仅在Linux --desktop启用；普通服务和WPF流程不变 |
| 自动测试和CI | 扩展 | Linux运行真实固件并验证安装后目录和卸载 |

## 方案与边界

1. Windows `CIMC-Studio-0.3.0-Setup-x64.exe`：当前用户安装，无需管理员；默认LocalAppData/Programs/CIMC Studio，中文向导、开始菜单、可选桌面快捷方式、固定AppId升级、系统卸载入口。原导出工程、用户浏览器数据不由卸载器删除。开发验收用独立TestAppId和临时目录，避免触碰真实安装。
2. Linux `cimc-studio_0.3.0_amd64.deb`：目标Ubuntu22.04+/Debian12+ amd64，安装到/opt/cimc-studio，应用菜单与/usr/bin/cimc-studio入口。共享工作台在系统图形浏览器显示。PyInstaller onedir随包携带Python/Unicorn；用tar.gz提供同一目录便携版，保留符号链接。
3. Linux桌面会话：0700用户运行目录、fcntl锁、0600会话记录；重复启动验证当前实例后复用。仅监听localhost。浏览器关闭后180秒无活动自动退出；界面提供仅该模式显示的退出入口；退出接口校验同源及实例标识。普通命令行服务不自动退出。
4. Linux外部浏览器只在子进程环境还原LD_LIBRARY_PATH，避免冻结包库污染系统程序。退出只处理本实例，不按进程名杀进程。运行日志/状态保存在用户目录，/opt只读。
5. GitHub分别构建Windows与Ubuntu版本，安装器和冻结包测试完成后发布v0.3.0；保留v0.2.0可回退。不生成假Linux包，不从Windows交叉打PyInstaller Linux二进制。

不采用：将Windows WPF程序直接装到Linux（平台不支持）；强制用户安装Python/Keil（不能满足可安装成品）；本次切换Electron/Qt重写双端宿主（现有HTML和WPF已可复用，会扩大回归范围）；为本任务修改系统WSL/全局安全设置。

## 验收、风险与回滚

- Windows编译安装器；独立试装、快捷方式/卸载项检查；安装目录内运行实际固件与WPF；覆盖安装；卸载后程序/快捷方式消失，用户文件保留。
- Linux Ubuntu CI跑全套内核测试、冻结HEX/BIN与ADC/SPI/OLED测试；真实dpkg安装/卸载；会话重复启动、退出授权和空闲退出；Chromium浏览器复用已有UI验收。
- 下载CI构建的同一个Linux发行目录，在现有WSL运行冻结内核，以补充较新glibc验证；未实测系统不写成已验证。
- 原理图PDF、四页预览和全部固件/许可证必须包含在两种安装包中。
- 风险：浏览器缺失、发行版glibc、未签名应用的系统提示、升级时运行进程占用。用依赖声明、明确支持版本、同实例退出与独立安装测试控制，不宣称全发行版支持。
- 回滚：安装器只操作其文件清单；Linux由dpkg卸载；用户工程及浏览器数据保留；上一版发行包和Git标签不变。

实际结果记录到docs/validation-v0.3.md，完成后回写能力地图。

## 追加：更新提醒、Packages与公开仓库（2026-11-15）

用户明确要求“将推送更新和检查更新也加进去”，并要求将安装成品放进GitHub Packages后公开代码库。本节记录追加范围；这些操作已获得用户直接授权。

G1：涉及 `engine/updates.py`、`engine/server.py`、`tests/test_updates.py`、`tests/update_ui_smoke.py`、`web/index.html`、`web/app.js`、`web/styles.css`、`desktop/App.cs`、`.github/workflows/packages.yml`、`packaging/registry/Dockerfile`、`docs/install.md`、`docs/validation-v0.3.md`、`docs/releases/v0.3.0.md`、`README.md`、`.ai-governance/capability-map.md`，共15个文件。命中H1/H3/H4/H7/H8/H9；不涉及数据库、资金；功能口径按启动/定时应用内提醒、手动检查、用户下载后安装处理。判定大。

G2调查：`engine/server.py`已有同源本地HTTP API与线程服务；`web/app.js`已有设置偏好、toast、dialog及共享工作台；`desktop/App.cs`为WebView2宿主，外链应交系统浏览器打开；此前无远端版本检查。Packages官方支持Docker/OCI等注册表格式，EXE/DEB不属于原生包类型，因此使用带仓库来源标签的OCI安装文件包，并继续在Releases提供用户可直接双击/apt安装的文件。

方案：新增标准库更新查询模块，只向固定GitHub Releases API读取版本信息，严格校验版本与下载URL并缓存；前端在设置中提供检查、自动提醒开关、最新版本与下载入口，启动后和运行期间定期检查，不打断固件运行。离线不阻止仿真，不自动执行远端安装程序。Windows外链交系统浏览器。以Actions临时GITHUB_TOKEN发布两个GHCR安装文件包，与仓库关联；包发布后按用户要求公开仓库并验证匿名读取。公开前检查跟踪文件及历史中的凭证和超范围资料，不改写用户历史。

不采用：将凭证打入客户端、静默下载执行安装器、将软件更新描述为系统级后台推送、仅上传容器而删除普通安装包。验收包括版本顺序/缓存/错误及URL校验、前端新版本提示和手动检查、Windows外链、公开匿名版本读取、实际GHCR拉取文件哈希与Release一致。
