# V0.4 多固件与 Bootloader 实现前设计

日期：2026-11-16。用户要求能烧录两个及以上固件、数量自行选择，并选择运行；追加要求每次更新发布GitHub/软件、写公告，再删除旧文件。该请求已授权实现及后续版本发布，不重复索取实施确认。

## G1 复杂度

预计至少38个文件：`engine/firmware_images.py`、`engine/simulator.py`、`engine/app_version.py`、`engine/server.py`、`tests/test_multifirmware.py`、`tests/test_server.py`、`tests/test_connections.py`、`tests/ui_smoke.py`、`tests/multifirmware_ui_smoke.py`、`tests/package_smoke.py`、`tests/linux_browser_smoke.py`、`web/app.js`、`web/index.html`、`web/styles.css`、`firmware/boot_probe.c`、`firmware/app_probe.c`、`firmware/build-boot-probes.ps1`、`firmware/bootloader_probe.sct`、`firmware/app_a_probe.sct`、`firmware/app_b_probe.sct`、三个probe各自HEX/BIN文件（6个）、`docs/bootloader.md`、`docs/validation-v0.4.md`、`docs/releases/v0.4.0.md`、`README.md`、`CHANGELOG.md`、`.ai-governance/capability-map.md`、`scripts/build.ps1`、`scripts/build-linux.sh`、`scripts/build-windows-installer.ps1`、`desktop/App.cs`、`desktop/CimcLab.csproj`、`.github/workflows/ci.yml`，另有发布清理脚本/工作流及项目AGENTS流程约定。

| 条件 | 结果与依据 |
|---|---|
| H1 | 命中：上述跨端文件超过5个 |
| H2 | 未命中：无数据库 |
| H3 | 命中：新增load_set、state集合字段、工程v3 |
| H4 | 未命中：本地Host/Origin边界复用，不更改认证 |
| H5 | 未命中：无资金业务 |
| H6 | 命中：固件解析、Simulator复位与工程序列化被GUI/HTTP/多组验收共享 |
| H7 | 未命中：复用Unicorn、标准库、已有Keil与打包工具 |
| H8 | 命中：共享前端与内核同时扩展 |
| H9 | 命中：固件probe构建、0.4安装版本及CI/发布清理 |
| H10 | 未命中：按多镜像预烧录和启动选择实施，不扩张为完整IAP/OTA |

判定：大。未降级。

## G2 现状与复用

- `engine/simulator.py:34` 的parse_firmware要求每个文件起始处就是向量表，HEX洞填FF并丢失真实写入段信息。
- `simulator.py:273` load覆盖self.image；`:281` reset只装入这一份镜像；0地址映射的未写区域目前为0而非Flash擦除值。`:307`、`:446`已有VTOR状态与SysTick取向量逻辑。
- `simulator.py:647`已有接线/串口/ADC工程预检；`:677`项目v2只存固件元数据，不能恢复固件字节。
- `engine/server.py`为本地HTTP服务，原命令体上限6MiB，本次提高至16MiB以容纳完整工程；复用现有同源检查与错误路径。
- `web/app.js:403`附近prepareFile只处理单个文件，submit调用load；复用旧入口、新增独立可滚动多固件对话框。
- `firmware/build.ps1`已使用Keil6.22生成真实HEX/BIN，现有scatter固定08000000；新增三个独立probe目标，不修改用户私有工程。
- 能力地图已读取。复用原Flash取指、GPIO/OLED/ADC/SPI、真实UART、WPF/HTML/Linux宿主、更新源与安装工作流；新增镜像集合管理是因为单镜像状态不能表达共同烧录。

## 契约与方案

1. 新模块解析HEX/BIN为实际segments。保留旧parse_firmware wrapper及load语义。多镜像合成512KiB内部Flash，所有未写字节为FF，0地址别名与08000000映射一致。
2. `load_set`接受`images:[{id}, {filename,data,address}]`。既有id复用不可变原始文件；新文件BIN须设置地址，HEX用记录地址。重复id、坏编码、真实地址重叠、越界、空集先拒绝，失败不改CPU/日志/运行状态。没有固定文件数量上限；受Flash容量、单文件4MiB和序列化固件集合8MiB限制。集合预算按完整导出JSON（ensure_ascii=True，紧凑分隔符）计算，所有加载入口共用，避免id增量添加绕过限制；HTTP16MiB为工程其它字段及包装留余量。
3. 启动可传`bootAddress`（独立向量表基址）或`bootIndex`（列表中镜像起始地址），两者互斥。未指定时选择第一个镜像起点。启动向量必须128字节对齐，SP在已支持RAM内，向量8字节及Thumb入口至少2字节已实际烧录。非启动数据镜像无需伪造向量表。
4. `state.firmwares`为不含原始字节的元数据列表，包含id/name/format/size/address/writtenSize/spanSize/segments；`bootAddress`与`currentVectorAddress`分别表示复位入口及运行时VTOR。`state.firmware`保留为当前复位启动镜像的兼容元数据，提供id。bootIndex用于新增HEX尚未显示地址时的启动单选。
5. 实际Bootloader自行执行MSP/VTOR/BX跨镜像跳转；宿主不伪造“应用切换”。复位保留全部烧录镜像并从选定向量重新启动。ICSR清SysTick pending仅按有证据的核心位语义补齐。
6. 项目v3保存`firmwareSet:{images:[{id,filename,data,address}],bootAddress}`；无固件用null，导入v3 null明确清空固件。固件、接线、串口模式、ADC全部预检后原子提交。旧v1/v2仍能导入，且不替换当前固件。
7. UI保留单固件入口，在固件卡增加“多固件”。对话框可持续添加/删除，BIN独立地址，HEX内置地址，启动单选和可选自定义向量地址。已烧录条目用id重开编辑，修改只进草稿；点击一次烧录成功后才应用。原首屏仅增加紧凑数量/启动摘要，文件列表内部滚动。
8. 三个Keil probe：boot08000000、A08010000、B08020000。boot串口等待1/2，真实写VTOR/MSP并BX；两个应用输出不同标识/LED，记录入口MSP、VTOR及独立SysTick计数。

不采用仅在文件列表之间切换单一Flash（Bootloader无法读到APP）、简单拼接BIN并猜地址（破坏链接布局）、固定两槽（不满足数量自行选择）、宿主直接生成应用串口输出。此次不实现FMC在线擦写、OTA、选项字节或系统ROM Boot0启动；仍对未实现访问明确报错。

## 发布与清理

0.4.0更新Windows安装版、Linux DEB/便携包、HTML包、GitHub Release与已有Packages；公开源码及现有更新检查读取最新公告。公告写CHANGELOG、docs/releases与Release正文。把用户的后续更新规则写入项目AGENTS及发布流程文件。

只有新版本构建、安装运行验收、Release文件摘要和Packages回拉均成功，且公开更新接口能识别新版后，才清理旧版本安装分发文件、旧Release上传附件及对应旧Packages版本。保留Git源码/标签/提交历史、更新公告及验证证据。清理仅对本项目精确版本化路径/已枚举远端ID进行，不删除未匹配文件，不扫描用户任意安装目录。

## 验收与回滚

- 两镜像boot+A、三镜像boot+A+B、超过三份的非重叠集合；独立选择A/B启动；真实跳转后MSP/VTOR/串口/LED/SysTick结果一致。
- HEX洞可填，实际重叠拒绝；缺向量、坏SP/Thumb、未写入口、越界、错误引用与非法工程均原子拒绝，已有固件可继续执行。
- v3固件及接线往返；v1/v2兼容。固定板线不变。
- 1024x600、笔记本、390px对话框和原工作台无横向溢出；错误保留草稿；取消不更改已运行CPU。
- Windows安装后与Linux冻结包执行真实多固件；Ubuntu/Debian安装/卸载、同包WSL及原生WPF验收。
- 新版本发布前可回到旧标签构建；旧分发文件只在新版本确认可用后按用户要求删除，源码历史用于后续重建。
