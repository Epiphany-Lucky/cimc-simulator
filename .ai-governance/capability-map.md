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

禁区：不改原板固定网络；不猜测未知连线；不把未建模访问当成功；不上传本地密钥、个人目录或未授权第三方完整工程；不承诺已验证任意Keil固件。
