# V0.2 验收记录

日期：2026-11-15。目标：CIMC GD32F470VET6 V1.0。环境：Windows 11 x64、Python 3.13、Unicorn 2.1.4、.NET SDK 10.0.300、Keil Arm Compiler 6、Microsoft Edge / WebView2。

## 内核与固件

`python -m unittest discover -s tests -v`：**49 项全部通过**。原 GPIO、OLED、串口和 SysTick 回归继续通过。

| 检查 | 实际证据 |
|---|---|
| ADC 最低/中间/最高值 | Keil `adc_probe.hex` 在 Cortex-M4 上运行，通过 MMIO 读取 PC0，SRAM 分别得到 0/2048/4095 |
| ADC 与显示分离 | 改变输入电压不改变旧采样结果，只有固件转换才产生新样本；demo 的 OLED 数字位图及串口 A 回复实际核对 |
| ADC 寄存器 | ADC0/1/2、12/10/8/6位、左右对齐、EOC/ROVF、时钟/GPIO条件、复位保持旋钮位置及不支持模式报错 |
| SPI Flash 机器码 | Keil `spiflash_probe.hex` 和 `.bin` 均完成 JEDEC、编程、读回与擦除，SRAM 完成标志及各值符合预期 |
| SPI Flash 边界 | WEL/WIP、CS提交、页回绕、NOR 1→0、读地址回绕、擦除对齐、收发/溢出标志、掉电唤醒、MCU复位保留、SPI控制器复位不切换CS |
| 固定接线 | 所有专用端点禁止新增/删除用户跳线；H6 只接受两种完整组合；H7 始终接通；LED/KEY 继续可手动接线 |
| 工程与模式 | v2 模式/电压往返、v1 标准跳帽迁移；非法固定接线/不完整H6/模式矛盾/异常电压均拒绝，当前工程保持不变 |

主示例启动只读 JEDEC `C84013`，写入/擦除次数保持零；ADC 数值经固件更新 OLED 与串口，没有前端预置回复。单独的 Flash probe 会擦写仿真存储，用于验收。

## 浏览器与笔记本适配

`tests/ui_smoke.py` 已通过：真实鼠标/键盘交互、KEY/LED、OLED、UART、用户排针跳线增删、工程往返、BIN 导入、复位、减少动画及 390px 手机宽度。未捕获 JavaScript 异常。

`tests/laptop_smoke.py` 已通过：1536×740、1366×768、1280×720、1280×660、1093×614、1024×600 逻辑视口均无横向溢出，完整板卡、运行按钮、OLED、KEY 和 ADC 在首屏可见；下方串口区允许纵向滚动。390×844 手机布局无横向溢出。

同一浏览器验收还通过旋钮键盘/拖动/滑杆操作，确认 0 V→0、0.001 V→1、3.3 V→4095；RS232 模式通过实际终端输入 A 获得固件采样回复；切换终端页签不改变 H6；4 条系统连接只读。导入真实 Flash probe 后面板显示读取、两次编程及两次擦除。

桌面采用 PerMonitorV2 DPI 声明。`tests/desktop_smoke.py` 对正式发行 EXE 实跑通过：实际显示器1920×1080、DPI120（125%），工作区1920×1020；窗口1600×980完整位于工作区内。WebView2逻辑视口1266×747无横向溢出，实际点击示例运行后OLED和JEDEC输出通过；正常关闭自己的窗口后，自有后端端口停止。原生窗口截图与测量JSON保存在开发验收目录。

## 发行构建

`dotnet build desktop/CimcLab.csproj -c Release` 通过，零警告、零错误。发行构建继续使用 v0.1 已验证的本项目 PyInstaller bootloader 配置，并生成独立 Windows / HTML 本地包。

`tests/package_smoke.py artifacts/CIMC-Studio-0.2.0-html-local` 已通过：直接启动随包独立EXE，验证Keil HEX/BIN、OLED、UART回复、ADC实际采样、H6模式切换、SPI两种文件格式各自执行编程和擦除。另将 `ui_smoke.py`、`laptop_smoke.py` 指向 HTML 发行包的内核运行，通过全部交互检查，包括新增OLED四条固定线的显示与只读约束。

`tests/schematic_smoke.py` 对最终 HTML 发行目录检查通过：四页 3200×2257 预览完整加载，翻页、100%/200%/适合宽度缩放、1024×600和390px阅读区域边界、Esc/关闭后恢复焦点、阅读时屏蔽固件快捷键均正常。实际下载的PDF与原件SHA-256一致。`desktop_smoke.py` 也在正式Windows EXE的WebView2内打开原图、切至第2页、关闭并恢复焦点，全部通过。

页面预览由原PDF直接渲染，四页已逐页看图核对；不是重新绘制的电路。全套浏览器检查未捕获JavaScript异常。UI新增后，六种笔记本视口和ADC/串口/Flash交互回归再次通过。

## 限制

- 这些是限定模式下的软件与机器码验证，不是赛事官方评测或实物硬件验收，也不保证任意 Keil 工程兼容。
- ADC 为理想单通道软件触发，转换/校准立即完成；没有噪声、采样电容与真实转换时序。连续/扫描/外触发/DMA/中断等明确诊断。
- SPI 为 8 位主机轮询子集；Flash 忙延迟按指令数推进，不代表真实器件时间。Dual/Quad、保护寄存器写入、SFDP、安全区等未实现。
- Flash 内容跨 MCU 复位保留，但不跨内核重启持久化，也不保存进接线工程。
- HTML 仍需随包本地执行内核；无物理串口。原图视图不是精确实物 PCB 布局。
- 多显示器热切换、所有系统缩放组合及无 WebView2 的干净系统未做矩阵验收；当前实际显示器和列出的逻辑视口是本次证据范围。
