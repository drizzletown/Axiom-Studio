# Axiom Studio 1.6 — 软件构造生产线

## 一句话理解

用户定义目标与验收规则。AI 提议实现。Axiom Studio 管理候选、失败、独立测试和证据；需要用户判断的步骤才要求审批。VS Code 继续负责代码编辑。

## 从零开始

1. 运行 `python run_studio.py`，在“从目标开始”创建 `真实 C++ 工程` 项目。
2. 在生产导航中执行安全模型检查；逐项阅读验收场景，**人工确认并冻结**需求与性质映射。没有被当前性质覆盖的场景必须保留缺口，不允许进入构造。
3. 在“AI 构造生产线”选择该项目并点击“开始 AI 构造”。包含多个 `.cpp` 目标时，必须明确指定目标；这是为了防止错误修改文件。
4. 可以直接授权已配置的模型生成候选，或把 VS Code / 其他 AI 的候选完整粘贴到界面。此时不会执行或写入源码。
5. 阅读完整候选，确认内容摘要后批准应用。**授权执行 C++ 是另一项独立操作**。
6. 查看编译、测试、模型检查及 Gate 的最终结论；失败时查看诊断并由人工确认回退，然后在最多三次尝试范围内重新生成候选。
7. 导出本次生产轨迹的 JSON 摘要。该摘要带 SHA-256，但属于本地无签名记录；发布前须复核原始证据。

## 无头命令行

在 `Axiom-Studio` 根目录运行：

```bash
python scripts/assembly_cli.py list
python scripts/assembly_cli.py start wf-... --target my-project/ledger.cpp
python scripts/assembly_cli.py status as-...
python scripts/assembly_cli.py submit as-... --file candidate.cpp
python scripts/assembly_cli.py review as-... --sha256 <full-64-hex> --approve
python scripts/assembly_cli.py apply as-... --human-authorized-apply
python scripts/assembly_cli.py verify as-... --trusted-local-cpp
python scripts/assembly_cli.py poll as-...
python scripts/assembly_cli.py handoff as-...
```

AI 接入需设置 `AXIOM_STUDIO_LLM_ENDPOINT`、`AXIOM_STUDIO_LLM_MODEL` 和 `AXIOM_STUDIO_LLM_API_KEY`。每次 `generate` 都需要 `--allow-send-to-model`。若不配置模型，使用 `submit` 即可复用 VS Code。

## 禁止与局限

- 系统**不会**自行修改行为规格、测试、Gate 或项目冻结的验收契约。
- 系统**不会**把模型输出直接写入并执行；审查、应用、真实编译均需分别授权。
- AI 的自我评价不作为独立证据；验收结果来自已有 Axiom 引擎。
- 本地 SHA-256 事件链不是第三方数字签名，不抵抗能同时篡改整个数据库/文件和摘要的攻击者。
- 当前是**单一目标的可恢复构造循环**；多目标事务仍由此前的独立模块负责，两者尚未共享统一自动调度器。
- 未具备生产级恶意代码沙箱、企业权限治理、通用证明、自动生产发布能力。
- 真实模型服务是否可用取决于用户自己的配置；自动化测试使用模型模拟时会明确注明，不作为商业模型质量证据。
- 完整历史回归的偶发超时仍需单独解决。
