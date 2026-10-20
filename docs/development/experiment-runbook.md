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

## Syntax-error fixtures and explicit corpus coverage (2026-10-19)

An index can have every extracted symbol embedded and still be incomplete.
The Django 14725 run-v6 index retained one parse diagnostic. Upstream
`test_tag_fail_to_load` deliberately imports the invalid module inside an
`assertRaises(SyntaxError)` block. This is not a transient embedding failure.

`compass.coverage.index_coverage` retains strict full-corpus behavior by default.
The explicit `valid-python` evaluation policy only excludes parse-error files
whose exact indexed bytes are independently rejected by both Python AST and
tree-sitter. It records path, hash, interpreter, line and checks, without changing
index metadata or source files. File-size limits, valid-source extraction defects,
changed files and unclassified diagnostics remain blockers. No path or task-ID
exception is used, and the policy is evaluated without relevance labels.

`compass.sweep.run_swe_sweep(coverage_policy='valid-python')` records the policy
and exclusion inventory, keeps `index_complete=false`, and refuses to treat a
task with unindexed reference source as a successful measurement. A valid-Python
measurement is not a strict full-corpus success.

Frozen validation accepts `--index-coverage valid-python` only with an explicit
resume. The derived plan records the corpus-policy amendment, retains original
failures and task data, and reuses unaffected complete baselines after checking
eligibility. Never reinterpret a previous failed row in place or edit fixtures to
make a benchmark pass. Checks: `tests/test_index_coverage.py`, `tests/test_sweep.py`.

## External-tool recovery and transport capability (2026-10-19)

Serena can raise `Matched N>max_matches=100 symbols.` for a broad identifier.
`keel.tool_recovery.symbol_queries` uses the shared `RecoverySession`: substring
query, relative exact query, then upstream absolute/root exact query if needed.
All attempts share at most eight tool calls and a deadline. Only a typed
match-overflow error permits narrowing; permission and unknown errors propagate.
No source paths, task IDs, gold labels or raised result limits are involved.
Successful normal queries follow the original path. Evidence records rejected
queries, unqueried terms, failed recovery attempts and verified response shapes.
Source range and final quality checks remain separate; a query recovery is not
proof of a better answer. Actual cross-task experience is stored only when the
registered action and response validator succeed.

For a daemon timeout, do not infer a network/model failure from unrelated log
warnings. `keel.ipc.probe_named_pipe` runs a small server/client exchange using
the selected interpreter, with bounded subprocesses and cleanup. In this tool
environment the server returns WinError 5 and the client WinError 2. This verifies
a local transport permission boundary, not that all user terminals are broken.
`examples/cocoindex_retrieval_worker.py` now checks this before copying sources
or loading models, records `TransportUnavailable`, and does not attempt privilege
changes. Cached measurements remain usable after identity checks. A fresh user
terminal may support the transport; the same entry point must probe it again.

Worker changes are recorded in derived plans. Only explicitly reviewed predecessor
hashes permit reuse of successful unaffected measurements. Failed attempts are
retained and retried separately. Checks: `tests/test_tool_recovery.py` and the
CocoIndex transport-preflight regression in `tests/test_cocoindex_retrieval.py`.

## Native index deadlines and checkpoint continuation

Run-v10 passed transport checks and loaded its model, but reached the 900-second
worker deadline during indexing. Its native database was about 50 MB. The later
BrokenPipeError followed client termination; it is not evidence of the initial
cause. Rich transient progress is not useful redirected evidence. The CocoIndex
adapter now uses the upstream streaming callback and flushes counters to
index.stdout.log, with a ten-second heartbeat and the original hard deadline.

A retry may clone a stopped native checkpoint only after checking the package,
embedding settings, exact source manifest, archived source bytes and corpus
settings. The original run stays intact. Upstream incremental indexing validates
the cloned state at its new location; vector reuse is not independently measured
and successful continuation still requires a completed index and valid search.
This path has unit coverage; full Django continuation needs a terminal that passes
named-pipe preflight. Do not claim the timeout resolved before that run succeeds.

Run-v11 verified native continuation: 2,401 unchanged files, 330 additions,
zero processing errors, successful index response. Search then failed because
the new progress adapter indexed `.` while the CLI used a resolved absolute root.
The upstream client only translates path mappings; its daemon registry keys are
literal project strings. Both names attempted to open the same native database.
Always pass the resolved absolute project root across API/CLI boundaries. The
adapter now does so, with a canonical-path regression check. Search-stage failures
can clone the stopped checkpoint too. Full search success remains unverified
until the next native run; preserve the failed run and do not score it as zero.

## Native competitor comparisons

Audit upstream documentation and versioned source before claiming product
equivalence. `aider_retrieval_worker.py` calls native Aider ranked tags; its
query-only identifier hints and independent AST range packing are explicit
component adaptations, not full Aider. Record the native module hash and version.
`setup_aider_retrieval.py` uses an isolated pinned environment, actual-interpreter
probe, shared progress/atomic result writers and finite process deadlines.
Record `PIP_NO_INDEX` when installation finds no versions: that message alone
does not prove the package/version is nonexistent. Do not disable environment
network policy or infer quality from missing dependencies. Native installation
and a source/query-only probe must succeed before reporting native metrics.

## Same-pool structural ranking experiments

`compass.structural` reorders only supplied candidate IDs using resolved static
calls and fixed PageRank/RRF settings. Keep candidate membership, source ranges
and packing unchanged in a ranking-only experiment. Native Aider's different
pool belongs to a separately disclosed arm. Freeze task IDs and implementation
hashes before scoring new tasks. Include structural plans in exposure_registry,
including failed/planned IDs. `run_structural_validation.py` checks receipt and
artifact hashes before reusing completed tasks and uses parent-bounded task
processes. Network-bound snapshot failures are infrastructure outcomes, not
retrieval misses.

## Bounded continuation across index attempts

`examples/continue_index_validation.py` supervises repeated invocations of the
unchanged frozen structural runner. It retries only baseline index/recovery
wall-clock exhaustion, never coverage exclusions or unknown errors. A subsequent
round requires increased checkpoint vector counts or a newly completed task.
The supervisor has a round cap, total deadline, exclusive supervisor lock,
heartbeat log and per-round before/after observations. Deadlines include waiting
for a current run. On total deadline it stops its launched process tree; it does
not terminate a pre-existing run it is merely waiting for. Prior runner receipts
and failed attempts remain intact. Additional attempts are not first-attempt
benchmark scores. No frozen task, ranker setting or per-attempt budget changes.

Structural continuation revealed another corpus mismatch after Astropy 12907's
index completed: its reference ranges include `pyproject.toml`, while this
experiment indexes Python only. Xarray 3993 similarly includes `.rst` files.
For future protocols, run the existing reference/corpus eligibility check before
expensive embedding work, in the evaluation layer only. Do not expose reference
paths to retrievers, silently remove those labels, or retrofit corpus expansion
into an already frozen scored experiment. Retain the original exclusions.

This prevention is now implemented by `compass.evaluation_scope.reference_scope`
and gated in future `run_structural_validation.py` plans before embedding. It
reuses the indexer's source inventory and size policy and returns a recorded
out_of_scope result without passing reference paths to adapters. Unit checks
include an actual runner gate asserting that embedding/native tools are not
called. Scope eligibility is necessary, not sufficient for parse completeness.
The original v1 run is closed and its runner archived; new gate implementation
requires a new frozen plan, not silent migration of old scored results.

## Mixed text corpus experiments

`compass.text_corpus.TextCorpus` provides optional SQLite FTS5 retrieval over
declared Git-tracked text extensions with exact source-line windows, per-file
checkpoints, size/encoding omissions and stale/incomplete-index rejection.
`run_mixed_corpus_validation.py` freezes a separate protocol and preserves saved
Python-only controls' original coverage failures. It never removes reference
paths to improve scores. Passing expanded-corpus coverage does not imply improved
retrieval: the first five-task fixed interleave regressed on every task. Report
admission, chunking, ranking and packing interventions separately; do not promote
a richer corpus or force tool use merely because all files can now be indexed.

## Separate optional text-search MCP capability

`CompassService(enable_text_search=True)` adds `search_text` to that service's
tool list; default MCP discovery stays unchanged. Keep text retrieval separate
from automatic code-context mixing. The Scout-only profile is generated with the
selected interpreter and an absolute launcher while the bound repo follows the
active workspace. External caches stay outside audited source. Validate row/byte
caps, source freshness, ledger visibility and role restrictions, not just tool
discovery. SDK memory interoperability and raw-process stdio are distinct from
full SDK subprocess validation. Record transport-blocked checks explicitly.
See `docs/compass-text-search.md` and `tests/test_text_mcp.py`.

## Cold-build deadlines versus test failures

The optional Compass pilot's Matplotlib reference exhausted a 1,800-second
total harness deadline after roughly 930 seconds building its environment and
then installing system packages in the instance image. Its last log began the
editable wheel build, before tests. Inspect internal stage logs before assuming
dependency incompatibility or changing pins. `swebench_bridge.py grade --timeout`
exposes a bounded total deadline (default unchanged) and records it in grading
metadata. A longer retry needs a fresh output directory and must retain the
first timeout; it is not a replacement first-attempt score. Keep successful
paired tasks intact. A successful retry is required before claiming recovery.

## Package-source network failures

The Matplotlib reference retry failed in apt downloads with HTTP 502 and
connection timeouts, exit 100, before tests. Do not treat this as a dependency
version conflict. `keel.network_probe` and `check_repository_network.py` separate
host DNS/HTTP observations from runtime-container access using an existing image,
without pulling images, mounting host files or changing proxy/DNS settings.
Requests and subprocesses have deadlines; timeout cleanup targets only the
uniquely named diagnostic container. Permission-denied Docker access is an
unobserved container network, not proof of remote outage. Three regression
checks cover layer separation, credential-URL rejection and permission handling.
The initial tool-host probe failed HTTP access and could not access Docker;
ordinary-terminal container evidence is still required. Runtime-container
success does not prove build-network or large apt-download success. No recovery
experience should be marked verified until the reference actually completes.

The ordinary-terminal homepage probe later returned 200 in both layers, yet
another apt build still failed on concrete `.deb` downloads. A homepage sample
is insufficient recovery evidence. Use `--download --build` with an actual
failed package URL: the same bounded probe reads to EOF or the explicit byte
cap in host, runtime container and a disposable build. `download_complete`
requires EOF within the cap and a matching Content-Length when supplied;
HTTP reachability alone is not a complete download. This does not verify package
checksums or the whole apt transaction. The build inspects the local image ID,
uses no pull and no cache, and never retags harness images. Diagnostic images
are removed when possible. A Docker CLI timeout does not guarantee remote build
cancellation; do not interpret it as a completed or recovered build. Fixed
per-layer deadlines bound the local probe; retain failures and do not launch
full reference grading merely because a small request succeeds.

The first disposable build incorrectly used `FROM sha256:<local image ID>`.
BuildKit interpreted it as `docker.io/library/sha256:<tag>` and failed before
RUN; this is a diagnostic implementation bug, not a network-test result. Use
the inspected local image name/tag in FROM, with pull disabled, and verify its
ID again after building. Retain the ID in the result and reject changed or
unverifiable identities. Tests must inspect the generated Dockerfile as well
as command flags; mocked exit codes alone did not catch this failure.

After all three Python URL probes downloaded the package, `--apt-build` was
added to the same entry point. It uses `/usr/lib/apt/apt-helper download-file`
inside a disposable build, without install/update/source changes. A Linux
file-size limit caps output; a 30-second child deadline kills its process group.
Report completion, bytes and SHA256 only on successful download. This tests
APT acquisition of one URL, not index freshness, dependency resolution or the
full parallel/repeated installation workload. SHA256 is an observation, not a
comparison against trusted package-index checksums. Real Docker validation is
required separately from mocked portable tests.

`check_repository_network.py --apt-script <archived setup_repo.sh>` now extracts
one original standalone update/upgrade/install chain for an independent build.
Reject unsupported shell syntax instead of executing the rest of the repository
script. Preserve exact command, source hash, base ID, deadline and streamed log.
An archive cache keyed by base ID uses a locked BuildKit mount; docker-clean is
disabled only in this diagnostic image to retain downloads. This disclosed
cache-retention adaptation is not the original harness or an official score.
No automatic repeated full installs: inspect the bounded attempt first. Completed
APT work is not a successful Matplotlib install or reference-test result.

The first workload probe stopped before APT: Python's Windows text writes
created CRLF in `apt.sh`, making Bash reject `pipefail\r`. All generated Linux
shell files must use byte writes or explicit LF newlines. Assert raw bytes,
not `read_text()` comparisons (which normalize newlines). Existing harness
transport LF handling does not automatically cover newly generated contexts.

The corrected workload reproduced successful index update followed by HTTP 502
on some upgrade package downloads. `keel.network_probe.bounded_apt_attempts`
now supports at most three attempts under one total deadline, with per-attempt
logs and saved outcomes. Only fetch errors containing transient transport
evidence are retried; other fatal APT errors stop. Index-download warnings do
not count as success even with exit zero. `--attempts` defaults to one, so
recovery must be explicitly enabled. The original command, packages and sources
stay unchanged; the existing archive cache is shared. Completion verifies only
this diagnostic workload, not the reference task or a learned generic recovery.

APT may emit `repository ... InRelease is not signed` immediately after a
transient InRelease fetch failure. Retry only if the same repository URL and
suite match an explicit transient `/dists/<suite>/InRelease` failure; standalone
unsigned errors, other repositories, permanent fetch errors and explicit
NO_PUBKEY/BADSIG/EXPKEYSIG evidence stop. Never disable authentication. The first
three-attempt workload stopped after one attempt because this causal correlation
was missing; retain that outcome. Tests cover matching and mismatched suites,
standalone signature failures and mixed permanent/transient errors.

## Bounded network diagnosis after retries

The existing network entry accepts `--failed-workload` plus `--model-config`
in APT-script mode. `keel.network_recovery` validates the prior image/script
identity, supplies bounded redacted log evidence and host-extracted failed URLs,
and uses six model steps, a 60k-token ceiling and one shared wall-clock budget.
Registered actions are HTTP/HTTPS APT acquisition probes, one isolated HTTP
pipeline-depth-zero workload experiment, and stop. There is no arbitrary shell,
proxy/DNS edit, source switch or authentication bypass action. Failed and invalid
decisions return as observations, repeated actions are rejected, and recovery
requires full diagnostic APT completion. Probe success alone remains unresolved.
The pipeline experiment keeps exact packages and original command, using an
isolated APT_CONFIG; label it changed transport conditions, not an original
official reference score. Paid model diagnosis is explicit opt-in. This is not
automatically enabled on every runtime entry, nor is cross-task learning proven.
Tests simulate multi-round failed-probe/next-probe/recovery trajectories; actual
Docker/model execution is still required. A transport diagnosis may stop within
its supported action scope without establishing the root cause.

## MCP validation contract drift

The SDK subprocess validator retained a four-tool discovery assertion after
`get_symbols_overview` became a default fifth tool. This mismatch can be wrapped
in an SDK TaskGroup ExceptionGroup, hiding the useful cause. Update explicit
validation expectations when adding default tools, exercise the new tool via
the SDK, and report bounded leaf exception causes. Optional `search_text` stays
absent from default discovery. Memory-stream SDK checks do not replace the
Linux CI subprocess check; require the real CI rerun before claiming it passed.

## Canonical adapter boundaries

`parse_search` resolved result paths but compared them with an unresolved
repository root. Canonicalize both before containment and relative-path checks;
Windows temporary aliases/short names or relative roots must not create false
escapes. Keep traversal, existence and line-range validation strict. Report
which check failed instead of collapsing all failures into `invalid range`.
A relative-root CRLF fixture reproduces the mismatch independently of platform;
the exact Windows CI temporary-path alias remains unverified until rerun.

## Git encoding-filter test fixtures

An encoding test expected a diff immediately after adding working-tree-encoding
attributes without changing file bytes/stat. Windows CI returned no diff while
local Git reported one. Make the temporary fixture's newline policy explicit
and invalidate the target mtime before asserting filter-induced differences;
assert raw bytes still equal the committed blob. Keep the subsequent real-edit
rejection. This changes the fixture, not snapshot acceptance rules. Verify the
Windows runner again; local passes alone do not prove the CI cause resolved.

## Network ReAct protocol corrections

The first live network diagnosis spent three of six turns citing nonexistent
evidence, then used all remaining turns for probes. It did not execute recovery.
Always provide exact available evidence IDs, prior invalid decisions and explicit
non-execution feedback; a failed initial log is not a successful probe. Select
targets from the most recent failed attempt before older package URLs. Cap probes
at two and expose remaining registered actions so a successful inspection can
lead to a recovery test within the same model budget. These controls do not
force recovery: the model may stop, and full workload completion is still required.
Regression checks cover fabricated-ID correction, recent-stage selection and
probe-budget reservation. Preserve the unsuccessful live run as evidence.

Network reflection now receives bounded actual APT failure excerpts after a
transport workload experiment. That registered action is removed after one
attempt under unchanged conditions. Shared `ExperienceStore` records outcomes
in `network-experience.sqlite` beside runs; matching uses setup hash, image name,
base image ID and transport-policy version. Only a completed workload with a
matching concrete base ID is verified. Missing identity is not learned as
success. Prior verified experience is advisory and never skips fresh probes or
grants actions. Failed attempts are retained and surfaced as recent outcomes.
This is operational memory, not model-weight learning or proof of general
environment recovery. Tests cover failure-feedback handoff and prevent past
success from authorizing an uninspected current recovery.

The second live network run stopped after a successful current-stage probe,
with no recovery test despite remaining budget. Distinguish uncertainty from
blockage: a reversible registered experiment can test a hypothesis without
already proving root cause. Network recovery now challenges one early stop when
completed probe evidence permits an untried workload experiment and sufficient
time/steps remain. Review consumes the same model budget; a second stop is
accepted and recorded unresolved. This is not forced success or unbounded
persistence. Tests cover review-to-recovery and accepting a repeated stop.

## Resume reference grading under explicit transport conditions

The live network ReAct v3 completed the full diagnostic APT workload under
no_pipeline; its base ID matched and ExperienceStore recorded verified workload
completion. This is not proof of pipelining as root cause (cache/time differed).
`swebench_bridge.py grade --network-policy no_pipeline` now passes a child-only
registered policy to the harness adapter. It injects APT_CONFIG before repository
APT commands, preserves the original command/source/tests, and uses a separate
instance-image tag. The grading report stores policy/hash and discloses changed
transport conditions. Do not stack with packaging overlays or overwrite the
original comparison. Cached diagnostic image retention was disabled there;
this reference policy changes only pipelining, so success must be verified again.

Reference transport grading completed but reported 35 failed, 66 passed and
8 skipped tests. Many failures raise a version-scheme DeprecationWarning in
vcs_versioning, despite installation output reporting setuptools_scm 7.1.0.
Do not pin blindly or suppress warnings. Existing `environment_probe` now records
the selected interpreter, sys.path, launcher paths/shebangs and module/distribution
locations. `check_repository_network.py --inspect-grade` exposes that same
network-disabled, read-only instance inspection. This inspects the saved image,
not the deleted post-test container; it cannot prove what evaluation-time
installation changed. Compare against test-time logs before proposing recovery.

The saved instance inspection confirmed both setuptools-scm 7.1.0 and
vcs-versioning 2.6.0 register `release-branch-semver`; pytest uses testbed.
`--inspect-grade ... --check-scm-plugins` now compares each provider on identical
parsed SCM input, keeping DeprecationWarning as an error, and lists possible
reverse dependencies. This is a read-only counterfactual, not an uninstall or
full reference validation. A provider difference supports a collision hypothesis
but does not justify removing a required dependency without checking metadata.
The first inspection cut JSON mid-object at 14k characters. Preserve complete
JSON up to a declared 256 KiB cap; oversized results explicitly fail instead of
silently becoming invalid JSON. Tests cover warning-preserving provider
comparison and a valid result larger than the former truncation threshold.

## Evidence-gated SCM recovery and automatic reference continuation

`swebench_bridge.py recover-reference` validates the frozen task/reference and
the failed reference log, performs fresh read-only provider inspection, then
immediately invokes grading with registered `remove_unused_vcs_versioning`.
The policy is not an arbitrary uninstall tool: it requires the failing SCM
provider, a passing original provider, and no active reverse requirements at
execution time. Inside the disposable harness environment it uninstalls only
that provider, compares pip-check output before/after (pre-existing problems
are disclosed, new problems fail), and verifies default version calculation in
a fresh interpreter with deprecations treated as errors. The guard runs after
repository/evaluation installs. It does not alter tests, warning policy, source
or host packages. Combined network/plugin conditions get a separate image tag
and explicit grading metadata. Recovery has one shared deadline and one grade
attempt; success requires the actual official report. This is a registered
recovery for a known failure family, not arbitrary autonomous environment repair.
Do not merge reconstructed results into the old frozen comparison score.

Recovered reference policies are now validated against their recorded file
hashes by `run_swebench_task`, propagated into the trusted intermediate verifier
and final grade, and frozen throughout inference. Continuation preparation on
`run_swebench_tool_comparison.py` admits only a selected old task whose arms never
started, copies its frozen task/export, inherits unchanged model/profile and arm
order, binds successful reference files, and freezes current implementation.
The continuation executes just those two arms and reuses the successful reference
without regrading it. Prior completed pairs and their scores are untouched.
Disclose separate reconstructed conditions; do not call it the original frozen
first attempt. Tests cover propagation, reference tampering and skipped regrade.

## Interrupted paired run and patch-byte salvage

The Matplotlib continuation lost its terminal during optional-arm verification.
Keep its interrupted status and completed local-arm failure. Runtime patch
writing used Windows text translation over CRLF diff payload lines, producing
CRCRLF and malformed exported hunks. Write patch bytes exactly; test generated
CRLF-source diffs with Git reverse-apply checks, not string presence alone.
`swebench_bridge.py grade-snapshot` grades a preserved workspace Git diff with
the reference's validated policies and no new model calls. It checks exact base
HEAD, restricts changes to existing unprotected Python sources and records source
hashes; it does not modify old reports or restore conversations/global budgets.
This is independently scored saved source, not an Agent runtime pass or resumed
first attempt. Regrading cannot establish missing audit stages of an interrupted
run. Long-lived remote Docker containers may outlive a dead launcher; inspect
ownership before cleanup, never terminate unrelated containers.


## Saved-source failure feedback into a new Agent attempt

`run_swebench_task.py --resume-snapshot DIR --saved-repo DIR` binds a failed
saved-source grading to its task, successful reference conditions, source hashes,
base-relative patch and official report hash. Plan-only mode performs these checks
without inference. A new isolated checkout receives the validated patch. Critic
first reviews observed test failures and the saved diff, then Scout localizes
current source and the ordinary repair/verification loop runs under one fresh
attempt budget, including Critic calls. The original interrupted run is unchanged.
This is source-and-evidence continuation, not restoration of conversations or the
old global budget. New audit stages cover edits made in this new attempt; they do
not retroactively certify omitted stages of the interrupted run. Final export
includes the entire base-relative patch, while runtime changes.patch records the
new attempt delta. Reuse the reference's validated environment policies at every
verification. No task-specific repair answer belongs in this mechanism.
Regression checks cover Critic-first repair, shared budget exhaustion, source/report
tampering and existing reference/export behavior. Real task success remains an
experiment outcome, never inferred from passing synthetic regression tests.

## Model credentials before experiment side effects

A saved-source continuation reached Critic with no model credential in the current
terminal, then unnecessarily graded the unchanged seed. The task runner now
constructs and validates model configuration and invokes the provider's existing
local credential check before reference inspection, subprocesses, output creation
or workspace preparation. It reuses that model instance; no authentication request
or paid inference is used for preflight. Missing/invalid values exit immediately
without a trial directory or final grade. Plan-only remains credential-independent.
The regression covers missing and whitespace-invalid values, zero subprocess /
Agent / harness calls, and no secret value in the error. Local presence checks do
not establish remote credential validity or guarantee later service availability.
