# QQBot-service · P9～P14 连续交付总报告

日期：2026-09-23（用户时区）

## 最终结论

**已按授权从 P9 连续推进至最后阶段 P14，完成源码实现、逐阶段报告、回归测试及最终安全复核。最终 337 项测试全部通过。**

这是代码与离线验证交付，不是生产部署声明：本轮未重启正在运行的 QQBot/NapCat/Sub2API，未真实发 QQ 消息，未启用真实群主动功能或应用控制，未做真实网关付费调用/恢复探测。生产进程尚未加载本轮新代码。未自动提交或合并 main。

项目：`F:/Apps/QQBot-service`

当前分支：`p9-p14-continuation`（基于原 `p8-proactive-chat` 工作状态；底层提交仍为 `e6af2de`，本轮变更留在工作区）。原有未提交修改、P8文件和用户的 `QQBot-P5-P14阶段任务书/bot_persona_guide.md` 均保留，未覆盖或删除。

## 逐阶段结果与报告索引

| 阶段 | 交付功能 | 该阶段完成时全量测试 | 报告 |
|---|---|---:|---|
| P9 | 明确文件导入、本机FTS5知识检索、namespace隔离、删除/重建 | 256通过（新增10） | `docs/mcp-p9-rag.md` |
| P10 | Tool Broker、严格schema/权限、6个L0工具、3次循环上限、审计与超时 | 271通过（新增15） | `docs/mcp-p10-tools.md` |
| P11 | 指定应用白名单、L2申请、120秒一次确认、标准自重启/适配器 | 284通过（新增13） | `docs/mcp-p11-app-control.md` |
| P12 | 模型状态机、熔断、scope+owner粘性、串行备用、低频恢复探测 | 297通过（新增13） | `docs/mcp-p12-model-routing.md` |
| P13 | Chat/File/Media/Tool隔离、顺序保障、SQLite忙重试、模型2槽 | 312通过（新增15） | `docs/mcp-p13-workers.md` |
| P14 | 私密日聚合、管理员状态、离线1/7/30天报表、状态告警 | 328通过（新增16） | `docs/mcp-p14-observability.md` |
| 最终复核 | 撤权竞态、未知连接不重放、服务单实例/端口预占、文件禁工具等 | **337通过（追加9）** | 本报告及各阶段“最终复核补充” |

P8基线246项，本轮共新增91项，合计337项。阶段报告中的早期累计数保留为执行过程证据，不表示最终少跑测试。每个阶段实现前的最小计划也已写入对应 `docs/mcp-p*-plan.md`。

## 主要新增文件

- 知识库：`knowledge.py`、`knowledge_commands.py`。
- 工具框架：`tooling/__init__.py`、`tooling/registry.py`、`tooling/schemas.py`、`tooling/broker.py`、`tooling/builtin.py`、`tooling/conversation.py`。
- 应用控制：`app_control.py`、`app_executor.py`、`tools/control-napcat.ps1`、`controlled-apps.example.json`。
- 模型容灾：`model_router.py`。
- 并发与单实例：`task_dispatch.py`、`sqlite_runtime.py`、`service_instance.py`。
- 观测：`metrics.py`、`tools/report-metrics.py`。
- 新测试：`tests/test_knowledge.py`、`tests/test_tools.py`、`tests/test_app_control.py`、`tests/test_model_router.py`、`tests/test_concurrency.py`、`tests/test_metrics.py`、`tests/test_service_instance.py`。

主要集成修改为 `app.py`、`protocol.py`、`store.py`、`social_engine.py`、`tests/test_social.py` 和 `README.md`。没有为本轮任务改动生产 `config.json`、网关账号/价格/调度、OneBot凭据、原标准自重启脚本、下载防护或文件加密实现。

## 中途发现并自行解决的问题

1. **群知识跨域风险**：群内导入只允许本群namespace；全局common/role资料必须由管理员私聊明确导入，角色声明只收窄权限。
2. **工具成本和失控线程**：每消息最多3次、同工具失败不重试、每scope+actor每分钟10次执行预占；超时未结束的只读线程继续占执行槽，防止无限堆积。
3. **高风险应用确认绕过**：模型无确认工具；票据绑定用户、scope、工具/参数、白名单hash，确认先消费再执行；变更、撤权、过期及重放均拒绝。
4. **重启准备期间撤权**：准备消息经会话锁投递并确认成功后，再核验权限/白名单；无有效回执或已撤权不启动脚本。
5. **不明确的模型连接失败**：普通连接中断可能发生在已付费之后，最终改为 `connection_unknown`，不自动重放；明确ConnectTimeout和网关错误按策略处理。所有响应流显式关闭。
6. **文件分析误用工具上下文**：共用私聊生成分支时发现该风险，现明确排除文件分析工具模式，新增恶意文件要求调用工具的回归。
7. **并发下媒体间接堵聊天**：chat投递屏障不等待被视频阻塞且尚未运行的另一用户queued聊天，仍保持已运行聊天的出站顺序。
8. **并发共享状态和出站**：群关系/mood短时原子更新，OneBot线程本地Session，每job多段消息不交错；主动输出在真正投递时再次核验开关。
9. **第二服务实例误做恢复**：新增进程租约，并在打开Store之前预占loopback健康端口；覆盖新实例竞争和旧版本服务仍占端口两种情况。使用临时端口真实验证健康HTTP交接，没有启动真实业务worker。
10. **观测影响在途任务**：离线报告禁止实例化Store，使用SQLite只读连接；指标写入失败不改变业务成功/失败，不触发付费重试。
11. **工具环境问题**：MCP首次新增目录被拒绝后先创建合法目录再重试；Bash未找到PowerShell时改用固定完整宿主路径完成仅语法解析，没有修改系统PATH或执行应用脚本。

## 最终验证证据

- 全量命令：`.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests`。
- 最终结果：`Ran 337 tests in 24.390s`，`OK`。
- 新增/修改Python模块与测试 `compileall` 通过。
- `git diff --check` 通过。
- MCP工程error/warning诊断：0条（不替代运行测试）。
- NapCat适配脚本PowerShell AST语法解析通过，未执行启停。
- 20个集成/运行模块的AST、`shell=True`、eval/exec及典型硬编码key模式检查通过；这只是静态辅助检查，不声称形式化安全证明。
- 可选应用示例配置校验：默认控制关闭，只含qqbot/napcat/sub2api。
- 六份阶段报告均已写入本机项目，LF结尾且无行末空格。
- 测试中的 `delivery_not_confirmed` / `social_attempt_failed` 日志来自预期失败注入，相关断言均通过。

## 安全默认与兼容性

- 新旧群主动聊天保持默认关闭；已有人为开启的设置不被重置。
- 没有 `tool_calling_enabled: true` 和对应 `tool_models` 白名单时，仍走原无工具模型协议。
- 应用控制默认关闭；`controlled-apps.example.json` 只是配置片段，**不能覆盖完整config.json**；实际变更始终需新的管理员确认票据。
- 没有 `model_pool` 时不自动切备用、不自动付费probe。
- 知识库空库不影响旧聊天。新增表增量创建，旧jobs结构、WAL、记忆、关系与文件信息保留。
- 并发和观测会在新代码重启后生效，但不开放任何额外外部权限。
- 不读取完整聊天历史进RAG，不将私聊混进群知识，指标无QQ号明文、scope、正文、Prompt/回复、文件内容或凭据。
- 崩溃仍是processing→interrupted、sending→unknown；不会自动重跑付费任务或未知投递。

## 已知限制与未执行事项

- RAG是本机词法检索，不是语义向量检索；近义召回有限。
- 工具协议已用模拟网关和真实本地L0工具验证，真实供应商的tool_calls支持仍需上线前检查。
- L0超时不能强杀Python线程，依靠有限槽与只读边界；外部脚本超时不等于撤销已开始的应用操作，按unknown处理。
- QQBot自重启、NapCat和Sub2API启停仅验证控制链/白名单/确认/异常语义，未对真实运行服务做破坏性演练。
- 同一用户的文件/媒体会等待其顺序；不同用户不受该队列顺序约束。模型并发维持2，不是无限并发。
- 聚合统计尽力写入；崩溃最后一笔可能缺失。默认90天聚合保留，可离线保存JSON归档。
- 单实例保护针对生产main入口；本机维护程序直接打开Store仍有其既有恢复语义，因此离线报告已特意改为只读，其他手工维护须谨慎。
- 没有部署重启、真实QQ收发、真实模型付费验收、生产数据库写入、自动Git提交或main合并。本轮不代替P7.1/P8及后续阶段的人工验收。

## 交接

使用与配置详见 `README.md` 的P9～P14章节。源码和报告已经保存在本地项目，可在人工验收后按既有流程备份、合并及重启；不用重做阶段实现。数据库备份应使用SQLite在线备份或停机后完整备份，不能只复制正在WAL写入的主文件。

**本轮连续开发工作已结束，未启动任何超出P14的阶段。**
