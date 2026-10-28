# Axiom P2 第二批：多模型证据依赖与生命周期一致性

工程版本：0.4.0，冻结基线 AX-BL-0.2，概要设计 AX-HLD-1.0。

## 新增实现

- `composition.py`：跨模型导出性质/显式依赖的有向无环图；校验模型名字、导出项、文件位置、依赖环、重复和不认识的字段；严格核对每个模型的所有有限验证义务。输出 `Ready/Blocked`，目标明确为 `abstract-model-evidence-integration-readiness`，**不是组合行为精化证明**。
- `audit.py`：遍历内容寻址对象和模型/C++ 记录；检查证据与历史报告、模型摘要、二进制工件、Gate、评估记录之间的一致性；输出 `Consistent/Findings`。这是**同权限本地完整性检查，不是强身份认证或防恶意篡改**。
- `Workspace.record`：对声称为 Bounded 的外来验证报告重新运行有限验证器，并严格比对结果，防止上层调用伪造“验证通过”数据。
- `Workspace.object_path`：严格校验 `sha256:<64 个十六进制字符>` 的路径格式，拒绝证据记录携带的路径遍历内容。
- 新增 CLI：`ax compose-gate composition.json`、`ax audit`；保持 P0/P1/P2 原有接口不变。
- 新增 `scripts/run_p2b_demo.py`，支持连续 12 次演化的验证义务簿记实验。

## 复现

```bash
python -m pip install -e '.[test]'
python -m pytest -q
python scripts/run_p2b_demo.py

# 单独复现多模型准入：最初会阻断
ax --workspace .axiom-p2b compose-gate examples/composition/composition.json
ax --workspace .axiom-p2b verify examples/composition/account.ax
ax --workspace .axiom-p2b verify examples/composition/flag.ax
ax --workspace .axiom-p2b compose-gate examples/composition/composition.json
ax --workspace .axiom-p2b audit
```

## 阶段局限

1. 消费方与提供方的 `dependencies` 表示**证据/契约依赖声明**。本版**未验证**接口调用绑定、共享状态、消息交错、环境假设及跨模块运行行为，不能称为 assume-guarantee 组合证明。
2. 证据复用仅限同一规范化行为内核的有限抽象模型；尚不支持行为变化后的正式精化证明，也不代表 C++ 实现证明。
3. 内容校验和重放增强了同权限工具调用的稳健性；没有外部可信签名者，具有工作区写权限的攻击者仍可伪造一套自洽文件。
4. C++ 编译与执行仍未实现经过安全审计的 OS 沙箱：**绝不运行不可信输入**。CLI `--trusted-local` 是使用风险确认，不是安全隔离。
5. 连续演化实验统计的是**复用的验证义务槽位**，并没有证明墙钟时间缩短。为确保实验可信，每个版本同时执行完整模型检查。
6. 待补：P1 独立执行沙箱与独立证据签名、真实跨模块组合义务、实施级依赖传播，以及长期性能与缺陷率对照实验。
