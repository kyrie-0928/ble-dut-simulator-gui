# Codex 项目接手指南

## 认知层

### 项目背景

- 本项目是独立 Windows 上位机，通过 USB 串口管理最多 6 块 ESP32-WROOM-32D BLE DUT 模拟板；ESP32 再通过 BLE 与产测板交互。依据：`README.md`、`app.py` 的 `NODE_COUNT` 和 `SimulatorApp`。
- 当前种子库有 22 个 BLE 产品模板。Model 仅用于模板管理，产测板通过 MiBeacon Service Data 中的 PID 识别产品。依据：`README.md`、`products.json`、`tests/`。

### 技术栈和运行时

- Python 3 桌面程序；界面使用 Tkinter/ttk，持久化使用 SQLite，串口依赖 `pyserial>=3.5,<4`。依据：`app.py`、`storage.py`、`serial_node.py`、`requirements.txt`。
- 源码入口是 `app.py:main`；`build_app.ps1` 是 PyInstaller 单文件 EXE 打包入口。
- 串口默认 115,200 baud，与模拟固件 UART0（GPIO1/3）一致；Windows 端只配置 COM 口和波特率，不配置 UART 编号或 GPIO。
- `build/`、`*.spec`、`__pycache__/` 是可再生生成物；`dist/` 是可再生但可直接交付的 EXE 输出；`.idea/` 是本机 IDE 元数据。
- 本目录在 2026-08-18 不是 Git 仓库，不能假定删除内容可由 Git 恢复。

### 架构说明

- `app.py:main` 启用 Windows DPI 感知，确定源码或 PyInstaller 资源根目录，在 `%LOCALAPPDATA%\Linptech\BleDutSimulator\products.db` 建库，然后启动 `SimulatorApp.mainloop()`。
- `SimulatorApp` 负责产品编辑、6 个串口节点、配置下发、广播/断连命令和 ACK/事件状态。串口线程经 `_queue_node_event` 投递事件，Tk 主线程由 `_drain_node_events` 每 80 ms 消费；不要从串口线程直接更新 Tk 控件。
- `serial_node.py:SerialNode` 封装串口生命周期、读线程、写锁和 32 位滚动序号；`parse_sim_line` 解析 `@SIM` 行。
- `protocol.py` 是协议行为所有者：`FAMILY_SCHEMAS` 定义 Payload，`pack_payload` 负责小端打包、取值范围和 64 字节上限，`build_config_command` 生成带序号的 `CONFIG` 命令。
- `storage.py:ProductStore` 管理 SQLite schema 和 CRUD。仅当数据库没有 `meta.seeded` 标记时从 `products.json` 初始化；修改种子不会覆盖已有用户数据库。
- 真实 BLE 行为发生在 ESP32 固件侧，不在本仓库实现。

### 代码文件介绍

- `app.py` - UI 入口和应用编排；产品编辑、节点状态和 ACK 匹配。
- `protocol.py` - Payload schema、序列化、HEX 校验和配置命令。
- `serial_node.py` - COM 枚举、串口连接、后台读取和事件解析。
- `storage.py` - `Product` 数据模型与 SQLite 产品仓库。
- `products.json` - 首次建库种子及打包输入。
- `tests/` - 协议、22 个模板、命令、默认波特率及 SQLite CRUD 回归。
- `assets/linp.ico` - 窗口图标和打包输入。
- `build_app.ps1` - 单文件 EXE 打包入口，属于有效工程文件。

### 如何运行和验证

- `python -m unittest discover -s tests -v` - `verified`；2026-08-18 使用工作区自带 Python 运行 11 个用例，全部通过。系统 `python` 仍命中 Microsoft Store 占位符。
- `python app.py` - `documented`；启动 GUI，会读写用户数据库并枚举串口。
- `.\build_app.ps1` - `documented`；会清理并重写 `build/`、`dist/`、`*.spec`，可能使用相邻 `factory-gui-test` 的 PyInstaller 环境。
- `dist\*.exe` - `documented`；README 推荐的免 Python 运行方式。本次未做 EXE、真实串口、BLE、六节点或治具验证。

## 约束层

### 禁止重构原则

- 除非用户明确要求，不改目录结构、公共接口、协议格式、数据库结构、模块边界或线程模型。
- 修复问题时不顺手拆分 `app.py`、替换库、统一风格或迁移持久化方案。

### 最小修改原则

- 只修改与需求直接相关的最小文件和逻辑分支；保留命令格式、默认波特率、ACK 序号匹配、日志与已有模板行为。
- 修改前从 `app.py` 的调用点追到 `protocol.py`、`serial_node.py` 或 `storage.py` 的行为所有者。

### 禁止顺手优化原则

- 不做无关性能优化、依赖升级、全仓格式化、UI 整理或相邻问题修复。
- 不把 `build/`、`dist/`、`*.spec` 等生成产物混入源码修改。

### 不确定必须暂停原则

- 协议、固件 ACK、BLE 状态、治具判定或产品字段无法由本仓库确认时，说明缺少的固件、日志或硬件证据，不自行编造。
- 涉及数据库迁移、持久化兼容、删除交付物或改变串口线程退出行为时，先列影响并等待确认。

## 执行层

### 修改流程

每次维护、新增需求或修复前，必须先读取本项目的 `.agents/PROJECT_CONTEXT.md`，不要读取其他项目的同名文件。

1. 理解需求：明确目标、验收方式、硬件边界和不做事项。
2. 定位模块：从真实入口追踪调用链、状态来源、外部副作用和测试面。
3. 输出计划：修改前说明原因、方案、文件、风险和验证命令，此时不写代码。
4. 等用户确认后再修改，只做已确认的最小范围。
5. 出现计划外问题或证据冲突时暂停并重新确认。

### 编辑指引

- 改产品字段/Payload：先看 `protocol.py:FAMILY_SCHEMAS`、`pack_payload`，再看 `products.json` 和 `tests/test_protocol.py`。
- 改串口命令/ACK：先看 `protocol.py:build_config_command`、`serial_node.py`，再看 `app.py:_apply_to_nodes`、`_send_selected`、`_handle_node_event`。
- 改模板 CRUD/首次初始化：先看 `storage.py:ProductStore` 和 `tests/test_storage.py`；注意已有数据库不会重新导入 JSON。
- 改界面/节点状态：先看 `app.py:SimulatorApp`；后台事件必须经队列返回 Tk 主线程。
- 不直接编辑 `build/`、`dist/`、`*.spec`、`__pycache__/`。

### 常见工作流

- 应用配置：`_collect_product` -> `build_config_command` -> `SerialNode.send` -> ESP32 `ACK/ERROR` -> `_handle_node_event`。
- 串口接收：`SerialNode._read_loop` -> `parse_sim_line` -> `_queue_node_event` -> `_drain_node_events` -> `_handle_node_event`。
- 首次启动：`main` -> `ProductStore` 建表 -> `_seed_once(products.json)` -> UI 列表加载。

### 项目跟进文件

- `.agents/PROJECT_CONTEXT.md` 记录当前目标、决策、验证历史和硬件边界；稳定规则保留在本文件。
- 行为、协议、数据库、验证方式或风险变化后，同步更新项目跟进记录。

### 风险说明

- 命令依赖序号匹配 ACK；异常时先核对原始 `@SIM` 日志、命令和 `seq`，不要先加延时或重试。
- 自动化测试不能证明真实 COM、ESP32 固件、BLE、六节点并发或治具判定正确。
- 当前目录没有 Git 历史；删除或覆盖前先确认目标可再生或另有备份。

### Open Questions

- ESP32 通用模拟固件及其 `@SIM` 协议源码不在本仓库；涉及兼容性时需要固件仓库或串口日志。

