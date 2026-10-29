# Axiom Studio 2.0.0 — 可信软件生产里程碑版

**产品定位冻结**：以软件意图为入口，组织 AI 构造、行为规格、独立验证、可信证据与持续演化；代码编辑复用 VS Code。

**2.0 新增可信交付验证中心**：一键生成版本绑定的验证批次、识别受影响测试、在独立执行前要求明确授权、实际调用 Axiom 模型与 C++ 工程 Gate。跨批次共享由 Axiom 引擎负责的严格条件下的测试缓存，集成测试始终重跑。支持工作台、HTTP API 与命令行。参见 [发布说明](docs/RELEASE_NOTES_2.0.0.md) 和 [架构与使用指南](docs/AXIOM_STUDIO_2.0_里程碑架构与操作指南.md)。

> **边界**：本地可信源码原型；不是不可信代码执行沙箱、无通用形式化正确性证明、无生产发布许可。完整历史回归与 Windows 原生 GUI 验收尚不完整。

## 2.0 快速启动

```bash
python -m pip install -r requirements.txt
python scripts/release_selftest.py
python run_studio.py
```

在 Studio 首页选择已冻结规格契约的 C++ 工程，进入“可信交付验证中心”。不运行 C++ 时亦可创建验证计划、检查受影响测试。命令行 `python scripts/milestone20_cli.py --help`。

---

# Axiom Studio 1.9.0 — 多角色 AI 构造与增量影响分析

见 `docs/AXIOM_STUDIO_1.9_多角色AI协作与增量验证.md`。AI 候选不能自行提交、应用、执行或授权发布。

# Axiom Studio 1.8.0 — AI 构造任务并行准备与可信集成

**新的生产力能力：** 同一冻结验收契约下，将多个 C++ 模块构造任务并行准备成隔离的 AI / VS Code 任务包，独立暂存候选，再逐个审查、授权应用和运行真实 C++ 验证。不能把多个未审查的 AI 结果直接合并到一个工程。

在「跨模块软件生产计划」创建任务图后，点击「并行生成各模块构造任务」，复制任务交给 AI / VS Code，粘贴并暂存候选，再点击「提交人工审查」。前置模块发生变化时必须明确复核兼容性。失败诊断可形成受限修复提示。

命令行：`python scripts/fleet_cli.py --help`；说明：[1.8 使用指南](docs/AXIOM_STUDIO_1.8_并行构造与可信集成.md)。**并发仅用于只读准备**，不自动调用远程模型、运行 C++、放宽 Gate、签发生产授权。

---

# Axiom Studio 1.7.0 — 多模块可信软件生产任务图

**新的主路径：目标与验收契约 → AI / VS Code 提出实现 → 用户审查候选 → 独立测试与 Gate → 诊断反馈 → 可信演化。**

用户始终保留规格/验收标准和批准权。首次打开可从目标开始；完成规格验证与人工契约冻结后，在“AI 构造生产线”选择模块、暂存候选、审查批准、授权本地测试，或导出交接记录。代码编辑仍使用 VS Code。

运行：`python -m pip install -r requirements.txt && python run_studio.py`。无头使用：`python scripts/assembly_cli.py --help`。详细步骤：[1.7 多模块生产指南](docs/AXIOM_STUDIO_1.7_多模块生产指南.md)；原有 [1.6 构造生产线使用指南](docs/AXIOM_STUDIO_1.6_生产线使用指南.md) 继续有效。

**安全范围**：这是本地单目标构造循环，不包含无人值守的原生代码执行、生产级恶意代码隔离、第三方签署或正式发布授权。连接真实 AI 需要用户显式配置和每次授权。

---

# Axiom Studio 1.5.0 — 目标驱动的软件生产导航器

**先看软件目标，再看当前证据，然后只做下一步。** 1.5 新增「生产导航」工作台：用户建立项目后即可了解六个生产阶段，安全模型检查可一键运行；遇到需求验收、AI 候选审查或 C++ 执行，系统明确要求用户决策。变更会使旧结论失效；生产过程可以导出非签名交接摘要。**不会因为模型验证通过就声称整个自然语言目标已获证明。**

入口：`首次安装并启动AxiomStudio.bat`（Windows）或 `python run_studio.py`；CLI：`python scripts/pilot_cli.py --help`。完整说明：[1.5 发布说明](docs/RELEASE_NOTES_1.5.0.md)。

---

# Axiom Studio 1.4.0 — 可理解的设计评审与多方案对比

软件生产从**目标和验收场景**开始。1.4 新增可阅读的规格变化说明和两候选并排对照，突出需要人工复核的行为变化、业务需求映射缺口和外部可观察行为变更。**不进行自动方案排名或业务等价性证明**。1.3 新增「让 AI 帮我提出行为规则」：复制任务到 VS Code/AI，或连接已配置的模型生成候选；查看新旧 `.ax` 规则差异，进行独立模型检查，逐项确认场景和性质的对应关系，再创建**新的演化项目**。原始规格与证据保持原样。代码编辑继续交给 VS Code。

**零培训试用路径：** 打开软件构造全景 → 说出目标并创建示例项目 → 检查规则 → 确认验收场景并保存 → 让 AI 提出规则 → 检查候选 → 人工选择场景对应性质 → 批准创建演化项目 → 重新独立验证与冻结。

安装与运行：

```bash
python -m pip install -r requirements.txt
python scripts/release_selftest.py
python run_studio.py
```

实际 AI 连接配置（可选）：`AXIOM_STUDIO_LLM_ENDPOINT`、`AXIOM_STUDIO_LLM_MODEL`、`AXIOM_STUDIO_LLM_API_KEY`。**没有模型也能使用手动候选的完整验证/演化链路。** 模型生成、有限模型检查和自然语言场景的性质关联并不构成业务正确性证明或生产发布许可。详细信息见 [1.4 发布说明](docs/RELEASE_NOTES_1.4.0.md)。

---

# Axiom Studio 1.2.0 — 从真实业务行为定义验收标准

**打开就能理解新的软件生产方式：** 从目标开始 → 描述具体业务场景（在什么情况下、发生什么、必须得到什么） → 对照 Axiom 行为性质 → 发现尚未覆盖的需求 → AI 辅助设计规格 → 人工确认 → 独立验证与持续演化。无需先学习规格语法，也无需在 Studio 中重新编辑 C++。

本轮新增**场景式验收编辑器**：支持添加/删除业务场景、关联已有性质、诚实标明未覆盖项、自动保存草稿与防止并发覆盖、导出 AI 规格设计任务、人工冻结并在证据链中绑定草稿摘要。**未关联需求不会自动变成已验证需求**，即使冻结也会阻断测试级准入。

安装及运行：

```bash
python -m pip install -r requirements.txt
python scripts/release_selftest.py
python run_studio.py
```

详细功能与使用说明见 [1.2 发布说明](docs/RELEASE_NOTES_1.2.0.md)。代码编辑复用 VS Code；候选代码执行必须另行人工授权，且所有准入仍是测试级原型、不构成生产发布许可。

---

# Axiom Studio 1.1.0 — 从软件意图开始的无培训工作台

打开 Studio 后，首先看到的是 **「你希望软件完成什么？」**，而非编辑器或专业验证命令。填写项目名称、目标，选择一个可验证示例起点，点击 **「建立我的软件构造项目」**。系统将创建独立项目并在「我的软件项目」显示唯一的下一步操作。

**新手路径：** 描述意图 → 选择可检查的示例规格 → 运行安全模型检查 → 逐项阅读和确认验收规则 → 创建受约束的 AI 实现任务 → 人工审查候选 → 独立验证 → 测试级裁决。前四步可直接在首页完成；专业工具与项目记录按需展开。

**重要说明：** 用户输入的自然语言目标不会被自动编译成行为规格。示例性质的验证只说明示例规格满足特定有限模型检查，不表明用户全部需求已获得证明。连接 AI、应用代码、执行原生 C++ 和发布裁决仍受既有授权约束。

```bash
python -m pip install -r requirements.txt
python scripts/release_selftest.py
python run_studio.py
```

新接口：`GET /api/journey` 与 `POST /api/journey/start`（需要本地会话令牌）。欢迎页无需用户理解 Axiom 语法；已有项目仍保留完整专业工作流。代码编辑继续由 VS Code 提供。

[阅读 V1.1 开发说明](docs/RELEASE_NOTES_1.1.0.md)。

---

# Axiom Studio 1.0.0 — 面向 AI 的软件构造与可信演化工作台

这是可在本地启动的软件生产工作台正式发行版，核心是**需求与行为规格 → AI/人工构造 → 独立验证 → 可信证据 → 人工 Gate → 演化**，不是另造一个编辑器。使用 VS Code 进行源代码编辑与调试。

快速启动：

```bash
python -m pip install -r requirements.txt
python scripts/release_selftest.py
python run_studio.py
```

**1.0 新增**：全局生产总控台、项目/工单状态聚合、分阶段依赖、异常失效控制、环境诊断与可复现离线自验。既有多目标事务、AI 工单、批量模型验证和项目交接继续保留。

```bash
python scripts/production_cli.py cockpit
python scripts/production_cli.py doctor
python scripts/production_cli.py queue
```

[完整发布说明与适用边界](docs/RELEASE_NOTES_1.0.0.md)。本地测试级准入不等于生产软件发布许可；不可信原生代码的安全执行隔离仍未达到生产级。

---

# Axiom Studio V0.8 · 批量生产任务与断点恢复

**定位不变：** 组织软件构造和可信演化，不重复造代码编辑器。新增生产任务运行器，将多个项目的 Axiom 规格检查、模型验证和 Gate 集中执行；结果持久化、失败阻断、重启中断标记、显式重试与可校验交接包。

浏览器入口：**软件构造全景 → 生产任务中心 → 批量执行安全规格验证**。批次运行完全不执行 C++、不请求 AI 模型、不修改需求，也不会签发生产许可。C++ 与人工决策继续走原有受保护流程。

```bash
python scripts/production_cli.py batch-model
python scripts/production_cli.py runs
python scripts/v08_demo.py
```

见 [V0.8 批量规格验证与交付工作流](docs/V0.8_批量规格验证与交付工作流.md)。

---

# Axiom Studio V0.7 · 软件构造生产任务中心

**产品定位（冻结）：** 不重复制造已有开发工具，以需求与行为规格为约束，编排 AI 候选、独立验证、证据 Gate 与可信演化。代码继续交由 VS Code 或已有工具。

V0.7 的日常入口：**新建可运行项目 → 任务中心提示下一步 → 验证模型 → 人工冻结需求映射 → 交接构造任务 → 候选与方案评估 → 导出交接包**。

Windows 下安装依赖后双击 `启动AxiomStudio.bat`；跨平台运行 `python run_studio.py`。打开项目全景页面上方的 **新建可运行项目**。默认仅创建项目，不调用外部 AI、不执行 C++。

不使用浏览器也可以操作：

```bash
python scripts/production_cli.py templates
python scripts/production_cli.py init --template model-toggle --slug demo-app --name "Demo app" --goal "验证状态不变量" --verify-model
python scripts/production_cli.py queue
```

导入已有 C++ 工程须明确提供 `.ax` 规格和 `ax-cpp-project/0.1` 清单，详见 [V0.7 快速起步](docs/V0.7_面向生产力的快速起步.md)。签发准入依旧仅限测试级原型，生产发布始终禁用。

---

# Axiom Studio V0.4 — 需求到证据的软件生产协议

**冻结定位**：Axiom Studio 不重复开发代码编辑器，VS Code 用于编辑和调试；Axiom Studio 负责将 AI、行为规格、程序构造、独立验证、可信证据和持续演化组织为一套可追溯、可裁决的软件生产流程。

### 本版新交付（在 V0.3 之上增量实现）

- **生产契约**：从真实 .ax 规格建议性质映射；人明确确认需求后冻结契约，固定规格哈希、性质表达式指纹与不可放宽的准入规则；修改需新建演化分支。
- **可追溯构造图**：需求 ↔ Axiom Property ↔ 候选 ↔ 验证 ↔ 裁决，提供结构化 API 和 IDE 项目面板。
- **受约束 AI 任务包**：以冻结契约的摘要为依据，明确允许修改与禁止修改的内容；AI 只能提出候选，不能调整测试与 Gate。
- **测试级生产护照**：仅在原项目模型 Gate、独立 C++ 验证、人工确认、签发时实时 Gate 及审计链满足条件时签发；历史护照不等于当前可信发布。
- **未满足需求必阻断**：没有形式性质映射的需求不能因模型通过被自动标为满足。规格、契约、候选或审计变化采取保守失效。

### 启动与专项验收

```bash
python -m pip install -r requirements.txt
python run_studio.py
python -m pytest -q studio/tests/test_production.py studio/tests/test_production_http.py
python scripts/production_demo.py
```

Windows 仍可运行 `启动AxiomStudio.bat`。根目录 `Axiom-Studio.code-workspace` 继续使用第三方 VS Code，不开发新的代码编辑器。**本版不包含通用的自动 Agent 软件工厂或生产级发布授权**。

完整协议与安全边界见 [V0.4 软件生产契约与可追溯构造协议](docs/V0.4_软件生产契约与可追溯构造协议.md)。前版说明与功能保留如下。

---

# Axiom Studio V0.3 — 面向 AI 的软件构造与可信演化体系

**产品定位已冻结：** Axiom Studio 不重复制造已有的软件开发工具，而是把 AI、程序构造、行为规格、独立验证、可信证据与持续演化组织为一个完整的软件工程体系。**代码编辑不是核心，直接借用第三方 VS Code。**

## V0.3 新能力

- **默认首页＝项目全景：** 需求/规格、AI 实现候选、模型验证、独立 C++ 检查、证据、质量决策与演化记录。
- **独立编排引擎：** `studio/orchestrator.py`，SQLite 持久化，显式阶段状态机，禁止跳过验证/人工审批。
- **与已有引擎联动：** 真实 `ax check → plan → verify → model Gate`；候选使用 V0.2 原有人工审查工作流；人工最终确认前重新核验当前 C++ Gate。
- **变更保守失效：** 规格/工程清单摘要不匹配，旧流程标记 stale；演化需建立新分支，不能沿用原型准入。
- **流程事件链：** 前后哈希链接；可检测局部篡改，但不是拥有独立公钥信任锚的签名审计。
- **VS Code 适配：** 根目录 `Axiom-Studio.code-workspace` 使用成熟编辑器提供代码编辑、Git、调试等；包含验证/启动任务，不复制 VS Code。

## 如何运行

Python 3.10+；在 `Axiom-Studio` 根目录：

```bash
python -m pip install -r requirements.txt
python run_studio.py
```

Windows 可使用 `启动AxiomStudio.bat`；Linux/WSL2 可使用 `./launch.sh`。打开终端输出的 `http://127.0.0.1:8765/?token=...`。IDE 默认进入「软件构造全景」。

1. 新建项目，填写需求及 `cpp_project/ledger.ax`、`cpp_project/project.json`。
2. 点击「验证规格 → Gate」，引擎完成真实模型级检查。
3. 进入候选工作台，暂存（可粘贴、可授权模型生成）、审查、应用、独立测试 C++ 候选。
4. 工作流同步后，在项目中根据当前有效证据进行人工「测试级确认」。**绝不作为生产发布许可。**
5. 规格或清单发生变化时旧流程变为 stale；建立演化分支重新构造与验证。

建议同时用 VS Code 打开 `Axiom-Studio.code-workspace`，必要时查看实现细节或调试。Studio 项目流程并不依赖代码编辑器。

## 开发/验收

```bash
python -m pytest -q studio/tests/test_orchestrator.py
python -m pytest -q studio/tests/test_project_http.py
python -m pytest -q studio/tests/test_studio.py -k 'not cpp'
```

V0.2 候选流程、所有 Axiom P0—P2h 引擎代码仍然包含在包内。Linux 下本地 C++ 验证不具备生产级恶意源码执行隔离，**只可运行明确审查过的可信代码**。

详见 `docs/AXIOM_STUDIO_产品定位冻结基线_V0.3.md` 与 `docs/V0.3_编排流程与安全边界.md`。

---

# Axiom Studio V0.2 — 可信候选构造与审查工作台

**可运行本地 IDE 原型。沿用 Axiom 0.2 冻结理论及原有 Engine V1.0.0（P0—P2h），在 V0.1 上新增候选生命周期。**

## 启动（Windows 11 / WSL2 / Linux）

1. 安装 Python 3.10+，进入源码包的 `Axiom-Studio` 文件夹。
2. 执行 `python -m pip install -r requirements.txt`。
3. Windows 双击 `启动AxiomStudio.bat`；Linux / WSL2 执行 `./launch.sh` 或 `python3 run_studio.py`。
4. 使用终端打印的 `http://127.0.0.1:8765/?token=...` 安全本地链接打开工作台。端口占用可执行 `python run_studio.py --port 8999`。

**本地验证演示：** 打开 `two_account.ax`，顺序执行检查、义务、模型验证和 Gate。查看 `broken_conservation.ax` 的实际反例。C++ 工程示例位于 `cpp_project/project.json`；Windows 可在 WSL2 环境运行其 GCC/Linux 命名空间隔离测试。

## V0.2 新增：候选闭环

点击编辑器顶部 **✧ 候选** 或左侧 **AI 构造 → 打开候选工作台**：

1. **选择项目和目标**：默认清单 `cpp_project/project.json`，目标 `cpp_project/ledger.cpp`。候选只可修改已被清单列出、真实参与编译的非测试 `.cpp` 文件。
2. **取得候选**：在编辑框粘贴来自外部 AI 的 C++ 代码；也可通过显式同意后调用用户自行配置的兼容 Chat Completions 模型。未配置模型完全不影响其余功能。
3. **创建候选**：只将代码及内容 SHA-256 存入独立本地暂存库，不修改项目源文件、不编译、不运行。
4. **人工审查**：比较候选与原始文件，明确批准某一 SHA-256 摘要。规格、清单、未修改源文件、头文件或测试发生变化，将阻断沿用旧批准。
5. **应用源码**：需要再次人工确认；原始文件字节保存至内容寻址备份，候选以原子写入方式进入工作区。编辑器已有未保存修改时，界面阻止覆盖。
6. **验证 + Gate**：要求再次明确确认本地源码已审查且可信，然后调用**原始 Axiom 引擎**依次执行模型验证 → 模型 Gate → C++ 工程全量验证 → C++ 项目 Gate。任一步出错均停止后续流程，候选显示 `Blocked`。通过标记 `verified`，结论仅限 **`cpp-tested-prototype` 测试级准入**。

本轮未实现自动安全隔离任意 AI 生成代码，也没有向 AI 授权修改 Axiom 规格、编译测试、验证器、证据系统或 Gate 策略。

### 可选：连接个人模型提供方

目前实现的是 **OpenAI-compatible Chat Completions** 请求适配层，模型端点是*可选*的、由用户显式设置的配置，而非已包含云端账号或默认模型。AI 回复只创建待审查候选，不会自动应用。规格全文及当前目标 C++ 代码仅在用户主动点击 **连接模型生成** 且确认后发送给所配置的端点。

PowerShell 示例（请根据实际服务替换地址、模型；不要将密钥写入工作区或上传到仓库）：

```powershell
$env:AXIOM_STUDIO_LLM_ENDPOINT = "https://your-provider.example/v1/chat/completions"
$env:AXIOM_STUDIO_LLM_MODEL = "your-model"
$env:AXIOM_STUDIO_LLM_API_KEY = "<secret-from-your-provider>"
python run_studio.py
```

本机测试服务可使用 `http://127.0.0.1:<port>/v1/chat/completions`，其他非 HTTPS 远程地址默认被拒绝。接口已通过本机模拟提供方测试；**没有声称任何实际付费模型服务已联网验证**。

## 安全与可靠性边界

- 只监听 loopback，本地随机 token；无云端多人协作、无账号安全隔离。不要通过代理公开本地服务。
- 暂存区和证据库位于 `.studio-data/`，不属于可编辑工作区。候选内容采用 SHA-256 完整性自检，但当前没有防御拥有本机文件系统写入权的攻击者的独立签名服务。
- 为防“AI 修改测试获取假通过”，候选不能编辑 `test_*.cpp`，且所有未修改的工程文件（包括测试、头文件）与候选创建时的哈希绑定。变更触发冲突，不自动忽略。
- `Applied` 表示人类审查后文件发生了变更，不等于通过测试；`verified` 仅表示有限模型及声明的工程测试都通过，不表示通用 C++ 形式正确性/无数据竞争/生产许可。
- 当前隔离仍为实验性 Linux 命名空间/chroot；没有完整的 seccomp/cgroup 生产级沙箱。**不应编译或运行未经信任审查的恶意 AI 代码。**
- 连续执行多个不同的 C++ 候选时，本次验收环境仍复现了第二次编译运行超时。服务设有阶段超时并 fail-closed；该项未纳入已解决问题。首次单候选测试和故意错误候选的独立测试可重现。

## 测试与复现

```bash
python -m pytest -q studio/tests/test_studio.py
python -m pytest -q studio/tests/test_candidates.py -k 'not real_cpp_'
python -m pytest -q studio/tests/test_candidates.py -k 'real_cpp_a_good'
python -m pytest -q studio/tests/test_candidates.py -k 'real_cpp_b_bad'
```

其中真实 C++ 两个测试**需分别启动独立的 pytest 进程**进行现阶段环境复现。上述测试合计 15 个测试用例；不等同于“在单次回归运行中 15/15 全部通过”。合并连续 C++ 候选实验的超时问题仍需解决。

## 源码目录

```text
Axiom-Studio/
├── run_studio.py                  # 启动 IDE 本地服务
├── 启动AxiomStudio.bat            # Windows 启动脚本
├── studio/
│   ├── server.py                 # API、文件访问和原引擎调用
│   ├── proposals.py              # 候选、审查、摘要、应用、模型适配器
│   ├── static/index.html         # IDE 页面 + 候选工作台
│   ├── static/app.js             # 原有编辑器和验证交互
│   ├── static/candidates.js      # 候选 UI 交互和流程控制
│   ├── static/styles.css         # 暗色工作台主题
│   └── tests/                   # HTTP/API/真编译集成测试
├── workspace/                    # 实际可编辑项目
├── engine/                       # 完整 Axiom P0—P2h 验证引擎
└── .studio-data/                 # 启动或运行后自动生成，不随 ZIP 预置
```

**后续重点：** 消除连续 C++ 候选运行超时；在可信隔离和跨候选证据链通过审计后，再增加诊断驱动的 AI 候选迭代，以及 LSP、调试器、Git/CMake 集成。

## V0.5 软件生产编排引擎（2026-10-28）

产品定位冻结：Axiom Studio 组织 AI 软件构造、规格、独立验证、可信证据、持续演化，不再重复开发代码编辑器；编辑/调试可直接使用 VS Code。

新增 `studio/factory.py`、`/api/factory/*` 和项目全景内的生产活动面板。要求先冻结 V0.4 生产契约，再通过六阶段受控 DAG 执行。代码候选先暂存，人工审查 SHA-256 后才能覆盖工作区；执行 C++ 另需明确授权；验证结果只能来自 Axiom 独立引擎；最终 Gate 仅确认受限测试级原型。

真实演示：`PYTHONPATH=studio:engine/src python scripts/factory_demo.py --timeout 85`

实施与安全边界：`docs/V0.5_软件生产编排与验收.md`。

## V0.6 多目标生产事务与方案比较（2026-10-28）

本版新增 `studio/batches.py` 和 `/api/batch/*`，在已有冻结生产契约和真实模型 Gate 之上，暂存多文件组合候选，在独立临时工作区运行 C++ 单元/集成测试和 Gate，人工比较选择后可恢复地整体应用，实际工作区再次完整验证，并执行测试级人工裁决。错误方案不能靠影子测试或旧证据获得准入。

浏览器项目全景新增「多目标构造与方案比较」工作台；源码实现与调试仍建议直接使用第三方 VS Code。当前需要将外部 AI/VS Code 生成的整套候选以 JSON 形式导入，不包括自主多 Agent 编程。

- 专项测试：`PYTHONPATH=studio:engine/src pytest -q studio/tests/test_batches.py studio/tests/test_batches_http.py`
- 真实 C++ 演示：`PYTHONPATH=studio:engine/src python scripts/batch_demo.py`
- 安全范围及设计限制：`docs/V0.6_多目标构造事务与方案比较.md`

## V0.9 AI 构造生产工单（2026-10-28）

本版新增 `studio/workorders.py`、`/api/workorder/*`、项目全景内「AI 软件生产工单」以及 `scripts/workorder_cli.py`。生产工单将受限的 AI 候选、人工摘要审批、应用、独立真实 C++ 验证、失败诊断、人工回退和最多 3 轮修复串为持久状态机。真实模型调用需配置本地环境变量并显式授权；没有配置时可以粘贴 AI/VS Code 生成的候选。此版本**不会自行执行或批准 AI 代码**。

- 使用与安全限制：`docs/V0.9_AI构造生产工单与诊断反馈.md`
- V0.9 专项：`PYTHONPATH=studio:engine/src python -m pytest -q studio/tests/test_workorders.py`
- 真实正确/错误候选：`python scripts/v09_real_verify.py` 与 `python scripts/v09_real_verify.py --bad`
- 历史联合回归仍有超时，不宣称完全解决。

## 1.4 面向普通使用者的评审

1. 从主页描述目标、完善“前提—动作—期望结果”验收场景。
2. 打开规格候选工作台，让 AI / VS Code 提议行为规格，或粘贴候选。
3. 点击“独立检查”，查看“新增/改写/移除的规则”“需要留意的地方”“仍需人工确认的场景”。
4. 检查两个候选后，使用“对比两份方案”理解实际模型结构差别。对比只辅助决策，不自动选择或批准。
5. 由用户审查场景关联后，明确批准，系统才建立新演化项目；原始项目和证据不会被覆盖。

可复测：`python -m pytest -q studio/tests/test_design_review.py`；另运行 `python scripts/release_selftest.py`。
浏览器端 UI 已通过真实后端计算结果的离线数据桥接验收；原生 Windows 浏览器访问未在本次环境验收。

## 1.7 新增内容

新增多模块构造任务 DAG，自动识别工程中允许修改的实现目标，串行调度具有依赖关系的模块，并只在独立 C++ 测试通过后解除后继依赖。对外修改、审计异常及过期证据采取保守阻断。用户保留所有候选审查、代码应用和本地执行许可。命令行：`python scripts/task_graph_cli.py --help`。

