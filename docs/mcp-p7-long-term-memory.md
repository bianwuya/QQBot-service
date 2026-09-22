# P7 长期记忆阶段报告

阶段：P7

状态：完成，等待人工验收并合入 main

## 新增文件

- `long_memory.py`
- `tests/test_long_memory.py`
- `docs/mcp-p7-long-term-memory.md`

## 修改文件

- `store.py`
- `app.py`
- `protocol.py`
- `README.md`
- `docs/architecture.md`

## 实现内容

1. 新增 `user_profiles`、`user_profile_days`、`user_memories` 和 `memory_candidates`，由 `Store` 启动时以 `CREATE TABLE IF NOT EXISTS` 兼容迁移旧 SQLite/WAL 数据库。
2. 门槛严格为同一 `scope + owner` 有效普通聊天 `>=10` 轮且活跃自然日 `>=3`；未满足时只跟踪计数，不提取、不保存长期记忆。
3. 有效轮只在普通聊天成功生成、所有出站元素都收到成功回执后记录。命令、自定义命令、关键词人格回复、文件/视频任务、准入丢弃和发送失败均不计。
4. `MemoryChatOutput` 是仅存在于进程内的普通聊天标记；完整 outbox 持久化时不会写入额外用户正文，管理员 `/重发` 也不会重复增加互动轮数。
5. 第一版使用本地保守规则提取 `fact`、`preference`、`project`、`event` 四类短候选，不额外调用模型；不会回填启用前的 history。
6. 候选写库前校验类型、单行长度、置信度及密码、Token、账号、密钥等敏感模式；`memory_candidates` 和 `user_memories` 只保存结构化摘要，不保存完整聊天正文。
7. 完全相同或同类型近似记忆合并更新，保留 `updated_at`；候选记录程序合并结果，模型没有数据库写权限。
8. Prompt 只为已启用用户检索当前问题相关的记忆，基于关键词、类型和更新时间选择，最多注入 4 条；注入区明确标记为不可信背景资料且当前消息优先，并更新 `last_used_at`。
9. `relations` 保持不变：它继续表达 Bot 与用户的关系状态；长期记忆只表达用户事实、偏好、项目和事件。
10. 新增管理员命令 `/记忆 状态` 和 `/记忆 查看 <用户QQ号>`，只允许 `config.admins`，并限制在当前 scope 查询。

## 兼容性与安全

- 原功能：保持。P5 Reply Pipeline、P6 角色卡、关键词人格、命令、文件/视频和投递回执语义未改。
- 数据库：只增表和索引，不修改旧表；旧 settings/history/jobs 数据保持可读。
- 隔离：档案、候选和记忆均以 `scope + owner` 查询，不跨群或私聊串用。
- 崩溃/重发：成功发送后、job 完成前记录互动；发送不确定或失败不记录，人工重发输出不带有效轮标记。
- 日志：记忆失败日志只记录 job id 或固定事件名，不记录用户正文、QQ号或候选内容。
- 安全：无 RAG、主动聊天、Tool Calling、全量聊天日志或模型直接写库；未读取或实现 P8～P14。

## 测试

- P6 基线：122 项全部通过。
- P7 新增：16 项。
- 总测试结果：138 项全部通过，最终耗时 6.009 秒。
- 覆盖 9 轮、10 轮/2 天、10 轮/3 天、命令/关键词/文件排除、发送失败、候选校验、敏感模式、去重更新、完整正文禁止、Prompt 上限、旧库迁移、管理员权限和用户隔离。
- `py_compile`：`app.py`、`protocol.py`、`store.py`、`long_memory.py` 与新增测试通过。
- 配置/网关检查：`app.py --check` 成功，默认模型仍为 `deepseek-v4-flash-ga-260731`。
- Git diff 检查：通过。
- VS Code 诊断：0 个 error/warning。

## 运行验证

- 标准服务重启前使用 SQLite backup API 创建 `state/pre-p7-bot.sqlite3.bak`；备份中没有 P7 表。
- 重启后生产数据库自动出现 4 张 P7 表，初始 `user_profiles` 数量为 0，证明没有回填旧聊天。
- `/healthz` 返回 HTTP 200，`onebot_connected=true`、`qq_online=true`。

## 下一步

- 等待人工验收并合入 main；验收前不读取 P8 任务书。
