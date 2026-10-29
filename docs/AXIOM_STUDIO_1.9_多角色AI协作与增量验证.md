# Axiom Studio 1.9：可控多角色 AI 协作与保守增量验证计划

## 定位
不重新制造编辑器。复用 1.8 的跨模块任务图和 VS Code，新增两角色协作和更直观的变更影响建议。

## 日常操作

1. 完成软件目标、规格模型验证和人工验收契约冻结。
2. 在跨模块生产计划中创建任务图，点击“并行生成各模块构造任务”。
3. 在某个模块点击“AI 起草 + AI 复核”。须明确授权将规格与源码传输至模型接口。
4. 浏览完整候选和 AI 复核建议，点击“我已阅读源码：仅暂存候选”。
5. 经原有生产线的人工审查、授权应用、独立 C++ 验证与 Gate 后才算测试级通过。
6. 通过“查看变更影响”读取模块下游闭包及必须重做的全局检查。

## 模型配置

`AXIOM_STUDIO_LLM_ENDPOINT` 采用 OpenAI 兼容 Chat Completions 地址（HTTPS 或本机 HTTP）。
`AXIOM_STUDIO_LLM_MODEL` 为模型名称；可选 `AXIOM_STUDIO_LLM_API_KEY`。
没有模型时可用现有 VS Code 手动交接任务包。不在客户端存储密钥。

## 核心边界

- Builder 生成代码；Reviewer 只提供建议，**不属于独立验证**。
- 生成和复核仅通过允许的远程 API 调用，不自动运行、应用或暂存候选；后续暂存也必须由用户点击。
- 1—2 轮 AI 交互，超时和响应限额阻断；每轮使用不可变输入快照，变更即弃稿。
- 候选单独内容寻址存储；审计是本地哈希链，**不是可信签名**。
- 增量分析采用依赖可达性形成重验范围建议；无法证明隐藏依赖不存在。
- 全局 Axiom Gate、C++ 集成测试与 Gate 不会自动省略，禁止无证据复用与生产发布授权。
- 仍未完成系统级隔离执行、任意规模多 Agent 自治与生产级安全认证。

## CLI

```bash
python scripts/agent_cli.py status GRAPH_ID
python scripts/agent_cli.py impact GRAPH_ID cpp_project/module.cpp
python scripts/agent_cli.py run GRAPH_ID cpp_project/module.cpp --consent
python scripts/agent_cli.py stage AGENT_RECORD_ID SHA256 --acknowledge
```
`run` 的模型调用可能产生费用，并向配置的服务发送规格和源码。

批量生成：`python scripts/agent_cli.py batch GRAPH_ID moduleA.cpp moduleB.cpp --consent`（最多 3 个并行任务）。
