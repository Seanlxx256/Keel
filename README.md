# Keel

Keel 是一个以失败证据、预算和确定性验证为核心的编码任务运行时。目标是在固定模型下减少无效消耗，让“通过”更可信。设计依据是目录中的《keel & compass.pdf》。

当前是 **v0.2 模型驱动闭环**：既支持操作者提供任务 DAG，也支持模型根据自然语言目标分析影响面、规划和调用工具修改代码。Scout、Planner 和每个 Implementer 使用独立对话上下文；验证、基础审计与失败归档由确定性代码执行。目前不并行、不自动重试。

## 快速运行

Python 3.11+，运行时无第三方依赖。在项目根目录执行：

```powershell
python examples/demo.py
python -m unittest discover -s tests -v
python -m keel --help
```

Demo 在临时仓库中执行一次版本迁移，产物保存在 `.keel/demo-runs/<run_id>/`。

对自己的可丢弃工作副本运行任务（会直接修改指定仓库）：

```powershell
python -m keel run examples/task.json --repo D:/path/to/disposable-copy
python -m keel replay D:/path/to/disposable-copy/.keel/runs/<run_id>
python -m keel recall D:/path/to/disposable-copy/.keel/runs/<run_id> 1
```

示例任务要求仓库内存在包含 `API_VERSION = 1` 的 `app.py`。验收命令是参数数组，不经过 shell；请根据仓库调整命令。

## 模型驱动任务

模型接口目前支持 Ollama。先在本机运行 Ollama 服务并准备一个能遵循 JSON 指令的模型，将 `examples/agent-task.json` 的 `model.name` 改成已安装模型名，然后运行：

```powershell
python -m keel run examples/agent-task.json --repo D:/path/to/disposable-copy
```

该模式不需要填写 `work_items`。Scout 可列目录、搜索、读取；Planner 接收影响面摘要并生成带文件范围的 DAG；各 Implementer 只接收自己的子任务与已完成任务的摘要。模型不能调用 shell 或改变验收命令，写操作只支持现有 UTF-8 文件的精确文本替换。创建/删除文件尚未支持。

工具观察的完整内容写入账本，上下文返回最多 4000 字符预览与 fact ID，后续可分页 recall。模型只能 recall 当前会话获得的工具事实；`.keel` 和 `.git` 不能通过文件工具读取。模型原始回复也归档到本地账本，可能含仓库信息。角色内部的对话在本次会话中累积，尚未实现长期上下文淘汰策略。

请求前依据输入 UTF-8 字节数加输出上限保守检查 token 预算，完成后按服务返回的输入/输出 token 数核销；估算并非精确 tokenizer 计数，超额会在响应后停止。另有限制每个角色的轮数、总模型调用次数和请求超时。HTTP 超时不提供操作系统级硬墙钟隔离。

接口参考：[Ollama Chat 官方文档](https://docs.ollama.com/api/chat)。适配器使用非流式 JSON 响应，没有引入第三方 SDK。`Model` 协议可注入替代实现；测试使用脚本模型和模拟 HTTP 响应，不要求服务或密钥。**尚未对真实模型运行做质量评测。**

## 当前实现

- Scout：本地文本检索，返回行号、工作区内容指纹；未校准置信度返回 null。
- Planner：校验显式或模型生成的任务 DAG，按依赖顺序串行调度。
- Implementer：精确替换要求旧文本恰好出现一次；Python 修改先检查语法；禁止修改常见测试目录和内部目录。
- Verifier：运行操作者配置的验收命令，保存退出码、输出和超时证据。
- Auditor：将工作区前后快照比较，只允许声明过的目标文件发生变化。
- Critic：失败时记录结构化原因，当前交还操作者，不自动重试。
- SQLite 账本：完整事实外置，按 ID recall，失败记录持久保留。
- 只读文件缓存：按路径和文件内容寻址，返回重复次数，内容变化后自动失效。
- 调用次数、token 与墙钟预算：调用前检查，命令和模型请求设超时，模型 token 消耗按响应核销。
- JSONL trace、执行报告与 unified diff patch；CLI 成功退出码 0，任务失败 1，配置错误 2。

每次运行输出 `result.json`、`trace.jsonl`、`ledger.sqlite` 和 `changes.patch`。失败时保留已完成修改供检查，不自动回滚。

## 边界与后续

当前路径策略是应用层检查，**不是容器安全边界**。验收命令是受信任的操作者输入，能以当前进程权限写文件、联网或创建子进程；快照审计仅在执行后发现可见文件变化。命令超时只约束直接子进程，尚无整个进程树的资源隔离。应在可丢弃工作副本中使用。

尚未实现：隔离工作区并发、容器与命令能力策略、AST 反作弊与测试元数据校验、突变测试、早停模型、OpenTelemetry spans、Compass AST 索引/混合检索/级联路由/MCP、公开基准和消融实验。当前审计通过仅代表基础检查通过，不代表完整防作弊保证。

接下来优先补强独立验证与沙箱，再接 Compass 和评测。所有性能收益均需实测，目前没有效果声明。
