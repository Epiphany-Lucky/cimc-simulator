# V0.1 实现前设计

状态：用户已授权实现。日期：2026-11-15。

授权依据：用户“从现在开始写入，并且将第一版的文件存入GitHub中做好项目迭代工作……先进行第一版吧”；补充“也要提供HTML网页版的”；板卡选择“V2.0（优先）”。此授权承接上一轮需求审批，不另设重复确认。

## 复杂度

计划文件清单（至少21个）：README.md、CHANGELOG.md、.gitignore、.ai-governance/capability-map.md、docs/requirements-approved.md、docs/implementation-v0.1.md、docs/validation-v0.1.md、web/index.html、web/styles.css、web/app.js、web/board-v2.json、engine/server.py、engine/simulator.py、engine/requirements.txt、desktop/CimcLab.csproj、desktop/App.cs、firmware/demo.c、firmware/linker.ld、tests/test_engine.py、scripts/build.ps1、.github/workflows/ci.yml。

| 条件 | 命中 | 依据 |
|---|---|---|
| H1 五个以上文件 | 是 | 上述21个明确路径 |
| H2 数据库结构 | 否 | 无数据库 |
| H3 对外接口 | 是 | 本地HTTP界面与仿真内核协议 |
| H4 认证权限 | 否 | 无用户账户或身份系统，本地服务限定回环与来源 |
| H5 资金计费 | 否 | 无交易 |
| H6 修改已有公共模块 | 否 | 新建独立目录，不改现有项目 |
| H7 新依赖 | 是 | ARM引擎、WebView2、打包工具 |
| H8 跨端协同 | 是 | HTML、Windows宿主、内核 |
| H9 构建CI | 是 | 打包与GitHub Actions |
| H10 未明口径 | 否 | 已确认V2.0和纯仿真；硬件未知项按证据待核验，不自行替换 |

判定：大。无降级。现状证据：Get-Command确认.NET10、Python、arm-none-eabi-gcc、Git与gh可用；新建目录前Test-Path为False；用户GitHub身份Epiphany-Lucky；没有现有同名仓库。

## 技术设计

- 共用HTML/CSS/JavaScript工作台，桌面由WPF WebView2承载；网页版通过本地HTTP服务打开。同一固件内核供两端使用。
- Apple风格参考落实为低饱和背景、清晰字阶、克制阴影、圆角层次、短过渡、键盘焦点与减少动画设置。应用保持独立标识。
- 优先验证Python Unicorn的ARM M-class执行；采用经验证的GD32寄存器模型。Renode仍是后续完整外设/中断平台候选，不声称已有可用官方GD32模型。
- 固定板级网络与用户跳线分离；未知底板网络不冒充已核验。读写未实现外设明确诊断。功能支持范围写入交付说明。
- HEX校验与地址解析、BIN装载地址/向量表检查、固件执行/暂停/复位、GPIO LED/KEY、OLED、USART内部交互为本次实现重点。
- 示例固件由交付C源代码交叉编译生成，明确编译器来源；加载器同时接受用户Keil HEX/BIN，实际兼容范围以样本验证为准。
- 不采用预设OLED动画代替固件，不采用随意GPIO映射，不引入真实COM或扩展板功能。

## 影响与风险

影响仅限新项目目录和新私有GitHub仓库。原研究资料与其他项目保留。风险为V2原理图/原例程资料不完整、ARM外设支持子集、Windows运行时依赖。通过证据表、缺失外设诊断、可复现测试、明确发布说明处理；不伪造硬件验证结论。

## 验收

1. 真实编译的HEX与BIN加载及ARM执行产生一致GPIO/串口/OLED输出。
2. 按键输入、附加跳线影响固件；固定网络保持不变，冲突可见。
3. 串口输入由固件生成回复，不由界面生成。
4. 未支持访问和格式错误可诊断；持续运行不阻塞界面。
5. 浏览器和Windows EXE使用同一内核并通过界面操作检查。
6. 构建输出、测试记录、源码提交、版本标签、发布附件均可追溯。

G3结果将在docs/validation-v0.1.md逐项记录，未通过项目明确保留。
