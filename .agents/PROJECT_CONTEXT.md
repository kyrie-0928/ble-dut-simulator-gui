# 项目跟进记录

稳定操作约束见根目录 `AGENTS.md`；本文件只记录会随项目推进变化的事实。

## 当前项目目标

- 当前目标：维护独立 Windows BLE DUT 模拟器上位机，通过最多 6 路 USB 串口配置 ESP32 模拟节点，并保留单文件 EXE 交付流程。依据：`README.md`、`app.py`。
- 当前范围：`products.json` 含 22 个 BLE PID，覆盖 ES4、ES5、S5、E5、H3、T2DSB、C6/C6DB、E6D 数据结构。
- 验收分层：协议/存储自动化测试；Windows GUI/打包检查；真实 COM、ESP32、BLE、六节点和治具硬件验证。

## 架构和模块现状

- `app.py` - active；Tkinter UI 和业务编排，管理产品编辑、6 个节点、命令待确认状态及串口事件队列。
- `protocol.py` - active；产品族 schema、Payload 打包、BLE 名称编解码和 `CONFIG` 命令格式。
- `serial_node.py` - active；pyserial 适配、后台读线程、写锁、序号和 `@SIM` 解析。
- `storage.py` / `products.json` - active；SQLite CRUD、动态协议族定义、兼容迁移与仅首次导入的种子数据。
- `tests/` - active；覆盖无需硬件的协议、模板、串口默认参数与存储回归。
- `build/`、`*.spec`、`__pycache__/` - generated；可删除重建。`dist/` - generated/deliverable；未确认交付需求前不清理。
- `build_app.ps1` - active 打包入口；`start.bat` 已按用户要求删除。

## 关键决策记录

- 2026-08-19 - 按用户要求删除 `start.bat` 及其文档引用；源码仍可通过 `python app.py` 启动，EXE 继续由 `build_app.ps1` 生成。
- 2026-08-18 - 清理生成缓存和 IDE 私有元数据，但保留 `dist/` 现有 EXE：当前目录没有 Git，且 README 将 EXE 作为推荐运行方式。
- 2026-08-18 - 项目指南以当前源码为准；ESP32 固件行为只记录为外部边界。
- 2026-08-18 - PID 继续作为 MiBeacon 产品身份；Model 作为 BLE Complete Local Name，UTF-8 最多 18 字节，通过 `CONFIG` 第 10 个字段下发。

## 已完成变更

- 2026-08-19 - 协议族由固定代码定义扩展为 SQLite 持久化配置；支持新增、复制、编辑和删除未引用的自定义协议族，字段可配置名称、顺序、默认值、`u8/s8/u16/s16/u32/s32` 类型及数组数量。
- 2026-08-19 - 新品模板可选择动态协议族；编辑共享协议族时同步迁移引用产品字段，兼容值保留、不兼容值回退默认值；字段编辑区支持滚动。
- 2026-08-19 - 模板参数区移除挤占协议族输入宽度的行内管理按钮；在协议字段标题区提供“管理协议族”和“编辑字段名称/结构”入口，字段名称可直接进入结构编辑器修改。
- 2026-08-19 - 修复协议族编辑器新增字段后名称列被压缩为 1 px：表头与数据行统一列宽，字段名称和默认值列共同弹性伸缩。
- 2026-08-19 - 移除原始 Payload HEX、手动校验按钮和校验结果条；保存与应用配置仍自动校验。协议族管理和字段结构编辑按钮移至底部操作栏。
- 2026-08-19 - 模板底部操作栏改为三个等宽按钮列，按钮占满中间面板可用宽度，使用两个固定 8 px 间隔列，左右无额外留白。
- 2026-08-19 - 产品模板列表的产品名称列改为居中对齐，与居中的表头、PID 和 Model 列保持一致。

- 2026-08-18 - 新增 `AGENTS.md` 和本文件，记录入口、职责、线程/事件流、协议/存储边界、验证与维护流程。
- 2026-08-18 - 将 `.idea/` 加入 `.gitignore`；清理 `.idea/`、`__pycache__/`、`build/` 和时间戳 `.spec`，保留源码、测试、脚本及 `dist/`。
- 2026-08-18 - 重新规整三栏 UI：移除重复串口统计和节点冗余状态文字，在右侧底部保留唯一统计；选择框改为紧凑方形；左侧显示所选 UART 的产品、PID、BLE 名称和广播状态。
- 2026-08-18 - `CONFIG` 命令追加 Model 的 UTF-8 HEX；连接后主动查询 `STATUS`，并从 `model_hex` 恢复 ESP32 当前配置。
- 2026-08-18 - 窗口、任务栏和 PyInstaller EXE 统一使用黑底白字、保持方形比例的 `linp` 图标资源。

- 2026-08-19 - 日志收起高度改为使用标题栏实际请求高度，避免高 DPI 下固定 48 px 裁切标题与按钮。
- 2026-08-19 - Windows 顶层窗口首次映射后通过 `WM_SETICON` 设置 32/16 px `linp.ico`，退出时释放原生图标句柄。
## 当前风险和债务

- 环境风险：系统 `python` 命中 Microsoft Store 占位符；需使用可用 Python 3、Tkinter 和 pyserial 或明确的 Python 路径。
- 协议风险：新上位机的 10 字段 `CONFIG` 需要配套 0.2.0 固件；旧固件会拒绝该命令。`DISCONNECT`、ACK/ERROR 和真实广播名称仍需硬件联调确认。
- 持久化风险：`meta.seeded` 使 `products.json` 只在首次建库时导入；修改种子不会迁移已有用户数据库。协议族表会在现有数据库首次启动新版时自动创建，编辑共享协议族会影响所有引用产品，界面会先提示。
- 并发风险：串口线程通过队列切回 Tk 主线程；修改关闭、重连或事件处理时需检查重复 `LOCAL_DISCONNECTED` 和状态清理。

## 维护入口

- 产品族：`protocol.py:FAMILY_SCHEMAS` -> `products.json` -> `tests/test_protocol.py`。
- 配置/控制命令：`protocol.py:build_config_command`、`app.py:_apply_to_nodes` / `_send_selected` -> `_handle_node_event`。
- 串口：`serial_node.py:SerialNode` -> `app.py:_toggle_node` / `_queue_node_event` / `_handle_node_event`。
- 存储：`storage.py:ProductStore` -> `tests/test_storage.py`；字段变化先设计兼容迁移。
- UI 状态：`app.py:SimulatorApp`；用测试或串口日志确认状态来源，不用延时掩盖问题。

## 验证历史

- 2026-08-18 - `python -m unittest discover -s tests -v` - `blocked`；系统 `python` 是 Microsoft Store 占位符，测试未启动，不是用例失败。
- 2026-08-18 - `python -m py_compile app.py protocol.py serial_node.py storage.py` - `blocked`；同上。
- 2026-08-18 - 工作区自带 Python 执行单元测试 - `verified`；11 个用例全部通过。
- 2026-08-18 - 工作区自带 Python 执行 `py_compile` - `verified`；`app.py`、`protocol.py`、`serial_node.py`、`storage.py` 全部通过。
- 2026-08-18 - 源码静态追踪 - `verified`；确认入口、存储初始化、串口线程到 Tk 队列、命令及 ACK/ERROR 状态流。
- 2026-08-18 - Model/BLE 名称协议回归 - `verified`；13 个单元测试全部通过，包含 UTF-8 往返、18 字节边界及新 `CONFIG` 格式。
- 2026-08-18 - 修改后 `py_compile` - `verified`；`app.py`、`protocol.py`、`serial_node.py`、`storage.py` 全部通过。
- 2026-08-18 - 隔离 GUI 实窗验证 - `verified`；窗口状态为 `normal`，客户区 `1974×1498` 并居中，三栏宽度 `608/676/646`，没有截断或重叠；小屏幕会按屏幕边界收敛。
- 2026-08-18 - PyInstaller 打包 - `verified`；生成 `dist/BLE产品产测模拟器-V1-202608181703.exe`，窗口不再调用 `state("zoomed")`；未连接硬件。
- 2026-08-18 - 硬件验证 - `documented`；尚未连接真实串口、刷写 ESP32、验证 BLE 广播名称、六节点或治具。

- 2026-08-19 - 日志收起回归脚本 - `verified`；收起容器与标题栏请求高度均为 62 px，按钮底部为 53 px，标题和按钮完整显示。
- 2026-08-19 - Windows 标题栏图标 - `verified`；源码实窗截图显示黑底白字 `linp`，最终 EXE 的 `WM_GETICON` 返回有效 16/32 px 图标句柄。
- 2026-08-19 - 修改后回归 - `verified`；13 个单元测试全部通过，`app.py`、`protocol.py`、`serial_node.py`、`storage.py` 语法检查通过。
- 2026-08-19 - 动态协议族回归 - `verified`；18 个单元测试全部通过，覆盖自定义协议族 CRUD、32 位字段、64 字节上限、字段兼容迁移和内置协议族保护；主窗口及两个协议族对话框通过隐藏式实窗启动检查。
- 2026-08-19 - 协议字段 UI 复核 - `verified`；1600×1000 实窗交互检查确认两个管理按钮不重叠、协议族输入宽度充足，并确认字段名称输入框可编辑。
- 2026-08-19 - 字段名称列回归 - `verified`；使用真实 `cb` 协议族点击“添加字段”复现修复前名称输入框仅 1 px，修复后两行均为 167 px，并显示 `version` / `field_2`。
- 2026-08-19 - Payload 校验区精简回归 - `verified`；18 个单元测试和 `py_compile` 全部通过；实窗冒烟确认“原始 Payload”“校验 Payload”及结果条已移除，三个模板操作按钮位于同一底部操作栏，保存路径仍会拒绝超出 `u8` 范围的 `256`。
- 2026-08-19 - 模板底部按钮栏回归 - `verified`；实窗像素检查确认操作栏宽 595 px，三个按钮均为 193 px，间隔均为 8 px，左右余量均为 0；18 个单元测试和 `py_compile` 全部通过。
- 2026-08-19 - 产品名称列对齐回归 - `verified`；运行时 `#0` 列锚点为 `center`，实窗截图确认表头与产品名称同轴居中；18 个单元测试和 `py_compile` 全部通过。
- 2026-08-19 - 最终打包 - `verified`；生成 `dist/BLE产品产测模拟器-V1-202608190938.exe`，随后清理旧 EXE、`build/`、`*.spec` 和 Python 缓存。
## 下一步建议

- 下一次代码任务先用可用 Python 运行现有 13 个单元测试，再按需求追踪对应模块。
- 涉及固件协议或 BLE 异常时，需要匹配版本的 ESP32 固件源码或完整 `@SIM` 串口日志。

