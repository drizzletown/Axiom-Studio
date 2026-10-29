# Axiom Studio 1.7 — 多模块软件生产任务图

## 一句话说明

软件生产计划将一个工程的多个可修改 C++ 模块组织为依赖任务图。用户不需要管理验证命令，而是在模块就绪时启动既有的 AI 构造生产线，审查代码、明确授权 C++ 执行；系统记录独立验证通过的候选文件摘要，再允许后继模块启动。

此版本提供 **串行执行的依赖编排**，不包含多 Agent 并行修改或无监督执行。它复用 Axiom 1.6 Assembly、WorkOrders、Proposals 和 C++ 引擎，并不重复开发编辑器。

## 图形界面

1. 在“从软件目标开始”创建或打开有 C++ 工程清单的项目。
2. 先完成模型检查、验收场景核对和人工冻结契约。
3. 打开“跨模块软件生产计划”，选项目，点击“创建跨模块生产计划”。默认依工程模块生成串行依赖链。
4. 选择“开始这个模块”，进入 1.6 的 AI 构造生产线；人工审查候选，批准应用，独立授权 C++ 编译与测试。
5. 回到任务图，点击“同步各模块验证结果”。只有实际独立测试级通过，下一模块才会解锁。
6. 所有模块测试通过之后，还必须返回项目 Gate 和人工裁决；任务图本身不具备生产发布权。

## 命令行

```powershell
python scripts/task_graph_cli.py list
python scripts/task_graph_cli.py create <project_id>
python scripts/task_graph_cli.py status <graph_id>
python scripts/task_graph_cli.py start <graph_id> <workspace-relative-cpp-target>
python scripts/assembly_cli.py status <assembly_id>
python scripts/task_graph_cli.py sync <graph_id>
python scripts/task_graph_cli.py handoff <graph_id>
```

手工定义有向无环依赖，使用 `--tasks-json plan.json`，例如：

```json
[
  {"target":"generated_project/ledger.cpp","depends_on":[]},
  {"target":"generated_project/format.cpp","depends_on":["generated_project/ledger.cpp"]}
]
```

请按实际项目路径替换。只允许工程清单中的 `.cpp` 实现模块，不能计划测试、规格或清单文件。

## 数据与安全语义

- 创建时绑定项目版本、冻结契约、规格与清单摘要、列入工程清单的源文件和测试文件摘要。
- 后继任务依赖前序任务的 **独立 C++ 验证通过状态**，并绑定被验证候选 SHA-256；仅查看或暂存 AI 代码不会解锁任务。
- 所有模块在同一受信本地工作区串行操作；不是通用并行调度、事务型多仓库提交或安全沙箱。
- 只要有未经授权的源文件、测试、清单、规格变化，任务图立即阻断；需要人工进行演化版本处理，不自动继承证据。
- 事件链采用本地 SHA-256 哈希记录，能够发现意外篡改，但 **不是外部可信数字签署**。
- 每个模块执行编译/测试前必须由用户单独确认。不能将模型 Gate 或 C++ 测试级结果宣传为完整形式化证明或生产发布许可。

## 结构

- 后端：`studio/task_graph.py`
- API：`/api/task-graph/{list,get,create,start,sync,handoff,targets}`
- 前端：`studio/static/task_graph.js`
- 命令行：`scripts/task_graph_cli.py`
- 测试：`studio/tests/test_task_graph.py`
