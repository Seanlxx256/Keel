# 历史硬限制与可恢复拦截审计（2026-10-25）

本次为只读审计，没有调用模型、Docker 或重跑评分。初筛扫描 `.keel` 内 855 份选定名称的 JSON 文件，88 份含匹配文本。初筛包含 trial/result 重复、非终止字段及误匹配，**不是 88 次独立失败**；下列结论逐项核对实际报告、轨迹、账本或对照结果。初筛清单：`.keel/repair-review/hard-limit-audit-v1/inventory.json`。未穷举所有日志、未保存的终端记录或全部历史源代码版本。

主要结论：确有多个已付费、仍有部分资源的尝试，在遇到局部容量/协议问题后结束；其中一些应先进行可恢复处理。也存在真实授权预算耗尽和真实无效请求，不能把这些边界全部取消。**请求被拒绝与整个任务结束应成为两个独立决策。** 后续结果即使通过，也不自动证明原尝试在放开门槛后必然通过。

| 实际案例 | 已确认的拦截/消耗 | 判断与更合理的下一步 |
|---|---|---|
| feedback-replay-v1 | 名称26字符，旧上限24；1调用、1830 tokens，无比较 | 元数据问题。内部ID由主机生成，保留原名和映射；不需重新推理业务或生成候选。已有64字符修复和显式付费回复迁移；统一主机ID机制尚未实现。 |
| critic-questions-pair-v1 source | evidence 1023字符，上限1000；1调用6023 tokens | 表达长度不等于诊断无效。当前上下文容得下则警告继续；放不下才请求语义保留的缩写，不能直接切断引用。该输出包含待核查的语义错误，因此不宣称内容正确。 |
| critic-stability-v1 / v2 | 1024输出上限时2/3完成；失败样本finish_reason=length，实际completion=1024。相同冻结请求2048时3/3完成 | 输出额度导致可观察的不完整结果。保留原文，按角色/结构预留合理输出；若预算仍允许，明确记录扩大额度后的新调用。不能把截断JSON作为完成，也不是端到端修复因果证明。 |
| sphinx-9602-check-v1 | 2/3调用，16653/60000 tokens，35.875/120秒；InputCapacityExceeded | 本地请求容量问题，不是总预算耗尽。执行观察、重复源代码、历史脚本应形成原始账本与紧凑请求视图；程序先去重，再让模型决定下一步。后续已开发 request_view，但本次未重放原请求量化收益。 |
| model-contrast-v2 mini/full | 各2/3调用后上下文拦截；15300/14715 tokens，25.625/31.031秒，预算60000 tokens/120秒 | 两种模型都被宿主容量挡住，当时不能由 incomplete 推断模型能力差异。应首先修复/诊断请求包装，再继续同样协议；不默认扩大总预算。 |
| astropy-probe-informed-v2 | 下一调用估算不足；78160/120000 tokens、9/20调用、290.234/600秒 | 仍有41840 tokens，但**不能据此保证下一调用可行**。必须记录拒绝请求的输入估算、估算器、输出预留和固定/可选内容，才能证明是不是过保守。先更准确计数、压缩重复内容，再在剩余预算内重新分配；旧摘要缺这些细项，不能逆推出必过。 |
| astropy-14508-extended-v3 | 353926/400000 tokens、52/60调用、1185.422/3600秒，下一调用预留不足 | 尚有46074 tokens/8调用/时间，但不是任意原请求都能发送。与上项同类；更长时间无法单独解除Token限制。 |
| matplotlib-24627-stability-v1 trial-2 | 两次旧文本匹配2处，局部重复保护终止；6/20调用、40619/180000 tokens、149.235/1150秒 | 保留唯一匹配写入保护，不能随意改第一处。给出真实匹配位置/上下文，要求模型选择、补充锚点或重新定位，在共享预算内换策略。已有局部反馈改进；不等于统一可恢复控制器。 |
| astropy-14508-extended-v1 | 两次选择测试文件为可写目标后局部停止；7/60调用、43040/400000 tokens、69.938/3600秒 | 写权限边界必须保留。应区分“想读测试帮助诊断”和“要改测试”：提供只读取证路线、列出可写源码候选，要求返回新的可执行动作，不能让同一无效重定位反复消耗。 |
| astropy-inspection-repair-20261021-121956 | 请求测试文件5600–5685行，共86行；账本实际total_lines=3178；8工具、62898 tokens、11调用、101.297秒 | **纠正：并非单纯80行上限。** 请求超过文件真实末尾，而且异常将路径/范围/长度混为一谈。应返回真实范围，允许搜索符号、重选窗口；合法长区间可分块。不能放宽至读取不存在的行。 |
| astropy-execution-bridge-v1 | unknown observation导致整个尝试退出；7/20调用、63362/120000 tokens、79.281/600秒 | 证据引用真实性不能放松。持久化已执行结果，返回真实可用ID及引用失败原因，让模型纠正引用或撤回主张；禁止凭相似名称猜测映射、编造证据。 |
| sphinx-9602-probe-informed-v3 / agent-v2 | 分别12/12与20/20实际调用耗尽；仍剩部分时间/Token | 这是真实已声明的调用额度耗尽，不应事后自动追加。可在耗尽之前预留验证/最终解释调用、减少低收益重复定位；另起新授权实验可改变预算。剩余时间不等于剩余全部资源。 |

## 原始证据索引

- [候选名称失败](../../.keel/outer-improvement/feedback-replay-v1/proposal.json)、[预算](../../.keel/outer-improvement/feedback-replay-v1/report.json)。
- [Critic字段长度的保存复核](../../.keel/repair-review/critic-questions-pair-v1/offline-review.json)。
- [1024输出稳定性复核](../../.keel/repair-review/critic-stability-v1/review-summary.json)、[失败样本](../../.keel/repair-review/critic-stability-v1/trial-2/results/summary.json)；2048的三个实际 `trial-1/2/3/results/summary.json` 均completed，不能只读prepared_only的experiment.json判断未执行。
- [Sphinx上下文拦截](../../.keel/repair-review/sphinx-9602-check-v1/results/probe/report.json)。
- [mini容量失败](../../.keel/repair-review/model-contrast-v2/mini/results/probe/report.json)、[full容量失败](../../.keel/repair-review/model-contrast-v2/full/results/probe/report.json)。
- [Token预留停止](../../.keel/swebench/astropy-probe-informed-v2/trial.json)、[extended-v3](../../.keel/swebench/astropy-14508-extended-v3/trial.json)。
- [唯一匹配保护](../../.keel/swebench/matplotlib-24627-stability-v1-trial-2/trial.json)。
- [只读/可写目标混淆](../../.keel/swebench/astropy-14508-extended-v1/trial.json)。
- [范围拒绝](../../.keel/swebench/astropy-inspection-repair-20261021-121956/trial.json)、同目录 `run/ledger.sqlite` 事实14记录total_lines=3178、事实25记录请求5600–5685、事实26记录拒绝；使用只读SQLite查询。
- [未知引用](../../.keel/swebench/astropy-execution-bridge-v1/trial.json)。
- [实际调用耗尽](../../.keel/swebench/sphinx-9602-probe-informed-v3/trial.json)、[agent-v2](../../.keel/swebench/sphinx-9602-agent-v2/trial.json)。

## 拦截时该让模型再决定什么

不是再泛泛问“请反思”，也不是让模型决定关闭保护。主机先输出一个简短、类型化的事件：

```json
{
  "kind": "request_capacity",
  "protected_purpose": "fit_context_without_losing_required_evidence",
  "binding_constraint": "per_call_input",
  "remaining_budget": "measured counters, not a new allowance",
  "required_evidence_ids": ["current-failure", "current-source"],
  "allowed_actions": ["select_windows", "split_check", "defer_optional_history", "checkpoint_stop"],
  "attempted_repairs": ["exact duplicate removal"],
  "resume_point": "before blocked operation"
}
```

数值应来自实际事件；本例是接口设计，不是已实现事件。

程序可确定无损的操作先做：生成内部ID、去掉重复包装、规范化表示。涉及取舍的步骤再交给模型：选择保留哪些源码窗口、把什么检查拆成两步、定位哪个真实匹配、只读测试后修改哪段源码。模型必须返回允许的动作及参数，而不是只有建议。主机验证并实际执行，恢复原流程。

必须满足：

1. 当前失败/源码身份/已执行观察原始记录不丢；恢复不伪造新证据或测试通过。
2. 恢复调用与工具消耗同一总预算，不能通过“纠错轮”重置；预留恢复空间应在实验前声明。
3. 错误的路径/证据/权限边界保留，只开放安全替代动作。
4. 重复同一无效恢复应切换策略或保存停止；不能给无上限reasoning循环。
5. 恢复成功必须由“阻塞操作重新通过验证并到达后续阶段”确认；最终任务成功另看验收。
6. 用程序动作不需要额外模型调用时，不为了展示reasoning付费。

## 落地顺序

1. 类型化报错，先把“字段超长/ID不合法/未知引用/超出真实文件范围/单次容量不足/实际全局耗尽”从混合ValueError和budget_exhausted中分开。
2. 统一局部恢复入口，接上已有原始回复、账本、预算、request_view和唯一匹配反馈。先支持确定性的无损恢复，再支持受限模型决策。
3. 用上表冻结的失败输入做零模型回放和负例测试；保留不能安全恢复的拒绝。
4. 仅对确需语义选择的两个或三个检查点做有界模型对照。比较恢复后有效执行率、额外成本、错误放行率和最终结果，不只比较“少报错”。

本次只完成审计与设计；未实现统一控制器，也未宣称放开限制就能通过原任务。
