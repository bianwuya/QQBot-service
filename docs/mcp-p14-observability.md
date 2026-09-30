# P14 运行观测 · 阶段报告

状态：实现与离线验证完成；无公网面板、无第三方上传，未重启生产。

## 变更

新增 `metrics.py`、`tools/report-metrics.py`、`tests/test_metrics.py`；修改Store任务边界、模型路由、persona统计、social统计、Broker和worker边界。计划见 `docs/mcp-p14-plan.md`。

metrics_daily为本地自然日聚合（指标名、受控维度、样本数、总量、最大值），不记录逐消息events。系统：接受消息/任务、完成/失败/中断/unknown；模型：生成尝试/失败/切换/平均耗时/探测；人格：角色使用、OOC、重试、兜底；主动：尝试、确认发送、回应、达到预算或暂停的每日群次数；工具：申请/执行、成功/失败/超时/需确认；worker：chat/file/media/tool实际处理和投递耗时。

模型请求口径是路由的一次生成尝试（工具对话内部多个HTTP回合不重复计算）；probe单独计数，同时计入模型请求。主动sent只在原deliver确认成功后计数，发送前的保守预算预占不当作成功；回应沿用P8的120秒规则。任务状态重复写入不重复计数，重复入站事件不增加消息数。

/状态保持config.admins授权，最长1350字，含uptime/今日量/队列/健康与会话路由/Persona分布/Social/Tools/worker平均耗时。WARN/CRITICAL识别unknown增长、模型熔断/高失败率、工具高失败率、media运行超过600秒；只标记，不额外群通知。

离线用法：

```text
.venv/Scripts/python.exe -X utf8 tools/report-metrics.py --days 1
.venv/Scripts/python.exe -X utf8 tools/report-metrics.py --days 7 --json
.venv/Scripts/python.exe -X utf8 tools/report-metrics.py --days 30 --json
```

脚本SQLite mode=ro，不创建Store、不触发崩溃恢复；旧库无指标表时返回空统计。聚合保留90天；工具审计30天；过期确认票据额外保留24小时；不删除RAG或用户记忆。需要长期归档可保存离线JSON输出。

## 隐私

指标不存scope、QQ号、消息/Prompt/回复/文件正文、工具参数、token或密码。模型/角色/工具维度为安装内HMAC指纹，worker维度为固定枚举；拒绝任意指标名/维度。角色显示名仅在管理员状态查询时按当前目录映射，离线报告保持指纹。指标写入异常只增加丢失计数，不失败业务、不重跑付费模型或投递。

## 验证

新增16项；原312 + 16 = **328项全部通过**；py_compile、git diff --check通过。测试覆盖各类埋点、消息去重、状态幂等、实际worker边界、跨日1/7/30天、权限/长度、敏感字符串和QQ号不入指标、80次并发聚合仍只有1行、只读报告不改变processing任务、旧库不迁移、指标故障不重试模型、告警与数据保留边界。

## 问题与取舍

- 避免用Store打开离线报告，否则会错误执行processing/sending恢复：专用只读连接并有回归测试。
- 为保证隐私不保存原始模型/角色/工具标签；离线聚合以稳定指纹定位，不是明文用户维度分析。
- 统计属于尽力观测，业务提交与指标提交分开；极端崩溃可能丢失最后一笔统计，不让统计可用性决定业务是否成功。
- 无真实运营样本，本轮验证只来自临时库与模拟网络；不会伪造今日生产数据。

下一步：所有计划阶段已顺序实现，进行最终全量回归与安全复核，逐阶段人工验收及main合并留待操作者。

## 最终复核补充

最终复核完成：加上跨阶段安全补丁后，全量337项通过，compileall和git diff --check通过，工程error/warning诊断为0。各阶段首轮统计保留为过程证据；最终交付状态与已知限制见 docs/mcp-p9-p14-delivery.md。
