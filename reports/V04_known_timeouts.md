# 尚未解决的可复现性问题

- V0.4 专项测试：从完整 ZIP 干净解压后执行，两组共 13 项通过（见 V04_clean_extracted_focused_tests.txt）。
- 原 V0.3 旧版模型工作流回归：曾在 `test_model_only_and_stale_decisions` 等场景遇到超时，不宣称统一回归通过。
- 新版干净解压后的独立 `production_demo.py` 再运行：截至工具执行截止未返回结果；在源码构建工作区的首次单独运行获得完整 JSON（见 V04_production_demo.json）。该复现稳定性问题不计入本轮通过项。
- V0.4 不应作为生产级发布/安全隔离许可；护照仅限测试级原型。
