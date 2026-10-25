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

### Runnable source baseline and independent repetitions (2026-10-23)

runtime_snapshot.create_snapshot copies every implementation_hashes entry as raw
bytes into an isolated runtime tree, then checks source stability and verifies the
copy; verify_snapshot rejects changed/missing/added runtime files. Snapshot output
must be new; no overwrite. Creator dependency versions/interpreter are observations,
not a recreated environment lock or frozen remote model. Prompts/configs must also
be copied and hash-bound; never archive arbitrary credential files. Execute from
snapshot root with the snapshotted runner, not the live workspace. Tests cover
CRLF preservation, independence from live edits and changed/added-file rejection.
run_frozen_model_review supports explicit bounded request_budget (max80k tokens,
180s;1call per arm) so a known34k-byte prompt is not rejected by old24k default.
Critic stability study uses3predeclared independent samples, each48k tokens/60s,
same1024output; failed samples retained, no automatic retry or optional stopping.
Protocol completion is not semantic diagnosis or end-to-end repair reproducibility.

### Preserve completion failure diagnostics (2026-10-23)

full-repair-v5 stopped in the first Critic call before proposal/token-policy logic.
Adapter raises ModelCompletionError with finish reason, refusal/tool flags, usage
and output cap, but FrozenModel formerly wrote only exception type, losing cause.
FrozenModel now records a typed allowlist of these diagnostics plus known tokens;
never serialize arbitrary provider error text, raw exception objects or unknown
diagnostic fields. Propagate the same exception; no automatic paid retry. Test:
test_model_transport.test_completion_failure_preserves_safe_diagnostics_without_retry_or_secret_text.
Old missing finish reason cannot be reconstructed;1024output cap is a suspect,
not proof of truncation. Use a bounded frozen Critic-only check before another
full grading run; do not attribute pre-proposal failure to context-policy changes.

### Repair authorization versus displayed evidence (2026-10-23)

Workspace-protected paths (including tests and root escapes) are PolicyDenied and
must not enter model-response correction retries. A writable target lacking current
displayed evidence is InvalidProposal: reject the entire batch before any write,
allow bounded correction only against displayed files, never expand allowed_files
from a model claim. Protected paths pass through workspace policy first. Regression:
test_proposal_validation_feedback.test_policy_failure_never_retries,
test_proposal_evidence_scope (no partial writes and declared/unshown correction),
test_proposals.test_undeclared_writable_target_is_rejected_without_writes.
Local reproduction exposed contradictory legacy expectations. An attempted stricter
declared-target terminal rule also broke existing stale-target recovery tests and
was reverted; correction of rejected text does not authorize writing that target.
Use an actually protected path in the policy-no-retry fixture, not an ordinary
unselected writable path. Keep no-partial-write and bounded-correction assertions.

### Proposal evidence overflow after diagnostic handoff (2026-10-23)

Token-policy successor: see docs/proposal-context-budget.md and context_budget.py.
Explicit model-context/per-call-input/safety/independent-byte limits replace a
percentage relationship; remaining global budget and output reservation bind each
proposal. Legacy policy still supported, mutually exclusive. No deleted evidence.
Default estimator is visibly conservative bytes; offline encoding optional and
not provider exact. Adapter usage metadata and calibration reports support future
measurement, not automatic policy relaxation. Do not describe local/stub counting
tests as a calibrated tokenizer or Responses exact-count integration.

Explicit elastic proposal admission: agent.proposal_context_hard_bytes opts into
a hard ceiling from max_context_bytes up to at most110% of that soft target.
Default remains soft==hard. Scope is proposal modes only; no expansion of Scout,
Critic or probe requests. Always attempt existing lossless repacking above soft;
admit complete remaining payload only below hard and after shared input/output
budget reservation. Trace proposal_context_admitted with limits, used bytes and
output allowance. Runtime/config validation rejects bool/missing-soft/oversized
headroom before dispatch. SWE task flag --proposal-context-hard-bytes records
policy in trial/plan reports. Existing conservative byte-as-token estimate is
unchanged; this is not a model-token-window calibration or semantic trimming.
Tests test_proposal_context/test_proposals include cap enforcement, source-value
preservation, no dispatch on global-budget denial, and admission telemetry.

Small-overflow follow-up: minify full user payload JSON layout before reselection,
never whitespace inside source/log strings. Test semantic equality after decoding.
V3 replay48,075->47,999 under48k but only1byte margin: this is admission evidence,
not a robust headroom solution. Do not use this result to assert stable repairs.
Distinguish local byte cap from model token window and global billed-token budget;
soft-target/explicit bounded overflow policy remains planned, not implemented.

Capacity recovery follow-up: `ProposalCapacityExceeded` reports request bytes,
limit and fixed bytes after removing writable-source evidence. If the fixed floor
already exceeds the limit, source reselection cannot help; RecoveryController
records a trace and stops without a paid reselection. Otherwise allow normal
reselection, but reject a repeated identical failing goal/evidence/dependency/
readonly context before scheduling another selection. Distinct evidence remains
eligible; this is a no-progress guard, not automatic repair or budget expansion.
Regression coverage in test_proposal_context includes both stop paths, successful
changed selection and capacity-floor accounting. Success-request replay retains
goal/source/permissions/guidance; already-compacted view notice is not regenerated.

Full-repair-v1 reached the failing write in a model-designed probe, then five
source reselections exhausted recovery before patch generation. Fixed goal evidence
included duplicated outer execution JSON; narrowing source alone could plateau.
`proposals.compact_goal_evidence` produces an overflow-only view of JSON evidence
lines: minifies JSON layout and removes outer stdout only after exact equality
with retained child result, successful transport and empty outer stderr. Natural
task text, source windows, child output/code/status and provenance are preserved.
Raw goal remains in transcripts/ledger; request includes a view notice. Distinct
transport output stays intact; hard cap still applies. This does not guarantee
arbitrary requests fit. Tests: test_proposal_context plus proposal/repair suites.
Stored-request replay proposal-context-replay-v1:49,760->47,796bytes at48k,
0model/Docker calls, selected source unchanged. Not live patch/acceptance proof.

### Diagnostic request accumulation (2026-10-23)

Both model-contrast-v2 arms stopped before call3 at the local32k request cap,
despite remaining model-call/time/token budget. Stored execution rows contain
both outer JSON stdout and the parsed child probe, duplicating output in prompts.
Keep raw observations immutable. `diagnostic_inspection.request_view` removes an
outer stdout only when its parsed JSON exactly equals the retained child result,
and the outer process succeeded without stderr/timeout. If still too large,
older readable source windows are explicitly marked omitted with text hashes and
read/search reacquisition instructions. Keep complete child code/output/status,
IDs, freshness and source manifest; never silently truncate observations. Trace
every omission and retain the hard cap if the remaining request still cannot fit.
Only probe-comparison requests opt into this policy. This is request admission,
not a relevance check or successful diagnosis. Tests: test_diagnostic_request_view;
real stored-request replay: model-contrast-context-replay-v1/report.json,0model/
Docker calls; mini35,705->28,377bytes,full34,642->31,264bytes. Reconstructed next
requests are not paid end-to-end results. Version future paired plans explicitly.

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

## Catalog paging can defer selection and correct an invalid page response

A saved repair produced a useful Critic diagnosis but stopped before modification:
Scout repeatedly selected IDs absent from the displayed page. Previously every
intermediate page required at least one ID and the generic retry restarted the
catalog, although relevant files could appear later. Intermediate pages now allow
an empty carry; the final catalog result must still be nonempty. One invalid-ID
response receives explicit same-page feedback and one correction, under the same
model/token/time budget. Page construction reserves correction prompt space;
repeated invalid IDs still fail closed. No unseen ID is admitted and no task answer
is supplied. Regression checks cover empty early pages reaching a later candidate,
same-page correction, and rejecting a repeated invalid response. This mechanism
is tested synthetically; a fresh real repair is needed to establish task success.

## Exact proposal application across LF/CRLF transport

The saved-source repair reached Implementer, but its first proposal matched zero
raw substrings because model JSON used LF and the checkout used CRLF. Read-only
replay found all three first-proposal edits uniquely match after line-terminator
alignment; another proposal still has a genuine content mismatch. Proposal
validation now aligns old/new LF/CRLF terminators to uniform source style, then
performs the original exact unique match, AST/audit checks and atomic batch
validation. The actual writes use those validated aligned strings. Unchanged
regions are never rewritten; mixed/lone-CR source remains strict exact matching,
without guessing a dominant style. Newline-only proposals are not effective edits.
Normalization indices are recorded with proposal validation. Tests cover both
newline directions, byte preservation, ambiguity, atomic rejection, no-op and real
content mismatch. Historical proposal replay is not fresh Agent execution or
proof of official repair success. Preserve all old artifacts and use a new output
for the next model/harness run.

## Preserve inspected source as navigation hints after an exploration turn limit

The next real continuation again failed catalog selection despite explicit
same-page correction. Scout had read relevant source but used all exploration
turns, so its final summary was absent; the full alphabetical catalog restarted
without preserving inspected paths. Exploration now records host read_file /
read_lines paths only when their source hashes match the exploration snapshot.
These paths are filtered through the full writable Python catalog and any
caller-supplied allowed scope, then displayed first without excluding other
candidates. They are navigation hints, not automatic repair targets. Paths are
not extracted from model prose or arbitrary MCP payloads. Cached evidence is
reused only under the existing unchanged-source/goal check.
Paged selection schemas now enumerate exactly the displayed page plus carried
IDs. Host validation remains authoritative for noncompliant providers. Pagination
capacity checks include the same enum schema used by actual calls and reserve
bounded correction space within the configured context cap. Tests cover a local
turn limit after protected/source reads, source-first display with other candidates
retained, protected-path exclusion, enum membership and bounded page sizes. No
real-task success is claimed before another model/harness attempt.

## Preserve tested repair candidates rather than exporting only the last edit

The Astropy transfer attempt executed three verification rounds but finished with
2 preservation failures versus 1 in the saved seed, then exhausted the next-call
budget. Do not turn this into success by rerunning or reporting only the issue test.
The task runner enables preserve_repair_candidates for adaptive localized repair.
Failure feedback includes a hash of the complete grouped tested-ID universe;
only completed grading with matching identity and per-group totals is comparable.
Each candidate's declared source bytes, hashes and observed verification are
archived separately. A conservative explicit ordering minimizes PASS_TO_PASS
failure count first, then FAIL_TO_PASS failures; ties retain the earlier version.
This is a policy tradeoff, not universal quality or proof that every test improved.

On budget exhaustion, deliberate recovery stop or verification failure, validate
scope/audit and checkpoint hashes before restoring the retained source. New files
first touched after that checkpoint revert to their recorded pre-edit bytes.
Historical attempts remain in the report, runtime remains failed, and independent
final grading evaluates the selected workspace afresh. Do not restore after
policy/audit failures or claim that inherited source gained retrospective audit.
Mixed/incomplete/unknown test evidence is not ranked. Checkpoints are local run
artifacts, not conversation resume or changed global budgets. Tests cover CRLF
byte restoration, keeping failed attempt evidence and failed status, rejecting a
different test universe and refusing tampered checkpoint bytes. Real Astropy
transfer effectiveness remains untested after this change. This does not yet
enforce that a Critic next_check was performed: that is a separate remaining gap.

## Bind Critic source inspection to fresh observations before another proposal

Astropy transfer produced repeated next_check diagnoses while editing did not
converge. The task runner now enables require_diagnostic_inspection for adaptive
localized repair. After a non-stop Critic route (including saved-source entry),
localization/planning determines writable scope, then a bounded inspection chooses
1..3 source windows from that scope plus existing failing-test Python paths.
The host executes read_lines through the read-only Scout gateway, records actual
fact IDs, source hashes, line limits and truncation, and requests a short assessment
citing only those observations. Test reads never expand write scope. Changed
source hashes or invented fact IDs are rejected before a proposal. Insufficient
evidence stops the attempt without inventing execution; normal candidate selection
can retain an earlier tested version. Supported/refuted assessments and actual
observations are given to the proposer, retaining original scope and audit rules.

Two model calls per inspection and all reads share the run's existing budget;
there is no shell, arbitrary probe, package install, budget reset or task-specific
answer. Host checks establish provenance/freshness/citation validity, not semantic
proof that every natural-language next_check was completed. In particular reading
code is not executing a reproducer. Assessment remains a model judgment and the
independent verifier remains authoritative. Regression checks cover a successful
Critic-read-assess-edit sequence, read-only test evidence, invented citation denial,
insufficient-evidence stop and model-budget exhaustion before editing. Synthetic
checks do not establish Astropy transfer success; a separate fresh run is required.

## Adaptive diagnostic paging: chunk limits are not task failure conditions

The next real Astropy inspection requested test lines 5600..5685 (86 lines),
which the diagnostic wrapper rejected before reading because it imposed the
underlying 80-line chunk limit on the entire requested range. A valid large source
range now passes through the shared read_lines gateway, which still bounds each
observation to 80 lines / 3000 characters. Host progress reports actual read bounds,
effective requested end (clipped to EOF), unread line count and next unread line.
The model may finish based on sufficient evidence, request the pending remainder,
or choose different windows within the same readable scope. It cites actual facts
and explains the next check, without arbitrary shell execution or write access.

The host tracks interval coverage without allocating ranges proportional to a
possibly huge requested end. Repeated covered windows are not read again. New
source lines are a cheap coverage signal, not proof of relevance or approaching a
solution. A first no-progress round permits changing direction; a second consecutive
no-progress continuation stops. Continuing with no pending range/new check also
stops. There is no fixed total page-count limit in this loop: all model calls,
reads, context sizes and wall time remain bounded by the original global budget.
Source hashes are revalidated; range overlap does not count as new coverage and
no continuation can expand readable paths. Prior source bodies stay in the ledger;
new prompts contain current pages and a prior fact index, while the final proposal
receives at most three cited source observations with explicit provenance.

Regression checks cover an 86-line range completing as 80+6 with model-visible
remaining progress, repeated-range suppression/no-progress stopping, global-budget
exhaustion and path escape denial. The original failed run is untouched. Synthetic
coverage checks do not establish real Astropy repair success or validate a model's
claim of semantic progress; independent grading remains authoritative.

## Locate named diagnostic targets before scanning unrelated pages

The real adaptive Astropy inspection performed 15 assessment calls, covered 919
new source lines and stopped on repeated reads without editing. It scanned roughly
900..1600 in a test file while the named failing test definition was at line 2020.
This demonstrates why new line coverage is not semantic investigative progress.

Diagnostic checks now support literal {path,query} searches as well as source
ranges. The shared Workspace search_code implementation accepts an optional paths
scope, uses a distinct cache key and preserves path policy/budget checks. Scoped
literal search does not require building a Compass index, and test files remain
read-only. Before planning, names from observed failed test IDs are searched in
those existing files. Located definition lines and actual search fact IDs are
navigation evidence, not generated test answers or permission to edit tests.
Repeated identical searches reuse observations rather than charging new scans.

Progress reports distinguish targets located/read from lines covered. Two rounds
that still miss the same target require a target-directed search/read, otherwise
stop; repeated unchanged next_check text and citations also stop. Reading a target
signature is only a navigation milestone, not proof of having understood its body.
Search-only citations cannot finish supported/refuted without a cited source read.
All previous global limits, no-progress protection and source hash checks remain.
Models can still misjudge relevance: independent source modification, audit and
verification determine task success. Tests cover a target after 2000 unrelated
lines, search-then-read navigation, early stopping of continued blind scanning,
scoped search isolation and metadata path denial. Real full repair remains pending.

## Replay cached source bodies across diagnostic searches without inventing progress

The next real inspection found/read the target immediately but still stopped:
subsequent stateless assessment requests showed search hits and only an index of
older source reads. When the model requested those reads again, interval dedup
skipped the tool without replaying the existing body. It therefore repeatedly
claimed it had not seen the implementation. This was a context-delivery defect,
not evidence of an unavailable source or proof the model could not solve the bug.

Diagnostic request construction now keeps up to three complete relevant source
pages alongside current search results. Requested cached ranges take priority,
followed by search-matching source, previously cited source and recent windows
per file. Omitted body IDs are explicit and the full fact index/ledger remains;
a narrower range selects another cached page. No source body is silently sliced.
Covered read requests replay original fact IDs/text without a new read_lines fact,
coverage increment or no-progress reset. Source hashes are checked before reusing
bodies and after assessment. The model may conclude with sufficient evidence on a
replay round, while endless requests still stop under unchanged global budgets.
Tests exercise read-search-replay completion, one read fact and zero new coverage,
bounded body retention/explicit omissions and stale-source denial. Real historical
windows were replayed read-only; no old source, score or model budget was changed.
A fresh real repair is still required to establish task effectiveness.

## Stop layering mechanisms when development repair efficacy is unproven

A descriptive review of six Astropy continuation revisions recorded 553,140 tokens
and 114 model-call attempts without a resolved continuation. These revisions are
not paired controls and include a connection/infra error, so the totals establish
cost exposure, not causal regression or a benchmark success rate. Offline replay
of four cached-range requests confirms current context delivery only; it does not
replay model reasoning or establish future repair success.

Before more recovery features or expensive reruns, freeze a simple-vs-required
inspection pilot using the same saved patch, task, grading/reference, model/tools,
checkpoint policy and budgets. run_swebench_task exposes --diagnostic-inspection
required/off (default unchanged); both arms still use ordinary Critic feedback and
independent grading. The treatment toggle is reported explicitly. The frozen local
pilot checks implementation/input hashes, preserves incomplete/error arms, reuses
matching completed arms and stops on infrastructure/model connection failures.
One attempt per arm is not statistical evidence. If both fail, report no efficacy
winner; if both pass, report costs descriptively. Record historical failures and
include full costs rather than promoting a mechanism on synthetic tests alone.
See docs/evaluations/diagnostic-inspection-review-v1.md for the review and prepared,
not yet executed, pilot. No additional runtime recovery feature was added here.

## Completed inspection ablation: simplify defaults and retain falsifiable lessons

The frozen simple/required Astropy pair completed with no resolved arm. Simple
spent 156,074 tokens / 30 calls with four verifications; required inspection spent
68,107 / 13 with no edits or verifications. Lower spend from stopping early is not
an efficacy-preserving optimization. Actual checkpoint hashes confirm the simple
arm restored its earlier seed after four equal-ranked candidates. Preserve all
scores and do not rerun the old plan after changing implementation.

The task runner now defaults diagnostic inspection off in configuration, execute
API and CLI; explicit required remains an experimental option. This avoids an
unproven mandatory gate, without asserting a generalized performance advantage.
Offline inspection found six zero-hit prose-like queries against a literal-search
tool; individual identifiers matched in the same source copies. Store this as a
versioned experience/prompt candidate with source evidence and counterexamples,
not an automatically verified repair rule. Test unseen tool-use cases before
promoting guidance; full-task benefits still require independent evaluation.
See docs/evaluations/diagnostic-inspection-review-v1.md. No additional runtime
recovery/long-term-memory system is added on the basis of these failures.

## Separate search-contract evaluation from repair reasoning

examples/evaluate_search_guidance.py prepares or executes six synthetic literal
search cases against the real scoped ToolGateway. Cases include a legitimate
multiword phrase, case-insensitive identifier matching, recovery from a prose
query miss, a decoy in another file and an absent identifier. Expected labels and
fixture source are not included in model prompts. Baseline/candidate ordering is
counterbalanced; one response per case/arm means at most twelve model requests,
with no retries, a 45-second request timeout and a 600-second stage ceiling.
Credentials are checked before creating an execute output. Failures retain an
incomplete report and completed observations; original runs are never overwritten.
Input/guidance/implementation hashes and raw replies are recorded. No prompt is
promoted automatically. The local fixture/scoring tests verify tool behavior only;
even a perfect model score would establish neither causal diagnosis nor improved
task repair. These examples become development material after their first use.

## Diagnose through discriminating observations before claiming reflection gains

The search-guidance pilot improved a semantic boolean answer, while search choices
were identical in effectiveness. Report these components separately rather than
using aggregate scores to claim a historical failure was fixed.
examples/evaluate_diagnosis.py now isolates diagnosis in synthetic twin cases with
identical symptoms and different underlying causes. Fixed host-owned probes are
executed through CommandRunner; model text cannot become executable code. Before
execution the model predicts both hypotheses' outcomes; only actual-case results
enter the next model request, while counterfactual fixture results remain scorer
evidence. Correct guesses without valid discriminating evidence fail. Protocol
errors count as failed cases; model/infra errors stop as incomplete, preserving
attempt counts and raw replies. Use shared Budget and atomic_json; hashes and
completed-arm receipts guard resume. Existing completed arms are reused without
model calls; incomplete arms are not automatically retried. This runner changes
neither production reflection nor domain-specific repair behavior. Closed-menu
diagnosis results cannot establish free-form investigation or repair efficacy.

## Observe recovery questions without turning activity into a success criterion

The real diagnosis pilot had correct first probe choices/predictions in all eight
arms; two baseline arms failed evidence-ID validation. Do not use the aggregate
2/4 versus 4/4 as evidence for mandatory diagnostic gates. A smaller opt-in
recovery.monitor_progress now records the existing Critic question, post-decision
file/symbol facts and matching new verifier receipts, then supplies a bounded
inventory to the next Critic. Reuse the existing grouped verification_score and
test-universe comparison; no extra role, model request, permissions or stop rule.
New facts alone do not certify relevance, freshness, execution or hypothesis truth.
Without matching new verifier facts, old supplied results are not revalidation.
Terminal inventory precedes candidate restoration. The default remains off; larger
Critic input must still fit the existing context/budget caps. Validate plumbing
separately from actual task efficacy and freeze a new plan for any comparison.
See docs/recovery-progress.md and tests/test_recovery_progress.py.

## Freeze a reduced-budget recovery-feedback pair before another full task

run_recovery_progress_comparison delegates to the shared task runner, with equal
12-call / 80,000-token / 900-Agent-second ceilings and feedback as the only
treatment. New task-runner overrides can only shrink defaults and are reported.
Verify completed-arm receipts against trial, final grading and trace before reuse;
preserve interrupted outputs and stop on model/infra errors without paid retry.
Count actual Critic dispatches with progress context so a flag with zero exposure
cannot be called an effectiveness measurement. Keep fixed order, seen-task scope,
independent final grading cost and changed budgets explicit; historical runs with
different implementation/limits are not substitute controls. Freeze after all code
changes/tests, then validate inputs again before execution. Preparation is not a
real-model result. See tests/test_recovery_progress_comparison.py.

Preparation exposed a system-Python versus configured-venv mismatch: only the
latter had MCP/LangGraph. When a profile is enabled, check the actual host's MCP
client before freezing, not just the server's separate interpreter. Preserve the
unused earlier plan as invalidated and prepare a new identity under the intended
interpreter. No dependency installation or paid retry is implied by this check.

## User-authorized larger-budget exploration (2026-10-21)

After the short pair failed, the user explicitly requested one higher-budget
attempt before cost optimization. The shared task runner now has an opt-in extended
profile (60 calls / 400,000 tokens / 160 tools / 3,600 Agent seconds), twelve
recovery actions and eight adaptive verification repairs. Standard defaults stay
unchanged; overrides only shrink the selected profile. Adaptive runtime accepts
up to eight repair attempts explicitly; non-adaptive modes retain the prior cap.
Keep repeated-failure guards, provenance, audit and independent acceptance intact.
Record actual costs, stop reasons and total elapsed time; increased allowance is
not permission for an automatic sequence of new attempts. Existing frozen pairs
remain historical. Prepare a fresh single-run identity and preserve all failures.
Validate credentials before output creation; missing tool-process credentials do
not imply the user's configured terminal lacks them. If a successful trajectory
is found, treat it as development evidence and validate cost-cutting ideas rather
than hardcoding its path or claiming a new benchmark rate.

## Separate writable selections from readable evidence (2026-10-21)

An extended run stopped on repeated protected-test selection before editing;
global budget was not exhausted. Error wording alone did not prevent recurrence.
Single-request file-selection schemas now enumerate the actual writable catalog,
as pages already did. Host-observed paths outside that catalog are explicitly
read-only navigation evidence; host correction is a separate bounded field.
Keep host validation even with schema constraints, since JSON-object providers can
ignore them. Never silently filter an invalid selection or choose surviving paths
on the model's behalf. Count the schema in capacity/paging calculations. Actual
offline replay of 510 paths changes one 33,213-byte request into two bounded
46,782/20,198-byte requests; this is overhead, not a cost-savings claim. Keep
frozen prior attempts and validate real-model behavior separately. See
docs/writable-localization-contract.md and tests/test_writable_selection_contract.py.

## Proposal target handoff and bounded correction (2026-10-21)

The extended-v2 run ended on an Implementer proposal targeting a historical file
omitted from the current Scout selection. The write guard correctly prevented the
edit, but treated a writable-source scope mismatch as a terminal security violation.
Proposal schemas now enumerate only current evidenced targets (including the
schema embedded for JSON-object providers). Host validation still checks every
path and the entire batch before writing. Protected, escaping, internal and
hard-linked paths, stale source and audit failures remain terminal. A writable
out-of-scope target is an InvalidProposal: existing recovery may regenerate the
batch against unchanged, current evidence, with shared budgets and repeat guards.
No file is automatically added, retained, read or edited on the model's behalf.
This repairs an execution contract; it does not establish better localization,
causal diagnosis or task success. Preserve the historical policy-denied score.
Checks: tests/test_proposals.py and tests/test_recovery_controller.py, including
mixed-batch atomicity, correction, protected paths and repeated-mismatch stopping.

## Recovery source handoff (2026-10-21)

Progress inventories are not source delivery. When monitor_progress is enabled,
RecoveryProgress.context now includes bounded whole source windows from previously
observed facts, lexically ranked against the prior check question. It may reuse
earlier rounds but never future rounds. Each included window is compared with
current source; a recorded full-file hash must also match. Missing historical
hashes permit only a current-window-match claim, not whole-file freshness.
Reads consume the shared tool budget. Whole windows exceeding the 4,500-byte
content allowance are omitted explicitly; if the total Critic prompt exceeds its
existing cap, bodies are removed with a capacity omission marker. No cap increases,
new model calls, new source ranges or write rights are implied. Permission failures
still propagate. Model interpretation and probe execution remain unverified.

Offline v3-ledger replay selects fact14 (test body) and a fact21 source window,
using the currently restored seed; it is not a replay of historical execution or
evidence of repair improvement. Tests: tests/test_recovery_progress.py, including
actual Critic request delivery, unchanged unknown-check status, stale content,
full-file hash mismatch, byte limits and future-round exclusion. Keep the feature
opt-in and assess model diagnosis separately before another full paid repair.

Frozen diagnostic prompt pairs can use examples/run_frozen_model_review.py.
They store pending state before dispatch, preserve failed responses and validate
completed receipts before reusing a paid arm. No automatic retry follows an
unreceipted attempt. Freeze both requests before execution and record when context
is reconstructed against a restored workspace rather than historical state.
Two model responses are a qualitative review, not a repair benchmark; output
schema validity is not a diagnosis-quality score. Tests: test_frozen_model_review.

An optional targeted_source_review may resolve exact definition names explicitly
mentioned by the Critic's next_check, within current-plan and previously observed
paths. Reuse existing AST structures and complete-definition evidence; bound reads,
whole-window bytes and additional review calls. This is static read-only inspection,
not execution or permission expansion. Keep it separately opt-in, record source
hashes and inspection ledger, suppress unchanged repeat follow-ups and retain global
budgets. Single-arm frozen follow-up reviews avoid paying for completed controls
again. Do not equate a better textual diagnosis with a verified repair.

## Explicit Critic questions (2026-10-21)

CRITIC_QUESTIONS defines concise field-level obligations: failure location and
phase; established/excluded/unknown observations; prior-check execution/result/update;
and next target/question/support/refutation. Questions are included in JSON Schema
descriptions and the system prompt for structured and JSON-object providers.
Unknown is valid when the missing evidence is specified. Do not ask for private
reasoning traces or let a filled checklist count as proof of correct reasoning.
The six-field wire format remains compatible; the original 1,000-character hard
field bound has been superseded by the soft-length policy below.
Host validation checks shape and action, not truth or complete semantic
coverage of every label. No keyword-based correctness score or automatic repair
success follows. The next role receives the check's predictions as tentative
criteria, not authority to edit outside its scope. New prompt efficacy needs a
fresh frozen diagnostic review; previous plans and paid outputs remain historical.

Use recovery.validate_critic_decision in both runtime and diagnostic review so
shape/action errors are explicit. Preserve raw responses and validation_error on
failure. The historical strict-length experiment rejected evidence with 1,023
characters vs 1,000. Preserve that frozen measurement; do not repair it by
truncating text or replacing the failure with a successful completion receipt.

## Soft diagnostic length, hard resource boundaries (2026-10-21)

Per-field length is a brevity target, not a correctness or security requirement.
The live Critic schema no longer uses per-field maxLength. Nonempty string fields,
exact keys and valid routing actions remain mandatory. Over 1,000 characters
produces critic_length_warnings, recorded in runtime trace/report and review
results, without truncation or automatic retries. Runtime still checks the complete
serialized decision against configured max_context_bytes before routing; oversized
replies remain in the ledger and stop explicitly. Model output limits, transport
response limits, total token/time/tool budgets and downstream prompt caps remain.
No automatic summarization or budget expansion was added.

Revalidate saved outputs offline under a new, identified policy and retain the
original file/hash/status. .keel/repair-review/soft-length-v1/offline-review.json
shows the actual 1,023-character reply accepted unchanged by current Critic routing,
with warning and zero new paid calls. This says nothing about the diagnosis being
right or the task passing. Tests: test_critic_prompt and test_frozen_model_review,
including actual routing, no extra calls, whole-context rejection and raw retention.

## Preserve caller frames beside exception tails (2026-10-21)

verification_feedback.failure_feedback now includes bounded failure_locations,
separate from existing failure_excerpts. For each pytest failure block it keeps
the first marked statement and following reported file/line, not just the final
internal raising frame. ANSI is stripped, blocks remain separate, context omissions
and omitted block counts are explicit. Unsupported/missing caller formats return
not_established; do not fabricate a location. This is log navigation evidence,
not proof of test phase, causality or permission to access a reported path.
Reported coordinates belong to the graded snapshot, not necessarily current source.

bounded_verification retains these structured fields, so both ordinary verification
and saved-source continuation reach Critic with caller and exception evidence.
Existing observed-output markers still exclude setup and applied test patches.
Offline extraction from extended-v3 identified the first hdu.writeto call at the
graded test line 2051. Prior artifacts remain unchanged. Tests cover internal
frames, long passing tails, multiple blocks, absent callers and explicit omissions.
Changing feedback cannot establish model improvement without a fresh review.

## Optional evidence consistency supervision (2026-10-21)

Use diagnosis_supervision.review_diagnosis rather than another repair runner.
This separate-context request reviews the existing diagnosis and evidence catalog,
including stderr. Validate exact claim/evidence quotations before accepting a
conflict assessment. Quotation provenance is checkable; contradiction semantics
are not a host-proven fact. Keep the feature opt-in, same configured model, no
new tools or permissions. At most one correction and one recheck follow a conflict;
persistent conflict stops. Insufficient evidence must not be promoted to a success.
All calls share existing budgets and are recorded. Tests must demonstrate both
successful control-flow recovery and bounded unresolved conflict, without claiming
scripted-model success establishes live LLM effectiveness.

For bounded live supervision review of an archived diagnosis, use
examples/review_saved_diagnosis.py. It replays the initial diagnosis through the
production controller without a provider call, then permits up to three new calls
for review/correction/recheck. Budget model_calls includes one cached slot; report
new_provider_calls separately to avoid misreporting new spend. Shared cap is
60,000 tokens / 360 seconds, each live request at most 120 seconds. No source files
or acceptance commands execute. Freeze input evidence/config/implementation and
persist pending dispatch, ledger and report. Failed/interrupted outputs block
automatic paid retry; completed receipt-checked outputs reuse without dispatch.
Credential preflight happens before output creation. Test this with scripted
models and measure actual request capacity before giving the launcher to a user.

Observed supervision protocol failure: consistent plus nonempty no-conflict
findings, wrong claim field and added quotation marks. Schema descriptions must
say findings contains contradictions only and is [] otherwise. Enumerate evidence
IDs, validate raw exact substrings in their named origin and persist the specific
validation_error. Do not normalize away a bad reference or promote a failed review
to a successful one. A format-correct consistent verdict still requires qualitative
assessment; successful parsing cannot establish semantic supervision quality.

## Global-budget exploration (2026-10-22)

Explicit budget_driven recovery disables local repeat/action ceilings, while
keeping global calls/tokens/tools/time and write/audit rules. Supervisor protocol
errors receive validation feedback and may correct within that same budget.
Default recovery behavior remains bounded as before. Use
examples/run_bounded_exploration.py for one frozen attempt with an outer deadline
including preparation and final grading. Preserve console/watchdog artifacts and
never restart a prior dispatch. Reserve grading time within the outer cap.
Timeout stops the child process tree; Docker cleanup is not independently certified.
--record-model-transcript durably records full model messages/schema and replies,
not provider configuration, headers or hidden reasoning. Normal tool evidence,
patch candidates, verification artifacts and traces remain in the trial output.

## Windows Docker startup: verify requested rights, not just file writability

See [the verified local incident](docker-wsl-recovery-20261022.md). A VHDX can be
writable under Modify while WSL attach fails: the captured wslservice.exe request
included WRITE_DAC under an impersonated user. Back up the ACL and identify the
actual process, identity and requested rights before recommending a scoped grant.
Do not copy machine-specific account/path commands into automatic recovery rules.
No recursive ACL reset, Everyone grant, VHD deletion or filesystem repair follows
from an E_ACCESSDENIED string alone. Bare attach/unmount provides a separate check;
successful attach is not evidence of filesystem integrity or a healthy engine.

Distinguish STATUS_COMMITMENT_LIMIT from access denial and distinguish a missing
Linux block device after attach failure from a missing host file. Confirm a new
backend start time after a full Desktop exit; reopening the GUI may keep the failed
backend alive. Engine health requires Server readiness, not just a running client.
Future runner integration must test infrastructure-error routing separately from
code repair: preserve the candidate, bound recovery by the shared deadline, and
verify that unavailable Docker does not spend code-repair rounds. These runner
changes/regression tests are proposed, not established by this manual incident.

### Infrastructure routing now implemented (2026-10-22)

`keel.verification_infrastructure` recognizes structured unavailable-verifier
results separately from test failures. Runtime records these attempts outside code
repair rounds, preserves the candidate, and retries only within configured 0..2
attempts and the shared tool/time budgets. Persistent unavailability returns
environment_blocked before Critic/Implementer routing. Arbitrary stderr strings or
exit codes alone are not classified as infrastructure failures. An acceptance
command changing the workspace is rejected rather than retried on changed source.

`run_swebench_task.py --infrastructure-guard` checks Docker Server before checkout
or inference and again before final grading; it enables one retry of unavailable
verification with a two-second observable wait. A blocked runtime preserves export
artifacts and skips redundant final grading. It does not restart Docker, change
host ACLs, retrieve learned repairs or diagnose arbitrary new infrastructure errors.
Use the existing bounded launcher so setup, checks and retries count in total time.

Tests: test_verification_infrastructure and test_swebench_task verify zero model
dispatch on preflight failure, no Critic/code edits after unavailable verification,
same-candidate transient recovery, shared tool-budget exhaustion and skipped final
grading. These synthetic checks are distinct from a live Docker recovery experiment.

## Explicit model transport retries and retained instance images (2026-10-22)

Use the shared `model_transport.invoke_with_retries` through FrozenModel with its
bound runtime Budget. Roles already reserve the first dispatch; each extra dispatch
must call allow_model again. Retry only typed ModelTransportError (compatible
provider disconnect/reset/timeout/incomplete-read or HTTP 408/429/selected 5xx).
Do not retry credentials, redirects, certificate failures, schema/usage errors or
truncated/refused completions. Defaults remain zero retries; SWE opt-in requires
the durable model transcript. Waits and per-dispatch timeouts use remaining shared
time. Record every failed request; absence of usage is not absence of spend.
Unknown failed usage consumes a conservative input-byte/output reservation, listed
separately in budget reports; it is not a measured provider token or billing total.
Known failed usage is charged once. This is bounded transport recovery, not a new
model diagnosis or permission to restart a whole experiment.

For SWE use `--retain-instance-image`: one fresh session scope is passed to every
verifier and final grader. Inside the harness, apply cache naming AFTER environment
policies; the cache tag hashes session, generated Dockerfile, setup scripts,
environment/base image references and prior policy tag. Different setup recipes
must not collide. Official --cache_level instance retains the resulting image;
tests still execute in fresh containers with new run IDs and prediction hashes.
No old test report is promoted to a new pass, no cached-score reuse, and no global
Docker prune. The first build can still require network; this prevents redundant
later builds, not all network failures. Reuse is session-scoped, not a proof of
immutable upstream registries or dependencies across future experiments.

Tests: test_model_transport (runtime binding, same-request recovery, finite retry,
call/token/time limits, unknown usage, no protocol retry), test_harness_cache
(same recipe/scope, changed recipe/environment/policy/scope), and SWE entry/bridge
tests (same scope to verifier/final grader, retention flag, no fake score). Also
instantiate real harness 3.0.0 TestSpec offline to check tag generation. Actual
Docker reuse and live provider recovery still need experiment evidence.

## Bind diagnostic handoffs to actual localization (2026-10-22)

Legal writable IDs are not evidence that a selected edit scope addresses the
pending diagnostic question. Paged selection may prune earlier candidates; trace
retained_ids and discarded_previous_ids so the handoff can be reconstructed.
Do not hard-pin task-specific paths or treat path overlap as causal proof.

Opt-in recovery.diagnostic_handoff reviews the actual localized source definitions
and the pending validated Critic check BEFORE planning mutations. Reuse the existing
diagnostic inspection request/whole-definition readers. Include named read-only
test paths as evidence, never as new edit permission. An aligned review must quote
selected source; redirect must quote an observed replacement and select only from
the original writable catalog. Redirect triggers fresh focused localization, not
direct execution of a model-proposed path or patch. Preserve observations and raw
replies, check freshness, and keep all reads/calls in the shared budgets. Propagate
the concise assessment as untrusted context to the Implementer. blocked reports a
specific missing capability/evidence rather than claiming a check was performed.

The host verifies source quotation provenance and permission boundaries. The
reviewer still judges relevance; it may approve a poor plan. A source/planning
review does not execute the Critic's runtime probe and cannot establish test pass.
Scope review presently covers diagnostic-driven re-localization, not every possible
within-file edit or a complete semantic execution supervisor. Defaults stay off.

For short live assessment, reuse run_frozen_model_review.py with response_contract
diagnostic_handoff, arms drift/target. Validate using the production quote/scope
validator; preserve pending/failed receipts and do not auto-retry a paid micro-run.
Compare rejection of known drift with acceptance or concrete blocking of the
target control; parsed JSON is not an automatic quality score. First audit frozen
trajectories and test routing locally before another long, paid repair attempt.

Source quotation provenance must tolerate CRLF/LF transport equivalence only.
Use keel.source_quotes for LF display and validation; retain original byte hashes.
Do not strip indentation, collapse whitespace, normalize quotation marks or use
fuzzy matching. A valid saved response rejected by an older validator can be
revalidated offline into a separate, hashed derivative artifact, without changing
the failed receipt or paying for another model call. Freeze policy migrations
explicitly; dispatch only the unfinished control under a new plan.
Evidence: handoff-alignment-v1 drift quoted two exact source passages except for
line endings; offline-review-newline-v1.json records both matches and zero calls.
Regression: test_diagnostic_handoff accepts CRLF/LF and rejects changed source text.

Conditional response-field invariants enforced by the host must be stated in the
model instruction, including the empty-list case. diagnostic_handoff aligned and
blocked require replacement_files=[]; redirect requires a changed permitted scope
with replacement-source citation. Keep validation strict and errors actionable.
Regression checks must cover prompt instructions as well as invalid replies.
Evidence: target-v2 returned aligned with exact citations but repeated the current
path in replacement_files; this is a protocol failure, not quote fabrication.

## Diagnostic answers must not be forced into edits (2026-10-22)

In diagnostic-handoff proposal recovery, pass the pending next_check and hypothesis
as structured diagnostic_check. The proposal response must include diagnostic_answer
in the SAME budgeted call. Use the shared keel.diagnostic_answer contract: exact
pending question, explicit answer, hypothesis update, supplied fresh source-window
citations and a specific missing-evidence field. An unknown answer requires edits=[]
and an undetermined hypothesis; preserve the blocker before any write. Source-only
answers do not certify runtime probe execution. No general shell capability is
implicitly granted. Protocol errors use existing bounded/shared-budget correction.

Do not require at least one edit when the responder cannot establish what to fix.
For these diagnostic proposals, reject all-Python AST-identical batches (comments
or formatting only) before writes. AST difference is only a necessary heuristic,
not semantic progress: equivalent refactoring can still pass this gate. Preserve
all raw replies, answer facts and check_execution=not_established; provenance is
not a proof that the answer is correct. This currently covers proposal recovery
with diagnostic_handoff enabled, not every AgentSession or non-Python edit.

Evidence: bounded v4's first candidate only added comments despite unchanged test
failure; subsequent candidates mainly rewrote equivalent expressions. Relevant
scope review did not complete the diagnostic question. Regression checks:
test_diagnostic_answer, test_diagnostic_handoff runtime redirect/proposal path,
test_proposals and test_verification_repair. Live model compliance remains untested.

For diagnostic-answer micro-reviews, reuse run_frozen_model_review with contract
diagnostic_answer and production proposal_request/validate_response. Source files
must be explicitly mapped and hashed in frozen_files, and evidence SHA must match
before any paid dispatch. The reader cannot access unmapped paths. Preserve raw
replies, costs and receipts; valid unknown is a completed protocol review, never
task success. Report patch_validation=not_performed: do not silently apply patches
or equate answer provenance with patch validity. Review source-answer and missing-
execution controls separately; synthetic controls are not benchmark evidence.

Rejected compatible-model completions must preserve finish_reason, refusal/tool
flags, token breakdown and configured output allocation. Keep bounded rejected
assistant content as untrusted diagnostic material; never accept it as a patch or
retry it as a transport error. Use ModelCompletionError. Historical merged errors
cannot retrospectively prove truncation. Frozen reviews can explicitly freeze a
new output allocation within existing request/call/token budgets; preserve old
failures, reuse completed arms, and record capacity changes as a new experiment.
Tests: test_compatible_models and test_frozen_model_review cover rejected content,
status distinction, single usage charge, explicit max_output and preserved failure.

## Route unknown diagnostic answers through bounded source acquisition

Under diagnostic_handoff proposal recovery, DiagnosticEvidenceNeeded records the
validated unknown answer before writes. RecoveryController may call the existing
inspect_diagnosis once per exact pending question, using its current verification
and named readable source paths. Do not reset budgets or create a new model session
budget. Existing search/read pagination, freshness and no-progress guards remain
active. A single acquisition may contain several read/assessment steps, all under
the original limits. It is not permission for arbitrary commands or runtime probes.

Keep returned source windows in readonly_diagnostic_evidence, separate from patch
targets. Exact fresh citations can use these windows, but edits still use only the
original writable/evidenced files. Merge same-file windows only when SHA matches.
Snapshot-check acquisition; record assessment/evidence in the recovery report.
An insufficient inspection, absent citable windows or another unknown after this
acquisition preserves its blocker and stops before edits. Supported/refuted source
assessments remain untrusted; re-answer the original question before proposing a
patch. Source reads alone never establish execution or task acceptance.

Regression: test_diagnostic_acquisition exercises real search/read tools and shared
inspection with fake model replies: unknown -> read test -> cited re-proposal,
second unknown, insufficient inspection, unchanged global budget, and refusal to
edit read-only tests. Live performance remains unverified.

For a bounded live acquisition check, reuse review_saved_diagnosis with mode
diagnostic_acquisition. Replay the saved unknown reply without provider usage;
report the host dispatch reservation separately from new live calls. Run the
production RecoveryController.propose and existing inspection tools against copied,
hashed source files. Keep ledger/transcript outside the source workspace. Override
replace only at the final mutation boundary so validated proposals are held,
not applied; report proposal_validated_edits_held, never repair pass. Source
snapshots must match before/after; insufficient evidence is evidence_blocked.
Preserve incomplete outputs with no automatic paid retry. Record requests,
responses, rejected completion diagnostics and usage before moving to the next
step. Current micro limits: <=4 live calls /240 seconds /80k tokens /20 tools,
<=60 seconds and 2048 output per call; saved replay uses one host call reservation.
Frozen host test bodies are not automatically the harness's patched test source.

## Action-capability probe comparison, opt-in experiment

Use diagnostic_probe_pair in review_saved_diagnosis to compare the same frozen
question/source under equal per-arm caps. Keep the tool loop and response schema
shared; only probe availability differs. Resolve the operator's existing Docker
image to a local ID before paid calls; never pull/build or fall back to host Python.
Use CommandRunner's network-none/read-only/non-root/capability/resource limits.
Model-authored Python runs in a child inside that container for <=10 seconds;
output goes to files with hard RLIMIT_FSIZE limits, and returned stdout/stderr are
capped. Outer timeout uses remaining shared time and existing container cleanup.
No host report mount, credentials or Docker socket is provided to the container.

Mounted candidate source and installed image packages are different provenance.
A probe that imports the unchanged package does not establish current candidate
behavior. Preserve script, input windows, image ID, execution output and final
answer for manual inspection. Repeated identical actions stop. Record diagnostic
outputs only; no patch application or official score. Completed arm receipts may
be reused after identity checks; incomplete arms must not be automatically rerun.
Predeclare distinguishing evidence and cost/repetition criteria, rather than
promoting a change because JSON validated. One exposed case and fixed arm order
do not establish general performance or causal accuracy improvements.

After an optional tool goes unused, distinguish voluntary tool choice from
ability to design/use an experiment. A required-probe capability review must be
a separately frozen probe-only plan (arms=[probe], probe_policy=required). Preserve
the optional baseline; do not repeat it or relabel forced execution as the same
comparison. Permit an explicit blocked/unknown outcome with a stated obstacle;
the host does not certify that obstacle as real. One early final answer receives
policy feedback, a second stops; corrections consume the same call/time budget.
Probe attempt does not guarantee success or a relevant observation. Do not promote
the policy until scripts, candidate provenance and reasoning show actual benefit.

Probe action interfaces must state parameter semantics: executable Python in code;
query/path empty. A probe intention in query with code="" is an invalid tool call,
not an attempted container execution or output-size failure. Reflect active policy
in action schema and expose byte bounds before dispatch. Permit at most one typed
argument correction within existing shared budgets; never synthesize a task script
on the host or count invalid arguments as probe use. Retain raw reply and costs.
Regression: test_diagnostic_probe covers natural-language query/empty code followed
by corrected execution, and repeated empty code without container launch.

## Candidate package execution and failed child correction

Use candidate_context in a fresh probe interpreter to intercept qualified imports
of hashed mounted modules. Retain image-provided parent/dependency packages and
normal relative-import semantics; register before importing the package so eager
reexports bind to candidate objects. Reject preimported target packages instead of
mixing cached classes, verify bytes before compilation, and record each candidate
module's origin/SHA/loading result. Do not import package files under arbitrary
top-level spec names. Package initializers retain fallback dependency search paths.
This is a generic source loader, not task-specific code repair. Dynamic package
data, extension modules and arbitrary project startup behavior remain unproven.

candidate_imports and correct_failed_probe are explicit experimental flags, default
off. Distinguish outer executor status from nested child returncode/timeout. A
wrapper returncode0 does not mean the experiment succeeded. With correction enabled,
only first child script failure/timeout permits one DIFFERENT probe; two attempts
maximum, same global model/tool/time limits. Executor failures are not blindly
retried, successful probes do not earn extra executions, duplicate scripts stop.

Before another paid trial, run test_candidate_imports (relative dependencies,
eager reexports, initializer fallback, SHA changes, preimport rejection and actual
generated worker in a trusted local child), and test_diagnostic_probe. Production
model code remains Docker-only. The optional test_probe_docker_fixture uses the
existing image/interpreter from KEEL_TEST_PROBE_PLAN with zero provider calls and
stores evidence under .keel/probe-selfchecks. Its default skip is not a Docker pass.

Use review_saved_diagnosis --check-imports for a zero-model actual-candidate check;
explicit --import-path entries come from the frozen source catalog. Verify source
plan hash/source bytes, and record CURRENT implementation hashes separately from
the historical plan. Passing requires real candidate file origin and executed
loader SHA, not merely returncode0. Distinguish import_failed, provenance_failed
and execution_unavailable; Docker pipe denial does not test package importability.
Preserve outputs under a new path, and do not invoke a model to diagnose the import
interface before deterministic importability has been established.

A thin mount on cwd/sys.path can create namespace parent packages before a late
PEP 660 editable finder sees the real package. In candidate_context remove only
snapshot search entries while the explicit hashed source finder is active; restore
sys.path on exit. Do not invent missing package configuration. Test with an editable
finder AFTER PathFinder, not only an installed directory on sys.path: the latter
misses this failure class. Explicit candidate package initializers and external
dependency paths must still work. Native namespace-only projects remain outside
the current validated scope. On preflight import failure preserve parent package
origins/search paths to distinguish namespace shadowing from missing dependencies.

Successful probe execution does not imply diagnostic completion. Experimental
continue_successful_probe permits one DIFFERENT follow-up that cites the preceding
execution observation, within the same existing budgets and total two-probe cap.
Do not silently change old once-only trial policies. Repeated scripts stop; source
citations alone cannot justify an execution follow-up's provenance. The host checks
references, not semantic relevance; final diagnosis remains manually reviewed.

A separately frozen continuation may reuse one completed historical probe. Bind
its original script/output/report hash and image ID, verify all candidate source
hashes before paid calls, and label it historical. Report prior_probe_attempts and
new_probe_attempts separately, preserving prior costs. Do not treat reused output
as fresh verification. Incompatible image/source must block before model dispatch.

Required-probe completion is local to the current investigation. Historical
executions remain reusable context and count toward the unchanged execution cap,
but cannot satisfy the fresh-execution gate. Expose current_question_execution_ids;
withhold answer until fresh execution exists and require its citation in the final
answer. One policy correction uses the same budget, repeated violations stop,
and blocked/unknown remains available. Do not synthesize experiment code or
equate a fresh citation with causal validity. Optional reviews keep their existing
behavior. Regression: test_required_continuation_cannot_finish_using_only_historical_execution
and test_required_answer_must_cite_fresh_execution_not_just_source. Preserve old
paid results and migrate frozen implementation hashes before any new live trial.

Diagnostic blockers now use diagnostic_closure host predicates. A cited current
outer executor nonzero returncode/timeout establishes an observed execution
obstacle, not its root cause. Historical output, missing observations and child
script failures cannot certify blocking. Unsupported blocker and premature answer
share one correction allowance and existing total budgets. Repeated violations
remain unresolved; current runner's legacy evidence_blocked status on RecoveryStopped
does not certify a real environmental blocker. Report closure separately.
Regression: test_diagnostic_closure plus diagnostic_probe false-blocker-to-probe
and actual-executor-failure tests. Default repair runtime is not yet integrated.

Use run_swebench_task --diagnostic-report with saved-source continuation to pass
receipted raw candidate executions into Critic changes and Scout context. Validate
report hash, candidate manifest paths/hashes and executed loader markers; exclude
historical-only/failed executions and do not import model verdicts as facts. Check
saved and prepared workspaces, freeze report/receipt identity during inference,
and bound payload size. Imported output remains historical, not fresh acceptance.
Preserve new-attempt and assisted provenance. Tests: test_diagnostic_evidence and
test_diagnostic_execution_is_forwarded_in_saved_continuation. This does not enable
the experimental probe executor inside ordinary runtime or prove repair benefit.

Decision guidance lives in decision_guidance and is delivered to Critic, proposal
and experimental probe requests. Five questions cover facts, alternatives, action
choice, observable success and switch conditions. Reuse existing response fields
and bounded outputs; do not request hidden chain-of-thought, add case answers or
infer correctness from labeled prose. Proposal summaries must name the expected
behavioral difference, not present comments/equivalent rewrites as fixes. Prompt
delivery tests are not behavioral enforcement or live efficacy evidence; migrate
frozen implementation identities before another review.

Paged localization treats an empty page result as no update when carry is
nonempty, with localization_empty_page_preserved trace. Nonempty selection still
replaces/prunes; all-empty scans still fail. This prevents total erasure without
unbounded union, but is not a keep/add/drop protocol or relevance guarantee.

SWE bugfix proposals enable agent.require_python_ast_change before writes or
acceptance. Whole-batch Python AST equality rejects comments/formatting-only edits;
generic proposal mode defaults off so documentation tasks remain possible.
Docstrings remain in AST because __doc__ can be observable. AST difference does
not prove semantic change: equivalent variable rewrites still pass. Do not claim
blanket no-op detection or saved grading duration from static replay. Replay full
proposals against exact seed, not only snippets. Tests: test_paged_localization,
test_proposals and test_diagnostic_answer.

Main runtime may opt into diagnostic_execution (immutable Docker execution config,
absolute container python, max_model_calls1..4) in adaptive localized-proposal mode.
Pending Critic checks from saved continuations and later recovery execute before
patch generation. Reuse diagnostic_probe.investigate and run_probe, shared global
budget/ledger/trace; narrow readable/candidate-import paths to selected source.
Refresh bytes before execution; stale localization anchors fall back to bounded
current file evidence rather than asserting old positions. Raw executions and
unverified assessment enter the patch goal. Unknown, noncompleted experiment or
verified executor failure does not authorize a patch. No source write/network/host
fallback added. This gate does not certify relevance or causal interpretation.
CLI: --diagnostic-probe-config; results: diagnostic_executions. Test actual runtime
handoff, executor failure, unknown result and global budget sharing before live use.

Diagnostic citations use current observation IDs, with a dynamic enum and explicit
available_evidence_ids. Unknown string IDs receive one typed correction within
unchanged stage/global budgets; repeated errors stop unresolved. Never infer aliases
such as evidence-2 -> source-2 or rerun a completed probe to fix a reference. Keep
execution in ledger even when final interpretation fails. Tests cover corrected
answer reusing one execution and repeated unknown IDs without tool dispatch.

For baseline-versus-candidate causality, use review_saved_diagnosis
--compare-source-tests with frozen source variants and one exact test selector.
source_comparison reuses run_probe/candidate loader, fixed immutable image,
2-tool/60s total budget,10s child deadline, no model/network/source edits. Export
baseline bytes from the task base commit without checking out over saved work.
Require actual executed loader hashes and identical installed test-file hashes.
Collection/setup/teardown errors, skips, missing results and timeouts are unavailable,
not failing target tests. This diagnostic does not reproduce every official harness
condition. Baseline also failing does not prove patch irrelevance. If baseline
passes/candidate fails, block rollback may localize the contrast but interactions
and invalid partial patches must be retained, not scored as evidence of causality.

Read-only pytest diagnostics need writable runtime storage before plugin imports.
source_comparison sets HYPOTHESIS_STORAGE_DIRECTORY to an isolated /tmp directory
before importing pytest/test modules. Keep warning/error policy and source/tests
unchanged; apply adaptation equally to variants and record it plus implementation
hashes. Example evidence: baseline-candidate-v1 exited4 loading conftest with a
HypothesisWarning about unusable /testbed/.hypothesis/examples, reports=[]; target
never ran. Do not score this as a failing baseline or relax warnings to get a pass.
Test generated code ordering with a trusted fixture, then validate in real Docker.

source_comparison.rollback_blocks compares logical lines (ignoring LF/CRLF for
partition only) and aligns restored lines to candidate newline style. Preserve
each variant/hash and syntax-invalid partial variants; do not count invalid syntax
as target failure. block_rollback plans reuse completed controls only after exact
control plan/report hashes and image/interpreter/test selector match; each new
test must match control test-source hash and executed candidate provenance.
Run only new rollback variants, not baseline/candidate again. Independent single-
block reversions are not full delta debugging and may miss interacting causes.

On an existing comparison output inspect report before changing paths. Use
--resume-from REPORT with a NEW output to reuse independently completed variants
even when aggregate status is running/incomplete. Match plan hash, source manifest,
raw structured result, loader provenance, test hash and executor implementation.
Only comparison orchestration migration is allowed/recorded; preserve previous
implementation/budget/report hash. Never reuse unavailable rows, overwrite old
output or infer whole-run completion from one passing block. Tests verify actual
reuse without another probe and rejection of plan mismatch.

Transfer completed rollback evidence with run_swebench_task --comparison-plan and
--comparison-report, only alongside validated saved-source continuation. Validate
frozen control/variant identities, raw structured results, loader markers and exact
saved/prepared candidate. Import compact outcomes plus observed reversion diffs,
not a developer repair answer. Retain bound historical evidence in Critic changes,
saved-source Scout goal and diagnostic bridge input, including later rounds.
Subsequent source edits invalidate freshness but do not erase historical contrasts.
Do not force model state updates from narrative conclusions or claim this is a full
question/hypothesis ledger. Test delivery and tamper/mismatch rejection first.

### Interrupted provider transport and unchanged seed grading (2026-10-23)
V6 Scout URLError lost wrapped reason; do not infer a specific transport cause. Provider boundary now exposes safe reason type, never raw error text/URLs. Retry known transient reset/timeout/EOF/temporary-DNS errors via existing model_transport shared budget; certificate failures, malformed output and unknown string reasons remain terminal. Explicit retries0..2 are required and unknown usage is conservatively reserved. FrozenModel records allowlisted reason types. Regression: tests.test_model_transport wrapped-error cases and existing budget/retry tests.
For failed saved-source continuation, compare current full workspace_patch with validated seed_patch after exporting prediction. If identical, skip final grade with official_resolved=null and explicit skipped_unchanged_failed_seed; do not claim cached success or fresh verification. Changed candidates still grade. Regression: tests.test_swebench_task checks both branches. This avoids duplicate evaluation, not Docker image/network recovery.

When urllib URLError wraps FileNotFoundError, do not infer which file or classify all URL errors transient. Isolate with examples/check_model_connection.py using exact launcher interpreter and user process; bounded unauthenticated GET, no generation/credentials/redirect following. Compare reason/errno/safe stack frames and CA override existence. Tool-process network failure can differ from user process. Windows trust store may work with no default cafile/capath. Preserve each diagnostic output (exclusive create); HTTP401 without credentials means HTTP transport answered, not valid authentication or completion readiness.

### Default trial image retention (2026-10-23)
Repeat2 internal official harness passed175tests then cleanup retained0images; final stage rebuilt and git clone TLS failed. Existing harness_cache scopes generated instance recipe plus unique trial, excludes candidate patch; cache_level=instance preserves setup image, fresh containers/scores. Task runner now defaults retain_instance_image=True; --no-retain-instance-image explicitly restores cleanup behavior. No environment recipe/source/test changes. Bridge grade CLI exposes --instance-cache-scope for standalone scoring retries. Never reuse previous scores as fresh tests, never mutate prior grading_error. Existing test_harness_cache verifies recipe/scope isolation; test_swebench_task now checks default forwarding to both verifier/final grade. Grade-only recovery may need initial clone because old image is gone; retention cannot promise network restoration.

Mocked official-harness unit tests must bind both dataset schema and harness version. Reading installed metadata while mocking the harness makes a classic fixture fail before its intended assertion, or makes a no-report test pass for the wrong reason. Pin only mocked test metadata to matching3.0.0; keep explicit incompatible5.x rejection check. tests.test_swebench_bridge15pass with installed user environment. This is fixture isolation, not changing real grading compatibility or proving remote CI green.

### Windows file identity and floating deadlines (2026-10-23)
CI Windows temp paths can spell same file with long username or8.3alias. For existing imported files use Path.samefile, not raw Path string equality; preserve candidate source hash/provenance checks. Do not globally loosen writable-path validation. Deadline addition/subtraction can exceed original timeout by an ULP even at zeroelapsed (212.18+300-212.18). Bound forwarded remaining by min(original timeout,deadline-now), reject exhausted budget, do not relax hard-cap tests. tests.test_candidate_imports and test_reference_recovery deterministic rounding check cover boundaries;27related local checks passed, remote verification pending.

### New-case preflight after development success (2026-10-23)
Use shared seeded select/prepare plus actual runtime_snapshot. Freeze ID list before reference outcomes; no swapping unavailable tasks. Separate reference-only bounded Docker stage (no model) from fresh-base Agent trial; do not transfer case-specific saveddiagnosis/goldpatch. Disclose public-task/knownrepo exposure and bounded scan omissions. Exposure scanning skips dependency environments .venv/venv/envs and raises on120s traversal deadline rather than accepting partial exclusions. Tests.test_swebench_batch covers real receipt retention, env exclusion and deadline failure; prior runs remain immutable.

### Nonstandard test roots must share read/write/audit policy (2026-10-23)
Pilot pytest7432 added testing/python/integration.py test because protected_path omitted testing. Official test pass does not certify source-only protocol. Add generic exact testing directory component to shared protected_path rather than repository/file-specific branch. Localization writable catalog calls workspace.path(write=True), direct writes use same path policy, audit_text catches out-of-band changes; read-only test evidence stays available. Regression tests in test_audit/test_writable_selection_contract cover enum visibility/direct denial/audit addition/mixedcase/separators and production _pytest paths.61relatedchecks passed. Preserve old official scores plus protocol violation, do not delete test edit and relabel original success. Any post-fix rerun is a separate exposed development attempt.

### Reference build to network recovery handoff (2026-10-23)
Use keel.reference_network_recovery plus existing extract_apt/apt_workload/network_recovery rather than manually copying logs into a fictional diagnosis. Validate actual reference export/task receipt/private graderinput, one matching instance setup/log/Dockerfile, transientfetcherrors and currentimmutableimageID. Retry unchanged APT, preserve its diagnosis/logs; dispatch bounded registered transport experiments only if stillfailed; regrade reference afresh before accepting. Never promote probe/workload success to officialacceptance. Archive original grading_error and disclose reconstructed no_pipeline conditions. API and harness interpreters remain explicitly separate. CLI and optinbatch reuse same bridge; unsupported Condatimeout/signaturefault not a networkexperiment. tests.test_reference_network_recovery covers actual loop handoff with fakeprovider/Docker,input/image drift,signature/taskrejection,referencefailure; batchtest checks successfulrefhandoff. Local61relatedchecks pass,livevalidation pending. See docs/reference-network-recovery.md.

### Nested subprocess timeout must survive inherited pipes (2026-10-24)
reference-network-v1 inner dockerbuild600s never returned before outer1800s kill; stopped at FROM extraction beforeAPT,not diagnostic network evidence. Directchild kill plus timedjoin followed by buffered stdout.close may block if surviving descendants retain pipe/readthread lock. Do not treat timeout argument or mocked cleanup checks as proof of enforced return. Before rerun, test a real descendant holding inheritedstdout and require bounded process-tree termination, nonblocking/bounded reader cleanup and explicit process/result status; do not synchronously close a pipe still held by a live reader. Outer watchdog remains separate protection; Dockerdaemon build cancellation still must be reported as unverified. Live causal frame not captured, new cleanup mechanism not implemented yet.

### Verified local process containment migration (2026-10-24)
Use run_harness directlog/regularfile polling, not pipe-reader join plus blocking buffered close. Windows tool taskkill can be denied even for fixture descendants; Popen.pid may be only a venvredirector. Use process_job trustedbootstrap to join an ownedkillonclosejob before spawning tool, and same containment in outerwatchdog; POSIX uses isolatedgroup. Preserve production cleanup uncertainty for detached/daemon work. Tests.test_harness_process_cleanup uses realchild/grandchild heartbeats and independent workerdeadline,includingnestedjobs,not fakePopen only. Oldfrozencontrol2s hungpast12s;newfixture3.156s bounded. RequiredprocessreceiptIOfailure still propagates aftercleanup. Networkprobes sharethisrunner and suppressrawconsoleoutput to retaincredentialredaction.69related+14watchdogchecks pass;Dockerhealthnotcertified. Before further30minruns use check_docker_runtime zero-model60sbuild/150souterguard,networkdisabled,identitychecks,uniquetagonlycleanup. See docs/process-timeouts.md.

Docker readiness validation must distinguish server-info response from actual local-image build. docker-runtime-user-v2 passed network-disabled FROM/Python/export in50.031seconds after direct user Docker response recovered; previously stalled layer extraction completed37.1seconds. This does not validate APT or explain prior daemon unresponsiveness. For next recovery use a new output and explicit runtime migration bound to verified snapshot/selfcheck; never restart old unsafe frozen runner or overwrite prior interruption evidence.

### Progress-aware stage budgets (2026-10-24)
A large coldAPT install downloaded434MB then was still unpacking at597.3s when fixed600s killed it. Use shared AptProgressBudget with run_harness consumption and apt_workload receipt propagation, not a new retry loop or unconditional larger timeout. Distinct recent milestones may extend a soft allocation inside immutable hard stage/globaldeadline and reserved grading time. Count repeats/counter-only/speed-only changes as no progress; persist renewals and reason. Do not classify stage_budget_exhausted as transient acquisition or claim workload success. tests.test_stage_progress includes realprocess softdeadline continuation/termination; archived offline replay stage-progress-replay-v1 renews this historical600s boundary by120s, does not prove futurecompletion. Current implementation covers originalAPT retry only, not generic Conda/Agent scheduling.

When wrapping an APT workload inside Dockerbuild, its lifetime includes export/unpacking after RUN completes. v3 reached RUN DONE832.4s then package-only progress renewal stopped export at960. Consume recognized BuildKit forward terminal phases in the shared policy; one bounded quietgrace perphase, never renew from repeated duration/heartbeat lines, preserve harddeadline/reserve. Archive phase/transition receipts, require CLI success before promoting workload. tests.test_stage_progress includes realquietchild and export/unpack/repetition/hardcap regressions. Do not describe rawlog replays with inferred arrivaltimes as exact wallclock replay or Docker acceptance.

### Diagnose exact failed acquisitions before another full install (2026-10-24)
v5 original/no_pipeline each exited100afterhundredsofMB; singleunrelatedsuccessfulprobe cannotexplain failedpackages. Shared failed_workload_inputs validatesdiagnosis/script/image andextracts latestattempt terminalEFailedtofetch targets(reverseorderdedup),notGetlines/BuildKitrepeatedsummaryfirst. Reusable network_transport_comparison validatescurrentbaseID/inputhashes andruns two registeredAPTbuildprobes onidenticalhost/path HTTP/HTTPS. Preserve firstobservationbeforesecond,stopidentitydrift,excludecredential/query/fragment/nonstandardportURLs. No fullinstall/model/proxy/sourcechanges. Packagecap8MB canpreventfullresultsandmustnotbeinterpretedasnetworkoutage; chooseboundedfailedpackageexplicitly. Comparecontenthashwhenbothcomplete; transport reachabilitynotworkloadsuccess.37relatedchecks pass,realuserDockerpairpending. APTprobe failurehints are allowlistedTLS/DNS/connection/timeout/HTTPstatus,neverrawcredentialstderr.

### Acquisition retry must preserve failure and measure cache (2026-10-24)
Use shared apt_transport.transport_prefix for registered retry_acquire, unchanged originalAPTchain, boundednativefailedfile retries plus existingtransient-onlywholeworkloadretry. Cachemountaloneisnotcachehitevidence. Recordbefore/after archiveinventory andcacheID; preservecommandexitstatus throughEXITtelemetrytrap,partialinventoryonfailure/timeout. Missingtelemetrydistinctfromrequiredresultfailure. Tests.test_apt_transport coverssharedgradingprefix,nonstacking,transientretry/installerrorstop,cacheobservationpropagation andnonzeroCLIexit. Existingreferencepolicyreceiptsmustexplicitlyallownewregisteredpolicy andbinditsdefinition; don'tapplytooldfrozenruns/oldsuccess. Liveeffectrequiresseparatefrozenrun; noAPIorhostsettingschange.

Reference harness completion/exit0 is not reference acceptance.24627retry_acquire ranpytest butreferenceofficial_resolvedfalse,SCMversion-schemeDeprecationWarningsandNumPy/pandasrequirementImportErrors dominate. Inspectretainedinstance distributions/providers/requirementsread-only beforealteringenvironment; sameerrorclassfrompriorcaseisadvisory,notpermissiontoassumeidenticalprovider/dependencyfix. KeeprawpytestcountsseparatefromofficialF2P/P2Puniverse. ReusecompletedAPT/retainedrecipeimage; don'trerunwholeenvironmentorrepairbusinesssourceforreferencecompatibilityfailure. No droppingtests/warnings/signatures or relabelingreferencepass.

### Reference compatibility recovery is an executable controller (2026-10-24)
Use extended reference_recovery plus dependency_compatibility, not advice-only next_check. Bind actualfailedreference/export/log/policyinputs; inspectretainedimagewithoutrebuild; reuseexistingSCMguard. ForImportErrorcollectdeclaredactiveconstraints,resolveatmost3noneditableconsumersinboundedreadonlynetworkcontainer,preserveprovideranchors/allotherinstalledversions. Rejectunapproved/newpackages,verification/buildtoolchanges,editabletargets,newreverse-dependencyconflicts,image/evidencedrift. PIPdryrunmax3rounds/150sshared,notper-round150. Applyexactpolicyafterrepo/evalinstall,runfreshreferencegrade,propagatepolicyreceipttoAgentverification. Cachehashmustincludecompatibilityprogram/pins: installcachewrapperafterallrecipeadapters. Missingimages/unsupportedconflictsarenotzeroqualityorsuccess. NewoptinbatcharmcapturesreferencefalseandhandsverifiedrecoverytoAgent. See docs/reference-compatibility-recovery.md and tests.test_dependency_compatibility/test_reference_recovery/test_swebench_batch/test_harness_cache.103relatedcheckspass;budgetfollowup26pass,realDockerpending.

Compatibilityv1realinventoryfound8consumers/9constraints andstoppedat3limitbecausedevelopercodeselectedeveryhistoricalconflict. Fixselection,notlimit: joinobservedsite-packagetraceframeswithactualmodule/distributionmetadata; intersectdeclaredconflicts; excludealreadyhandledregisteredactions;preserveunrelatedbaselineevenwhensharingprovider. Protectclassiceditablelocationsundertestbednotonlydirect_urlmetadata. Recordselectionandplanned/submitted/verifiedactionstates; oldv1SCMactionwasaplan,notactualremoval. tests.test_dependency_compatibility largeunrelatedinventory/sharedprovider/unlinkedtrace/handledprovider regressions plus71relatedcheckspass. Newactualmodulemappingandresolveroutcomeawaitlivev2; don'tclaimv1environmentfailureorcompletedrepair.

Compatibility recovery live acceptance boundary (2026-10-24): v2 failure-linked selection/resolver/application/fresh reference chain completed with zero models,1F2P+776P2P passing (raw777passed64skipped),1320.156s. Persist resolver-selected policy and live application markers alongside fresh official report; dry-run success alone is insufficient. Propagate identical hashed policies into subsequent Agent verification, preserve baseline unrelated conflicts and original failed receipts. Reference acceptance qualifies reconstructed environment only; never report it as Agent repair success or feed reference patch to solver. Evidence: .keel/environment-recovery/matplotlib-24627-compatibility-v2/recovery.json and reference-grade/logs/run_evaluation/keel-b560c8fd9eab4c30895da0dd8dbf370e/reference-preflight/matplotlib__matplotlib-24627/report.json.

### Shared trial deadline instead of unrelated Agent cap (2026-10-24)
Opt-in run_swebench_task --total-seconds replaces --max-agent-seconds; deduct elapsed preflight/preparation, reserve final-grade time and20s cleanup, allocate remaining integer seconds to runtime (within profile ceiling). Pass actual remaining time to final grade, never independent default1800. Reject conflicting explicit limits; record allocations/grade timeout in trial shared_deadline. Keep outer watchdog as enforced containment with small additional margin. Tests.test_swebench_task shared-clock regression consumes100s preparation/700s runtime and asserts1080s Agent allocation/980s final timeout under1800s total600s reserve. Legacy explicit per-stage experiments remain unchanged. This scheduling change gives feedback recovery an opportunity, does not establish successful repair or cheap smoke screening.

### Ambiguous patch recovery and empty prediction classification (2026-10-24)
Frozen3sample stability run produced2officialpasses and1earlyproposal failure: identical old-text matched2occurrences twice, localrepeatguard stopped despite globalbudget remaining. Preserve unique-match safety; never apply first match or count this as exhausted globaltime. Corrective feedback should provide bounded actual match locations/context and allow disambiguation/relocalization within explicit budgets. Empty exported patch makes officialharness skipinstance (0run/1empty), so missingperinstancereport is secondaryclassification, notDocker/testfailure; identify no-candidate outcome before grading. Existing results are evidence only; implementation/regression still planned. See .keel/swebench/matplotlib-24627-stability-v1-trial-2/trial.json and final-grade/harness.log. Keep3scheduled denominator and separateunavailableofficialscorefromactualfailedtests.

Implementation followup: shared proposals.ambiguous_edit_feedback provides at most3 current-source match line/column/snippets and omitted count; caller must regenerate unique context, exact-match/atomic-write guard remains. Per-line bounded snippets avoid an unbounded file dump; recovery error envelope1800chars, original request context caps still active. run_swebench_task checks export receipt empty_patch and records unresolved/skipped_no_candidate with original failure and no official score. Tests.test_proposal_validation_feedback exercises real rejection->feedback->unique second edit with unchanged source before retry; tests.test_swebench_task asserts empty candidate skips grader and retains persisted cause. Live model benefit pending; old stability outputs remain immutable.

### Saved proposal checkpoint replay (2026-10-24)
Use examples/replay_saved_proposal.py for small protocol tests: bind original request/schema/evidence and exact source bytes, reproduce original rejection with injected saved response before spending, require unchanged source, then one provider correction using new host feedback. Validate with production _propose_once on isolated copies, persist reply before validation, refuse existing output/input drift, keep provider timeout60s and outer watchdog. Do not call a syntactically/scoped valid candidate a behavioral repair. Windows fixtures must hash identical byte/newline representation to production evidence. tests.test_saved_proposal_replay covers correction/rejection/drift/preservation; realproviderresultpending. Frozen actualcheckpoint: .keel/repair-review/ambiguous-proposal-v1.

### Executed test contract versus base-worktree test source (2026-10-24)
Sphinx9602 targettestabsentfrombasecheckoutbutaddedinofficialeval.sh. Do not reportbasefilelookupasreadingexecutedtestcontract. Use verification_context.failure_test_context and executed_test_patch_context on actualarchivedoutput/script; labelbothreadonlypartialcontexts,bindrawhash/testid/candidatesourcehash. Parseonlytargettestfilepatchsection; neverexecuteshellorreadreferencesolutionpatch. Missing/oversizedcontextfailsexplicitly,nosilentinventedbody. Useexistingcandidate-importpreflightandrequiredprobeexecutorbeforenewfullrepair; a scriptcompletedstatusisnotsemanticdiagnosisorofficialacceptance. Tests.test_verification_context plus diagnostic_probe/candidate_imports/diagnostic_execution40checkspass; actualSphinxdiagnosticpending.

Sphinx check-v1 live result: normal candidate imports passed, but model chose to simulate parser using handwritten replacements; candidate import markers remained empty. One script self-correction completed, then accumulated source-print/output/code exceeded32k diagnostic request bound before final reasoning. Distinguish script completion from observed candidate behavior. Preserve rawledger and cap failure; require relevant candidate execution and avoid duplicating already supplied source in probe stdout. Increasing context alone does not validate a surrogate experiment. Evidence .keel/repair-review/sphinx-9602-check-v1/results/probe/report.json and ledger.sqlite; no mitigation implemented yet.

### Probe validity and request-view evidence preservation (2026-10-24)
Opt-in require_candidate_execution uses bounded child profile receipts validated againstcandidate modulehashes; import-only andsurrogateswithoutactualfunctioncalls cannotclose. One correctiveprobe mayaddressmissingcallswithinunchangedglobalbounds. This is necessaryexecutionevidence,notproofthattargetoperation/inputwasrelevantorinterpretationcorrect. Legacydefaultunchanged; realchildfixturemustdistinguishcallfromimport, hashmismatchmustnotcount.
For diagnostic context, compact only verifiedduplicatewrappers/exactorCRLF-LF-equivalentsourceechoes andolderprogramtext, withexplicitIDs/SHA/bytecounts; preserveallrawobservationsinledger,latestprogramanddistinctoutputs/errors. Do notraise32kcaporsilentlytruncatefactstoavoidfailure. ExistingSphinxrawnextrequestreconstruction61009->31245bytesshowsfitforrecordedobservations,notallfutureprobes. tests.test_diagnostic_request_view/test_diagnostic_probe/test_candidate_imports coverimmutability,results,callgate.57relatedcheckspass; actualSphinxcheck-v2pending.

### Probe call-context preparation (2026-10-24)
When realcandidateprobe failsbeforetarget becausecontextobjectsareincomplete, derive syntacticattributeaccess/localcallees fromselectedcurrentfunctions with probe_context.context_inventory and provideactualfixture/constructor evidence readonly. Includeconditionalaccesscaveat; defaultNone isnotproofvalidforanypath. Do not hardcodecase-specificcontextfieldsorprebuildsolverexperiment. Initialcontextviewmustretainentry/calleecompletefunctionspluscontract/fixture,deferringwholepreambles/otherhelperswithoutdeletingreadablefiles; offlineadmissiontestshouldassertnoessentialsourceomissionbeforedispatch. Expose remainingmodelcallssoagentcanreserveinterpretation,notjustexecuteuntilcutoff. tests.test_probe_context andexistingprobe suites59pass; actualSphinxv3pending. Runtimefeedbackadaptationisnotlongtermmodellearning.

### Candidate-root interference after context entry (2026-10-24)
Entry-time sys.path cleanup alone doesnotprotectthin mountedtrees ifmodelprobe reinserts/workspaceafterentry. Candidate ancestor lookup mustuseoriginalproviderchainwiththin-rootsearchentriesexcludedatlookuptime,retaineditablefinderandnamespacesupport,restoresearchstateevenonerror. Keepcandidateleafhashchecksandmodulecleanup; no eagerparentimportorspecificpackagefieldpatch. Regression test_path_inserted_inside_probe_cannot_shadow_editable_parent failsagainstactualoldhelperandpassesnew;60relatedchecks pass. Beforepaidretryrunactualsameimagezero-modelold/newnormal/insertioncontrols; executorunavailableisnotexpectednegativeimportresult. CurrentSphinxDockercontrolpending.

ActualSphinxDockercontrolvalidated (2026-10-24): oldnormalpass/oldlatepathinsertImportError/newnormalpass/newlatepathinsertpass onidenticalimageandcandidatehashes,0models. Treat4matchedexpectationsascontrolledloaderrepair,not4successfulimportsorbusinessacceptance. Import-onlyreceiptslegitimatelyhaveemptyfunctioncalllist. Preserveoldnegativeandtestallbranchesbeforepaidprobe; inspectoriginalscriptfixturebehaviorseparately. Evidence .keel/repair-review/sphinx-import-control-v1/summary.json.

### Runtime operational knowledge is reviewed advice (2026-10-24)
Use shared operational_knowledge/ExperienceStore, not automatic developer-document ingestion or copied memory adapters. Cards require exact applicability, bounded guidance, evidence and implementation hashes; register as candidate, promote only after explicit evidence review, deprecate/version without fallback. Hashes establish identity, not factual correctness. Runtime hooks are opt-in verification Critic and diagnostic probes; record catalog/card IDs and typed episodes, never auto-promote from a successful model claim. Advice never grants permissions or fresh acceptance, and must yield context space to current failure evidence. Keep shared DB outside candidate workspace; optional storage failures must not swallow required local checkpoint failures. Freeze config/catalog/implementation/evidence for paid comparisons; episodes may accumulate without altering catalog hash. Seed mechanism evidence is not causal retrieval efficacy: run paired independent evaluation before claiming learning/general improvement. See docs/operational-knowledge.md and tests.test_operational_knowledge/test_diagnostic_request_view.

Operational knowledge comparisons must first prove the chosen failure actually matches a reviewed card. A repaired executor may no longer trigger the old failure during normal work; use an explicitly historical frozen checkpoint for mechanism/action comparison and do not count it as held-out repair success. Bind experiment-local evidence and snapshot implementation, compare identical arms with only knowledge config changed, retain actual delivered advice in model transcripts (not just retrieval matches). Keep zero-model execution preflight before paid work and expose incomplete arm outcomes; single fixed-order pair is exploratory, not success-rate proof. See .keel/repair-review/operational-memory-pair-v1/protocol.json and tests.test_operational_knowledge diagnostic integration regression.

### Unavailable diagnostic actions and explicit episode migration (2026-10-24)
Build per-turn action enum from actual executor allowance; probe_available=false must remove probe. If a provider still returns an enabled-but-exhausted action, preserve evidence and return one typed protocol correction within existing budgets, never execute it or silently extend allowance. Disabled executors remain denied; repeated invalid actions stop. Tests.test_diagnostic_probe verifies1execution/3calls correction, schema agreement and exhausted-budget preservation. Typed policy exceptions such as PolicyDenied do not end in Error: extract explicit error_type and exception class independently of prose regex. tests.test_operational_knowledge covers this and real retrieval.
Use explicit import-episodes for experiment-to-shared migration: source readonly, typed bounded prevalidated batch, destination atomic, content-idempotent, no raw logs/automatic card promotion. Keep separate register/review/promote lifecycle. Catalog changes require new config; preserve prior config/snapshots and successful partial migration rather than rerunning blindly after a smoke assertion. Developer-reviewed lessons must be labeled separately from automatic episodes and live repair success. Actual migrated store/card receipt: .keel/operational-knowledge-v1/migration-v2.json;83relatedchecks pass, real-model post-fix outcome pending.

Constructor preflight before model diagnosis (2026-10-24): if source establishes a concrete fixture API mismatch, validate initialization with the actual installed test constructor in the same candidate-aware sandbox before paying for diagnosis. Preserve the original failed script, label any developer-prepared fixture assistance, and avoid supplying a business repair. Compile the generated child program and inspect literal file contents, not only the host wrapper. First request admission must retain the full target/callee and executed test contract. A passed initialization check is not a target-function observation or acceptance; paid investigation must still invoke the real mounted candidate. Example .keel/repair-review/sphinx-9602-check-v4; actual fixture result pending user execution.

Sphinx v4 actualdiagnostic boundary (2026-10-24): real constructor preflightpassed, firstmodelprobe tried importing a readable.txt fixture as a Python module and failed, secondmodelprobeinlinedtheprovidedinitializationandcalledactualhashloaded_parse_annotation/type_to_xref, thirdinterpretedrawnodes. Distinguish a source/snippet evidence path from an importable module; readable availability is not import registration. Keepfirstfailureandcost. Initialization can invoke candidate setup, so generic function-call receipt alone is not target relevance: inspect named target receipts and actual operation/input/output.3calls23785tokens/60souter supportdiagnosisclosureonly,notbusinessrepair. Nextusehashboundrawdiagnostic_reporthandoffwithfreshverification; don'tpromoteSphinxbusinesssolutionintogeneraloperationalcards. Evidence .keel/repair-review/sphinx-9602-check-v4/results/report.json.

Generated direct API runners need actual call-binding checks (2026-10-25): production execute(model_config) expects a parsed mapping, whereas CLI --model-config accepts a file path. Compile-only/productionunitchecks do not catch a generated WindowsPath passed to a mapping interface. Evaluate the actual generated call against production API with model factory intercepted, asserting configuration type before checkout/Docker/provider dispatch. Verify all wrapper interpreter/runtime/watchdog paths exist, not just PowerShell parser success (mixed separators can defeat replacements). Preserve launcher failure classification/cost separately; reuse completed hash-valid snapshot grade in new output/protocol instead of rerunning expensive validation. Evidence sphinx-9602-probe-informed-v1/console.log and v2/offline-interface-check.json.

### Exact seed-byte recovery instead of relaxed evidence hashes (2026-10-25)
Shared saved_repair.restore_seed_bytes is called by run_swebench_task after per-command core.autocrlf=false git apply and before diagnostic identity checks. Trust only original receipt-bound saved bytes; verify all sources/paths and compare full inventories before writes. If and only if LF/CRLF normalization is equal, restore exact saved bytes, then run unchanged strict hashes. Real content changes or changed originals stop, never normalize away differences to certify evidence. Record before/expected/after hashes and actioncount in trial.seed_restoration, honor existingdeadline, do not consume paidcalls/extendpermissions. Tests.test_seed_restoration usesrealGitautocrlftruecheckout/apply->strictfail->restoration->strictpass and real-content rejection; test_swebench_task verifies restoration before Agent/handoff. Actualfailedv2bytesreplayedofflinein .keel/repair-review/seed-restoration-v1/report.json. Preserveoldfailuresandreuseonlyvalidatedcompletedgrade. Scripted/unit/replayproofisnotlivebusinessacceptance; candidateoperationalmemorynotautopromotedfromit.

### PathLike launch arguments must be serializable before required receipts (2026-10-25)
Normalize interpreter PathLike at grade API boundary with os.fsdecode before building command/metadata. subprocess may accept Path but JSON receipts do not; initial-requiredreceiptwrite and finallywrite can both fail, hiding successful prior runtime acceptance. Do not use catch-all json default=str or erase provenance types globally. Test actual grade(Path(sys.executable)) reaches harness launch with serializable recordedcommand; missingofficialreportmustremainnull/error. PassedAgent/verificationexportisreusable: repairlaunch, bindoriginalprediction/result/task/environmentcachehashes, freshgradeinnewoutputwith0modelcalls. Preserve originalerrorandruntimepass distinction. tests.test_swebench_bridge/test_swebench_task40pass; actualSphinxruntime1F2P+45P2Ppassed, separatefinalgradingpending in .keel/repair-review/sphinx-9602-final-grade-v1.

### Outer improvement candidates must not own their checker (2026-10-25)
Use outer_improvement with shared evaluate_diagnosis trials for first offline prompt-only selection. Keep fixed probe source/oracle/scorer, permissions and aggregate Budget outside model-editable fields. Persist paid dispatch/raw output before validation; require complete same-case comparisons, strict improvement and no per-case regression; support reject-all and never auto-promote production. Completed-arm receipt/config/implementation checks and cumulative budget apply on explicit resume; interrupted arms remain unavailable, not zero-quality or automatic retries. Regression tests.test_outer_improvement runs actual child fixtures with scripted provider and tests regression rejection/reuse/tampering. Exposed synthetic cases qualify control flow only; independent cases/repeated live results are still required for improvement claims. Fixed developer feedback is not automatic trajectory learning.

### Frozen prompt validation must separate protocol repair from diagnosis (2026-10-25)
Pilot-v1 candidates all tied4/4, incumbent2/4 mainly invalid observation citations. Do not claim first-listed winner superior. New validation mode retains exact original prompts and receipts, supplies identical explicit observation-ID/boolean contract to all arms, uses newly constructed twin-cause families plus historical control and repeats twice with reversed order. Preserve old pilot and evaluator defaults; changed protocol rates are not directly comparable. Reports separate protocol failure/conclusion/prediction/grounded pass and disclose tied eligible maxima. tests.test_outer_validation checks real fixed fixtures, shared contract/oracle exclusion, ties and no-proposal repeated execution/resume. Developer-authored synthetic transfer is not independent repository acceptance; no production promotion.

### Feedback replay identity uses persisted representations (2026-10-25)
When deriving prompt candidates from completed evaluation failures, validate source manifests/model config/proposal and all trial receipts before dispatch. Keep hidden fixture source/oracle truth tables/host labels outside proposer feedback; include only public contract, recorded model actions/results and measured outcome flags. Limit one candidate and two failed-family cases plus one passing control; keep original scorer, record development exposure and require fresh selection later. Use shared outer controller/trial budgets rather than a separate paid loop. Canonicalize manifest JSON before equality checks: tuples become lists on disk and otherwise produce false resume drift. tests.test_outer_feedback caught actual resume failure and now proves canonical same-input resume without additional calls, tamper/config rejection, real fixed child comparison, and <=300s entrypoint enforcement. Preserve interrupted arms; scan all registered trial-directory names for cumulative usage, not only old case-* prefixes.

### Candidate metadata length must not discard reusable paid work (2026-10-25)
Actual feedback-replay-v1 returned valid guidance but ID diagnostic_probe_precision has26characters and oldschema/validatorallowed24. Maintain shared safe ASCII64characterbound, reject path/reserved/duplicates. Preserve rawpaidreplybeforevalidation. Use explicit --reuse-proposal migration into newoutput for unambiguous pre-trial failures only: matchingprotectedinputs/model/budgets, one recordedcall, knownmatchingusage, no tools/trialarms, savedreplyvalidundernewcontract. Record previous/currentimplementation and sourcehashes, carry spentcalls/tokens/time, never rewrite oldresults or redispatchproposal. tests.test_proposal_migration coversrealpreviousrejection->reuse->solvercomparison,oldfileimmutability,changedinputrejectionandno-paid-resume; actualsavedreplyofflinemigrationmustbecheckedbeforeanotherpaidrun.

### Historical limit audits need causal classification, not keyword counts (2026-10-25)
Read-only audit scanned855selectedJSONsummaries;88matchedfilesincludeparent/childduplicatesandprosefalsepositives,not88independentfailures. See docs/evaluations/hard-limit-audit-20261025.md and .keel/repair-review/hard-limit-audit-v1/inventory.json. Checkactualbindingconstraint/usage/rejectedrequest/nextstagebeforelabelingunnecessarylimit. Confirmedlinecheckrequested5600�C5685whenfile3178lines: cannotfixbyraising80linelimit; returnactualrangeandallowsearch/reselection,chunkonlyvalidranges. Critic1023/1000charfailureand1024outputlength2/3vs2048completion3/3aredirectprotocolcompletionevidence,notend-to-endcausalpass. Actual12/12or20/20callcapsremainauthorizedstops; localrepeat/tokenreservationfailureswithotherresourcesleftneedtypedrecoverybeforewhole-tasktermination. Genericnextreasoningmustchooseallowedexecutableactionswithsamebudgetandimmutableevidence,notwaivesecurity/checkersorblindlyrepeat. Auditdoesnotgrantnewbudgetsorproveunblockedtaskwouldpass.

### First shared typed guard adapters (2026-10-25)
Use guard_recovery.GuardIncident/GuardViolation for explicitcode/category/protectedpurpose/allowedactions/details, not exception-string guessing. Outer --recover-guards generates host candidateIDs/full originaldisplaymetadata mapping withoutguidancechanges and makes one unknowncitationcorrectiveaction possible under unchanged3turn/globalbudget. Validate all other actionfields before offering correction; no illegaltool/scopebypass, guessedIDmapping, rawreplydeletionorbudgetreset. Record rejectedstep/guardevent before newmodeldispatch. Resume validates canonicalmapping and manifestmode; retain historicalscores. Tests.test_guard_recovery covers actualdownstreamfixedprobe/completion, repeatedbadreference/no-budget/illegalprobe negatives,longnamehostidentity/fullcomparison/resume. Offlinehistoricalreplay scriptedcorrectiveactions are controlflow evidence, not realLLMcorrection. Token/source-range/productionruntimeadapters remain planned. See docs/guard-recovery.md.

### Token reservation failure is not the same as exhausted authorization (2026-10-25)
Use context_budget admission metrics/typed guard incident for both local and remaining-budget reservation failures. Actualspenttoken/callceilingsremainBudgetExceeded; currentrequesttoobigwithbudgetleftisInputCapacityExceededandmayenterexistingboundedmodelsource-selectionroute,whichmustalsopasssharedbudget. Opt-in proposal_context_policy.recover_capacity enablesatmostJSONlayout+registeredexactduplicate-goal-wrapperrepacking inproduction _propose_once before reselection. Persistoriginalmessages/schema/incident inrequiredledgerbeforeretry; neverdropcurrentevidence/changeoutput/safety/policy/window/budget. Independentbyteceilingstillapplies. tests.test_token_guard_recovery exercisesoriginalrejection->preservingrepack->onescriptedcall->validatedrealWorkspacewrite,sourceimmutability/checkpointfailure/realexhaustion/boundedno-progressandtypedselectionfeedback. Tests.test_context_budget actualdepletiontestnowsetsspenttokens; priorzero-spendoversizedrequestwasreservationfailure. See docs/guard-recovery.md; otherrole/byte/outputadaptersnotyetunified.

### Historical capacity replay distinguishes representation savings from token estimation (2026-10-25)
Use capacity_replay/replay_request_capacity with source/implementation hashes, deadline, new output and receipt; reuse production repack_proposal_messages instead of copying compaction logic. Dispatched transcript requests are not missing pre-admission rejected requests. Separate UTF8-byte estimate reductions from actual prompt/totalusage; totalusageonlyboundsinputandmustnotbeusedasexactinput. Actual13requests333742->331893fallbackunits(0.554%) doesnotjustifylargeheadroomclaims.3actualpromptcountpairs show4.06�C4.40estimate/actual; don'tdivideallestimatesbyobservedratio. Verifytokenizeractuallyinstalled/configuredbeforeclaimingithelpsruntime; inspectedlauncher/harnesslacktiktokenandv7policynolocalencoding. Scoutearlystopnotfixedmerelybyproposal-onlyrepacker. See docs/evaluations/token-capacity-replay-20261025.md; tests.test_capacity_replay plusshared97checks pass.

### Counting activation must match the actual role interpreter (2026-10-25)
Use explicit prepare_token_counting/tokenizer_setup toinstallonlywhenuserpasses--install,exportlibrarymodel-mappedencoding,generatehash-boundrequire_local_tokenizerpolicyandoptionalzero-providerhistoricalcalibration. SharedCommandRunner/stagetimeouts/10sheartbeat/180stotal,newoutput,requiredstage/report artifacts,unchangedinputhashesandparentofflineverificationrequired. OrdinaryruntimeusesofflineEncodingconstructoronly,noget_encoding/modelresolverdownload; oneentrycachewithpercallrawhashchecks. Strictasset/dependencyfailuremustnotfallbacktobytes. Allconfiguredpolicyrolecalls(localization/Scouttoolloop/Critic/diagnostic/proposal)shareoriginalBudget andusageobservations; no-policyworkflowslegacy. Keepactualbytecaps/providerframinguncertaintyandsafety,don'tclaimlibrarytextcountproviderexact. tests.test_role_token_counting coversstrict/cached/hash/rolebudget/export/workerplanning; docs/token-counting.md activationcommand. Realpackage/assetsnotverifieduntiluserpreparationruns; mockcountingengineproveswiringonly.

### Stage logs and semantic receipts must never share a path (2026-10-25)
Real tokenizer preparation completed install/export but parent stage('export') overwrote child export.json metadata with process result, causing KeyError. Use *-process.json for execution logs and export.json onlyforsemanticreceipt. Unit tests of individualworkerandparentverificationmissedtheirintermediatewriteinteraction; testfullworker-output->parentlog->strictverifysequence. Recovercompletedexpensiveassetsintonewoutputaftermodel/config/policy/hashchecks,markmetadatareconstructionexplicitly,neverre-download/reinstallorrelabeloldfailure. Actualv2offlineactivation/calibrationpassed0providerin2.469s,126regressionspass; see docs/token-counting.md. Existingcallerpolicymustexplicitlyselectnewstrictpolicy; nooldrunmutationorbusinesssuccessclaim.

### Three-role token counting checks are interface experiments, not repair scores (2026-10-25)
Use frozenrole_token_check/CLI withsnapshot+messages/schema/config/encodinghashes andoneBudget3calls45000tokens180s; keeppercalltimeouts/outputallowancesexplicit. NeverwriteproposededitsorrunDockerinthissmoke. Persistpending/rawreplybeforevalidation; receiptsforcompletedroles; explicitresumeonlyreusesverifiedcompletionsandcarriesusage/time,refusesunreceiptedpaidcalls. Credentialpreflightbeforeoutputcreation. HostchecksCriticstructure/Scoutcatalog/editscopeonly,notsemantictruthorpatchacceptance. Historicalresponseinjectionmustbelabeledprovider0andreplayedusage,notnewbilledcost. tests.test_role_token_check coversbudget/resume/no-source-write/failedrolestop/keypreflight; actualsnapshotzero-providertokenizerreplayandPSsyntaxcheckbeforepaidlauncher. See docs/evaluations/role-token-live-v1.md.


### Base-relative prediction export must use Git text normalization (2026-10-25)
Astropy v8 and both accepted repeats had CRLF saved source versus LF HEAD. workspace_patch forced core.autocrlf=false, exporting unchanged lines as a file-wide change (~105700 bytes). Actual bytes contain no CRCRLF; initial display-based attribution was incorrect. Use command-local core.autocrlf=input for Git diff: Git applies its normal text conversion while preserving CRLF blobs, binary files and explicit -text attributes; never globally change Git config or replace CR bytes in an arbitrary patch. This affects export representation only; keep original workspace/accepted artifacts and strict evidence hashes unchanged. tests.test_prediction_newlines applies exported patches to real temporary repositories and checks exact expected bytes, untouched index/worktree, binary and attribute preservation, real edit visibility and newline-only no-op.49relatedchecks pass. Actual three-success offline export/apply replay in .keel/repair-review/prediction-newlines-v1/report.json reduced patches to2379-2386bytes and reproduced candidate bytes modulo declared text newline conversion. This is not fresh official acceptance of a re-export.


### Cold reference builds can consume the shared grading deadline (2026-10-25)
Matplotlib24026 reference-v1 built successfully in~1058s but1200s overall harness timeout expired after eval-script copy, with no official test report. Inspect internal build completion/stage timestamps before classifying a quiet harness as hung or network-failed. Preserve the unavailable result and reuse only a matching completed image in an explicit new grading output; check tag/image identity against prior build evidence, bind original task/recipe inputs, retain total deadlines. A completed image is preparation evidence, not acceptance. No automatic budget increase, source changes or task replacement. transfer-24026-reference-v2 uses cached-image guard and existing bounded harness. Stage-oriented diagnostic readers should avoid printing private reference diffs from run_instance.log; accidental developer exposure must be disclosed and never copied into solver context.


### Scoring completion must not masquerade as reference acceptance (2026-10-25)
24026 cached-reference CLI returned0 for graded/official_resolved=false, so watchdog status passed only meant process completion. Executed grade and grade-snapshot CLI now exit0 only for graded+official_resolved=true; false/null exit1. Keep structured grading result and process status distinct, preserve old misleading receipts with explicit interpretation. tests.test_swebench_bridge.test_grade_cli_exit_requires_official_acceptance covers true/false/null. A failed gold/reference result blocks agent launch and routes to existing evidence-gated compatibility diagnosis; do not repair labels, suppress warnings or count this as agent failure.


### Cached grading needs explicit original recipe provenance for recovery (2026-10-25)
24026 compatibility-v1 stopped in10s before any probe because cached-reference grading had no logs/build_images/instances recipe. Do not infer recipe absence means image/environment absence, scan arbitrary historical directories or copy logs into completed runs. recover_reference now accepts optional recipe_grade (CLI --recipe-grade): require identical full frozen grader input, original reference grading, one expected instance recipe; hash original grade/input/context and recheck during recovery. Diagnosis remains bound to the cached failure; inspection uses original recipe directory with allow_restore=false. Fresh launcher checks exact previously observed image ID. Tests.test_reference_recovery covers cached failure->explicit source->revalidation, unrelated task rejection before output/inspection and source drift preventing grading. Actual failed-input offline check intercepts before Docker and proves provenance route only, not recovery success. Preserve old failed output and use new frozen implementation/output for live follow-up.


### Network failure during compatibility revalidation must preserve earlier policies (2026-10-25)
24026 compatibility-v2 completed provider/dependency diagnosis and selected a consumer policy, but adapted image rebuilding failed at Ubuntu APT connection exit100 before tests. Classify this as required revalidation unavailable, not proof policies failed or succeeded. Existing reference_network_recovery now offers explicit preserve_compatibility: verify registered plugin policy and consumer-policy receipt hashes, include files in immutable inputs, carry exact policies to fresh grading, report reconstructed conditions even if original APT retry succeeds. Keep same-category network stacking and packaging overlay combinations rejected. tests.test_reference_network_recovery covers preserved policies through actual controller-to-mocked-grader boundary and opt-in/tamper/repeated-network negatives. No dependency re-resolution or failed-task replacement; prior successful preparation is retained, final acceptance remains required.


### A diagnostic cache is not automatically an official-build cache (2026-10-25)
24026 network-v1 diagnostic APT succeeded with~439MB retained archives, but official harness rebuilding independently downloaded434MB and failed one502. Record successful diagnostic work separately from fresh official acceptance and verify which build backend/cache actually consumes it. Do not replay a completed diagnostic merely because official grading failed; preserve input-bound completed work, route the new failure to bounded official transport retry when evidence supports it. Existing retry_acquire preserves APT package commands/signature checks. Explicit CLI --plugin-policy forwards registered SCM policy alongside hash-validated dependency policy and transport policy; tests.test_swebench_bridge.test_grade_cli_preserves_all_explicit_recovery_policies covers the actual CLI-to-grade handoff. Cache bridging remains unimplemented and must not be advertised as recovered downloads.


### Share reference recipe scope explicitly, never reference test results (2026-10-25)
After expensive compatibility reference preparation passes, fresh repair should not silently get a new recipe-cache scope if reuse is authorized. run_swebench_task --reuse-reference-image validates accepted same-task reference first, retained instance metadata and scope, then passes scope to both verifier and final grading; fresh containers/tests/reports remain required and recipe hashing still prevents mismatched setup reuse. Defaults remain isolated. tests.test_swebench_task covers valid handoff and missing/invalid/retention-disabled negatives. Plan-only validates policy/scope metadata, not Docker image existence or exact generated recipe identity. Official make_test_spec may fetch remote environment files even in a developer 'offline' key reconstruction; classify unavailable network accurately instead of claiming an offline recipe check passed.


### Register recovery transitions instead of requiring a new human command (2026-10-25)
Use reference_pipeline for same-task reference failure -> evidence-gated compatibility -> registered APT retry -> fresh official acceptance. Cold timeout can regrade once only after completed-build/image identity checks. One deadline spans recovery; combined batch flags now include initial reference time in that allowance and hand the verified reference to the original Agent automatically. Persist a required running checkpoint before dispatch and artifact hashes before routing; terminal resume reuses verified results, interrupted stages never redispatch blindly. Reject signature errors, unrelated recipes, policy drift and repeated strategies without modifying labels/tests. Historical artifact replay is not a new live recovery. Tests.test_reference_pipeline and batch joint-mode test cover transition/order, deadline carry, cache origin, artifact drift, interrupted resume and original-task launch.

### Bridge caches by content and backend, not by reporting an archive directory (2026-10-25)
apt_archive_bridge exports a completed source/base-bound diagnostic cache into a data-only local image using the same BuildKit backend and no network/APT. Official SDK builder validates base/archive image IDs and copies that artifact; generated setup checks bounded streaming hashes before supplying files to the unchanged APT chain. Cleanup hook temporarily disabled only to preserve injected archives through update/upgrade, restored via exit trap; no signature/warning/package/test bypass. Artifact identity participates in recipe hashing and is receipted/forwarded to verification. Opt-in unavailable bridge stops, does not silently redownload. Actual injected archive bytes are transport evidence, not proven download savings or task success. Reject corrupt files/path traversal/mismatched workloads/foreign image tags/existing cleanup traps. CI unit tests use isolated fake harness modules rather than making full SWE-bench a test dependency; actual SDK import belongs in explicit Docker selfcheck. Exported archive image is retained for reuse, owned temporary consumer image removed; no global prune.


### Dockerfile and shell parsing are separate boundaries (2026-10-25)
Actual apt-archive-bridge-live-v1 failed before cache access: Dockerfile line3 unknown instruction import. Shell quoting a multiline Python program does not continue a Dockerfile RUN instruction. Write the program as an LF context file, COPY it and use a single-line RUN. tests.test_apt_archive_bridge now inspects the actual generated build context at the build boundary, checks instruction framing, copied program compilation and offline flags.27 focused checks pass; this is not live Docker validation. Preserve v1; v2 reuses original diagnosis/cache and completed actual MCP checks without APT/model fallback.


### 2026-10-25: live cross-backend APT archive transport verified
User ran apt-archive-bridge-live-v2: watchdog passed200.047s, actual selfcheck189.171s, export38.641s, zero model calls. Official SDK consumer observed389archives/439051774bytes (about419MiB). Artifact JSON SHA256 matches export receipt; no consumer_cleanup_error reported. This supersedes pending Docker transport status only: existing BuildKit cache -> data-only image -> official SDK build now verified with network disabled and no APT install. Does not establish actual APT reuse/download savings, fresh official acceptance, automatic pipeline live success, or daemon-wide cleanup. Next validation should reuse retained hash-bound artifact in real original-workload reference grading, preserving environment policies and prior scores, rather than rerun the transport smoke or model repair.


### 2026-10-25: actual APT cache reuse and fresh reference acceptance
apt-archive-reference-live-v1 watchdog passed1020.125s, zero model calls. Fresh grading.json official_resolved=true, runtime_status=reference_only, no infra failure. New instance build imported389archives/439051774bytes. Actual APT log reports Need to get0B/5003kB and0B/434MB: archive reuse now observed during real install, superseding transport-only uncertainty. Metadata update still fetched49.0MB; do not claim network-free construction or total network savings. Official report hash checked against new run report. Original task/reference and compatibility/plugin/retry_acquire policies preserved, declared reconstructed conditions; this is environment/reference validation, not a new autonomous repair score or proof of full automatic recovery chain. Next gap: real end-to-end registered recovery handoff, preserving the successful preparation rather than repeating downloads.


### 2026-10-25: connect retained archive evidence to registered recovery controller
Developer added optional apt_archives and explicit instance_cache_scope to reference_pipeline/CLI. Hash-bound artifacts participate in input/resume identity; APT retry checks original base tag and exact command before forwarding; conflicting existing archive policy rejected. Scope reuse affects recipe builds only, fresh official tests still required.38related checks passed4.811s; initial new regression fixture incorrectly parsed FROM platform flag, corrected test fixture (not product workaround). New reference-pipeline-live-v1 starts from archived24026APTfailure, uses just-accepted artifact/cache scope with pre-dispatch image identity guard,600s shared/660s watchdog, zero model calls. Live outcome pending; proves only registered APT route and fresh reference acceptance if successful, not compatibility selection or Agent repair handoff. No business-task hardcoding or prior-score replacement.


### 2026-10-25: bounded preparation discovery replaces exact artifact handoff
Added reference_assets.discover_assets and reference_pipeline/CLI preparation_roots. Explicit evidence roots/direct children only,30s shared-deadline slice and256directory envelope; validate same frozen task, official report hash/resolved flag, identical registered policies, APT command/base, archive/base/retained instance image identities. Reject mismatches with reasons; no matching asset stops before grader instead of blind rebuild/download. Selected evidence hashes enter required pipeline artifact ledger and resume validation. Fresh grading remains required; prior acceptance never becomes current score.65focused tests pass8.159s incl5discovery variants and existing batch original-task handoff. Initial implementation accidentally inserted discovery into cold-timeout branch; new tests caught all5cases, moved to APT route before freeze. Prepared reference-discovery-live-v1: authorized evidence directory only, no exact archive/scope passed,600s/660s,0models; real outcome pending. Existing batch Agent handoff already tested, not newly live-verified here. Discovery is opt-in CLI, not global automatic memory search or new task repair claim.


### 2026-10-25: preparation discovery integrated into batch recovery and original-task handoff
run_swebench_batch preparation now accepts repeatable preparation-root only with combined network+compatibility recovery, validates roots before output creation, freezes authorized paths in plan hash, forwards them to real controller. Execute cannot override frozen roots. Existing accepted-reference path forwards exact recovered directory and reuse_reference_image to original Agent; unsuccessful discovery/recovery does not start that task Agent and preserves fixed batch IDs. Added positive/negative wiring tests with mocked controller/Agent;65previous+2new=67focused checks pass9.776s, zero provider/Docker. Discovery execution itself had prior real evidence, but this batch integration is not a new live model success. No new paid run prepared merely to repeat accepted reference scoring. Next meaningful evaluation is a bounded complete task run or independent failure case, with preparation reuse and model costs reported separately.


### 2026-10-25: bounded real recovery-to-Agent experiment prepared
Added prepare_continuation API to existing batch runner:one explicit exposed frozen task, archived unresolved reference inputs hash-bound, no initial grading replay or inherited candidate source. Existing controller automatically discovers prepared assets, freshly validates environment, then launches original task from base. New strict require-all-resolved exit checks both official acceptance and passed runtime; prevents a completed unresolved batch appearing as watchdog pass. Frozen recovery-agent-e2e-v1 uses sameGPT5.4configuration/localtokenizer,20calls180000tokens80tools,600sreference plus1200ssharedtrial incl300sfinalreserve and60scontainment. New outputs/budgets, full transcript, no paid calls dispatched bydeveloper.69related checks passed9.279s, incl original-task handoff, no duplicate initialgrade, changed oldevidence rejection and strict exit statuses. Live outcome pending; exposed developmental orchestration check, not new held-out score or evidence of general RSI.
