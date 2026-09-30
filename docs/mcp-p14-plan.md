# P14 运行观测计划

新增 metrics.py、tools/report-metrics.py、tests/test_metrics.py；在Store任务状态、模型路由、人格、主动聊天、Broker和worker边界加入聚合埋点。metrics_daily按本地日/固定指标名/受控维度聚合，不记录逐消息明细；模型/角色/工具标识使用HMAC指纹，worker类型为固定枚举，不存QQ号/scope/正文/Prompt/响应/参数/凭据。统计故障不得引起付费任务重试或投递失败。

/状态保持指定管理员权限并控制长度，显示uptime、今日量、队列、模型健康/切换、Persona、Social、Tools和worker平均耗时。离线脚本支持1/7/30天文本/JSON，必须只读SQLite，不能创建Store以免执行崩溃恢复。WARN/CRITICAL只识别不通知，不增加公网metrics接口；90天聚合保留，工具审计30天、过期确认票据有限保留，不碰RAG/记忆源数据。
