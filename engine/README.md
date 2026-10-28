# Axiom P0—P2h 可运行研究原型

**Axiom 0.2 冻结理论基线不变。** 概要设计：V1.0。工程版本：1.0.0。

本工程已有：P0 有限状态模型验证；P1 可信本地 C++ 的有限差分与 ASan/UBSan 检查；P2 第一批同一行为内核下的逐义务证据复用；**P2b—P2f 跨模型依赖、双组件抽象交错、有限 C++ 轨迹和真实原生线程历史测试**。

> 本工程未提供通用 C++ 精化证明，也不具备生产级不可信代码安全执行能力；最新 P2f 仅对观察到的真实 C++ 线程历史进行测试级线性化检查。`Ready` 只代表两个独立抽象模型在指定证据依赖下满足集成准备条件。`Approved` / `Tested` 也均受前述阶段范围限制；不是生产发布许可。

## 运行环境及快速开始

Python 3.10+，Lark 1.1+，pytest 7+。P1 C++ 演示另外需要 g++（支持 C++20、ASan/UBSan）。

```bash
python -m pip install -e '.[test]'
python -m pytest -q
python scripts/run_p2b_demo.py
```

## P2b CLI

```bash
ax --workspace .axiom compose-gate examples/composition/composition.json
# 初始 Blocked：未有独立模型证据。
ax --workspace .axiom verify examples/composition/account.ax
ax --workspace .axiom verify examples/composition/flag.ax
ax --workspace .axiom compose-gate examples/composition/composition.json
# Ready：仅限“独立抽象模型验证 + 声明的证据依赖”。
ax --workspace .axiom audit
```

其余 CLI：`check`、`plan`、`verify`、`gate`、`impact`、`evolve-impact`、`evolve-gate`、`cpp-verify --trusted-local`、`cpp-gate`、`evidence`。

详见 `docs/P2B_实施说明.md`；已有历史设计、源码和回归测试保留在包内。

## 可信性与执行安全

1. 模型有限穷举的 `Bounded` 不意味着任意输入、并发执行或真实 C++ 实现已证明正确。
2. P2b 不会在缺失导出性质、缺失模型验证、证据不匹配、形成循环依赖时批准集成准备。
3. `audit` 是本地对象/索引的一致性检查，没有独立可信密钥管理，不能对抗同权限写入者伪造一致的证据。
4. P1 C++ 编译器和候选程序没有经过安全审计的 OS 沙箱。只允许运行事先审计的可信本地代码，生产级安全执行仍属于未完成工作。

## P2c 第三批：真实跨组件抽象行为检查（0.5.0）

在 P2b 的**独立模型证据依赖**之外，本版新增 `ax product-verify` 与
`ax product-gate`。两者使用 `ax-product-composition/0.1` 显式配对两个有限
抽象模型的全部 Action，同步输入且要求输出相等，并穷举同步原子操作形成的
乘积状态空间，检查跨组件关系不变量。报告可追溯、可回放，产物摘要与当前
模型绑定。Gate **必须同时具有两个局部模型证据和同一绑定版本的乘积验证证据**。

```bash
ax --workspace .ax-prod verify examples/product/Source.ax
ax --workspace .ax-prod verify examples/product/Mirror.ax
ax --workspace .ax-prod product-verify examples/product/product.json
ax --workspace .ax-prod product-gate examples/product/product.json
python scripts/run_p2c_demo.py
```

`examples/product/product_broken.json` 中的两个独立模型都能分别通过局部
有限验证，但同步时会违反 `MirroredState`，验证器输出可复现反例。

**限制：** 只支持两个组件、每个 Action 恰好参与一对同步、两端输入参数及
值域一致、输出相等、原子同步执行；不支持任意交错、消息队列、网络故障、
通用组合精化证明、真实 C++ 组合正确性，也没有不可信 C++ 的 OS 沙箱。
任何验证超出资源预算都给出 `Unknown`，不通过 Gate。先前 P1 的 C++ 执行
仍仅限经审计的可信本地程序，不能把这里的抽象乘积结论用于生产发布。

详细的验收与设计边界见 `docs/P2C_实施说明.md`。


## P2d 第四批：两组件交错执行与独立签名证据（0.6.0）

新的 `ax interleave-verify` 穷举双组件的**独立原子操作交错**与**显式同步 rendezvous**，在每一个全局状态检查跨组件安全性质，并返回最短步数的反例（BFS）。`ax interleave-gate` 要求两份当前局部模型证据以及同一组合绑定的模型级有界检查证据。所有 Action 必须恰好被归类为同步对或独立操作之一，避免漏掉可执行行为。

```bash
ax --workspace .ax-new verify examples/interleaving/Source.ax
ax --workspace .ax-new verify examples/interleaving/Mirror.ax
ax --workspace .ax-new interleave-verify examples/interleaving/product_safe.json
ax --workspace .ax-new interleave-gate examples/interleaving/product_safe.json
ax --workspace .ax-new interleave-verify examples/interleaving/product_broken.json
python scripts/run_p2d_demo.py
```

`product_safe.json` 同步修改两侧状态、独立执行只读 `peek`，组合安全性质成立；`product_broken.json` 允许两边独立执行 `set`，即使两个局部模型均通过，也会被一次独立步骤打破跨组件相等不变量，产生可复现反例。所有性质都仅涉及有限抽象状态与**原子操作边界**；不存在线程指令交错、网络故障、异步消息队列、公平性/活性、C++ 实现精化的结论。

### 可选的独立 Ed25519 证据确认

新增 detached `ax interleave-attest` 与 `ax interleave-verify-attestation`：外部受信任签名者在当前 Gate 通过、证据完整性审计通过、有限验证器独立重放通过以后，对特定绑定版本的摘要出具 Ed25519 签名。验证方必须在受保护的部署/CI 控制域内**固定公钥与预期 signer ID**，并独立重算当前报告与 Gate。私钥必须处于工作区之外，且不得随源码包发布。

```bash
# 在隔离的可信签名工作区执行；private.pem 不应属于 Axiom 项目或候选代码工作区：
ax --workspace .ax-new interleave-attest examples/interleaving/product_safe.json \
  --private-key /secure/offline/private.pem --signer trusted-qa --out /secure/out/receipt.json

# 在独立受控的验收方环境执行：
ax --workspace .ax-new interleave-verify-attestation examples/interleaving/product_safe.json \
  --public-key /secure/pinned/trusted-qa.pem --signer trusted-qa \
  --attestation /secure/out/receipt.json
```

**安全声明：** 这仅认证受信任签名者认可了某个有限抽象模型检查结果，不能认证真实 C++ 的执行正确性，也不是远程证明。若攻击者控制签名私钥、验签程序或外部公钥配置，签名不能建立可信性。普通 `interleave-gate` 仍只是本地完整性准入，不因此成为生产发布准入。当前仍不能安全运行不可信 C++；`cpp-verify` 继续要求 `--trusted-local`。

完整设计与验收见 `docs/P2D_实施与验收.md`。

## P2e 第五批：Linux 隔离执行与 C++ 多步可观察轨迹检验（0.7.0）

新命令 `cpp-trace-verify` 将双组件布尔状态模型与 **真实编译运行的 C++ 候选** 连接。仅支持 `Source`/`Mirror` 两个组件、同步 `set` 和两个独立 `peek` 操作、固定的 C ABI。它枚举所有长度不超过 `--depth` 的**原子操作调度序列**，在每条序列前复位状态，重复并逆序运行，逐步核对 C++ 返回值及状态快照是否属于抽象语义允许的后继。正常和 UBSan 两个二进制分别运行。失配返回反例；构建失败、超时、沙箱不可用均不可准入。

C++ 编译器和二进制在试验性的 Linux `user`、`mount`、`network`、`pid` 命名空间中运行，并通过 chroot 隔离工作目录；`/usr` 只读，网络 namespace 不配置外部接口，设置 CPU/文件/输出限额。**该机制没有生产级沙箱安全认证**，缺少 seccomp 白名单、cgroup 资源强限制和内核攻击面的防护，不能视为已能安全执行任意恶意 C++ 代码。若内核不允许建立命名空间，验证结果为 `Unknown` 并阻断。

```bash
python -m pip install -e '.[test]'
ax sandbox-probe
ax --workspace .ax-p2e verify examples/interleaving/Source.ax
ax --workspace .ax-p2e verify examples/interleaving/Mirror.ax
ax --workspace .ax-p2e interleave-verify examples/interleaving/product_safe.json
ax --workspace .ax-p2e cpp-trace-verify examples/interleaving/product_safe.json \
  --candidate cpp/trace/correct.cpp --depth 4
ax --workspace .ax-p2e cpp-trace-gate examples/interleaving/product_safe.json \
  --candidate cpp/trace/correct.cpp --depth 4
python scripts/run_p2e_demo.py
```

`cpp/trace/broken_one_side.cpp` 与 `broken_hidden_state.cpp` 为故障注入样例，验证器会返回可复现失配轨迹。`cpp-trace-gate` 检查当前抽象模型证据、跨组件证据、候选源码摘要、当前检测器版本以及给定深度的 C++ 测试证据；即使显示 `Approved` 也只指 **cpp-deterministic-schedule-tested-prototype**，并始终标记 `release_authorized=false`。

**范围边界：** 并未真正运行多个 C++ 线程；调度覆盖是**原子 API 调用序列**，不是指令级交错，也不包含实际弱内存模型、数据竞争、网络延迟或崩溃恢复；不能被解释为一般 C++ 精化证明。旧版 `cpp-verify` 仍须 `--trusted-local`，未自动迁移到本隔离路径。P2e 仅交付受限的跨组件 C++ 行为试验，尚未完成 P2 整体验收。

## P2f 第六批：真实 `std::thread` 并发历史与线性化检查（0.8.0）

新增 `ax cpp-history-verify` 与 `ax cpp-history-gate`：在上一阶段的受限双布尔组件 Axiom 规格之上，使用 C++20 的两个 **真实操作系统线程** 同时运行 `axiom_call`，记录每次调用的 invocation/response 的全局原子事件序号、操作输入与返回值，再通过搜索满足实时优先关系的顺序执行，检查有限**观察到的**历史是否存在合法线性化；全部线程退出后，用测试专用 `axiom_snapshot` 检查最终状态。

候选 ABI 不同于 P2e：`axiom_reset(left,right)`、`axiom_call(opcode,desired) -> int`、`axiom_snapshot(&left,&right)`，见 `cpp/history/correct.cpp`。绑定的抽象规格仍为 `examples/interleaving/product_safe.json`。已包含带互斥锁的正确 C++ 实现、单边状态更新错误、仅在重叠调用时出现错误的候选。

```bash
export PYTHONPATH=src
python -m pytest -q
python scripts/run_p2f_demo.py

ax --workspace .ax-p2f verify examples/interleaving/Source.ax
ax --workspace .ax-p2f verify examples/interleaving/Mirror.ax
ax --workspace .ax-p2f interleave-verify examples/interleaving/product_safe.json
ax --workspace .ax-p2f cpp-history-verify examples/interleaving/product_safe.json \
  --candidate cpp/history/correct.cpp --repeats 2
ax --workspace .ax-p2f cpp-history-gate examples/interleaving/product_safe.json \
  --candidate cpp/history/correct.cpp --repeats 2
```

`repeats` 范围 1..16，每次使用六组固定并发模式并逆序重放。每轮重置状态，启动两个 `std::thread`，各执行 1—2 个操作；检查器强制验证同线程顺序及非重叠调用的实时顺序。验证器不是完整的并发状态空间穷举；操作越短，某些指令级交错可能永远未被观察到。

**重要保证边界**：`Tested` 是实际发生的、已完成调用历史在指定样本下的线性化测试结论，不是一般 C++ 并发精化证明、不是整个 C++ 内存模型保证，也不等于不存在数据竞争。本版使用 UBSan 而**没有**取得有效的 ThreadSanitizer 检查结果。最终状态检查依赖候选实现的专用快照适配器，其正确性本身需要审计。沙箱仍仅为实验性 namespace/chroot 隔离，不可信 C++ 代码的生产级安全执行未实现。Gate 所显示的 `Approved` 仅为 **cpp-native-threads-observed-linearizability-tested-prototype**，并始终为 `release_authorized=false`。

P2f 同时实现**源代码修改导致实现级测试证据失效**的连续版本实验：抽象语义证据保持有效，改动后的 C++ 证据必须重新运行；本地存储报告支持一致性审计，但不存在独立可信存储或外部签名的实现级证据放行。

## P2g 第七批：种子调度压力测试 + ThreadSanitizer + 实测增量基准（0.9.0）

保留 P2f 历史 API 和全部已有测试，增加独立的 `cpp-stress-verify` / `cpp-stress-gate` 命令。
两个实际 `std::thread` 运行相同有限任务集合；每个测试使用记录在报告中的种子，在调用开始、进入候选 API 和返回之间注入可重复的 `yield` / 微睡眠 / 自旋扰动。**种子确定了扰动请求，但无法确定内核线程的实际调度。** 采用 Axiom 抽象操作作为独立线性化预言机，依照 C++ 观测的调用/返回事件检验，再使用独立的 normal、UBSan、ThreadSanitizer 三种构建运行同一类实验。

```bash
export PYTHONPATH=src
python -m pytest -q tests/test_cpp_stress_p2g.py
python scripts/run_p2g_demo.py

# 或完整 CLI（必须先存储两个模型与其抽象交错证据）
ax --workspace .ax-g verify examples/interleaving/Source.ax
ax --workspace .ax-g verify examples/interleaving/Mirror.ax
ax --workspace .ax-g interleave-verify examples/interleaving/product_safe.json
ax --workspace .ax-g cpp-stress-verify examples/interleaving/product_safe.json \
   --candidate cpp/history/correct.cpp --repeats 1 --seed 104729 --seed-count 2
ax --workspace .ax-g cpp-stress-gate examples/interleaving/product_safe.json \
   --candidate cpp/history/correct.cpp --repeats 1 --seed 104729 --seed-count 2

# 有缺陷但对外行为可能正确的 C++ 程序，会被 TSAN 检出辅助共享变量的竞争：
ax --workspace .ax-g cpp-stress-verify examples/interleaving/product_safe.json \
   --candidate cpp/history/racy_auxiliary.cpp --repeats 1 --seed 104729 --seed-count 2

# 比较逐轮全部重验与有约束的按新性质重验，两种规模都输出实际测时。
python scripts/run_p2g_benchmark.py --state-bits 1
python scripts/run_p2g_benchmark.py --state-bits 9
```

参数范围：`repeats=1..4`、`seed=0..1000000`、`seed-count=1..8`。准入要求当前抽象交错证据、相同候选源码摘要、相同版本与种子组合、以及三种运行模式全部成功；任何编译器/TSAN 不可用、超时、线性化失败或检测到数据竞争均不得通过。审计检测证据记录不一致；本地同权限写入者仍可能伪造一致的存储，本阶段不是独立信任根。

已知限制：该压力测试仅覆盖**观察到**的有限线程历史；ThreadSanitizer 只对实际执行到的访问报告数据竞争；实验隔离依旧未具备 seccomp/cgroup 级的生产安全保证。即使 Gate 显示 `Approved`，它也始终设置 `release_authorized=false`。此阶段**没有**形式化证明任意 C++ 实现的正确性，也未完成 P2 所有退出条件。

测试数据与风险分析见 `docs/P2G_实施与验收.md`。

## P2h 第八批：多文件 C++ 项目的依赖绑定与增量回归（1.0.0）

新增 `cpp-project-verify` 和 `cpp-project-gate`。这一批不替换 P2f/P2g 的原生线程历史检查，提供**独立的多文件 C++ 项目**原型。样例含两个实现组件（`Ledger`、`receipt`）、两个模块级测试及一个跨组件集成测试，另外绑定同目录中经独立穷举的 `ledger.ax` 抽象模型。

```bash
export PYTHONPATH=src
python -m pytest -q tests/test_cpp_project_p2h.py
python scripts/run_p2h_demo.py
ax --workspace .ax-p2h cpp-project-verify examples/cpp_project/project.json
ax --workspace .ax-p2h cpp-project-gate examples/cpp_project/project.json
# 强制重新运行全部测试目标
ax --workspace .ax-p2h cpp-project-verify examples/cpp_project/project.json --full
```

每个 C++ 测试目标使用隔离构建和**独立的正常/UBSan 两种执行模式**。从真实 GCC `-M` 依赖输出收集本地头文件和系统头文件的内容摘要，拒绝项目中未声明的 C++ 文件、外部未声明头文件及符号链接，并将当前规格语义、源码、编译器、构建参数、校验工具代码和系统头文件快照绑定到缓存键。只有 `Tested` 的目标证据允许被复用；**跨组件集成测试每次都重新编译与执行**。任何目标失败、规格改变、未绑定源码加入或关键验证条件变化，均阻断本阶段 Gate。`release_authorized` 永远为 `false`。

本功能提供的是**受限、可信本地 C++ 项目的测试证据复用**，并未证明 C++ 代码对 `.ax` 规格的语义精化；测试样例规模很小、也不代表任意 C++ 编译/头文件环境、动态依赖和并发行为。实验性 Linux namespace/chroot 机制尚无生产安全审计，不得投入恶意或不可信 C++ 代码。缓存只保护工作区内文件完整性，**不抵御与 Axiom 同权限的攻击者篡改整套证据系统**。详见 `docs/P2H_实施与验收.md`。
