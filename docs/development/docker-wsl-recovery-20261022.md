# Docker / WSL 启动故障复盘（2026-10-22）

## 结果与证据边界

用户最终反馈 Docker 已恢复。最强的前后验证是：同一管理员终端手动附加
`docker_data.vhdx` 时拒绝访问；只新增该用户对该文件的 `WDAC` 后，附加和
卸载均成功；随后完整退出 Docker 后台、关闭 WSL、重新启动 Desktop，用户
确认恢复。没有删除 VHDX、恢复出厂设置或重装。尚未重新执行 Keel 任务。

## 分别发生了什么

| 现象 | 证据与判断 | 处理及验证 |
| --- | --- | --- |
| 无法保存 daemon.json / windows-daemon.json 临时文件 | 用户 `.docker` 目录普通用户只有读取/执行权限，配置文件无 ReadOnly 属性 | 建议给本机 Admin 用户该目录的 Modify；后续启动进入更后阶段，但没有单独的即时写入验证收据 |
| StorageVSP 事件 8，状态 0xC000012D | STATUS_COMMITMENT_LIMIT，说明当时系统内存提交额度不足；C 盘当时仅余 0.62 GiB | 用户清理后报告 8.9 GB；后续实测约 9.86 GiB。低空间可能影响分页文件增长，但并未证明它造成后来的挂载拒绝；没有证据表明用户实际更改了分页文件 |
| vpnkit bad magic，文本中包含“将磁盘…附加” | 不是足以确诊网络故障的证据；握手读到了挂载错误文本 | 获取完整 WSL 和 backend 日志，定位到 VHDX 附加被拒绝 |
| WSL E_ACCESSDENIED；bootstrap 找不到指定 WWID 数据盘 | 数据文件仍存在，约 70.1 GiB；backend 显示 AttachDisk/MountVhd/HCS/E_ACCESSDENIED | 独立 bare attach 同样失败，故问题不局限于 Docker bootstrap；disk not found 是附加失败的下游表现 |
| 普通可写权限看似正常，仍挂载失败 | Procmon：wslservice.exe CreateFile，ACCESS DENIED，模拟 Admin，Desired Access 包含 Write DAC；已有 Modify 不包含修改 DACL 权限 | 备份 ACL，针对该文件/该用户补 WDAC；同终端立即验证附加、卸载成功 |
| 权限修复后 Desktop 仍转圈 | backend 仍为 01:19 启动的旧进程；重新打开的 GUI 是新进程，后台未重启，持续等 socket、返回503 | 从托盘完整 Quit，执行 wsl --shutdown，再启动 Desktop；用户反馈恢复 |

尚不知道原目录/文件权限为何变成这样；不能把所有故障归为同一个原因。
没有证据证明 VHDX 文件系统损坏、物理磁盘损坏或安全软件实施拦截。

## 本机实际使用的关键操作

以下路径和账户仅属于本次机器，不是通用自动执行配方。权限变更需要管理员
终端，先确认对象、主体和缺失权限。不要递归扩权或授权 Everyone。

配置目录写权限的建议命令：

```powershell
icacls 'C:\Users\Admin\.docker' /grant 'Admin:(OI)(CI)M'
```

本轮已保存的原数据盘 ACL：
`.keel/docker-data-acl-before-wdac-20261022-013555.xml`。
Procmon 证实缺少 Write DAC 后，仅补充这一项：

```powershell
icacls "D:\Docker\WSL\disk\docker_data.vhdx" /grant "LAPTOP-70IONR1U\Admin:(WDAC)"
```

Docker 完全退出、其他 WSL 工作保存后，在管理员终端验证：

```powershell
wsl --shutdown
wsl --mount --bare --vhd "D:\Docker\WSL\disk\docker_data.vhdx"
```

仅在附加成功后执行定点卸载：

```powershell
wsl --unmount "D:\Docker\WSL\disk\docker_data.vhdx"
```

然后正常启动 Docker Desktop，用 `docker info` 的 Server 信息检查引擎。
bare attach 只附加块设备，不执行文件系统挂载、格式化或 fsck。

## 哪些排查没有直接解决问题

- Compute-Admin 只有旧的服务启动成功记录，不能证明当前服务健康。
- VmSwitch 285 网络统计警告，没有证据解释磁盘挂载失败。
- 单纯释放空间没有消除这次 AttachDisk 拒绝访问。
- 在管理员终端运行也未绕过服务模拟用户时所缺的文件权限。
- 关闭/重新打开主窗口不等于重启 backend。
- componentsVersion.json 缺失只是本次日志中的警告，未证实为致命原因。

有效转折是 Procmon 在失败时记录的实际进程、模拟身份与 Desired Access，
而不是继续根据“Access denied”猜测或泛化授予完全控制。

## 对 Keel 的教训

此前 bounded-30min-v1 消耗 60 次模型调用、333,032 Token、100 次工具调用。
六轮新验收第一次超时，后五轮 Docker 503；没有得到新测试结果，却继续代码
修复，最终耗尽调用预算。保留全部旧轨迹，不把它算作代码修复质量下降或新
测试失败，更不能声称这次环境恢复是 Keel 自主完成的。

后续应实现：运行前健康检查；运行中将 infrastructure failure 与 test failure
分流；环境不可用时冻结代码候选，有限检查/恢复后重验同一版本，不能从历史
失败推断当前测试结论。权限或主机安全策略变更应明确范围与执行主体。
这是下一步工程目标，文档记录并不等于运行时已具备自动恢复能力。

可复用的防回归检查应涵盖：Docker 503 不进入改码循环、暂时故障恢复后复用
同一候选、持续不可用明确结束为环境阻塞、所有等待遵守总时限并留下轨迹。
这些新检查尚未在本轮实现；本轮为实机排障复盘，没有新增付费模型调用。

参考：
[Windows 文件权限](https://learn.microsoft.com/en-us/dotnet/api/system.security.accesscontrol.filesystemrights)、
[WSL 磁盘附加](https://learn.microsoft.com/en-us/windows/wsl/wsl2-mount-disk)、
[Windows 分页文件与内存提交](https://learn.microsoft.com/en-us/troubleshoot/windows-client/performance/introduction-to-the-page-file)、
[Process Monitor](https://learn.microsoft.com/en-us/sysinternals/downloads/procmon)。
