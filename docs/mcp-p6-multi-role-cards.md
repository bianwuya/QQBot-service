# P6 多角色卡阶段报告

阶段：P6

状态：完成，等待人工验收并合入 main

## 新增文件

- `persona_cards/__init__.py`
- `persona_cards/loader.py`
- `persona_cards/engine.py`
- `persona_cards/state.py`
- `persona_cards/roles/xiaozayu/card.json`
- `persona_cards/roles/xiaozayu/prompt.md`
- `persona_cards/roles/xiaozayu/corpus.json`
- `persona_cards/roles/normal/card.json`
- `persona_cards/roles/normal/prompt.md`
- `persona_cards/roles/normal/corpus.json`
- `tests/test_persona_roles.py`
- `docs/mcp-p6-multi-role-cards.md`

## 修改文件

- `persona.py`
- `app.py`
- `protocol.py`
- `README.md`
- `docs/architecture.md`
- `docs/persona-xiaozayu.md`

## 实现内容

1. 将小杂鱼的身份、内核、表层、边界、状态、触发器、关系规则、回复限制、Prompt 与 43 条语料迁移为正式角色卡文件。
2. 新增 `normal` 普通助手机制验证卡；两张卡都经过统一结构校验。
3. 加载器逐卡隔离 JSON、字段、Prompt 或语料损坏；单卡损坏不阻止其他角色和服务启动，没有有效卡时使用最小安全角色。
4. 新增角色无关的 Prompt 构建、触发器、关系更新、语料 LRU、OOC、fallback 和回复长度引擎。
5. `persona.py` 改为薄兼容门面，旧 `CORPUS`、`FALLBACKS`、`FR_ROUNDS` 和三参数 `build_prompt` 继续可用，现有验收脚本无需同步重写。
6. 新增管理员命令 `/角色`、`/角色列表`、`/角色 <id|名称>`、`/角色 默认`；命令名进入内置冲突保护，普通用户不能更改角色。
7. 角色选择层级为群覆盖 > 全局默认 > 内置默认；私聊使用全局默认。选择保存在现有 `settings.persona_role`，未增加数据库表或字段。
8. 小杂鱼继续使用旧 `persona_state`/`persona_used` 键；其他角色使用带 role id 的独立键，群与群之间的状态继续按 scope 隔离。
9. P5 Reply Pipeline、persona 单次 OOC 重试和原 fallback 语义保持不变，但回复上限改由角色卡提供。

## 兼容性

- 原功能：保持。原小杂鱼核心、3 轮脆弱态、43 条语料、20 条 LRU、OOC、fallback 和 relations 行为均通过旧测试。
- 数据库：兼容。只新增可选 settings key；旧库没有 `persona_role` 时自动使用小杂鱼。
- 配置：兼容。`config.json` 无需修改。
- 权限：保持 `config.admins` 为唯一管理权限来源；群主/群管理员没有角色切换权限。
- 安全：角色卡只定义 Prompt 和本地纯数据，没有给模型增加工具、文件系统或命令权限。
- 后续阶段：未读取或实现 P7～P14 的需求。

## 测试

- P5 基线：106 项全部通过。
- P6 新增：16 项。
- 总测试结果：122 项全部通过，耗时 3.903 秒。
- `py_compile`：`app.py`、`protocol.py`、`persona.py`、`persona_cards/*.py` 与新增测试通过。
- 配置/网关检查：`app.py --check` 成功，默认模型仍为 `deepseek-v4-flash-ga-260731`。
- Git diff 检查：通过。
- VS Code 诊断：0 个 error/warning。
- 运行验证：服务标准重启成功；`/healthz` 返回 HTTP 200，`onebot_connected=true`、`qq_online=true`。

## 发现但未处理

- 未开放普通用户的私聊个人角色覆盖；P6 任务书允许本阶段只保证群角色与全局默认，私聊使用默认角色。

## 下一步

- 等待人工验收并合入 main。
