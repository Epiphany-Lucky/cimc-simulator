# 能力地图

2026-11-15 初始化。新目录 `cimc-simulator` 初始只有目录与已审批范围文档；不修改现有 epiphany 项目。

| 能力 | 处理 | 入口 | 理由与边界 |
|---|---|---|---|
| 需求约束 | 复用 | docs/requirements-approved.md | 用户已授权第一版开发，新增 HTML 网页版与 V2.0 目标 |
| 硬件资料 | 复用 | ../CIMC2026-research/资料索引.txt | 已有官方图片；完整连接映射仍须核验 |
| 共享界面 | 新增 | web/index.html, web/styles.css, web/app.js | 新项目没有可用的仿真工作台 |
| 固件内核与外设 | 新增 | engine/ | 不以网页动画替代ARM机器码执行 |
| 桌面容器 | 新增 | desktop/ | 同一HTML用于WebView2与浏览器 |
| 验证固件 | 新增 | firmware/ | 需要可复现的真实机器码链路测试 |
| 自动检查与发布 | 新增 | tests/, scripts/, .github/workflows/ | 建立可重复构建和版本迭代 |

禁区：不改原板固定网络；不猜测未知连线；不把未建模访问当成功；不上传本地密钥、个人目录或未授权第三方完整工程；不承诺已验证任意Keil固件。
