# Axiom Studio 1.0.0 — 本地软件生产工作台首个正式发布版

发布日期：2026-10-28

## 冻结定位

Axiom Studio 不重复制造已有的软件开发工具，而是把 AI、程序构造、行为规格、独立验证、可信证据与持续演化组织为一个完整的软件工程体系。代码编辑和调试优先交由 VS Code 等成熟工具。

## 1.0 交付范围

- **生产全景总控台**：以项目状态为入口统一呈现规格、生产契约、构造候选、独立验证、人工裁决、演化六个环节。各项状态从现有 Axiom 引擎与流程/证据管理器实时取得；无法读取或审计失败时不推断通过。
- **AI 生产工单**：保留 V0.9 的受约束候选生成/导入、内容摘要审查、人工应用、独立 C++ 工具链验证、失败诊断与明确回退。
- **多文件候选和方案对比**：保留 V0.6 多目标构造事务、全目标源文件原子切换与受控回滚。
- **批量有限模型任务**：保留 V0.8 可重试的批次持久化、规格验证与可校验交接包；默认不会执行原生代码。
- **CLI 与本地 HTTP API**：新增 `cockpit`、`doctor`，现有操作、鉴权与限制保持不变。
- **离线自验**：新增 `scripts/release_selftest.py`，在临时工作区运行真实模型验证和证据状态核对，不调用外部 AI 或原生执行。

## 安装与启动

1. Python 3.10+，联网安装依赖时需 `lark`, `pytest` 等，使用 `python -m pip install -r requirements.txt`。
2. 在项目根目录执行 `python run_studio.py`，或 Windows 下双击 `启动AxiomStudio.bat`。
3. 打开终端提供的带本地访问令牌的地址，默认查看 **软件生产总控台**。
4. 先运行 `python scripts/release_selftest.py` 验证基础安装。
5. `python scripts/production_cli.py doctor` 检查工具链；`python scripts/production_cli.py cockpit` 获取项目状态 JSON。
6. C++ 使用 Linux GCC/Clang/WSL2；任何原生编译和执行必须在审查源码后单独确认。

## 保证边界与已知限制

此 1.0.0 是**可本地安装使用的软件生产工作台正式版本**，**不是经过生产级安全认证或形式化正确性认证的企业发布流水线**。

- 测试级 `Approved/Tested` 不意味着完全精化证明、无数据竞争证明或生产发布许可。
- 实验性 Linux 隔离并不保证恶意 C++ 安全执行；仅运行充分审查的可信本地源码。
- AI 模型调用须额外配置提供商，并要求明确授权；无模型服务时仍可导入第三方生成候选。
- 历史全量联合测试在某些环境中出现过长时间阻塞。本次验收以列出的分组和干净解压自验为准，不能推断其他用例已通过。
- 单机本地服务，不提供企业多租户、外部安全审计、远程零信任部署或生产签发。
- Windows 上的 GUI/原生 C++ 执行路径没有在本次 Linux CI 环境进行原生 Windows 验证。

## 升级

保留原版工作区与 `.studio-data` 的独立备份后升级。新工程不主动导入旧版运行时的私有状态；旧版证据只作为历史记录使用。生产准入永远保持禁用。

## Release validation

The source ZIP includes the SHA-256 manifest; verify it before use. The offline self-test checks real bounded-model execution and absence of unauthorized release. It does not certify the compiler or native execution sandbox.
