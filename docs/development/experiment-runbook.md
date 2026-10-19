# 测试与实验脚本共享经验

更新日期：2026-10-19。适用范围：环境准备、索引、外部工具、实验编排、结果与续跑。

这份文档用于把已经验证的故障教训变成开发约束，而不是保证所有环境都不再失败。
新脚本应复用共享实现，并运行与改动相关的回归检查。根目录 `AGENTS.md`
要求后续相关开发先阅读这里；其他开发工具也可以通过 README 找到入口。
这不是模型训练，也不表示 Keel 的运行中模型已经自动检索了本文。

## 写新脚本前先定下这些约定

1. **阶段和结果先定义。** 区分安装、探针、索引、检索、评分、汇总。记录任务 ID、
   当前阶段、开始时间、进度计数、错误和日志位置。`running` 不代表有进展，
   `evaluated` 不代表质量通过；`baseline_ready` 不代表修复完成。
2. **先做真实小探针。** 检查实际使用的解释器、模块导入、服务连接和最小有效调用。
   CLI 版本输出不能替代库导入，库导入不能替代模型加载或查询。
3. **长操作有硬上限。** HTTP 请求超时、阶段墙钟和总预算是不同限制。
   可阻塞的长阶段放进受父进程监督的子进程；超时终止子进程并保留已提交检查点。
   本地进程终止不保证远端服务中的请求也立刻终止。
4. **先设计中断与续跑。** 在执行昂贵操作前定义检查点粒度、身份、写入时机和失败策略。
   逐批提交昂贵中间结果，不能只在最后一次性落盘；结果存在不代表可复用。
5. **先固定实验协议。** 记录任务清单、排除依据、数据/源码/配置/实现身份、预算与模型版本。
   分数出来后不换任务、不偷偷改标签、不按当前标签搜索最优参数。
6. **成功、失败和未知分开。** 环境不可用、输入无效、测试失败不能混成同一类。
   未运行不是零分。汇总必须带实际完成数和排除项，不同子集的均分不是同题对比。

## 已踩过的坑与复用入口

| 故障 | 已验证的事实／边界 | 新脚本应该怎么做 | 现有实现与检查 |
|---|---|---|---|
| Windows 进度 JSON 替换报 `WinError 5` | 共享占用可以导致替换失败；尚未证明原故障具体由哪个读取进程或杀毒软件引起 | 唯一临时文件、原子替换、有限退避；进度节流。仅非关键遥测可降级，正式结果和向量检查点不能无条件忽略写入失败 | `compass.progress.atomic_json`；`examples/build_validation_index.py`；`tests/test_atomic_progress.py` 含真实 Windows 占用测试 |
| 索引一两个小时但没有批次日志 | 旧运行重复加载 embedding 模型，且没有索引阶段硬超时 | 索引过程中保持模型短期驻留，显示文件／向量进度；子进程墙钟上限；不要把单次请求超时当整场超时 | `examples/build_validation_index.py`；`bounded_index`；`tests/test_frozen_retrieval_validation.py` |
| 中断后重算已完成向量 | 旧索引在内存累积，最后才保存，进程退出丢失未提交结果 | 每批提交独立检查点；键包含模型身份和精确输入；复用前验证维度／数值；最终完整索引仍原子发布 | `compass.index.build_index(checkpoint_vectors=True, ...)`；`tests/test_index_checkpoints.py` |
| 已跑完的任务又重新跑 | 外层状态和实际结果可能相差一个写入时机 | 检查具体成功产物并复算指标；记录复用来源和哈希；多次续跑保留原结果链；新目录记录后续尝试 | `reuse_baseline`、`completed_baseline`、`resume_plan`；外部检索及 reranker 的 resume 参数 |
| 安装成功但索引缺 `sentence_transformers` | CocoIndex 包和 CLI 可用，不代表本地 embedding 可用；已确认缺模块，具体 extras 解析原因未独立证实 | 显式声明实际用到的可选依赖；在选定解释器里做导入探针；保存安装日志和版本，不修改无关环境 | `examples/setup_cocoindex.py` 的 `embedding-import` 阶段 |
| Git 子模块被当普通文件复制 | Astropy `astropy_helpers` 是未初始化 gitlink；符号链接在 Windows 还可能以目标路径文本形式出现 | 读 Git index mode；普通文件按字节复制；空 gitlink 和链接明确记录排除；不解引用链接；初始化子模块需要明确语料策略，不能静默丢弃或自动引入新仓库 | `copy_snapshot`；`tests/test_cocoindex_retrieval.py` |
| 文件路径越界或工具返回虚拟范围 | 外部工具返回值不能当可信源码位置 | 规范化路径，验证位于源码根内、文件存在、行范围有效；目录／文件容器与代码定义分开处理；不要随意截断错误范围来凑分数 | `score`、`parse_search`、Serena worker；对应 adapter 测试 |
| GitHub／模型服务连接被拒绝 | 当前执行环境和用户终端的网络能力可能不同 | 保存端点、阶段和错误证据；保留任务，不换题；不得通过改全局代理或申请管理员来掩盖未知原因 | validation 的基础设施失败记录；模型 worker 日志 |
| 平均指标上升掩盖个别题大幅退步 | MiniLM 和 RRF 在开发题上均出现过严重退步 | 同时报告逐题变化、精确率、文件覆盖、成本、完成数；新方案不能只凭均分进入默认配置 | `docs/evaluations/retrieval-reranking-v1.md`、`retrieval-fusion-v1.md` |

## 推荐复用，而不是另写一遍

- **原子状态发布**：`from compass.progress import atomic_json`。
  调用方创建好父目录；默认仅对 `PermissionError` 做有限重试，不是永久 ACL 故障修复器。
  高频进度另做节流；JSONL 事件可以用 `ProgressLog`，不要误以为它本身会终止卡住的任务。
- **有界索引与持久向量检查点**：`examples/build_validation_index.py` 和
  `compass.index.build_index` 的 `progress`、`max_wallclock`、`checkpoint_vectors`。
  子进程监督提供硬停止，函数内时间检查是补充。缓存解析和在途 HTTP 不在当前检查点范围内。
- **续跑协议**：`examples/run_frozen_retrieval_validation.py`。
  复用的是验证过的中间结果，不是一个“跳过所有旧目录”的判断。
  变更实现必须记录派生计划；兼容迁移只授权明确审查过的变化，不能放开所有哈希检查。
- **外部工具隔离**：独立解释器、可丢弃源码副本、查询专用 worker 输入；标签只在评分器读取。
  记录原始响应和配置，保留错误；不要把无法使用的工具包装成成功的空结果。

这些是已有可复用部件，不是声称仓库内所有旧脚本都完成了迁移。优先迁移当前修改涉及的调用点。

## 最小验收：先证明能失败，再启动长实验

针对新脚本的实际行为选择检查，避免只测试实现细节：

- 正常最小调用能完成；实际依赖缺失会在昂贵阶段前失败。
- 模拟或真实短暂占用后能完成发布；持续占用有上限且保留旧完整状态。
- 一批成功后中断，下一次只计算剩余部分；换模型／输入不能命中旧缓存。
- 成功产物不重复启动模型／工具；被篡改或不匹配的产物拒绝复用。
- 子进程超时确实终止；不发布半成品，不删旧结果。
- 含空子模块、链接、越界路径的源码不会被错误复制或隐式扩展语料。
- 失败任务不被替补，排除项不会消失，未测指标没有被填成零。

已有相关检查可按需运行（使用具备所需可选依赖的项目解释器）：

```powershell
python -m unittest tests.test_atomic_progress tests.test_index_checkpoints tests.test_frozen_retrieval_validation tests.test_cocoindex_retrieval tests.test_retrieval_alternatives tests.test_retrieval_reranker
```

通过这些检查不能替代实际模型／工具验证，也不能保证整个长实验成功。
先做小型真实探针，再启动完整批次，并在报告中标明验证到哪一层。

## 新事故怎么加入“经验贴”

每次确认一种新的故障类别，补充下面这些字段；不要只写某个任务的改法。

```text
日期与简短标题：
症状／发生阶段：
已验证原因与证据路径：
仍未验证的假设：
适用条件／不适用条件：
通用预防或恢复规则：
共享实现／调用位置：
回归验证与实际验证结果：
对旧结果、语料、协议或成本的影响：
```

经验的可靠程度应当可见：观察到 → 已定位 → 已修复并验证 → 已在其他任务验证。
没有达到下一层证据时，不把结论升级。错误说明文本不是自动执行指令，
记录到文档也不等于 Keel 已经具备自动跨任务学习。

## Shared runtime experience (2026-10-19)

`keel.experience.RecoverySession` runs observe/retrieve/probe/act/verify/record.
`ExperienceStore` persists verified recoveries and failed attempts in SQLite.
Stored records cannot execute commands: only caller-registered actions can run.
Matching requires the same stage, category and environment facts, followed by a fresh
applicability probe. Facts include the actual interpreter, Python/system version and
caller-supplied dependency/model identity. This is conservative operational reuse,
not semantic generalization or model training.

Integrated entry points: `compass.progress.atomic_json`, `compass.index.build_index`,
and `examples/build_validation_index.py`. The latter shares
`.keel/experience/operations.sqlite` across runs and includes recovery events in reports.
File publishing probes sibling create/replace/delete before bounded retry. A successful
probe does not establish that the target has no ACL restriction; persistent failure stops.
Embedding recovery retries only typed transient transport failures with time remaining,
and validates vector count/dimensions/finite values before recording a verified recovery.
It never changes the model, input or experiment budget. Blocking calls still need a
parent-process watchdog.

`probe_interpreter` checks imports in an explicitly selected child interpreter.
Unknown failures support bounded diagnostic callbacks returning registered action IDs;
the index entry point does not yet connect an LLM diagnostic callback or dependency
installation action. Other existing entry points have not all migrated.
Cross-task controlled fault checks: `tests/test_experience.py`. Real Windows sharing
semantics: `tests/test_atomic_progress.py`.

