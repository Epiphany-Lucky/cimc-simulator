# 能力地图

2026-11-15 初始化。新目录 `cimc-simulator` 初始只有目录与已审批范围文档；不修改现有 epiphany 项目。

| 能力 | 处理 | 入口 | 理由与边界 |
|---|---|---|---|
| 需求约束 | 复用 | docs/requirements-approved.md | 用户已授权第一版开发，新增 HTML 网页版与 V1.0 目标（用户最新修订） |
| 硬件资料 | 复用 | ../CIMC2026-research/资料索引.txt | V1四页原理图已核对；固定网络和原排针脚号录入board-v1.json |
| 共享界面 | 新增 | web/index.html, web/styles.css, web/app.js | 新项目没有可用的仿真工作台 |
| 固件内核与外设 | 新增 | engine/ | 不以网页动画替代ARM机器码执行 |
| 桌面容器 | 新增 | desktop/ | 同一HTML用于WebView2与浏览器 |
| 验证固件 | 新增 | firmware/ | 需要可复现的真实机器码链路测试 |
| 自动检查与发布 | 新增 | tests/, scripts/, .github/workflows/ | 建立可重复构建和版本迭代 |
| 笔记本适配 | 修改 | desktop/App.cs, web/styles.css | 按实际监视器工作区/DPI约束窗口，短屏布局不缩小全局字体 |
| 板载ADC | 新增并集成 | engine/adc.py, firmware/adc_probe.c | PC0固定输入；软件触发单次转换，结果来自真实MMIO |
| 板载SPI Flash | 新增并集成 | engine/spiflash.py, firmware/spiflash_probe.c | 复用Unicorn/SPI1/GPIO网络，GD25Q40E轮询指令子集 |
| 固定端点保护 | 修改 | scripts/generate-board-v1.py, engine/simulator.py | 固定网络和H7只读；H6只准两种模式；v1工程迁移和原子拒绝 |
| 原图阅读 | 复用并新增入口 | docs/reference/, web/assets/schematics/, web/app.js | 原始V1 PDF不变，四页渲染预览在侧栏只读查看，复用现有弹窗/静态服务 |
| Windows安装升级卸载 | 新增 | packaging/windows/, scripts/build-windows-installer.ps1 | Inno当前用户安装，固定产品ID；验收独立TestAppId不触碰正式安装 |
| Linux发行与应用菜单 | 新增 | scripts/build-linux.sh, packaging/linux/ | Ubuntu22.04构建onedir、deb、tar；复用原固件内核和浏览器界面 |
| Linux会话生命周期 | 扩展 | engine/desktop_session.py, engine/server.py | 用户级独占锁、当前实例退出校验、180秒无客户端退出；WPF生命周期不变 |
| 软件更新 | 新增并复用界面 | engine/updates.py, web/app.js | 固定GitHub版本源、语义版本比较、缓存；设置内检查和应用内提醒；原外链处理复用 |
| Packages发布 | 扩展 | .github/workflows/packages.yml, packaging/registry/ | 官方GHCR OCI安装文件包，与Release安装文件哈希一致；无长期凭证 |
| 多固件共同烧录 | 新增并复用内核 | engine/firmware_images.py, engine/simulator.py, web/app.js | 多HEX/BIN按实际段共同占用512KiB内部Flash，拒绝真实重叠；无固定槽数，单文件4MiB、集合导出JSON8MiB；复用ARM取指与原外设 |
| 启动向量与真实Bootloader | 扩展 | engine/simulator.py, firmware/boot_probe.c, firmware/app_probe.c, firmware/build-boot-probes.ps1 | 独立启动向量、MSP/VTOR/BX跨镜像跳转，三份Keil产物与SysTick证据；不扩展为FMC在线IAP |
| 工程完整固件恢复 | 扩展 | engine/firmware_images.py, engine/simulator.py, tests/test_multifirmware.py | v3保存完整集合和启动选择，整体预检后提交；v1/v2保持兼容，不保存CPU/RAM/SPI运行快照 |
| 多固件发布与验收证据 | 扩展 | docs/implementation-v0.4.md, docs/validation-v0.4.md, docs/releases/v0.4.0.md, firmware/BOOT_PROBES.md | 区分源码/真实fixture/安装包/在线发布证据；发布验收后清理旧分发附件，保留源码、标签、公告与报告；GHCR仍私有 |
| SysTick指令预算调度 | 修复并扩展 | engine/simulator.py, tests/test_scheduler.py, tests/package_smoke.py | 异常进入/返回在同预算内连续执行；被截断指令不计数；每64条hook与异常边界检查宿主时间片，按剩余周期休眠；真实固件/分块一致性/响应性/冻结包吞吐验证，保持功能模型边界 |

禁区：不改原板固定网络；不猜测未知连线；不把未建模访问当成功；不上传本地密钥、个人目录或未授权第三方完整工程；不承诺已验证任意Keil固件。
