# 独立治理服务与远程 Worker

这一版把治理数据访问从 Worker 中移出：服务端独占 SQLite，Worker 通过带身份的 HTTP
协议申请操作。它已接入 Keel 的可选 `governance` 配置，复用原有预算和工具治理接口。
它是受控环境中的可执行原型，不是公开互联网服务或已认证的分布式沙箱平台。

## 运行链路

```text
Worker A 的受信任 Keel 宿主 ──认证请求──┐
                                      ├─ 控制服务 ─ SQLite
Worker B 的受信任 Keel 宿主 ──认证请求──┘
```

服务端配置固定 principal、task_id、scope 和各角色的工具授权。Worker 请求不能添加
预算、改变 scope，或读取其他 principal 的运行。服务端生成 run_id，内部 owner 不返回。
响应与业务更新在同一数据库事务提交；原有同机控制接口仍可使用。

远程 Worker 默认不能靠自报 usage 释放额度。报告“用了 0 Token”只产生带来源标记的
观察，已预留额度继续占用。只有服务端显式授予 `trusted_usage: true` 的受信任计费适配器
才可提交权威 usage。当前没有服务端模型代理来独立核实提供方消耗，不能将普通 Worker
的报告当作提供方账单。该保守模式可能较早耗尽额度，这是保护边界，不是成本优化收益。

## 无需密钥的真实演示

```powershell
python -m examples.demo_remote_governance --output .keel/remote-governance-demo-v1
```

演示自动生成临时身份凭据，仅通过子进程环境传递，不写入配置或日志。它启动：

1. 一个独立服务进程，最长 45 秒，外层演示总上限 60 秒；
2. 两个独立 Worker 进程，各自仅获得自身的演示凭据；
3. 两个 Worker 同时申请 40 Token，共享上限 70，所以只能一个成功；
4. 两边尝试的禁用搜索都应被拒绝，未实际执行搜索或模型调用；
5. 成功申请者上报 0 Token，服务端仍保留 40 Token；
6. 保存 Worker 报告、控制库、服务日志和检查结果，清理启动的进程。

`authorized_model_attempts` 是协议中的预留次数，`actual_provider_calls` 为 0。
这不是代码修复质量或吞吐评测。输出目录已存在时拒绝重跑，保留原始结果。
演示启动的是普通 OS 进程，没有为它们建立容器或操作系统用户隔离；“未传数据库路径”
不等于同主机同用户的恶意程序无法扫描或访问数据库。
报告中服务进程的 `termination_requested: true` 表示演示结束后的主动清理；非零退出码
不单独等于控制场景失败。清理另外记录 `root_exited` 和 `descendants_verified`，不把根进程
已退出扩大成经过认证的全树/容器清理。

## 手动启动服务

服务配置示例，不包含实际凭据：

```json
{
  "path": "D:/KeelControl/control.sqlite",
  "scopes": {
    "tenant-a/campaign-1": {
      "max_tokens": 120000,
      "max_model_calls": 20,
      "lease_seconds": 900,
      "denied_tools": ["mcp__search__web_search"]
    }
  },
  "principals": [
    {
      "id": "worker-a",
      "token_env": "KEEL_CONTROL_A_TOKEN",
      "scope": "tenant-a/campaign-1",
      "task_id": "task-a",
      "tools": {
        "scout": ["list_files", "read_file", "read_page", "read_lines", "search_code", "recall"],
        "planner": ["list_files", "read_file", "read_page", "read_lines", "search_code", "recall"],
        "implementer": ["list_files", "read_file", "read_page", "read_lines", "search_code", "recall", "replace"]
      },
      "trusted_usage": false
    }
  ]
}
```

启动前在服务端安全设置 `KEEL_CONTROL_A_TOKEN`，要求至少 32 字符，无两端空白。
不同 principal 不能共用凭据。实际部署应使用随机凭据和秘密管理服务，保护服务配置文件。
示例路径需要操作者选用可写且受保护的目录，本模块不更改系统权限。

```powershell
python -m keel.control_service --config service.json --host 127.0.0.1 --port 8788 --max-seconds 300 --ready-file service-ready.json
```

只在 loopback 上允许明文 HTTP。非 loopback 监听需要 `--cert` 和 `--key` 启用 TLS；客户端
使用系统证书验证，不提供跳过验证选项。TLS 监听和请求均有超时，但本轮真实测试以本机
HTTP 为主，未完成跨节点证书、入口代理及公网安全检查。stdlib HTTP 服务不应直接当作
生产公网入口；连接限额之外，生产还需要鉴权审计、限流、证书轮换与平台安全措施。

## Worker 配置

把下面片段加入已有合法 Keel 任务配置；其他字段，如任务、验收和执行环境仍需提供：

```json
{
  "governance": {
    "endpoint": "http://127.0.0.1:8788",
    "token_env": "KEEL_WORKER_CONTROL_TOKEN",
    "task_id": "task-a",
    "timeout_seconds": 3
  }
}
```

在受信任 Worker 宿主中设置 `KEEL_WORKER_CONTROL_TOKEN` 为该 principal 的凭据。
不要给不可信代码沙箱挂载控制库或注入该凭据。客户端配置不接受 path、scope、额度或
工具授权字段；它们由服务端授予。服务端租约要大于任务墙钟预算。
启用的 Compass/MCP 工具也必须逐个加入服务授权，工具名字不能用模糊前缀自动放行。

## 幂等、失联和服务中断

- 每个 RPC 带唯一 operation_id；缓存键绑定 principal，参数哈希不一致时拒绝复用。
- 写入业务结果和缓存响应在同一事务中；存储失败会回滚，不发布虚假成功。
- 响应丢失后，客户端保留未确认操作并阻止新动作。`reconcile_pending()` 只核查同一个
  RPC，不自动重新执行模型调用、搜索或文件修改。
- 工具授权或额度申请的缓存响应在运行过期后不能重新授予执行权限。
- 服务重启后身份绑定、已提交操作和额度仍在；服务端周期性标记过期运行不可达，
  不释放未知消耗、不自动重新启动任务。
- 客户端不跟随重定向，不使用继承的代理转发控制凭据，单次请求有超时和大小限制。
- 服务端处理线程有上限，过载返回 503；这不是已测得的吞吐保证。

当前没有跨机器 Worker 的完整崩溃续跑接口，丢失客户端状态后需操作者结合服务器记录
核查。服务重启支持的是保留控制状态，不是自动恢复原工作区和外部副作用。

## 哪些记录可信

服务端能确定记录的内容包括：认证身份、授予的工具、原子预留、幂等响应和租约状态。
Worker 上报的源码修改、测试结果、阶段说明等统一标记为 `worker_observation`，带
`authority` 来源说明。Worker 的最终 verdict 也标为报告，不等于服务端独立验收。
Worker 不能通过通用事件接口伪造服务端 `model_intent` 等控制事件。

服务没有托管实际模型和工具执行，所以仍需 Worker 可信宿主配合。具有任意 shell、
网络或宿主文件权限的恶意业务程序，可能直接绕过协议；认证服务本身不等于防绕过沙箱。
后续需要受控工具/模型代理、独立凭据边界、出口策略和 Sidecar/节点监控一起验证。

## 已验证与未验证

`tests.test_control_service` 使用真实 HTTP、SQLite 和 OS 子进程，覆盖：

- 错误凭据、任务/运行越权、角色工具越权及客户端额度扩权拒绝；
- 两个进程争抢共享额度，实际子进程突然退出后的未知消耗保留；
- 响应丢失、原操作核查、参数冲突、事务失败回滚及服务重启；
- 服务不可用时阻止提供方调用，格式错误的来源标记；
- 普通用量报告不能退款，受信任用量需要显式授权；
- 真实本地 Explicit 验收，以及脚本模型的 Agent 路径接入远程治理。

脚本模型检验接口，不是提供方实测、修复收益或独立模型评测。还没有 Ray/Kubernetes
部署、容器级网络隔离验证、MySQL/Redis/S3/ES 接入、生产负载或 SLA 结论。

2026-11-15 本机验证：18 项服务相关检查，以及合并的 126 项相关回归检查通过（1 项跳过）。
真实三进程演示最新结果在 `.keel/remote-governance-live-v4/report.json`；未调用提供方。

后续的[真实双 Docker 隔离验证](docker-isolation-validation.md) 已提供有界运行入口，
当前执行环境因 Docker 管道权限未完成实际容器检查，不能与进程演示混为同一证据。
