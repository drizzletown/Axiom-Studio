# Axiom Studio 1.3.0 — 行为规格候选工作台

发布日期：2026-10-28。本地受控研究原型版本。定位冻结：面向 AI 的软件构造与可信演化体系，复用 VS Code，不重复实现编辑器。

## 开始使用（直观的操作顺序）

1. 打开 **软件构造全景**，从软件目标建立示例项目。
2. 检查现有行为规则；在 **确认验收规则** 界面编写“前提—动作—预期结果”，保存场景。
3. 点击 **让 AI 帮我提出行为规则**。可复制设计任务交给 VS Code/AI、粘贴完整 `.ax` 规格；若有 OpenAI-compatible Chat Completions 端点，必须经明确许可才能上传目标、场景和规格。
4. 在新工作台查看原规格与候选的文本差异，点击 **独立检查候选规则**，执行 Axiom check、plan、verify、model gate。失败候选不能进入新版本。
5. 对每个场景，人工选择候选中实际存在的 Property，或选择“暂无对应性质”。勾选审查确认后，**批准并创建演化项目**。
6. 新项目从 `draft` 重新开始：重新验证新规格、人工确认场景、重新冻结契约。原项目的证据、Gate 和批准不被移植。

## 实现机制

- `studio/spec_workshop.py`：规格候选的 SQLite 持久化、不可变源码摘要、当前输入一致性检查、审计事件、候选查询与历史。
- `studio/static/spec_workshop.js`：面向普通用户的四步式操作、差异预览、验证结果、场景关联审查和演化入口。
- 实际 Axiom 模型检查在独立临时证据目录进行；不执行生成的原生 C++。
- 关联只表明人工主张的可追溯性，并不证明场景与性质在语义上等价。
- 规格草稿对原项目只读；人工批准后才为演化子项目创建 **新的** `.ax` 文件。原工程若含 C++ 清单，同时创建独立 `.json` 清单副本，测试源文件不改动。
- 模型通过后还会在创建演化项目之前重验一次；父规格、场景及原项目审计链发生变化则拒绝推广。
- 环境变量：`AXIOM_STUDIO_LLM_ENDPOINT`、`AXIOM_STUDIO_LLM_MODEL`、可选 `AXIOM_STUDIO_LLM_API_KEY`。仅支持 HTTPS 远程端点或 localhost HTTP 开发服务，不配置时使用任务复制/手动粘贴。

## 接口

- `GET /api/spec-workshop/task?id=<wf-id>`
- `GET /api/spec-workshop/list?id=<wf-id>`
- `GET /api/spec-workshop/get?candidate=<sp-id>`
- `POST /api/spec-workshop/create` — `id, source, notes`
- `POST /api/spec-workshop/generate` — `id, consent:true`
- `POST /api/spec-workshop/check` — `candidate`
- `POST /api/spec-workshop/promote` — `candidate, digest, mappings, confirmation`

写操作均受 Studio 会话令牌保护。候选源码与持久化记录使用 SHA-256 校验；这不是外部数字签名。

## 可验证结果与限制

- 1.3 规格工作台专项 12 项通过，其中使用了真实 Axiom 模型检查、模拟本地模型 HTTP 接口与仅检查文件结构的 C++ 清单分支测试。
- 既有验收场景、新手引导、总控 26 项通过。
- 原始 Windows 环境安装、未经信任源码的安全沙箱、真实商业大模型的生成效果、全部旧版联合回归未在本轮验收。
- 用户自然语言不能自动产生可证明其等价的 Axiom 规格；规格草稿可能含有不完整或错误的建模假设。
- 单用户本地 SQLite 与摘要链不构成敌对环境下的独立可信签署，不能授权生产发布。

## 命令

```bash
python -m pip install -r requirements.txt
python -m pytest -q studio/tests/test_spec_workshop.py
python -m pytest -q studio/tests/test_intent_spec.py studio/tests/test_journey.py studio/tests/test_cockpit_release.py
python scripts/release_selftest.py
python run_studio.py
```
