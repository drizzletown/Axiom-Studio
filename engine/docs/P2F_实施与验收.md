# Axiom P2f — C++ 原生线程执行历史与有限线性化测试（0.8.0）

设计依据：Axiom 0.2 冻结内核、概要设计 V1.0；沿用 P0—P2e 工程。P2f **未更改** Type/State/Action/Property/Observation，也未改变抽象模型。

## 实施范围

- `cpp/history/`：新 ABI 的正确、单侧更新错误、仅在重叠写入时暴露缺陷的实现。
- `src/axiom/cpp_history.py`：生成有限并发试验；用真正 C++20 `std::thread` 启动双工作线程；记录 invocation/response 顺序；基于 Axiom 语义后继检查是否存在满足 real-time order 的线性化；对静止后快照做模型对应检查。
- `src/axiom/history_store.py`：存储工件摘要与实验范围，Gate 绑定规格、源码、工具版本、ABI、测试次数和完整实验记录。
- `src/axiom/audit.py`：扩展本地记录交叉引用与基础完整性审计。
- `src/axiom/cli.py`：`cpp-history-verify` 与 `cpp-history-gate`。
- `tests/test_cpp_history_p2f.py`：纯逻辑测试、故障注入、门禁失效和实验运行。

## 线性化判定

设每个已完成调用的 invocation 序号为 `start`，response 序号为 `finish`。严格保留 `finish_i < start_j` 所产生的实时优先关系。对所有满足前驱条件的候选顺序递归搜索，每一步从已有 Axiom 模型 Action 的真实有限状态后继生成允许结果；只有全部实际返回值匹配且最终静止快照与抽象末状态一致时，该观测历史被接纳。

仅处理试验运行记录的**已完成**调用；不支持未完成调用和 pending operation 的一般线性化语义。两个线程各执行 1—2 个操作，测试样本并非所有操作指令交错。最终状态通过仅用于测试的 `axiom_snapshot` 取得，对该适配器的可信性还需独立审查。程序本身可能有未被此次执行暴露的数据竞争，也没有完整 C++ memory model 证明。

## 实验结果

环境支持实验性 Linux rootless user/mount/network/pid namespace 时，执行 `PYTHONPATH=src python scripts/run_p2f_demo.py`：

- 初始未验证 / 只有抽象模型证据：门禁阻断。
- 正确双线程 C++ 候选：`Tested`、原型 Gate `Approved`。
- 只改 C++ 源码注释（语义未变）：旧实现级证据不可复用，必须重新执行测试。
- 两个缺陷候选：`Violated`，Gate `Blocked`，提供可重现的观测历史。
- 四条实现级记录通过本地审计一致性检查；不可视为独立认证。
- 每个正常完成的编译模式执行 24 个试验、80 次 API 调用（`repeats=2`）。使用 normal 和 UBSan 两种构建，未使用 TSAN。
- 全工程自动回归 146/146 项通过（基于本次完整回归测试）。

## 运行方法

```bash
export PYTHONPATH=src
python -m pytest -q
python scripts/run_p2f_demo.py
ax --workspace .ax-p2f verify examples/interleaving/Source.ax
ax --workspace .ax-p2f verify examples/interleaving/Mirror.ax
ax --workspace .ax-p2f interleave-verify examples/interleaving/product_safe.json
ax --workspace .ax-p2f cpp-history-verify examples/interleaving/product_safe.json --candidate cpp/history/correct.cpp --repeats 2
ax --workspace .ax-p2f cpp-history-gate examples/interleaving/product_safe.json --candidate cpp/history/correct.cpp --repeats 2
```

## 限制与下一步

1. P2f 证明了测试架构可执行真实线程历史检测，但不证明一般 C++ 并发精化。不能对未观测调度作出保证。
2. 实验性隔离缺少经认证的系统调用限制与 cgroup 等资源隔离，不允许生产级不可信代码执行。
3. Gate 只表示测试级原型符合已定义记录和本地证据要求，`release_authorized=false`；仓库内能够同时改写数据库和代码的攻击者仍可能伪造一致的本地证据。
4. 下一步应扩展真实多线程任务集、探索系统性调度扰动、加入可用的 TSan 独立路径、强化隔离与外部可信证据，再开展真实 C++ 演化开销对照实验。
