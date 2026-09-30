# P11 指定应用控制计划

新增 app_control.py、app_executor.py、tools/control-napcat.ps1、controlled-apps.example.json 与测试；修改 Tool Broker/注册表/内置工具及 app.py/protocol.py。默认 app_control_enabled=false、controlled_apps 空，不改生产配置，不执行真实启停。

模型只接触 app_id/action 的语义化 schema，实际脚本来自本机手工白名单。status 为管理员L0；start/stop/restart 为L2申请，所有变更一律返回短时确认票据，模型无确认工具。只有同一管理员在同一会话发送 /应用 确认 <id> 才执行；票据一次消费、绑定工具/参数/白名单版本、过期拒绝。实际执行也经Broker审核并写审计。

QQBot自重启复用 tools/restart-service.ps1，审计和“准备重启”确认投递成功后才分离启动，不另写重启逻辑。NapCat适配脚本仅匹配项目的node.exe。Sub2API仅引用既有native脚本，保留蓝绿轮换语义，不运行它们。已发现网关重启可能等待3700秒排空，因此采用有限超时并将超时标记unknown，不声称超时意味着撤销/成功。所有动作默认仅私聊管理员，群需本机显式allowlist。
