# 新手指南重写进度（编辑记录，不属于正文）

当前交付：keel-compass-beginner-guide-20261029.docx，第 1—25 节。原稿不覆盖写入。
原则：主题可合并，但每项必须有去向；不把已有实测、教学假设与未来设计混写。
本轮：前六节既有复习表并入 6.13—6.14，来源说明放在开篇；新增 7—10 节。
后续批次：11—14 恢复/诊断/预算/环境/可观测性；15—18 Compass/评测/工程案例；19—20 记忆与微调；其后整合原稿其余章节与面试题。
原稿第 21—45 节、233 道题库条目及全部原附录主题仍需逐项重写与复核；不能据当前交付宣称已完整覆盖。

## 原稿标题逐项清点

- [pending_mapping] 阅读路线与使用方法
- [pending_mapping] 目录
- [rewritten_topic_in_chapters_1_10] 1 先理解代码任务和基本开发术语
- [pending_mapping] 为什么这件事在代码安全 / 仓库扫描里很重要
- [rewritten_topic_in_chapters_1_10] 2 LLM Agent Harness 和 Runtime
- [rewritten_topic_in_chapters_1_10] 3 项目解决什么问题及当前边界
- [rewritten_topic_in_chapters_1_10] 4 用户使用场景和不适用场景
- [rewritten_topic_in_chapters_1_10] 5 一次任务需要提供哪些输入
- [pending_mapping] 模式
- [pending_mapping] explicit：用户已经知道具体答案。用户已经给出具体修改 → 程序执行并验证
- [pending_mapping] agent：模型调查 → 模型规划 → 模型通过工具修改 → 程序验证
- [pending_mapping] proposal：用户给范围 → 模型提修改 → 程序应用并验证
- [pending_mapping] localized-proposal：模型连定位也要自己做。模型找范围 → 模型提修改 → 程序应用并验证
- [rewritten_topic_in_chapters_1_10] 6 六角色和完整执行流程
- [pending_mapping] A. 没有启用修复尝试
- [pending_mapping] B. 非 adaptive，但设置了修复尝试
- [pending_mapping] C. 启用了 adaptive recovery：验收失败后，由程序检查是否允许恢复，再让 Critic 决定继续修复、重新调查或停止。适用于当前支持的 agent 或 localized-proposal：
- [pending_mapping] ① localized-proposal 中的 Planner 可能只是包装工作项
- [pending_mapping] ② 普通非自适应 Critic 可能只记录失败
- [pending_mapping] ③ 不是所有失败都应该自动继续
- [pending_mapping] 用一个教学任务串起全部步骤
- [pending_mapping] 第一步：Scout 找问题
- [pending_mapping] 第二步：Planner 确定改哪里
- [pending_mapping] 第三步：Implementer 改代码，但第一次改错了
- [pending_mapping] 第四步：Verifier 运行测试，发现改错
- [pending_mapping] 第五步：Critic 分析失败
- [pending_mapping] 第六步：再次修改和测试
- [pending_mapping] 1. 程序发现测试失败
- [pending_mapping] 2. 程序发送两条消息
- [pending_mapping] 3. 共用的模型客户端发送请求
- [pending_mapping] 4. LLM 返回结构化回答
- [pending_mapping] 5. 程序处理回答
- [rewritten_topic_in_chapters_1_10] 7 状态机 DAG 和工具执行链
- [pending_mapping] LangGraph 的 State Node Edge 与 Reducer
- [pending_mapping] checkpointer store 和 thread_id 怎样配合
- [pending_mapping] Plan and execute 与 ReAct 如何选择
- [rewritten_topic_in_chapters_1_10] 8 证据 上下文与根因判断
- [rewritten_topic_in_chapters_1_10] 9 写入范围和应用层安全控制
- [rewritten_topic_in_chapters_1_10] 10 验证 审计和突变测试
- [pending_mapping] 11 自适应恢复和诊断探针
- [pending_mapping] 12 预算 上下文容量和停止条件
- [pending_mapping] Token 优化如何计量与证明
- [pending_mapping] 上下文压缩有哪几种 不应删掉什么
- [pending_mapping] 模型选型怎样避免只看价格或单次成功
- [pending_mapping] 13 Docker 依赖准备和环境恢复
- [pending_mapping] 14 可观测性 账本和检查点
- [pending_mapping] 简历中的 checkpoint 恢复应如何解释
- [pending_mapping] JSONL 与 OTLP 怎样定位阶段故障
- [pending_mapping] 15 Compass 从索引到上下文
- [pending_mapping] 16 评测体系与实验设计
- [pending_mapping] 17 必须记牢的实测结果与负结果
- [pending_mapping] 简历中的四任务检索组件比较
- [pending_mapping] BM25 三次独立重建到底验证了什么
- [pending_mapping] 18 三个适合面试展开的工程案例
- [pending_mapping] 案例一 Astropy 从反思停滞到执行证据
- [pending_mapping] 案例二 Matplotlib 24627 从环境到自主纠错
- [pending_mapping] 案例三 Matplotlib 24026 的恢复成果交接
- [pending_mapping] 19 从运行记忆到外层改进
- [pending_mapping] 长短期记忆怎样从零设计
- [pending_mapping] 记忆的写入 检索 验证与遗忘
- [pending_mapping] 怎样提高记忆正确性而不作绝对保证
- [pending_mapping] 记忆如何评测 是否真的让系统变强
- [pending_mapping] 20 Scout 微调从数据到结果
- [pending_mapping] 21 高频面试问答
- [pending_mapping] 1 用一句话介绍项目
- [pending_mapping] 2 你的创新在哪里
- [pending_mapping] 3 为什么不是简单套 API
- [pending_mapping] 4 为什么不只用一个很长的提示词
- [pending_mapping] 5 六个角色是不是六个 Agent
- [pending_mapping] 6 为什么 Critic 也会错
- [pending_mapping] 7 怎么证明没有改测试作弊
- [pending_mapping] 8 验收是谁定义的
- [pending_mapping] 9 为什么需要参考补丁预检
- [pending_mapping] 10 依赖都固定了为什么还失败
- [pending_mapping] 11 重试和恢复有什么区别
- [pending_mapping] 12 如何避免无限循环
- [pending_mapping] 13 为什么时间还剩却停止
- [pending_mapping] 14 怎样解决上下文太长
- [pending_mapping] 15 模型推理过程能观察吗
- [pending_mapping] 16 Compass 和 RAG 有什么关系
- [pending_mapping] 17 混合检索就是 RRF 吗
- [pending_mapping] 18 为什么向量检索不一定更好
- [pending_mapping] 19 T2 为什么反而变差
- [pending_mapping] 20 Serena 节省 47% 是项目整体收益吗
- [pending_mapping] 21 你的学习机制会自动越用越强吗
- [pending_mapping] 22 为什么微调 Scout 而不是整个 Agent
- [pending_mapping] 23 LoRA 为什么省资源
- [pending_mapping] 24 checkpoint 包含什么
- [pending_mapping] 25 如何排除数据泄漏
- [pending_mapping] 26 训练 loss 降了能说成功吗
- [pending_mapping] 27 排序正确为什么答案仍错
- [pending_mapping] 28 怎样证明恢复机制有用
- [pending_mapping] 29 最难的问题是什么
- [pending_mapping] 30 下一步优先做什么
- [pending_mapping] 31 SFT DPO RLHF 有什么区别
- [pending_mapping] 32 LoRA 和量化有什么区别
- [pending_mapping] 33 为什么只训练回答 Token
- [pending_mapping] 34 BCE 和 NLL 能说明什么
- [pending_mapping] 35 怎么公平比较几个策略
- [pending_mapping] 36 多次重复为什么还不能证明泛化
- [pending_mapping] 37 怎么减少缓存造成的实验误判
- [pending_mapping] 38 军师和监督有什么不同
- [pending_mapping] 39 如何防止经验库误导
- [pending_mapping] 40 为什么不先做 MCTS 或更多 Agent
- [pending_mapping] 22 面试口述与简历表达
- [pending_mapping] 三十秒介绍
- [pending_mapping] 三分钟展开
- [pending_mapping] 简历可用表述
- [pending_mapping] 围绕这份简历的追问链
- [pending_mapping] 可直接口述的三段实验回答
- [pending_mapping] 23 项目关键概念与能力边界
- [pending_mapping] 角色分工与成功判定
- [pending_mapping] 执行环境与权限边界
- [pending_mapping] 验证证据与因果判断
- [pending_mapping] 预算与失败恢复
- [pending_mapping] 经验复用与参数学习
- [pending_mapping] 评测数字与成果复用
- [pending_mapping] 24 复习计划与面试前检查
- [pending_mapping] 25 原始笔记中需要展开的经历与纠正
- [pending_mapping] 兼容性任务为什么需要三个对照
- [pending_mapping] 一次失败必须先确定发生在哪一层
- [pending_mapping] 反馈从哪里丢失
- [pending_mapping] Astropy 停滞的七种现象
- [pending_mapping] 执行成功为何仍未完成检查
- [pending_mapping] 主机故障的证据链
- [pending_mapping] 从失败中留下什么
- [pending_mapping] 26 把职位描述翻译成能力要求
- [pending_mapping] 面试回答的四层结构
- [pending_mapping] 27 从零理解机器学习和 PyTorch 的语言
- [pending_mapping] 模型为什么能够学习
- [pending_mapping] 概率与损失如何对应
- [pending_mapping] 常见训练术语
- [pending_mapping] 把 JD 中的 NLP 方向对上具体任务
- [pending_mapping] 28 Transformer 与大语言模型怎样处理代码
- [pending_mapping] 从文字到下一个 token
- [pending_mapping] Attention 的直观含义与公式
- [pending_mapping] 三种常见模型结构和两类分词
- [pending_mapping] Temperature 与稳定性
- [pending_mapping] 29 从普通 RAG 到仓库级检索
- [pending_mapping] 一次完整的检索增强
- [pending_mapping] BM25 向量与重排各解决什么
- [pending_mapping] 为什么代码不能只按固定字数切块
- [pending_mapping] 检索失败如何分诊
- [pending_mapping] 30 Agent 工具协议与多角色设计
- [pending_mapping] Workflow 与 Agent 的分界
- [pending_mapping] 工具调用的完整生命周期
- [pending_mapping] Agent Card 与军师是不是必需
- [pending_mapping] 状态 DAG 与并发
- [pending_mapping] 31 上下文管理与可恢复执行
- [pending_mapping] 提示词之外还要管理什么
- [pending_mapping] 何时继续 何时停止
- [pending_mapping] 中断后怎样避免重复消费
- [pending_mapping] 32 从轨迹构建训练数据
- [pending_mapping] 预训练 继续预训练 SFT 分别是什么
- [pending_mapping] 什么轨迹能当好样本
- [pending_mapping] 教师监督与标签噪声
- [pending_mapping] 数据质量报告怎么写
- [pending_mapping] 33 LoRA QLoRA 与 Scout 表示实验
- [pending_mapping] 低秩更新为什么省
- [pending_mapping] 生成答案与候选打分是两种训练任务
- [pending_mapping] 编号不变性和上下文可见性
- [pending_mapping] 保存什么才能严格续训
- [pending_mapping] 34 一个能逐行解释的 PyTorch 训练例子
- [pending_mapping] 语言模型训练要多处理什么
- [pending_mapping] 显存不足怎么查
- [pending_mapping] 35 RLHF DPO PPO 和 GRPO
- [pending_mapping] 为什么有示范还需要偏好
- [pending_mapping] PPO 到底优化什么
- [pending_mapping] DPO 如何直接利用偏好对
- [pending_mapping] GRPO 与可验证奖励
- [pending_mapping] 怎样合理延伸 Keel
- [pending_mapping] 36 多模态代码模型与仓库应用
- [pending_mapping] 多模态究竟增加了什么
- [pending_mapping] 为什么只做 OCR 不够
- [pending_mapping] 一个可落地的后续课题
- [pending_mapping] 数据和消融怎样设计
- [pending_mapping] 多模态预训练岗位会进一步问什么
- [pending_mapping] 37 推理服务 性能与安全边界
- [pending_mapping] 一次生成的成本花在哪里
- [pending_mapping] 提示注入为何影响代码 Agent
- [pending_mapping] 企业代码系统如何增加治理
- [pending_mapping] 38 怎样设计有说服力的实验
- [pending_mapping] 先写要回答的问题
- [pending_mapping] 常见指标怎样计算
- [pending_mapping] 四个适合 Keel 的小实验
- [pending_mapping] 归因比讲故事更重要
- [pending_mapping] 39 两道 REPO 级系统设计题
- [pending_mapping] 设计一个公司内部代码修复助手
- [pending_mapping] 设计截图驱动的业务页面修改助手
- [pending_mapping] 40 研究阅读 自我改进与论文题目
- [pending_mapping] 怎样读一篇 Agent 论文
- [pending_mapping] 可做的三个研究问题
- [pending_mapping] 外层改进的准入规则
- [pending_mapping] 41 扩展面试题 从第 41 问到第 100 问
- [pending_mapping] 41 Agent 和固定链的核心差别
- [pending_mapping] 42 为什么不用一个大提示词解决全部工作
- [pending_mapping] 43 多个角色是否意味着更多独立知识
- [pending_mapping] 44 什么时候触发独立顾问
- [pending_mapping] 45 为什么模型建议检查却没有检查
- [pending_mapping] 46 怎样识别任务真的完成
- [pending_mapping] 47 证据引用有效能证明结论正确吗
- [pending_mapping] 48 怎样证明探针相关
- [pending_mapping] 49 怎样防止重复空转
- [pending_mapping] 50 上下文和长期记忆有什么区别
- [pending_mapping] 51 如何解释 RAG 的收益来源
- [pending_mapping] 52 混合检索就是 RRF 吗
- [pending_mapping] 53 为什么精确符号适合关键词
- [pending_mapping] 54 reranker 和 embedding 有什么不同
- [pending_mapping] 55 代码块多大合适
- [pending_mapping] 56 GraphRAG 是否一定优于普通 RAG
- [pending_mapping] 57 文件改了索引怎么办
- [pending_mapping] 58 向量库是不是必需
- [pending_mapping] 59 Transformer 的 Q K V 是什么
- [pending_mapping] 60 为什么因果模型看不到后续候选
- [pending_mapping] 61 低温是否能保证复现
- [pending_mapping] 62 预训练与 SFT 最大差别
- [pending_mapping] 63 SFT 为什么只对回答计算损失
- [pending_mapping] 64 attention mask 与 loss mask 相同吗
- [pending_mapping] 65 LoRA 为什么仍可能 OOM
- [pending_mapping] 66 rank 越高越好吗
- [pending_mapping] 67 QLoRA 和量化推理一样吗
- [pending_mapping] 68 训练 loss 下降为什么不代表定位更准
- [pending_mapping] 69 小数据怎么避免泄漏
- [pending_mapping] 70 强模型可以直接当真值教师吗
- [pending_mapping] 71 排序提高为什么集合没提高
- [pending_mapping] 72 固定阈值 0.5 为什么未必最优
- [pending_mapping] 73 如何确认梯度真在更新 LoRA
- [pending_mapping] 74 为什么 zero_grad 不能省
- [pending_mapping] 75 eval 和 no_grad 有何区别
- [pending_mapping] 76 权重 checkpoint 能严格续训吗
- [pending_mapping] 77 RLHF 比 SFT 多了什么
- [pending_mapping] 78 DPO 一定比 PPO 好吗
- [pending_mapping] 79 GRPO 为什么用一组回答
- [pending_mapping] 80 Keel Critic 是 value model 吗
- [pending_mapping] 81 如何防止奖励钻空子
- [pending_mapping] 82 为什么失败轨迹不全是负例
- [pending_mapping] 83 什么是信用分配
- [pending_mapping] 84 为什么多模态不能只 OCR
- [pending_mapping] 85 视觉编码器和连接层做什么
- [pending_mapping] 86 多模态代码任务如何验收
- [pending_mapping] 87 如何证明自己做过预训练
- [pending_mapping] 88 pass@k 和成功率能混用吗
- [pending_mapping] 89 如何看待 2/3 冻结重复成功
- [pending_mapping] 90 工具开放组没有调用工具意味着什么
- [pending_mapping] 91 本地测试全绿为什么用户运行仍失败
- [pending_mapping] 92 长阶段如何设计进度
- [pending_mapping] 93 为什么缓存有了还会重复下载
- [pending_mapping] 94 哈希相同能证明什么
- [pending_mapping] 95 如何定义自我改进而非自动重试
- [pending_mapping] 96 外层候选为什么可以全部拒绝
- [pending_mapping] 97 如何向产品经理解释项目价值
- [pending_mapping] 98 项目最重要的一次判断纠正是什么
- [pending_mapping] 99 如何回答个人贡献
- [pending_mapping] 100 入职后优先做什么
- [pending_mapping] 42 分阶段准备与可交付成果
- [pending_mapping] 第一阶段 能解释并亲自操作
- [pending_mapping] 四道应亲手完成的编码练习
- [pending_mapping] 第二阶段 把现有项目讲扎实
- [pending_mapping] 第三阶段 选一个能独立验证的新增课题
- [pending_mapping] 面试前最后一次自检
- [pending_mapping] 43 Excel 题库逐题答辩与复习索引
- [pending_mapping] Keel 项目深挖
- [pending_mapping] 题库 Q001  一句话说清 Keel 是什么，解决谁的什么问题。
- [pending_mapping] 题库 Q002  为什么做这个项目？你是怎么找到这个问题的？
- [pending_mapping] 题库 Q003  Claude Code、Codex、Cursor 都有了，你为什么还要自己做一个？
- [pending_mapping] 题库 Q004  用一句话说 Keel 和 Claude Code 最大的区别。
- [pending_mapping] 题库 Q005  如果做成产品，第一个付费用户是谁？他原来怎么解决这个问题？
- [pending_mapping] 题库 Q006  这个项目现在最大的问题是什么？
- [pending_mapping] 题库 Q007  如果只能保留一个模块，你留哪个？为什么？
- [pending_mapping] 题库 Q008  这个项目花了多久？哪部分最费时间？也最没价值？
- [pending_mapping] 题库 Q009  有没有哪个设计后来被你推翻了？
- [pending_mapping] 题库 Q010  如果重做一遍，架构会怎么改？
- [pending_mapping] 题库 Q011  为什么是六个角色？五个行不行？八个呢？
- [pending_mapping] 题库 Q012  Scout 和 Planner 的职责边界在哪？会不会重叠？
- [pending_mapping] 题库 Q013  Verifier 和 Auditor 为什么要分开？
- [pending_mapping] 题库 Q014  Critic 什么时候触发？它拿到什么输入？
- [pending_mapping] 题库 Q015  六个角色里，哪些是 LLM，哪些是确定性组件？
- [pending_mapping] 题库 Q016  角色之间怎么传数据？为什么不共享一个大 context？
- [pending_mapping] 题库 Q017  某个角色失败了，怎么决定重试还是继续？
- [pending_mapping] 题库 Q018  各角色的 prompt 怎么组织？有共享的 system prompt 吗？
- [pending_mapping] 题库 Q019  怎么保证 Planner 拆出的 work item 粒度合适？
- [pending_mapping] 题库 Q020  work item 拆错了会怎样？你怎么发现的？
- [pending_mapping] 题库 Q021  为什么不用自由 ReAct 循环？
- [pending_mapping] 题库 Q022  你的自研状态机和 LangGraph 的 StateGraph 有什么区别？
- [pending_mapping] 题库 Q023  为什么要做成两种编排后端可互换？这个抽象的边界划在哪？
- [pending_mapping] 题库 Q024  checkpointer 存了什么？恢复时怎么保证一致性？
- [pending_mapping] 题库 Q025  进程在 Implementer 跑到一半挂了，重启后会发生什么？
- [pending_mapping] 题库 Q026  DAG 校验具体校验什么？环检测怎么做的？
- [pending_mapping] 题库 Q027  现在是串行执行，为什么不并行？
- [pending_mapping] 题库 Q028  两个 Implementer 同时改同一个文件怎么办？
- [pending_mapping] 题库 Q029  如果要支持并行，账本需要改吗？
- [pending_mapping] 题库 Q030  路径震荡（反复在几个状态间跳）你怎么防？
- [pending_mapping] 题库 Q031  你的审计具体能检测什么？不能检测什么？
- [pending_mapping] 题库 Q032  AST 不变量具体检查哪些规则？举三个例子。
- [pending_mapping] 题库 Q033  为什么用 AST 而不是正则？
- [pending_mapping] 题库 Q034  突变测试怎么抽样？抽多少？为什么不全量？
- [pending_mapping] 题库 Q035  如果 Agent 用一种你没想到的方式绕过验收怎么办？
- [pending_mapping] 题库 Q036  测试身份比对怎么做？测试改名了怎么识别？
- [pending_mapping] 题库 Q037  为什么验收要在容器里跑？不在容器里会怎样？
- [pending_mapping] 题库 Q038  容器里断网，那需要联网的测试怎么办？
- [pending_mapping] 题库 Q039  你怎么知道审计本身没有误报？
- [pending_mapping] 题库 Q040  如果任务本身就是「修改测试」，你的不变量怎么办？
- [pending_mapping] 题库 Q041  上下文账本和 RAG 有什么区别？
- [pending_mapping] 题库 Q042  Context 和 Memory 的区别是什么？
- [pending_mapping] 题库 Q043  为什么不用上下文压缩？压缩有什么问题？
- [pending_mapping] 题库 Q044  分页召回怎么触发？模型怎么知道要召回什么？
- [pending_mapping] 题库 Q045  SHA-256 校验在校验什么？防什么？
- [pending_mapping] 题库 Q046  陈旧证据怎么检测？
- [pending_mapping] 题库 Q047  账本会不会越来越大？怎么清理？
- [pending_mapping] 题库 Q048  跨角色交接时，接收方看到的上下文有多大？
- [pending_mapping] 题库 Q049  如果账本里存了错误的事实，下游怎么办？
- [pending_mapping] 题库 Q050  你的会话历史现在还在累积吗？
- [pending_mapping] 题库 Q051  权限怎么设计的？按什么粒度？
- [pending_mapping] 题库 Q052  为什么 Agent 本体还跑在宿主机上？
- [pending_mapping] 题库 Q053  MCP 工具白名单怎么按角色下发？
- [pending_mapping] 题库 Q054  Agent 请求一个没权限的工具会发生什么？
- [pending_mapping] 题库 Q055  命令级策略怎么判定？为什么不用正则匹配 rm -rf？
- [pending_mapping] 题库 Q056  提权流程你设计了吗？应该怎么做？
- [pending_mapping] 题库 Q057  沙箱逃逸你考虑过吗？容器逃逸的常见路径有哪些？
- [pending_mapping] 题库 Q058  Prompt injection 在你的系统里会造成什么后果？
- [pending_mapping] 题库 Q059  四维预算具体怎么核算？Token 是估的还是实测的？
- [pending_mapping] 题库 Q060  预算耗尽时会发生什么？是硬杀还是降级？
- [pending_mapping] 题库 Q061  墙钟预算怎么强制？能抢占正在跑的调用吗？
- [pending_mapping] 题库 Q062  trace 里记了什么？一次运行大概多少 span？
- [pending_mapping] 题库 Q063  为什么用 OTLP 格式而不是自定义？
- [pending_mapping] 题库 Q064  你的 trace 有下游消费者吗？还是只给人看？
- [pending_mapping] 题库 Q065  失败归因能归到多细？举个实际的例子。
- [pending_mapping] 题库 Q066  如果加一个指标判断「这次运行健不健康」，你加什么？
- [pending_mapping] 题库 Q067  跑一次要多久？多少钱？哪一段最贵？
- [pending_mapping] 题库 Q068  你怎么知道六角色比单 Agent 好？做过对比吗？
- [pending_mapping] 题库 Q069  哪些任务 Keel 不适合做？
- [pending_mapping] 题库 Q070  没有测试的仓库怎么办？
- [pending_mapping] 题库 Q071  长任务怎么做早停？什么信号说明这条轨迹没救了？
- [pending_mapping] 题库 Q072  LLM 接口挂了，你的系统怎么降级？
- [pending_mapping] 题库 Q073  如果要支持 10 人同时用，你的架构哪里会先垮？
- [pending_mapping] Compass 项目深挖
- [pending_mapping] 题库 Q074  一句话说清 Compass 解决什么问题。
- [pending_mapping] 题库 Q075  为什么 coding agent 需要专门的检索，不能直接 grep？
- [pending_mapping] 题库 Q076  RAG 和 grep 在代码场景里各自什么时候更好？
- [pending_mapping] 题库 Q077  为什么不直接把整个仓库塞进长上下文？
- [pending_mapping] 题库 Q078  三级检索的分档依据是什么？
- [pending_mapping] 题库 Q079  升级闸门的四个信号具体怎么算？阈值怎么定的？
- [pending_mapping] 题库 Q080  为什么是级联而不是先判断难度？
- [pending_mapping] 题库 Q081  T2 的成本是 T1 的多少倍？你实测过吗？
- [pending_mapping] 题库 Q082  升级判错时，两个方向的代价一样吗？
- [pending_mapping] 题库 Q083  代码怎么分块？为什么按语法单元而不是固定窗口？
- [pending_mapping] 题库 Q084  一个函数超过 chunk 上限怎么办？
- [pending_mapping] 题库 Q085  符号表存了什么？调用图怎么建的？
- [pending_mapping] 题库 Q086  为什么用 SQLite 递归 CTE 而不是图数据库？
- [pending_mapping] 题库 Q087  跨文件、跨语言的调用关系怎么处理？
- [pending_mapping] 题库 Q088  增量索引怎么触发？怎么知道哪些要重建？
- [pending_mapping] 题库 Q089  索引陈旧了会怎样？Agent 会用到旧数据吗？
- [pending_mapping] 题库 Q090  向量库为什么选 LanceDB 不选 Milvus？
- [pending_mapping] 题库 Q091  embedding 用的什么模型？为什么选它？
- [pending_mapping] 题库 Q092  有没有做领域微调？为什么没做？什么情况下你会做？
- [pending_mapping] 题库 Q093  检索表示和展示表示为什么要分开？
- [pending_mapping] 题库 Q094  BM25 和向量怎么融合？RRF 的 k 取多少，为什么？
- [pending_mapping] 题库 Q095  混合检索的权重怎么调的？
- [pending_mapping] 题库 Q096  重排做了吗？为什么还没做？
- [pending_mapping] 题库 Q097  CORE-Bench 子集怎么选的？12 个仓库怎么挑的？
- [pending_mapping] 题库 Q098  173 条查询够吗？统计上有意义吗？
- [pending_mapping] 题库 Q099  BM25 的 NDCG@10 只有 10%，是不是太低了？
- [pending_mapping] 题库 Q100  文件命中率 47% → 72%，那个 47% 的基线是怎么跑的？
- [pending_mapping] 题库 Q101  行级精确率 43%，那召回是多少？
- [pending_mapping] 题库 Q102  为什么 T2 的行级召回反而比 T1 低？你的解释是什么？
- [pending_mapping] 题库 Q103  发现这个反常之后你做了什么？
- [pending_mapping] 题库 Q104  3 个任务的结论能推广吗？局限在哪？
- [pending_mapping] 题库 Q105  如果要证明「什么时候该升级到 T2」，你会怎么设计实验？
- [pending_mapping] 题库 Q106  预算从 100 行加到 500 行，召回只从 3% 到 9%，说明什么？
- [pending_mapping] 题库 Q107  MCP 的四个工具怎么划分的？为什么是这四个？
- [pending_mapping] 题库 Q108  stdio 和 HTTP 传输的区别？为什么先做 stdio？
- [pending_mapping] 题库 Q109  如果仓库有一百万行代码，你的索引还撑得住吗？
- [pending_mapping] 题库 Q110  Compass 和 Keel 的接口为什么这么设计？返回值带哪些元信息？
- [pending_mapping] Agent 通用
- [pending_mapping] 题库 Q111  什么是 Agent？和 workflow 有什么区别？
- [pending_mapping] 题库 Q112  ReAct 的原理是什么？它的局限在哪？
- [pending_mapping] 题库 Q113  Agent Loop 和 Harness 的边界在哪？
- [pending_mapping] 题库 Q114  如果只给你一个 LLM API，你怎么从零搭一个 Agent？
- [pending_mapping] 题库 Q115  Prompt → Context → Harness 这个演进你怎么理解？
- [pending_mapping] 题库 Q116  Function Calling 怎么实现的？模型怎么知道有哪些工具？
- [pending_mapping] 题库 Q117  工具 schema 怎么设计？工具多了模型会乱调吗？
- [pending_mapping] 题库 Q118  工具选择准确率怎么提升？
- [pending_mapping] 题库 Q119  工具调用失败了怎么处理？重试几次？指数退避？
- [pending_mapping] 题库 Q120  工具返回内容太大怎么办？
- [pending_mapping] 题库 Q121  并行工具调用什么时候能用，什么时候不行？
- [pending_mapping] 题库 Q122  MCP 解决了什么问题？没有 MCP 之前怎么做？
- [pending_mapping] 题库 Q123  MCP 和 Function Calling 是什么关系？
- [pending_mapping] 题库 Q124  MCP Server 和 Client 各自负责什么？
- [pending_mapping] 题库 Q125  MCP 有哪些安全风险？
- [pending_mapping] 题库 Q126  A2A 和 MCP 的区别？
- [pending_mapping] 题库 Q127  Skill 和 MCP 有什么不同？
- [pending_mapping] 题库 Q128  Skill 的渐进式加载是怎么回事？为什么要 lazy load？
- [pending_mapping] 题库 Q129  上下文窗口不够了怎么办？列出三种做法并比较。
- [pending_mapping] 题库 Q130  三级压缩是怎么做的？压缩时怎么保留关键信息？
- [pending_mapping] 题库 Q131  压缩和外置记忆各自适用什么场景？
- [pending_mapping] 题库 Q132  Prompt Cache 怎么用？什么情况下会失效？
- [pending_mapping] 题库 Q133  短期记忆和长期记忆怎么分？各自存什么？
- [pending_mapping] 题库 Q134  记忆该存什么、不该存什么？存错了有什么后果？
- [pending_mapping] 题库 Q135  多 Agent 和单 Agent 怎么选？
- [pending_mapping] 题库 Q136  多 Agent 之间怎么通信？共享状态还是消息传递？
- [pending_mapping] 题库 Q137  子 Agent 产生幻觉怎么办？父 Agent 怎么发现？
- [pending_mapping] 题库 Q138  多 Agent 的状态冲突怎么解决？
- [pending_mapping] 题库 Q139  取消信号和预算怎么在 Agent 树里传播？
- [pending_mapping] 题库 Q140  Agent 死循环了，你怎么排查、怎么修？
- [pending_mapping] 题库 Q141  HITL 应该卡在哪些节点？
- [pending_mapping] 题库 Q142  风险分级怎么做？什么操作必须人工确认？
- [pending_mapping] 题库 Q143  Agent 的熔断机制怎么设计？
- [pending_mapping] 题库 Q144  需求在多轮传递中丢失怎么办？
- [pending_mapping] 题库 Q145  Rules 和 Memory 的区别？
- [pending_mapping] 题库 Q146  Temperature=0 就是确定性的吗？
- [pending_mapping] 题库 Q147  Agent 的无 AI 兜底方案怎么设计？
- [pending_mapping] 题库 Q148  你怎么评价一个 Agent 框架的好坏？
- [pending_mapping] 题库 Q149  LangGraph 的核心抽象是什么？它解决了什么 LangChain 解决不了的？
- [pending_mapping] 题库 Q150  LangGraph 的 checkpointer 和 interrupt 分别怎么用？
- [pending_mapping] 题库 Q151  Agent 的可观测性应该记哪些东西？少记一样会怎样？
- [pending_mapping] 题库 Q152  Agent 的成本怎么拆？哪一部分通常最贵？
- [pending_mapping] 题库 Q153  给一个 Agent 系统做压测，你会测什么？
- [pending_mapping] RAG 与检索
- [pending_mapping] 题库 Q154  给你一个长 PDF 和一个用户问题，从输入到答案中间发生了什么？
- [pending_mapping] 题库 Q155  分块策略有哪些？各自适用什么文档？
- [pending_mapping] 题库 Q156  固定窗口分块有什么问题？举个会出错的例子。
- [pending_mapping] 题库 Q157  chunk 多大合适？这个数怎么定出来的？
- [pending_mapping] 题库 Q158  父子索引是什么？解决什么问题？
- [pending_mapping] 题库 Q159  top-k 怎么选？k 大了有什么坏处？
- [pending_mapping] 题库 Q160  什么时候不应该用 RAG？
- [pending_mapping] 题库 Q161  稠密检索和稀疏检索各自的失效场景是什么？
- [pending_mapping] 题库 Q162  多路召回的结果怎么融合？怎么去重？
- [pending_mapping] 题库 Q163  RRF 的原理是什么？为什么说它免调参？
- [pending_mapping] 题库 Q164  重排的作用是什么？什么情况下重排反而更差？
- [pending_mapping] 题库 Q165  Rerank 效果变差了，你按什么顺序排查？
- [pending_mapping] 题库 Q166  query rewrite 什么时候有用？什么时候有害？
- [pending_mapping] 题库 Q167  HyDE 是什么？什么场景适用？
- [pending_mapping] 题库 Q168  权限过滤应该在检索前还是检索后？为什么？
- [pending_mapping] 题库 Q169  recall@k / precision@k / MRR / NDCG 分别衡量什么？
- [pending_mapping] 题库 Q170  怎么从零构建一个检索评测集？
- [pending_mapping] 题库 Q171  评测集泄漏怎么防？你的筛选清单是什么？
- [pending_mapping] 题库 Q172  线上效果和离线评测对不上，你怎么查？
- [pending_mapping] 题库 Q173  检索质量下降了，怎么定位是索引问题还是查询问题？
- [pending_mapping] 题库 Q174  embedding 模型怎么选？看哪几个维度？
- [pending_mapping] 题库 Q175  什么时候值得微调 embedding？ROI 门槛在哪？
- [pending_mapping] 题库 Q176  向量库怎么选？几种常见方案的取舍？
- [pending_mapping] 题库 Q177  索引更新用全量重建还是增量？各自什么代价？
- [pending_mapping] 题库 Q178  长文档和短文档混在一起检索有什么问题？
- [pending_mapping] 题库 Q179  代码检索和文本检索的本质区别是什么？
- [pending_mapping] 题库 Q180  代码里的注释和 docstring 该不该参与 embedding？
- [pending_mapping] 题库 Q181  怎么处理一个多语言混合的代码仓库？
- [pending_mapping] 题库 Q182  GraphRAG 是什么？什么场景值得上？什么场景是过度设计？
- [pending_mapping] 题库 Q183  RAG 系统的端到端延迟怎么拆？哪一段最容易优化？
- [pending_mapping] LLM 基础与工程
- [pending_mapping] 题库 Q184  Transformer 的 attention 复杂度是多少？为什么长上下文贵？
- [pending_mapping] 题库 Q185  KV Cache 是什么？它怎么影响推理成本？
- [pending_mapping] 题库 Q186  为什么长上下文模型在中间位置的召回会下降？
- [pending_mapping] 题库 Q187  SFT / DPO / PPO / GRPO 的区别？
- [pending_mapping] 题库 Q188  什么是 reward hacking？工程上怎么防？
- [pending_mapping] 题库 Q189  结构化输出怎么保证？JSON Schema 约束是怎么实现的？
- [pending_mapping] 题库 Q190  模型输出不符合 schema 怎么办？重试还是修复？
- [pending_mapping] 题库 Q191  模型路由怎么做？按什么分档？
- [pending_mapping] 题库 Q192  小模型能做什么、不能做什么？
- [pending_mapping] 题库 Q193  本地部署和 API 的取舍？什么时候必须本地？
- [pending_mapping] 题库 Q194  vLLM 和 Ollama 的区别？各自什么场景？
- [pending_mapping] 题库 Q195  量化对效果的影响？INT8 和 INT4 分别损失什么？
- [pending_mapping] 题库 Q196  Prompt 工程现在还重要吗？和 Context 工程是什么关系？
- [pending_mapping] 题库 Q197  Few-shot 的例子怎么选？选错了会怎样？
- [pending_mapping] 题库 Q198  CoT 什么时候有用？什么时候反而有害？
- [pending_mapping] 题库 Q199  LLM-as-judge 有哪些已知偏差？
- [pending_mapping] 题库 Q200  你怎么知道你的 judge 是准的？
- [pending_mapping] 题库 Q201  幻觉怎么度量？最后那 1–2% 的幻觉怎么找？
- [pending_mapping] 题库 Q202  确定性校验和模型校验各自的适用边界？
- [pending_mapping] 题库 Q203  成本怎么优化？列三个具体手段并排序。
- [pending_mapping] 题库 Q204  延迟怎么优化？首 token 和总时长分别怎么降？
- [pending_mapping] 题库 Q205  怎么估算一个 Agent 系统的月成本？
- [pending_mapping] 题库 Q206  流式输出在 Agent 场景里怎么做？工具调用怎么流式？
- [pending_mapping] 题库 Q207  上下文里 system / user / tool 消息的组织顺序有讲究吗？
- [pending_mapping] 题库 Q208  模型升级了，你怎么确认不会把线上搞坏？
- [pending_mapping] 工程与系统设计
- [pending_mapping] 题库 Q209  Python 的 asyncio 和多线程怎么选？
- [pending_mapping] 题库 Q210  怎么实现一个带 TTL 的本地缓存？淘汰策略选什么？
- [pending_mapping] 题库 Q211  SQLite 的并发写怎么处理？WAL 模式解决了什么？
- [pending_mapping] 题库 Q212  你项目里 Redis 用来做什么？为什么不用别的？
- [pending_mapping] 题库 Q213  幂等怎么保证？Agent 重试场景下尤其怎么做？
- [pending_mapping] 题库 Q214  限流怎么做？令牌桶和漏桶的区别？
- [pending_mapping] 题库 Q215  ACID 分别是什么？
- [pending_mapping] 题库 Q216  Docker 的分层文件系统是怎么工作的？
- [pending_mapping] 题库 Q217  容器的只读挂载和非特权模式分别防什么？
- [pending_mapping] 题库 Q218  CI 里怎么跑需要 GPU 或需要联网的测试？
- [pending_mapping] 题库 Q219  设计一个代码助手，支持 100 个工程师同时用，你怎么做？
- [pending_mapping] 题库 Q220  设计一个 Agent 评测平台，要能公平对比多个 Agent。
- [pending_mapping] 题库 Q221  给公司内部做一个 coding agent 平台，第一步做什么？
- [pending_mapping] 题库 Q222  手写：从一段文本里提取所有函数定义的行号区间。
- [pending_mapping] 教学代码 Python 3.11 及以上
- [pending_mapping] 题库 Q223  手写：实现一个带并发上限和超时的任务调度器。
- [pending_mapping] 教学代码 Python 3.11 及以上
- [pending_mapping] 行为与反问
- [pending_mapping] 题库 Q224  自我介绍，两分钟。
- [pending_mapping] 题库 Q225  为什么投这个岗位？为什么是我们公司？
- [pending_mapping] 题库 Q226  Agent 这块你是怎么学的？学习路径讲一下。
- [pending_mapping] 题库 Q227  最近读过什么论文或技术文章？讲一个你印象最深的结论。
- [pending_mapping] 题库 Q228  你遇到过最难的技术问题是什么？怎么解决的？
- [pending_mapping] 题库 Q229  你有没有做出来不 work 的东西？
- [pending_mapping] 题库 Q230  和别人技术意见不一致时你怎么处理？
- [pending_mapping] 题库 Q231  你实习能来多久？能保证每周几天？
- [pending_mapping] 题库 Q232  你的职业规划是什么？三年后想做什么？
- [pending_mapping] 题库 Q233  你还有什么想问我的？
- [pending_mapping] 本章校正清单与来源
- [pending_mapping] 44 评估如何设计执行和解释
- [pending_mapping] 先把证据分成不同层级
- [pending_mapping] 一次仓库修复的验收链
- [pending_mapping] 项目已经做过哪些对照
- [pending_mapping] 基线消融和配对各回答什么
- [pending_mapping] 指标如何避免奖励错误行为
- [pending_mapping] 独立评测与统计怎么说
- [pending_mapping] 面试两分钟回答
- [pending_mapping] 45 自修复经验学习和系统迭代
- [pending_mapping] 四种改进发生在不同地方
- [pending_mapping] 任务内恢复的真正闭环
- [pending_mapping] 我们从几次卡住中学到了什么
- [pending_mapping] 操作经验库如何工作
- [pending_mapping] 怎样保证记忆尽量正确
- [pending_mapping] 外层系统迭代做到了哪一步
- [pending_mapping] 怎样测系统是否真的越来越会处理问题
- [pending_mapping] 与微调和强化学习如何衔接
- [pending_mapping] 面试三组重点追问
- [pending_mapping] 本次重点内容的证据导航
- [pending_mapping] 附录一 配置和源码导航
- [pending_mapping] 附录二 来源与证据索引
- [pending_mapping] 附录三 原始笔记覆盖地图
- [pending_mapping] 附录四 初学者术语速查
- [pending_mapping] 代码与执行
- [pending_mapping] 模型与训练
- [pending_mapping] 系统与评测
- [pending_mapping] 附录五 工具对照与研究方向
- [pending_mapping] 附录六 本次扩展的网上资料与使用边界

## 第 11—14 节续写记录

本轮覆盖原稿第 11—14 节的恢复、探针位置、预算层次、容量历史、计数、压缩与成本评测、模型对照、环境构建、依赖/网络恢复、主机故障、日志、OTLP 和 checkpoint 边界。
保留原稿具体实验数字及限制；新增十二处实际代码节选、中文注释和本地源码链接。前十节正文段落 XML 保持，只有开篇范围与导航更新。
下一批：第 15—18 节 Compass 检索链路、评测设计、已有指标与工程案例。其余章节与题库继续待办，不宣称全书完成。
本轮完整状态以 .keel/notes-expansion-20261029/chapters-11-14-qa/source-heading-inventory.json 为准，前面的清点保留历史。

## 第 15—18 节续写记录

覆盖 Compass 索引/语法块/T0-T1-T2/BM25/向量/RRF/重排/打包/新鲜度/MCP；评测层次/SWE-bench/参考隔离/兼容性三组合/指标与标签/对照/留出/分母；完整保留原稿第17节四组表格数字与负结果；三个工程案例融入正文。
重点纠正文件命中口径：region_metrics 的 hit_file_rate 是核心文件覆盖比例，file_metrics 的 hit_file 是二元命中；NDCG 的具体增益定义按冻结协议。前十四节正文段落 XML 与注释保持。新增八处实际源码节选及报告链接。
当前标题覆盖与状态见 .keel/notes-expansion-20261029/chapters-15-18-qa/source-heading-inventory.json；原清点保留历史。下一批第19—20节记忆、系统改进与Scout微调，后续继续原稿其余概念、训练、JD与题库，不宣称全书完成。

## 第 19—20 节续写记录

覆盖运行/长期记忆、经验卡实际生命周期、适用性与正确性、冲突/遗忘/污染/评测、受限外层改进与负结果、RSI研究边界；以及Scout数据审计、真实SFT/LoRA、loss mask、候选评分、排列/因果读出/阈值、四组表示结果和资源工程。
九处实际源码附中文解释、行号和链接；保留既有四组数值及失败限制，明确未替换默认Scout、未证明官方修复率提高。前十八节正文段落XML保持，原稿不变。
当前清点：.keel/notes-expansion-20261029/chapters-19-20-qa/source-heading-inventory.json。后续将整合原稿第21节以后面试表达、JD映射、ML/NLP/Transformer/RAG/训练/多模态/系统设计及233道题库；重复主题融入既有相关章，必要时新增正文，不增加附录。

## 问答合并与纠正章节取消

按用户要求，原第21与41节不再分开。100个源问题按13主题整理，六组重复合并成94个练习单元，全部源编号唯一映射，见 chapters-21-22-qa/question-coverage.json。不是招聘真题或频率统计。
原笔记纠正/对比不单列；原第23/25节不按旧形式追加，正确且仍有用的知识仅按主题整合。原稿不删除。新第22节重写口述、简历、追问链和三项实验表达。
前20节原有段落XML与注释保持，仅开篇范围和导航更新。新稿主章节连续1-22，但原第41节已提前合并，不能仅按章节数量推断覆盖。
后续：原24/26等复习与JD要求、27-40基础和设计、42-45规划/Excel题库/评估与迭代专题仍需核对整合；不再新增纠正专章或拆出另一份41-100题。

## 新第23—25节 岗位准备与模型基础

原24/26/42合并成新23：JD能力、项目证据与缺口、复习产物和编码练习。原27/34合并成新24：ML术语、数值推导、shape、loss、训练循环与实际源码。原28重写为新25：token/embedding/attention/causal mask/结构/位置/生成与Agent边界。没有纠正专章。
保留前22节段落XML、注释和94合并问答。三处实际源码有行号与注释；四段Python代码仅做AST检查，教学数值用标准库复算。当前文档解释器无torch，未执行PyTorch例子，不能记成新增训练。
当前映射见chapters-23-25-qa/source-heading-inventory.json。剩余原29-33/35-40/43-45等需深化或查缺补漏，部分主题已在项目章节出现；Excel233题未宣称逐题完成。

## 新第26—28节：RAG、Agent设计与轨迹训练数据

原29重写为新26；原30/31合并为新27；原32重写为新28。补充从问题到检索证据、工具执行与上下文预算、准备执行提交和幂等、样本来源审核及任务组隔离。保留前25节段落XML、注释和94合并问答。四处源码带行号、哈希和教学注释；RRF与教学样本断言用标准库核对，无新模型/训练/任务运行。剩余原33/35—40/43—45及Excel233题仍需逐项核对整合，不能宣称全稿完成。当前覆盖映射见chapters-26-28-qa/source-heading-inventory.json。

## 新第29—30节 LoRA与强化学习

原33重写为新29，原35重写为新30。解释低秩参数、量化和精度、真实LoRA配置、表示与阈值、续训状态；补RLHF、优势、PPO概率比、DPO教学计算、GRPO组内归一化和可验证奖励风险。保留前28节段落XML、注释与94问答。源码与未来训练方案分开，未进行新模型/训练/基准执行。剩余原36—40/43—45及Excel233题仍待整合。

## 新第31—33节 多模态服务与系统设计

原36/37/39分别重写为新31/32/33。补图像编码与图文训练、截图到DOM和源码、双验收、视觉必要对照、prefill/decode/KV与吞吐延迟、权限与多租户、队列和取消、恢复降级和SLO。两处当前代码与未来设计分开。保留前30节段落XML、注释和94问答；原稿未改。几何教学代码用标准库执行，未做新视觉模型/浏览器/服务部署/任务测评。剩余原38/40/43—45及Excel233题需整合和最终逐项覆盖审计。

## 新第34—36节 可信评测自修复与研究设计

原38/44合并新34；原45重写新35；原40重写新36。补实验单位、检索与pass@k算例、配对消融和基线回退、分层验收、成本分母与统计边界；串起恢复、知识生命周期、负面外层结果与留出；将动作空间、表示、多模态转为研究问题。保留前33节段落XML、注释和94问答。两处源码有行号哈希，五份本地报告链接已核对存在。标准库执行教学计算，未运行新任务/模型/训练。原43与Excel233题尚待逐题整合；其他来源主题仍需最终覆盖审计。

## 新第37节 Excel题库Keel深挖

Excel共233题，Keel类别73题已按九组主题与一组练习编入新37，原编号Q001—Q073和原单元格位置保留。答案依据当前实现纠正只靠mock处理联网测试、未压缩历史、六角色均LLM、LangGraph通用崩溃恢复等前提，不背书题库的公司真题标签。原工作簿及准备状态未变。前36节段落XML、注释和94旧问答保留，两处源码有行号哈希。其余160题为Compass37、Agent43、RAG30、LLM25、工程15、行为10，仍需分批整理。逐题映射见chapters-37-qa/excel-question-coverage.json。此时不能宣称全题库完成。

## 新第38节 Excel题库Compass深挖

Q074—Q110共37题编入正文，原题与单元格位置保留。核对T0/T1/T2、四数值升级信号与其他原因、SQLite层级CTE、保守调用关联、增量与会话新鲜度、可选向量后端、表示与模型身份、重排负结果和不同指标口径。纠正四工具、未做重排、全面SDK服务端等过时前提，当前核心代码工具五个另有可选文本工具。前37节段落XML、注释和94旧问答保留，累计Excel110/233已编入，还剩123题。三处源码有行号哈希，本地评测链接已检查。原Word与Excel未改；无新检索/模型/训练/任务运行。覆盖见chapters-38-qa/excel-question-coverage.json。

## 新第39节 Excel题库Agent通用

Q111—Q153共43题按循环、工具、协议、上下文、协作、审批、框架与评测组织。补教学工具循环，执行标准库断言；两段当前源码带行号哈希。澄清三级压缩非统一定义、Skill可含脚本、缓存非答案复用、温度零非确定性保证、框架能力不等于项目实现。保留前38节正文XML、注释与94问答，原Word/Excel不变。累计153/233，余RAG30、LLM25、工程15、行为10；覆盖见chapters-39-qa/excel-question-coverage.json。未运行新模型/任务/训练。

## 新第40节 Excel题库RAG与检索

Q154—Q183共30题以手册导出限额问题串起PDF解析、分块父子索引、召回融合重排、改写HyDE、权限、评估、模型选型、更新与GraphRAG。补权限过滤顺序教学代码并执行断言，一段实际融合源码有行号哈希。澄清RRF并非没有参数、HyDE假想文本不是真实引用、GraphRAG不等于已有调用图。前39节段落XML、注释与94问答保留；原Excel与Word不变。累计183/233，余LLM25、工程15、行为10。覆盖见chapters-40-qa/excel-question-coverage.json。无新模型/检索/训练或任务运行。

## 新第41节 Excel题库LLM基础与工程

Q184—Q208共25题覆盖稠密注意力复杂度、KV、位置敏感、训练目标、格式、路由、部署、量化、提示与CoT、评审与幻觉、成本延迟、流式与版本升级。明确错误率未由题目给定，有限零错误抽样不证明零风险；评委偏好一致非代码真值。虚构月成本用Decimal执行，单侧二项上界用标准库复核；一段源码带行号哈希。保留前40节段落XML、注释与94问答；原Word/Excel不变。累计208/233，余工程15、行为10，最后还需覆盖审计。无新模型/任务/训练。

## 新第42—43节 Excel工程与行为题收尾

Q209—Q223工程15题与Q224—Q233行为10题已编入正文，累计233/233。保留原题、编号与单元格；不虚构Redis、客户、团队、出勤或个人背景。补TTL/LRU、AST函数范围和有界协程调度器教学代码，执行正常、失败、单项超时、总截止、空输入与外部取消检查，明确协作取消不保证强制停止。源码账本局部带行号哈希。保留前41节段落XML、注释与94问答；原Word/Excel不变。覆盖见chapters-42-43-qa/excel-question-coverage.json。题目齐全后仍需原稿主题、术语、事实、引用与视觉总审查；不把233覆盖称为全稿完成。

## 43节首轮总审查与正文补漏

机械核对：43主章节、94合并问答、Excel233唯一原编号；50个本地超链接原先均存在，59份源码节选文件哈希匹配。补回兼容性三格、策展失败、反馈截尾和纠正请求容量、真实行范围、工具研究状态、源码/配置入口与资源术语，均放回相应正文，不新建补充章。保留原段落和表格XML，仅原位调整两处开篇表述；保留高亮加粗注释与原稿。来源主题映射保存在manuscript-audit-v1/source-heading-inventory.json。映射不表示逐句等价或已通读认证；网页链接未全量在线探测，视觉检查仍受缺少soffice限制。未运行新模型/任务/训练。

## 前14章第二轮阅读衔接与术语审查

原位调整10段正文，补2段辨析；第5节保留概念导读，第7节明确进入代码层；第8—11和14节补足承接关系。区分独立会话、独立验收与独立留出案例，区分Keel外围程序与SWE-bench官方harness，明确action路由与next_check文字不是同一种执行。纠正“前十节只讲正常修复”的不准确概括。无删题、无新增附录，保留所有表格XML和未改段落XML、注释与代码。43章、233题、94合并问答不变；57本地链接、59源码身份和章节编号检查通过。此次仅为前14章定向语义/可读性审查，后15—43章仍需继续通读；未做全稿事实认证。再次尝试渲染，缺少soffice，逐页视觉检查未完成。报告：manuscript-audit-v2/verification.json。

## 第44—45节 Python与后端面试基础

新增35小节，讲解对象绑定、容器、拷贝、参数、闭包、装饰器、生成器、类、类型、异常、导入、编码、内存、并发和测试；后端沿修复任务请求展开HTTP、框架、数据库、SQL连接聚合、事务与隔离、索引、幂等、缓存、队列、超时、权限、流式进度、观测与部署。3份真实源码带行号与身份；14段Python语法检查、11段标准库教学代码执行通过，包含内存SQLite查询和重复提交对照。后端平台明确为教学设计，未宣称已部署FastAPI/Redis/PostgreSQL/Celery。保留前43章正文XML（仅更新2处范围说明）、原表格和导航旧行、注释、233题及94合并问答。原文件被占用，完整45章另存至 docs/interview/keel-compass-beginner-guide-20261029-python-backend.docx；以后继续编辑应以此版为起点，避免遗失新增内容。原Word与Excel未变。原始资料经查阅并链接；再次渲染因缺少soffice失败，结构检查不等同视觉认证。

## 2026-10-30 前六章红色疑问逐处解答与局部排版

以用户已批注的python-backend完整45章版本为起点，保留本轮前的备份。前6章23处红色段落全部补蓝色“已解答R01—R23”，包括4处表格段落，表内标记可跳转到紧随表格的对应说明。解释system/user/assistant、缺失测试、自然语言与JSON、模型服务与mode、native/LangGraph、失败路由、启动器/执行器、固定状态与动态数据、DAG依赖、写入前重验、读取测试、Critic校验、诊断模型、Verifier/Auditor、有限重修和检查点恢复范围。只调整前6章标题/正文/代码间距、13张表格边框留白及非内容空段落高度，不删除原问题。全部原文本节点、原运行格式、45个红色和182个黄色高亮保留，第7—45章XML逐块不变。45主章、233题和94合并问答不变；源码与本地链接核对通过。本次原文件可写，已原位更新，路径仍为docs/interview/keel-compass-beginner-guide-20261029-python-backend.docx。渲染因缺少soffice未生成页面，不能宣称逐页视觉认证；未改运行代码或执行任务。

## 2026-10-30 简历导向第零章

新增第0章44小节，放在原第1章之前，原1—45编号不变。按简历讲解设备LLM测试、Python/Selenium/Robot/Jenkins、有限重试与六任务计时、C/C++与嵌入式Linux、Zynq、Secure NTP/NTS、Safety Shutdown、Web UI更新歧义、SNMP、设备环境；再展开Keel编排/权限/预算/探针/Docker/AST/突变/官方验收/Serena成本/SQLite/检查点/OTLP，以及Compass的分块/图/BM25/向量/LanceDB/RRF/级联/增量/MCP与两类评测，补Git和模拟追问。每项连接概念、例子、考点、参考回答与事实边界，50组概念覆盖映射留在resume-coverage.json。4份真实代码节选，8段Python语法检查；3段标准库算术与1个纯RRF函数检查通过，Selenium/Robot/Jenkins片段明确未执行。四任务数字按两份原始比较汇总复核，CORE与成本按本地报告复核，没有新实验。个人六任务与设备经历未补造证据；Secure NTP协议、Web UI更新含义等待本人核实；SymPy成功需匹配任务记录，不拿16450失败充当成功。纠正SDK封装、checkpoint恢复和OTLP范围等过宽表述。用户当前版本已新增280黄/51红高亮，全部保留，原23解答、233题、94合并问答、所有旧正文与表格及媒体逐块保持；原文件可写，已原位更新。渲染仍因缺少soffice失败，未宣称逐页视觉认证。
