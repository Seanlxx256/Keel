# 30 分钟探索 v3 复核（2026-10-22）

## 可确认的结果

总耗时 960.093 秒；runtime 885.578 秒后 Scout 达到60次模型调用上限，
不是1,800秒总时限，也不是网络异常。累计319,490 Token、108工具调用。
完整轨迹60 request / 60 response，无 transport_failure/error 事件；因此
传输重试本轮没有触发，不能宣称它已完成真实断线自恢复。

四轮验收及最终评分均有有效结果，且全部相同：F2P 1成功0失败，P2P
173成功1失败，唯一失败 test_invalid_float_cards2。最终 grading.status=graded、
official_resolved=false；completed 只表示流程/评分完成，不是任务修复成功。
没有新的基础设施失败，infrastructure_attempts=[]。

最终 harness 明确输出 Found 1 existing instance images. Will reuse them，
实例运行约53.86秒，未重建或再次clone。这是实例缓存实际复用的证据。
总实验15分多与v2约20分的差异不能当成本降低因果评测：v2提前模型断线且
重建失败，v3用满调用配额，执行工作不同。

## 为什么仍未修好

从账本、轨迹和代码差异看，执行发生偏移：

- Critic 五轮问题持续要求检查 FITS 格式化路径并作直接序列化探针。
- file-selection-page 先选 card.py，后页选择将其丢弃，转向 misc.py、
  exceptions.py 等工具模块；anchor refinement 后形成了这些文件的编辑范围。
  此为实际候选丢失，不足以单独证明宿主分页算法有 bug，需进一步检查输入。
- 实际提案包括修改 dummy file-like write 的返回值、dtype 正则和导出 ERFA
  warning/error 符号，没有建立它们与失败调用的因果关系；重复验收未改善。
- 一次 work_item 标记 completed，但 summary 明说允许范围内无有效修复；
  completed 在这里不应被解释为完成了诊断检查或目标修复。
- 每轮 progress.check_execution=not_established；有读码事实但没有证明
  Critic 所要求的直接探针被执行。
- 四次 correct_proposal（无有效改动）、四次 correct_evidence_selection 和
  一次 relocalize 纠错均消耗了预算。
- 多次监督 consistent 主要判断诊断措辞不与证据冲突，没有验证后续选文件、
  实际修改是否执行了 next_check。其权限范围不是完整的执行方向监督。

按 llm_call_finished 事件统计：Scout 42调用/240,376 Token（约75.2%），
Critic含监督10调用/45,765 Token，Implementer 8调用/33,349 Token。总计匹配
60调用/319,490 Token。不是缺少继续调用的机会，而是定位、协议纠正和偏移
实施反复发生，未将假设闭合为可检验的实验。

停止时有5份候选记录，保留优先策略选回 saved-seed，恢复了3个被改文件；
最终重新评分仍剩同一回归。不能说候选机制改善修复，只能说没有把未经改善的
额外修改作为最终提交。历史候选及每次验证仍保留。

## 下一步应验证的通用机制

先对这份冻结轨迹做“诊断目标 → 候选保留 → 检查证据 → 实际修改”交接审计。
应让下一角色明确接受检查目标、区分只读检查路径和可写修复目标；若改选其他
区域，必须提出有实际证据的替代因果路径。执行监督应核对实际行动是否回答
指定问题，不能只给保留不确定措辞的诊断 consistent。没有运行工具时应报告
具体不可执行原因，不能把读码或完成提案当探针执行。

优先用冻结轨迹验证是否能识别本次偏移，再决定最小运行时修正；不将具体
Astropy 文件、值或答案写成系统规则，不先加预算或直接发起新付费实验。
本轮仅只读复核、写文档，0新增模型调用，旧输出/评分未改。
