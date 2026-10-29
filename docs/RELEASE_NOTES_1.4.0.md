# Axiom Studio 1.4.0 — 让行为规格可以被理解和比较

## 交付内容

- 可读规则评审：对 Type / State / Action / Property / Observation 做 AST 层面的新增、修改、移除差异解释。
- 逐场景复核提示：保留旧性质、性质被改写、性质消失、原本没有关联的场景，分别说明，不伪装成证明。
- 两候选并排比较：必须先完成各自独立有限模型检查；同项目、同冻结输入、相同场景摘要；不自动推举胜出方案。
- 无代码优先 UI：风险与需求缺口以用户语言呈现；高阶规格文本仍供专家按需查阅。
- 误批准保护：文本编辑但尚未重新暂存时，UI 立即禁止继续验证或批准旧候选。
- 只读评审 HTTP 接口：`GET /api/design-review/inspect?id=...&candidate=...` 和 `GET /api/design-review/compare?id=...&candidate=...&candidate=...`，要求本地 Token。

## 信任边界

比较基于当前被固定的 .ax 模型结构与已有的独立验证**历史记录**，不是重做完整验证，也不证明文本需求在形式规格中完整表达。没有自动采纳、没有执行 C++、没有新增生产发布权限。外部可观察行为变化和动作差异可能影响兼容性，必须人工审查。SQLite + SHA-256 为本地误改检测，不是第三方可信签署。

## 安装与测试

```
python -m pip install -r requirements.txt
python scripts/release_selftest.py
python -m pytest -q studio/tests/test_design_review.py
python run_studio.py
```

**环境限制**：浏览器自动化通过 Playwright 注入现有前端与真实后端结果完成，实际本地 HTTP 接口另行测试；宿主浏览器的网络访问被环境策略阻止。历史大规模联合回归仍有超时，不声称已完成全部回归。原生 Windows 未在当前环境操作验收。
