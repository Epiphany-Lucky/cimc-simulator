# V0.2 实现前设计：笔记本适配、ADC、SPI Flash、固定连线

日期：2026-11-15。状态：用户已直接授权本次修复与新增；不重复请求已授权工作的许可。

授权原话：“分辨率有点超出我的笔记本屏幕了”“ADC的旋钮也加进去”“SPI的Flash也加进去”“将固定接线进行固定化，不允许自行选择”。串口口径已确认：“用 RS232/RS485 模式开关切换，自动按原图连接，禁止任意改线”。LED/KEY 保留此前已确认的排针手动跳线。

## G1

具体文件：desktop/App.cs、desktop/CimcLab.csproj、web/index.html、web/styles.css、web/app.js、engine/simulator.py、engine/server.py、engine/adc.py、engine/spiflash.py、firmware/demo.c、firmware/adc_probe.c、firmware/spiflash_probe.c、firmware/build.ps1、tests/test_engine.py、tests/test_adc.py、tests/test_spiflash.py、tests/ui_smoke.py、tests/laptop_smoke.py、tests/package_smoke.py、scripts/generate-board-v1.py、web/board-v1.json、web/assets/board-v1.svg、scripts/build.ps1、.github/workflows/ci.yml、README.md、CHANGELOG.md、docs/quick-start.md、docs/hardware-evidence.md、docs/validation-v0.2.md、.ai-governance/capability-map.md。

| 条件 | 命中 | 依据 |
|---|---|---|
| H1 文件≥5 | 是 | 上列30个路径，另有生成的Keil测试固件 |
| H2 数据库结构 | 否 | 不引入数据库 |
| H3 接口 | 是 | 新增 adc_voltage、serial_mode 命令及adc/flash状态，工程增加串口模式 |
| H4 鉴权 | 否 | 复用本地同源策略，不改身份权限 |
| H5 金额交易 | 否 | 无交易 |
| H6 公共模块 | 是 | Simulator接口由server、固件测试、外设测试调用 |
| H7 新依赖 | 否 | 复用现有stdlib、Unicorn、WPF/WebView2、Playwright |
| H8 跨端 | 是 | Windows宿主、HTML和内核共同变更 |
| H9 构建CI | 是 | 新版本打包与测试入口 |
| H10 业务口径 | 否 | 串口选择方式已由用户回答；其他引脚按V1原图 |

判定：大，无降级。

## G2 调查与复用

- desktop/App.cs:40 固定 1480×960，最小1080×720，是超出笔记本可用逻辑屏幕的直接原因。Win32_VideoController命令报告本机1920×1080物理分辨率，适配须考虑系统DPI和任务栏。
- web/styles.css 已有宽度断点，可扩展短屏幕规则，不整体缩小字体。
- V1原图第1、2页确认 PC0→ADC→VR1滑臂，VR1为3V3/DGND间10kΩ电位器；SPI Flash为GD25Q40E、PB12 CS、PB13 SCK、PB14 MISO、PB15 MOSI。
- engine/simulator.py:313/359 现有MMIO分派可扩展；已有GPIO/USART图连接与诊断，不新建执行内核。
- scripts/generate-board-v1.py:80 当前将ADC/SPI信号保留在未实现固定网络表，改为有器件模型的固定网络。
- 能力地图已读取，复用现有页面、日志、工程导入导出、固件构建和双端发行流程。

## 设计

1. 桌面初始尺寸限制在监视器可用区域，使用DPI转换后的尺寸；允许缩到笔记本可用尺寸。监视器/DPI改变后重新约束正常窗口。短屏布局保证运行、OLED、LED/KEY、ADC操作可达，串口内容允许纵向滚动。
2. ADC为固定PC0/通道10的0–3.3V旋钮，可拖动并用键盘/滑杆精确调整。API `adc_voltage {voltage}`，state.adc包含voltage/referenceVoltage/value/bits/pin/channel/sampleCount/idealValue。value只在固件实际转换后更新。实现软件触发、单通道、轮询读取的寄存器子集；其他模式明确诊断。
3. SPI Flash通过真实SPI寄存器驱动GD25Q40E模型；包含JEDEC、读、写使能、页编程、擦除和状态读取。Flash会话内容跨MCU复位保留。受支持指令及限制以器件资料和测试记录为准，不假装完整SPI/Flash器件支持。
4. 原固定外设网络及其专用引脚只读，不可选脚或添加改接线。H7由系统固定接通；H6仅允许`serial_mode {mode:rs485|rs232}`按原图两种组合切换。系统管理连接显示只读，不进入用户跳线列表。用户跳线只在空闲GPIO与LED/KEY允许端点之间添加。
5. 接线工程保存串口模式；对V0.1标准H6/H7跳线执行明确迁移，其他试图改接固定端点的工程拒绝，保持导入原子性。

不采用固定百分比缩小整个窗口/网页的方案：DPI和可用工作区变化会再次溢出，且文字和排针命中区域变小。不采用旋钮直接伪造“固件采样结果”或前端生成Flash回复的方案：数据必须经过MCU MMIO。

新增独立ADC/SPI模型模块是为了隔离器件状态，复用Simulator执行与诊断，避免多模块互相覆盖寄存器。此次不扩展外部扩展板，不实现ADC DMA/中断或全速电气时序。

## 验收、风险与回滚

- 检查实际桌面物理窗口不超过当前监视器工作区；1366×768、1280×720、1093×614、1024×600浏览器视口无横向溢出、核心控制可见；保留移动端规则。
- Keil真实机器码读取ADC最低、中间、最高电压值，检查GPIO模拟模式和时钟条件；无转换时采样值不得被界面输入更新。
- Keil固件通过SPI完成ID/读写/擦除；写使能、页边界、复位保留、错误配置均有验证。
- 固定端点UI和API双层拒绝改接；模式开关只生成原图允许的H6组合，LED/KEY跳线仍可使用；旧工程迁移与异常导入回滚测试。
- 保留V0.1发行包，V0.2独立生成Windows/HTML包；实际运行打包内核、WebView2和浏览器，提交GitHub版本迭代。
- 最大风险是功能模型与真实器件未实现模式的差异；严格限定模式并记录诊断和证据。不把测试样本通过当作任意固件兼容。

G3实际结果记录于docs/validation-v0.2.md，完成后本设计归档。

### 用户追加：显示 OLED 固定线

用户要求“OLED的线也接上去”。在既有 PB8/SCL、PB9/SDA、3V3/VCC、DGND/GND 固定网络上增加四条只读可见路径，明确标为原板固定线，不增加用户跳线、不更改 MCU 引脚或网络图、不允许删除。沿用当前板卡 profile 和线层显示能力，以模型连接和 UI 只读检查验收。

### 用户追加：侧边栏原始原理图

用户要求“原来的原理图也放在侧边栏里”。在现有左侧栏增加只读原理图阅读入口，原始 V1 四页 PDF 保持原样复制到可访问的本地资源目录；用原页渲染图支持内嵌翻页、缩放和原 PDF 下载，无新运行依赖或外网请求。关闭阅读器返回原工作台状态。校验原件 SHA-256、四页图完整加载、下载一致、窄屏及快捷键隔离。新增文件为 web/assets/schematics/ 下原 PDF 与四张页面图、tests/schematic_smoke.py，其余复用 web 三文件和现有本地静态服务。
