# 带诊断与自适应恢复的本地任务模板

配置文件：`examples/localized-recovery-task.example.json`。
这是当前接口的配置示例，不是已准备好依赖、可原样执行的任务。
全零镜像 ID 和模型名是明确占位符，不对应真实资源。

## 使用前需要替换

- `model.name`：Ollama 实际安装且适合此任务的模型名。
- 两处 `image`：本机已存在、包含目标项目依赖及 pytest 的 Linux 镜像完整 ID。
  使用 `docker image inspect YOUR_IMAGE --format '{{.Id}}'` 查询。
  诊断桥要求 `sha256:` 加 64 位十六进制的不可变镜像 ID。
- `acceptance.command[0]` 与 `diagnostic_execution.python`：对应镜像内真实 Python 绝对路径。
- `recovery.write_roots`：目标仓库中实际存在、被授权修改的源码目录。
- `goal`、测试文件及验收命令：按真实任务填写，包含空输入预期和正常行为回归。

目标仓库可以采用如下布局；并不要求 Keel 自身仓库也采用这个布局：

```text
target-repo/
  src/...
  tests/test_parser.py
```

镜像应已准备好项目依赖和适当的导入环境。运行时只读挂载仓库到
`/workspace`，禁网，不会自动 pip 安装、下载镜像或在失败时回退宿主。
JUnit 写入 `{junit}` 指定的独立报告挂载路径；测试若需要其他写入，
应使用容器允许的 `/tmp`。修改源码仍由宿主受控写入入口执行。

## 执行

在已安装 Keel 的 Python 环境、仓库根目录下运行，对可丢弃工作副本操作：

```powershell
python -m keel run examples/localized-recovery-task.example.json --repo D:\work\target-repo
```

`--repo` 是实际修改目标，配置文件所在目录不决定目标仓库。
Ollama 在宿主提供模型服务；Docker 配置负责验收和诊断子执行，
不表示整个 Keel 或 Ollama 都运行在容器内。

## 开启的能力及边界

- `localized-proposal`：模型定位后提交受控修改提案，不是普通 `agent` 工具循环。
- adaptive recovery：允许在授权目录内按失败反馈修复或重新定位。
- `diagnostic_execution`：有待执行诊断检查时使用 Docker 探针桥。
  不是每次工具调用或每次补丁前必定运行探针。
- `monitor_progress`：记录恢复轮次与后续证据，不独立证明假设成立。
- `preserve_repair_candidates`：保存和选择历史候选；不意味着无条件完整会话恢复。
- JUnit：记录测试身份与执行结果；验收强度仍取决于实际测试覆盖。

诊断上限 3 次模型调用不是额外配额，仍消耗总 20 次调用、100000 token
和 600 秒预算。资源与步骤上限可能导致未完成，模板不保证修复成功。
`max_output` 是每次输出上限，不能与任务累计 token 上限混为一谈。

模板显式关闭了另一条诊断 inspection gate、实验性定向源码评审/监督/
handoff、突变抽样、MCP 与 Compass 及长期经验检索。不同开关不是重复功能，
不应为了“完整”而全部开启。`diagnostic_handoff` 与 `diagnostic_execution`
尤其不是同一个字段。静态审计不依赖 `mutation_samples` 才生效。
如需操作经验库，应另提供真实、经审核的目录配置和哈希，不能用空目录冒充。

## 输入由谁生成

`keel/cli.py` 读取 JSON，调用 `keel/runtime.py:run`。当前基础 CLI 没有
“任意一句话自动转换全部安全配置”的入口。用户或可信应用提供任务与运行约束；
模型在约束内产生定位、计划、补丁或诊断等结构化输出。
SWE-bench 专用 runner 的 `config_for` 会用 task 文件与显式参数组装运行配置，
属于程序适配，不是让模型决定权限、预算或官方验收标准。

相关校验分散在 `keel/runtime.py`、`keel/recovery.py`、
`keel/diagnostic_execution.py`、`keel/execution.py`、`keel/models.py`
等模块；当前没有一个覆盖全部运行配置的单一 JSON Schema 文件。

本模板仅完成 JSON 与相关组件校验，未运行真实模型、Docker 或验收。
