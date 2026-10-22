# 30 分钟探索 v2 复核（2026-10-22）

本次为已反复开发调试的 Astropy-14508 种子续修，不是独立成功率评测。
原产物位于 `.keel/swebench/astropy-14508-bounded-30min-v2`，未覆盖或重评分。

## 结果

- watchdog：unresolved，总计 1,210.125 秒；trial 1,209.547 秒。
- runtime：failed，Scout 阶段 model_error，RemoteDisconnected。
- runtime 381.843 秒、18 次派发、103,892 已记录 Token、15 次工具调用。
- 配额未耗尽：60 次调用 / 400,000 Token / 160 工具 / 1,500 秒 Agent；
  外层 1,800 秒也未到。失败派发可能已有服务端执行，未取得 usage，不能声称
  其费用为零或记录 Token 已涵盖所有实际支出。
- 运行前和最终评分前 Docker Server 都就绪，版本 29.8.2。
- 一轮新验收返回真实测试报告：FAIL_TO_PASS 1/1 成功；PASS_TO_PASS
  173/174 成功；唯一失败仍为 test_invalid_float_cards2，VerifyError 指向
  无效值字符串 5.0022221e-07。不能声称本轮消除了旧回归。
- 轨迹完整记录 18 条 request、17 条 response、1 条 error；两次监督均
  consistent，没有冲突纠正。consistent 不代表假设已验证或修复有效。
- 当前继承种子基础上的 changes.patch 为 516 字节；没有多轮成功修复轨迹。

## 为什么总共花了 20 分钟

模型中断后入口仍执行最终评分。中间验收的 run_instance.log 显示成功完成测试
后删除实例镜像；无 overlay/network/plugin policy 时桥接器未显式启用 instance
cache。最终评分因此重新构建同一实例镜像。

最终 build_image.log：01:57:11 开始 git clone，02:10:16 报 GnuTLS recv error
(-9)、unexpected disconnect、early EOF、invalid index-pack output，退出128。
harness 最后汇总 completed=0、errors=1，没有生成实例评分报告。桥接器因此
报告 Official grading did not produce one report；official_resolved 为 null，
不能把最终评分错误描述成已评分但 unresolved=false，或新的代码测试失败。

证据路径：

- `trial.json` / `run/result.json` / `model-transcript.jsonl`
- `verifications/d3e76f34fe7b468e9cd81c2e8eeb6259/feedback.json`
- 同验收目录下的 grading/logs/run_evaluation 实例日志，包含实例镜像删除记录
- `final-grade/logs/build_images/instances/sweb.eval.x86_64.astropy__astropy-14508__latest/build_image.log`

## 与 v1 的区别及下一步

v1 没有新测试结果、Docker 服务不可用时消耗到60次派发；v2 Docker健康检查
通过，得到了一次有效测试结果。环境恢复是人工排障的成果；由于本次
infrastructure_attempts=[]，不能据此宣称新分流的故障恢复路径已经实机验证。

本轮不支持修复能力提升的结论，暴露了剩余两项工程缺口：模型瞬态传输故障
没有在共享预算内纠正；已有镜像未保留，最终评分重复网络构建，放大偶发故障。
后续应先做通用、可追踪、受总预算限制的模型传输恢复（每次派发单独记录，
保留失败 usage 未知的事实），以及验证同环境实例缓存可复用。最终评分应绑定
实际导出的源码版本，不能把历史 verifier pass 当新评分收据。

先离线验证恢复与缓存策略，再决定新的有标识付费尝试；不再次直接增加预算，
不手写这道题的格式化答案，不更改模型或参考测试。本轮复核无新增模型调用。
