# 双 Docker 沙箱隔离验证

这套程序实际调用 Docker，不把工具参数单元测试或进程演示当作沙箱通过。
它复用 `CommandRunner.docker_command/run`、`docker_health`、`atomic_json`、`ProgressLog`
及共享进程清理入口；不拉取镜像、不构建镜像、不改变 Docker/WSL/网络设置，不调用模型。

## 当前结果与启动命令

2026-11-15 当前执行会话连接 Docker Desktop 的管道被拒绝：

```text
permission denied while trying to connect to the docker API at
npipe:////./pipe/dockerDesktopLinuxEngine
```

最终尝试保存在 `.keel/docker-isolation-live-v2/latest.json` 指向的报告，状态是
`unavailable`，实际检查集合为空、容器启动数为零。它不说明 Docker Desktop 在操作者
终端中也不可用，也不能作为隔离能力通过的证据。

在能够执行 `docker info` 的终端中，从仓库目录运行：

```powershell
& .keel/harness-v3/Scripts/python.exe -m examples.validate_docker_isolation --output .keel/docker-isolation-live-v2 --max-seconds 240 --resume
```

`--resume` 保留之前的预检失败，建立新尝试。输入或实现哈希改变时拒绝沿用旧目录，
应另选输出目录。若完整验证已通过，resume 会校验报告与产物哈希，返回 `reused`，
明确表示历史证据复用，而非重新验证当前 Docker 环境。

默认只在最多八个本地镜像中探测可用 Linux Python，优先名称为 `python:` 的镜像。
不下载镜像；支持空 ENTRYPOINT 的镜像。可以显式指定已有镜像和容器中的解释器路径：

```powershell
python -m examples.validate_docker_isolation --output .keel/docker-isolation-custom-v1 --image YOUR_LOCAL_IMAGE --python /usr/local/bin/python --max-seconds 240
```

实际执行前记录不可变 image ID，后续用该 ID 创建容器。缺少合适镜像则报告不可用，
不使用本机 Python 替代容器。指定不同镜像/解释器时应使用新输出目录。

## 验证步骤

1. **真实预检**：读取 Docker 服务版本、确认本地镜像，再在受限容器中实际启动 Python。
2. **并发双容器探针**：分别挂载 A/B 的一次性工作区与报告目录；B 保持运行，A 尝试
   观察 B 的进程标识，同时检查文件、网络及权限边界。
3. **正常验收对照**：可信宿主通过远程治理服务，分别修改两个一次性工作区的版本常量，
   并行运行真实 Docker 后端验收。检查运行状态、Docker 执行记录、源码变更和零模型调用。
4. **超时清理**：在容器内先写入“已启动”标记，再等待；共享执行器超时后应删除对应容器。
   如果超时发生在程序实际启动前，不能认作已验证运行中进程清理。
5. **控制服务中断**：关闭控制服务后，新的模型预留必须失败，固定提供方替身不得被调用。

控制服务及治理凭据在可信宿主侧，不挂进不可信执行容器。报告中的 Worker 是可信 Keel
宿主，它调度代码执行沙箱；不是给任意业务进程提供广泛工具权限和控制密钥。

## 检查内容与证据强度

| 项目 | 实际检查 |
| --- | --- |
| 文件边界 | 仓库可读不可写、容器根目录不可写；临时目录和报告可写；另一工作区与控制库不挂载 |
| 凭据 | 主机合成的测试凭据名在容器环境中不存在，不读取或输出真实用户密钥 |
| 网络 | Docker inspect 为 network=none；只有 loopback 网卡；保留测试地址及宿主控制端口连接失败 |
| 权限 | 非 root、CapEff=0、NoNewPrivs=1；inspect 没有 privileged/额外 capabilities |
| 跨容器进程 | PID/网络命名空间不同；Signal 0 检查目标进程可寻址性，B 仍在运行，不发送破坏性信号 |
| 资源 | inspect 核对 CPU、内存、swap、PID 和 tmpfs 配置，不进行耗尽内存或 fork-bomb 压测 |
| 审计与验收 | 两个真实 Runtime 的结果、补丁与执行记录；服务端控制记录仍与 Worker 自报观察区分 |

不同 PID 命名空间可能有相同数字 PID，不能仅凭 `kill(pid,0)` 成功就声称能控制另一个
容器。探针还核对所指进程的命名空间，无法确认身份时不算通过。它没有验证全部内核
漏洞、任意系统调用逃逸、宿主进程安全或生产级多租户隔离。

单个探针必须报告全部预定检查项和布尔类型，缺字段、空字典或字符串 `"true"` 不会
因为 `all([])` 而通过。Docker inspect 使用字段投影，不把镜像/容器完整环境变量落盘。
额外 bind mount、命名卷、可写源码、host 网络/PID 模式或缺失额度会导致拒绝。

## 时间、恢复与清理

每次尝试默认有 240 秒，预留 20 秒清理。Docker CLI、解释器预检、容器就绪、Runtime
和超时探针分别受剩余时间约束，进度文件和心跳持续写入。两个活跃探针作为一个阶段
执行，不尝试复用已消失的进程状态；阶段失败保留已有记录，显式新尝试重新建立容器。
没有自动重试、重新安装或后台修改服务设置。

只清理本次创建、已记录名字的容器，不枚举删除其他任务。容器删除失败标为
`cleanup_unconfirmed`，不继续启动后续容器。未检查到的场景不填零分，也不算通过。

每次尝试拥有独立目录、报告和 JSON 产物哈希；`latest.json` 只更新入口，不覆盖旧报告。
已通过结果仅在实现/参数一致且所有证据哈希匹配时复用，修改证据会被拒绝。

## 本轮已完成的检查范围

相关 97 项回归检查运行通过（2 项跳过），其中新模块有 15 项检查，真实 Docker 一项
未配置镜像而跳过。其余检查使用明确的模拟 inspect/探针结果测试校验逻辑、结果保留、
历史复用和拒绝条件，不是实际容器运行。当前真实 Docker 预检仍不可用，后续必须由
可访问 Docker 的执行环境完成这套真实验证，不能据此宣布安全里程碑通过。
