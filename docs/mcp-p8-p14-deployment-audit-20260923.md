# P8～P14 未部署功能盘点（2026-09-23）

## 结论与口径

并非“构建了但完全没有测试”：`docs/mcp-p8-proactive-chat.md` 记载 P8 的 246 项离线测试通过；`docs/mcp-p9-p14-delivery.md` 记载 P9～P14 及安全复核后 337 项通过。本次在当前工作区用项目 `.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_*.py' -q` 实测 343 项通过（含后来新增的小杂鱼声线测试），`git diff --check` 退出码 0。上述均不能替代生产运行验收。

当前分支 `p9-p14-continuation`，工作区有约 16 个已跟踪文件修改及 48 个未跟踪文件；它们混合了 P8～P14 和最近的人设修改，并非一次只会加载一个阶段的独立发布包。`config.json` 中 `social`、`tool_calling_enabled`、`tool_models`、`app_control_enabled`、`model_pool`、`workers` 均未配置。只读检查生产库 `state/bot.sqlite3` 时，尚无 `job_dispatch`、`knowledge_sources`、`metrics_daily` 等新表，`social_enabled` 设置也无记录；`/healthz` 仍报告 QQBot、OneBot 与 QQ 在线。这与汇总报告的“未重启生产”一致，但不能仅凭缺表证明所有运行细节。此次盘点未重启服务、未启用功能、未发送 QQ 消息。

## 有什么功能，缺哪种测试

| 阶段 | 已写入工作区的能力 | 离线证据 | 尚未完成的生产验证 / 开关 |
|---|---|---|---|
| P8 主动聊天 | 群内话题插话、冷场找话、熟悉用户触发；限额、冷却、安全文本过滤 | `docs/mcp-p8-proactive-chat.md`：36 项新测试，合计 246 项通过 | 默认关闭；未在真实群开启、未做真实 QQ 主动发送/付费模型效果验收 |
| P9 知识库 | 管理员显式导入文件；按群、角色、common 隔离的 SQLite FTS5 检索 | `docs/mcp-p9-rag.md`：新增 10 项，合计 256 项 | 未导入真实资料，未验证真实资料的召回、来源质量和现场提示注入表现；启动会创建新表 |
| P10 工具协议 | 6 个只读工具、权限 Broker、调用次数/超时限制与审计 | `docs/mcp-p10-tools.md`：新增 15 项，合计 271 项 | 缺真实供应商模型的 `tool_calls` 兼容测试；需同时配置 `tool_calling_enabled=true` 和 `tool_models` 白名单，当前均未设 |
| P11 应用控制 | 白名单状态/启停/重启、管理员二次确认票据、固定脚本调用 | `docs/mcp-p11-app-control.md`：新增 13 项，合计 284 项；脚本仅 AST 解析 | 未真实执行 QQBot、NapCat、Sub2API 的启停/重启；默认关闭，示例配置未安装；高风险，必须单独授权验收 |
| P12 模型容灾 | 故障分类、备用模型路由、会话粘性、后台恢复探测 | `docs/mcp-p12-model-routing.md`：新增 13 项，合计 297 项；后续修复未知连接不重放 | 未配置真实备用模型池，未做真实网关付费切换/恢复探测；无 `model_pool` 时按原单模型路径 |
| P13 并发与单实例 | 默认 2 个 chat、1 个 file/media/tool worker；模型并发 2 槽，任务顺序、SQLite WAL 兼容与实例租约 | `docs/mcp-p13-workers.md`：新增 15 项，合计 312 项；临时库 + mock 网络 + 本机锁/端口验证 | **无需开关，重启就启用**。尚无真实媒体压力、生产数据库迁移及长任务/出站并发验收；`Store` 会回填 `job_dispatch`，启动会检查并恢复在途任务状态 |
| P14 观测 | 本机聚合指标、管理员 `/状态`、只读离线报表、保留周期 | `docs/mcp-p14-observability.md`：新增 16 项，合计 328 项；最终总回归 337 项 | **无需开关，重启就启用**。没有真实运营样本；启动会建 `metrics_daily` 并创建本地盐，需观察生产写入、查询与性能 |

此外，P7.1 人格阶段已有模型评测和一次服务重启记录（`docs/mcp-p7.1-persona-hardening.md`），但报告仍写“等待人工验收并合入 main”。本次小杂鱼声线重构另做了 6+3 条离线真实模型抽样、全套 343 项测试，尚未通过生产 QQ 聊天验收（`docs/mcp-xiaozayu-voice-rebuild.md`）。

## 重启风险与建议

标准 `tools/restart-service.ps1` 会强制停止匹配的 QQBot Python 进程、等待并重新启动，**不会只挑本次小杂鱼改动加载**。P8、P10、P11、P12 当前缺少开启配置，可继续保持关闭；P13 的 worker/Store 迁移及 P14 的指标初始化、P9 的建表则会随重启直接执行。生产当前没有 queued/processing/sending 任务，但这是检查时的瞬时状态；WebSocket 断线期间平台消息不保证重放。新表为增量迁移，报告未声称已在真实生产库演练或完成回滚试验。

建议先确认 P8～P14 整体发布范围，对现有 SQLite 做在线备份并保存原配置/代码快照，在低流量时复核在途任务为零，再按项目标准重启；随后确认 `/healthz`、OneBot/QQ 在线、旧会话与权限、任务出站和指标。真实 QQ 群主动消息、工具、应用控制、备用模型应逐项显式开启并在隔离环境验收，尤其不得把 P11 的真实启停当成普通冒烟测试。若只想上线人设，请先制作经过测试的隔离发布包，不能在当前混合工作区直接重启并声称“仅更新角色卡”。
