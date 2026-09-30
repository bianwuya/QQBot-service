# P10 工具调用框架 · 阶段报告

状态：实现与离线验证完成。默认不启用真实模型工具协议，未调用真实网关付费接口。

## 变更与接口

新增 `tooling/{registry,schemas,broker,builtin,conversation}.py`、包初始化、`tests/test_tools.py`；修改 `app.py`、`protocol.py`。计划见 `docs/mcp-p10-plan.md`。

6个L0工具：get_time、get_bot_status、get_model_list、search_memory、search_knowledge、get_recent_files。状态/模型列表维持管理员限制，记忆与文件只返回本人当前范围，文件不暴露本机路径；知识继续经P9权限裁决。L1/L2/L3仅等级定义，本阶段没有对应执行入口。没有Shell、eval、动态import、任意路径/URL工具。

显式设置 `tool_calling_enabled: true` 且当前模型在 `tool_models` 白名单中，普通聊天才进入结构化 tool_calls；默认仍走原 chat，不依赖模型工具支持。主动聊天和关键词回复不启用工具。模型只能提请求，程序持有 actor/scope 和注册表，不能由模型选择Python handler。

Broker 严格schema（拒绝额外参数、类型/长度/整数范围错误）、权限/范围检查、每消息最多3次、相同工具失败不重试、每scope+actor每分钟最多10次执行预占。最多2个只读执行槽，超时调用返回timeout，未结束的槽继续占用防止堆积。超时线程不能强杀，因此本阶段仅只读工具；不将该机制当作可中止系统操作的沙箱。

新增 tool_audit：时间、scope、HMAC actor安全标识、注册工具名、risk、状态、耗时和错误码；不保存敏感参数、正文、token、密码或原异常字符串。started为pending，避免计作执行失败；速率只计started预占，避免开始/终态重复计数。

## 测试

新增15项；原256 + 15 = **271项全部通过**。compileall、git diff --check 通过。覆盖注册/重复注册、真实本地时间工具、未知/额外参数、管理员撤权、scope关闭与私聊owner不符、L3拒绝、次数/频率、超时槽上限、审计脱敏、handler异常、本人数据隔离、文件路径隐藏、结构化LLM模拟循环、旧路径兼容。未宣称已验证真实模型供应商tool_calls兼容。

## 中途处理与边界

- MCP首次新增目录下文件被边界校验拒绝，未发生部分写入；先在项目内创建 tooling 目录再按原补丁重试成功。
- 速率审计区分预占与终态，修正双倍计数；读取型管理员工具返回前再次检查撤权。
- 严格控制最低风险范围，没有为了未来应用控制预先放开高风险handler。
- 无生产配置或数据库修改；新增表在服务下次初始化时兼容创建。

下一步：按本轮授权进入 P11；保持默认关闭，验收和合并留待操作者。

## 最终复核补充

最终复核补充：发现文件分析与私聊共用分支可能意外带入工具上下文，现已明确把上传文件分析排除在工具模式外，并新增恶意文件请求工具的回归。最终全量337项通过，详见 docs/mcp-p9-p14-delivery.md。
