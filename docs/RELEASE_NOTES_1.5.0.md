# Axiom Studio 1.5.0 — 目标驱动的软件生产导航器

## 目标

Axiom Studio 是**面向 AI 的软件构造与可信演化体系**。用户从目标和实际验收行为出发，由 Axiom Studio 协调行为规格、AI 构造、独立验证、证据、人工决策和持续演化；不重新实现 VS Code 的编辑功能。

1.5 的新增价值是贯穿此前分散的工具，形成面向使用者的**生产任务（Mission）**。每个任务都显示当前目标、六个生产阶段、真实依据、下一步建议和责任主体。

## 在界面中使用

1. 打开「从软件目标开始」，填写项目名称和想实现的能力，选择一个可以运行的规格起点。
2. 创建后自动出现「生产导航」。它读取实际规格/工作流/证据，不编造结果。
3. 点击「执行安全的规格检查」：调用现有 Axiom 解析、计划、有限状态验证与模型 Gate。
4. 检查通过后，界面停在「确认软件验收规则」，必须由人检查场景与性质的关系。
5. 后续 AI 候选、真实 C++ 执行和测试级裁决仍在原有独立、受审查的工具链中完成。
6. 任何输入变化、审计链问题或未解决验证都会阻断旧结论；可以导出带摘要的本地生产过程交接 JSON。

## 新增核心组件

- `studio/pilot.py`：SQLite 持久化、六阶段实时状态、单步安全推进、失败阻断、意外中断恢复、哈希链审计、任务交接摘要。
- `studio/static/pilot.js`：项目选择、单一下一步、模型检查进度、人工环节、交接下载。
- `scripts/pilot_cli.py`：无界面批处理与生产任务查询，提供 `new / list / start / show / verify --wait / audit / handoff`。
- `studio/tests/test_production_pilot.py`：真实引擎检查、版本竞争、篡改、断电恢复、HTTP 鉴权、授权边界等。

## CLI 示例

```powershell
python scripts/pilot_cli.py new --slug mypilot --name "我的软件" --goal "开关只允许在合法状态之间切换。" --template model-toggle
python scripts/pilot_cli.py list
python scripts/pilot_cli.py verify mission-xxxxxxxx --wait
python scripts/pilot_cli.py show mission-xxxxxxxx
python scripts/pilot_cli.py audit mission-xxxxxxxx
python scripts/pilot_cli.py handoff mission-xxxxxxxx --output result.json
```

将 `mission-xxxxxxxx` 替换为实际返回的任务编号。

## 能力与限制

- **已实现**：目标导向的生产状态导航、现有有限模型验证的一键执行、已有工单/契约/版本的状态整合、保守失效、可追溯的本地操作日志。
- **未实现**：任意自然语言自动得出完整可靠规格、无人工授权自动执行生成的 C++、企业级代码沙箱、多 Agent 自主开发、强密码学签署、生产发布许可。
- **证据范围**：当前模型检查属于有限范围，C++ 属于受审查的本地测试。SQLite 哈希链可发现部分篡改，**不能抵御拥有数据库写权限的强对手，绝非数字签名**。
- **已知遗留**：部分历史集成套件联合运行偶发超时；浏览器实际联网访问在当前环境受管理员策略限制，不能算作 Windows 原生浏览器验收。新 UI 的构成、路径与脚本已通过检查，但用户可用性仍需真实用户研究。
