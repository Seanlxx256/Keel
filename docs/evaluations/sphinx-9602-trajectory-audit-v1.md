# Sphinx 9602：全局预算运行的离线轨迹审计

日期：2026-10-24。对象为 `sphinx-9602-agent-v2`。本次没有新模型、Docker 或测试执行，不修改候选源码。

## 已验证的事实

- 20 次调用分成 10 次 Scout 定位、5 次 Critic、5 次 Implementer。最后两次调用仍用于文件和定义选择，下一次补丁请求无法进入。
- 首轮定位包括 python domain、typing、autodoc；后续四次文件选择均收敛到同一个 `sphinx/domains/python.py`。定义行号及窗口会随源码修改而变化，不能声称所有请求逐字相同，也不能认定所有重新读取都没必要。
- 账本的 file/symbol 证据只包含生产源码，没有失败测试正文的读取记录。提案请求的 evidence 也只有生产源码窗口；文件选择请求的 `read_only_evidence_paths` 全为空。
- 一项重要补充：原始工作树有 `test_parse_annotation`，但没有目标 `test_parse_annotation_Literal`。该测试来自官方验收侧；真实测试日志包含其失败上下文。因此简单地“让 Scout 在原仓库读目标函数”并不能补齐这份证据。
- `diagnostic_executions` 为空；diagnostic inspection、targeted source review、diagnosis supervision、diagnostic handoff 均关闭。全局预算模式开启，不会自动开启这些机制。
- 失败测试数量排名（回归失败数、目标失败数）为 `(0,1) → (4,1) → (4,1) → (4,1) → (2,1)`。最终恢复到早期 `(0,1)` 候选。多次修改没有解决目标测试。

## 主流程的结构性断点

`runtime.critic_phase` 将 Critic 的问题追加到 `active_goal`。`replan` 路由返回 Scout，重新选择文件和定义，然后仍然进入补丁生成。

只有存在显式 `diagnostic_execution` 配置时，程序才设置并执行诊断任务。此次没有配置。因此不能把“提示要求先检查”视作“检查确实执行”，也不能因为出现重新定位证据就认定问题已经回答。

现有 `next_check` 常提到区分 Literal 与普通注解的处理路径。实际传递给下一角色的是该检查的文字，后续读取和修改没有独立的、已确认的实验结果作为中间交接。轨迹中的 `check_execution=not_established` 与此一致。

## 对先前判断的修正

1. 不是已证实的“Scout 把文件弄丢”。它反复找回同一个目标文件，源码也有实际更新。
2. 不是单纯“上下文长度不够”。关键验收测试正文没有作为文件证据进入请求；加大容器或 Token 上限不会自动补齐。
3. 不是全局时间耗尽。取消局部上限只是把终点移到 20 次调用上限，没有建立更有信息量的诊断循环。
4. 不把“未读取测试正文”单独宣布为唯一根因。即使提供正文，模型仍可能误解；当前证据说明它是可验证的信息缺口和下一项值得测试的因素。
5. 不将静态阅读一概判为无效。真正的问题是没有确认每次阅读是否回答了待判别问题，以及为什么同样目标需要重新完成两次模型选择。

## 下一步的最小实验

先补证据交接，再考虑完整运行：

1. 从本轮实际官方失败输出中提取完整、有限的失败测试上下文，保留 test id、原始日志哈希及候选源码哈希。不能用不存在该测试的原始工作树冒充已执行测试，也不读取/传递参考解答补丁。
2. 将实际测试契约与当前生产源码窗口一起交给一次受限的诊断请求，要求说明一个可执行、能区分竞争解释的检查；明确区分观察和推测。
3. 使用已有隔离探针执行器执行该检查，保存原始输出，再允许模型更新判断。若探针没有执行，不能把文本回答算完成。
4. 只有检查对诊断有推进后，再用新配置进行完整任务验收。保留既有失败，不改写原分母。

这仍是计划，尚未宣称反馈/探针能解决业务缺陷。避免给模型预置 Sphinx 的具体修法。

后续通用实现可评估：对同一文件保留稳定符号身份，源码改变时刷新内容而非必然重新选择文件；Critic 真正要求扩大调查范围时仍允许重新定位。不能无条件复用旧行号或旧源码哈希。

## 证据

- `.keel/repair-review/sphinx-9602-trajectory-audit-v1/report.json`：逐调用分类、选择结果、来源哈希及账本证据列表。
- `.keel/swebench/sphinx-9602-agent-v2/model-transcript.jsonl`。
- `.keel/swebench/sphinx-9602-agent-v2/trial.json`、`run/ledger.sqlite`、`run/result.json`。
- 该运行 `final-grade` 下的原始 `test_output.txt` 与 `report.json`。
- `keel/runtime.py` 的 `critic_phase`、`keel/recovery.py` 的 `localize`，及 `keel/diagnostic_execution.py`。
