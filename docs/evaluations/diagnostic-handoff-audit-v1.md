# 诊断到编辑范围交接：v3 冻结轨迹审计

原实验：`.keel/swebench/astropy-14508-bounded-30min-v3`。
离线报告：`.keel/repair-review/diagnostic-handoff-audit-v1/report.json`。
旧实验结果及评分不改。

四次计划中，三次没有保留 Critic next_check 明确点名的任何可写目标。
这与后续 dummy writer、dtype 和 exception 导出修改方向偏移相符。路径重合
本身不能证明因果关系；不重合也不自动证明替代路径错误。但已有流程没有要求
给出这类替代路径的实际证据，只校验文件/符号是否属于合法目录。

分页代码本来允许模型把上一页 carry 中的候选淘汰；因此不能简单称为宿主丢
数据或硬编码优先第一页。新 trace 显式记录 retained_ids、discarded_previous_ids，
保留这个排序策略，同时在诊断后重定位处复核实际范围是否与下一检查目标一致。

新增默认关闭的 diagnostic_handoff，复用现有诊断请求器和完整定义读码：

- aligned 必须引用实际选中源码；不是只说“诊断无明显矛盾”。
- redirect 必须引用可观察的替代源码，并在原可写目录内重新定位。
- blocked 给出具体缺失能力/证据，不假装检查已执行。
- 引用、目录和快照由宿主校验，相关性由模型判断；模型仍可能判断错。
- 测试文件仅作为只读线索，模型评估不是实际运行探针或测试通过。

分批110项相关检查通过。新的本地运行时集成使用替身模型：先选错误 helper，
评估要求改选目标，重新定位后 Implementer 只修改目标，真实本地断言通过。
这证明路由顺序/预算/权限约束，并不是 mini 的真实识别能力证明。

## 下一项小成本实测

`.keel/repair-review/handoff-alignment-v1/run.ps1` 复用现有 frozen-model-review
入口，使用生产 handoff prompt 和 validator，冻结两个请求：历史 drift 范围与
named-target 对照。每组 mini 一次，最多180秒/24,000 Token预算/1,024输出
Token，合计最多两次派发。两组输入约12,777/11,790字节，内容不同，不能作为
等量上下文的成本消融。

定义源码来自已保存 verification-0 候选；helper/测试线索来自恢复后的 base
源码，并非完整 graded test patch。输入、实现、配置哈希冻结。尚未调用真实模型。
先核查真实 mini 是否能指出 drift 并对 target 给出合理范围判断或具体阻塞；
完成解析不等于质量通过，不自动把 aligned 当作修复成功。不做源码修改、
不运行 Docker、不自动重试失败付费微测，也不立即重跑60次调用的完整实验。
# Live micro-review follow-up: newline provenance

The drift arm of handoff-alignment-v1 returned redirect to the intended source
target in one call (3,612 recorded tokens, 8.891 seconds). The old exact-byte
quotation check rejected two citations solely because source CRLF became reply LF.
The target arm did not run. A separate offline-review-newline-v1.json validates
the preserved reply with source-crlf-equivalence-v1, records both matches as
line_endings_only, and preserves the original failed artifact unchanged. No new
provider calls were made. This supports recognition of this particular drift,
not general reviewer accuracy or repair success. A new target-only frozen plan
uses LF source display while retaining original source byte hashes; its live
result remains pending.


## Target control protocol failure

Target-v2 returned aligned with four exact source citations, but incorrectly
filled replacement_files with the current path. One mini call cost 3,228 recorded
tokens and 7.75 seconds. Strict host validation correctly rejected it. The prompt
had omitted the empty-list invariant, now stated explicitly alongside redirect
and blocked rules. The failed result remains unchanged; inspection-v1.json is a
separate derivative. A separately frozen contract-v3 target control is prepared
but not dispatched. These two live calls show plausible scope judgments on this
frozen example, but do not establish reliable protocol compliance or task repair.

## Contract-v3 target accepted after manual review

One call, 3,190 recorded tokens, 10.016 seconds: aligned, empty replacement list,
two exact selected-source quotations. Relevant scope is supported; the reviewer
has not demonstrated a causal explanation of the failure or executed its probe.
All three live micro calls cost 10,030 recorded tokens including the two failed
receipts. The earlier drift reply was salvaged by a separately hashed offline
newline-policy replay; do not describe the original run as protocol-successful.
Prepared bounded-30min-v4 with diagnostic-handoff enabled and unchanged seed,
reference, model and budgets; no live dispatch yet. Compare actual routing,
source changes, fresh verifications and costs, not merely aligned verdicts.
