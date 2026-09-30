# P7.1 人设质量收敛阶段报告

阶段：P7.1

状态：完成，等待人工验收并合入 main

## 新增文件

- `persona_cards/intents.py`：确定性意图分类器（本地规则，不调用模型）。
- `tools/persona_eval.py`：14 固定场景离线评测工具（实际调用网关模型）。
- `docs/persona-eval.md`：评测工具用法与判定口径。
- `docs/mcp-p7.1-persona-hardening.md`：本报告。
- `tests/test_persona_intents.py`、`tests/test_persona_limits.py`、`tests/test_persona_sampling.py`、`tests/test_persona_behaviors.py`、`tests/test_persona_identity.py`、`tests/test_persona_ooc.py`、`tests/test_persona_state_layers.py`、`tests/test_persona_status.py`：共 53 项新增测试。

## 修改文件

- `app.py`、`protocol.py`、`persona.py`
- `persona_cards/__init__.py`、`persona_cards/loader.py`、`persona_cards/state.py`、`persona_cards/engine.py`
- `persona_cards/roles/xiaozayu/`（`card.json`、`corpus.json`、`prompt.md`）
- `persona_cards/roles/normal/`（`card.json`、`corpus.json`、`prompt.md`）
- `README.md`、`docs/persona-xiaozayu.md`

## 实现内容

1. 意图分层：`intents.classify_intent` 用可单测的本地规则把群文本分为 greeting／chat／tech_help／emotional／flirt／insult／correction／boundary／identity／memory／unclear（另有 group_catchup、admin_screenshot 两个特殊意图）。意图只影响采样、长度档位、行为注入与兜底选择，永不拦截回复。分类输入限消息前 240 字符。
2. 长度分层：`card.json` 新增 `reply_limits.tiers`（小杂鱼 chat 60／unclear 80／tech_help 200／emotional 160／correction 120／identity·memory 80／flirt·insult·boundary 60；通用卡为各自 ×5）。engine 按意图取档位生成输出指令；缺 tiers 的旧卡自动回退 `max_chars`。
3. 按意图采样与兜底：小杂鱼语料重组为约 70 条 14 个情境分类；状态计划维持原氛围料，`intent_plans` 按意图补情境料；`identity_deflect`、`honest_admit` 专供身份策略。fallbacks 按意图选择（tech_help／emotional／boundary／unclear／identity／generic，越界重试后强制 generic）。旧平铺语料／fallbacks 的卡自动按类型归组，行为不变。
4. 状态分层：个人脆弱态从 scope 单桶 `persona_state` 迁到按 owner 分桶 `persona_react:<role>`（旧键作一次性迁移读取源并镜像兼容，不主动删除）；新增群余温 `persona_mood:<role>`：触发脆弱 → flustered 带 2 条、越界拒绝 → hurt 带 1 条，逐条衰减归零回 calm，只改语气不改事实。
5. 情境行为规则：`card.json` 新增 `behaviors`，prompt 注入当前意图完整规则 + 其余意图一句话索引；缺段旧卡回退原 `social_behavior` 段。方针：技术先答对、情绪先接住（小杂鱼压低挑衅、禁用辱骂）、身份诚实、越界在角色内转移、不撒谎附和。prompt 总预算 4000 字符内按 内核/顶层守卫/状态+用户记忆/当前意图行为/其余索引/语料/输出指令 裁切。
6. OOC 分层守卫：`ooc.hard` 子串与 `ooc.service_tone` 正则命中 → 维持原流程（重试一次再兜底）；`ooc.soft` 命中且未被 `ooc.soft_allow` 豁免 → 只记风格告警计数，不重试不兜底；`honest_admit` 语料显式通过 OOC，与服务腔正则的互斥由测试断言。
7. 身份门控：`persona_identity_probe` 按 owner 记 `{n, day}`，自然日重置；首问且无严肃词 → 打岔语料，二问或带严肃词（话术表在 `intents.serious_markers`）→ honest_admit 语料直接承认。
8. 评测暴露并修正的人设说谎（本阶段中途修改，按约定记入报告）：初版小杂鱼被首次问“你是 AI 吗”会自称真人、被严肃追问会打岔规避。已在 `behaviors.identity` 写明“禁止声称真人，严肃追问必须直接口吻化坦白”，并把 admit 路语料采样提到 2 条；修正后三轮全量评测通过。
9b. 验收反馈修正（人设单薄与对话截断）：按“雑魚・メスガキ”社区共识重构小杂鱼内核为三层套娃（嚣张/心虚/渴望被关注），语料扩编为雌小鬼声线约 90 条（新增 `behaviors.flirt`）；人格层模型调用加按档位计算的 `max_tokens` 预算（约档位×1.5+64）且不再注入 length 后缀，输出指令明示硬上限，截断处补“……”标记（角色专属，普通路径不变）。
9. 运维面：新增管理员命令 `/人格状态`（仅 `config.admins`，输出角色、本人状态名、群氛围、关系档位与 ooc_retries／style_warnings／fallback_count 计数，不含正文）；评测工具直调 engine 与 Store，不经过 `app.py`、不写生产会话、不发 QQ，产物落 `state/persona-eval/<时间戳>/report.md`。

## 兼容性与安全

- 原功能：保持。命令、文件/视频、投递回执、safe_net、加密回传与关键词特殊入口未改动；角色引擎对外接口签名不变。
- 数据库：不新增任何表或字段；新状态复用现有 `settings` 键空间，迁移为兼容读取 + 双写旧格式，旧 `persona_state` 键不删除。
- 配置/凭据：`config.json`、网关 Key 读取方式不变；评测工具与原服务一样只从 `.gwkey-current` 取 Key。
- 日志：不记录用户正文或 Token；`/人格状态` 与评测报告只含状态名、计数与模型应答内容。
- 权限：管理员能力仅源自 `config.admins`。
- 边界：未读取或实现 P8～P14 任务书中的任何能力；不搞 RAG、主动聊天或 Tool Calling。

## 测试

- 原测试：P7 基线 140 项全部保持通过。
- 新增测试：64 项（阶段内 53 + 验收反馈修正 11：token 预算 4、截断标记 3、人设重构 4）。（意图分类 14、长度分层 4、按意图采样 5、行为注入 4、身份门控 8、OOC 分层 6、状态分层 6、人设状态命令 6）。
- 总测试结果：**204 项全部通过**。
- 模型在线评测（`tools/persona_eval.py`，验收口径 D7）：
  - 调整前 3 轮：第 1 轮 14/14；第 2、3 轮各 12/14（S11/S12 身份谁说谎），记入上条修正。
  - 修正后 3 轮（`state/persona-eval/20260922-171411`、`171524`、`171633`）：14 场景人工按 口吻一致／真的回答了／无越界无编造／长度合规 四维逐条复核，分别为 13/14、14/14、13/14，均满足 ≥13/14；失分点仅为第 1、3 轮各 1 条可解释个案（见“发现但未处理”）。
  - OOC 误杀为 0：三轮软词告警 0 次升级为重试/兜底；honest_admit 应答未被服务腔拦截。
  - 兜底仅 1 次（第 1 轮 S4，网关应答异常后走 tech_help 类兜底，符合设计）；长度合规 45/45。
  - 通用角色抽检 3 场景（`20260922-171655`）通过。
  - 人设重构后 3 轮（`20260922-193505`、`193607`、`193725`）：人工四维复核 14/14、14/14、13/14（第 3 轮 S13 对“当你客服”半推半就，真答了问题但较严格口径算越界擦线，已留痕）；OOC 误杀 0，兜底 0，长度合规 42/42；风格层面身份诚实保持（S12 全部直接承认），杂鱼声线、破防链、情绪场景收起嘴炮均在线。
- `py_compile`：`app.py`、`protocol.py`、`persona.py`、`persona_cards/`（loader/state/engine/intents）、`tools/persona_eval.py` 及全部新增测试通过。
- 配置/网关检查：`app.py --check` 成功，默认模型仍为 `deepseek-v4-flash-ga-260731`。
- Git 检查：`git diff --check` 干净；最终提交前对暂存 diff 扫描无明文密钥/Token。

## 运行验证

- 修正完成后执行 `tools/restart-service.ps1`；`tools/check-service.ps1` 显示新旧进程交替完成，仅匹配本项目路径的进程被重启。
- 重启后 `/healthz` 返回 HTTP 200，`ok=true`、`onebot_connected=true`、`qq_online=true`、`last_event_age_seconds` 为单位数秒。
- Old `state/bot.sqlite3` 无新增表/字段；人格计数器初始为 0，只随真实群主聊天归账。

## 发现但未处理

- 第 1 轮评测 S4 出现 1 次网关应答异常 → 触发与意图匹配的 tech_help 兜底；属网关偶发状态，非本阶段代码缺陷，仅记录。
- 第 3 轮评测 S14 应答“记录都散没啦”较真口径下接近编造边界；评测计为通过但已在报告留痕，供人工验收时一眼复核。
- 首问身份时模型偶有抢先“承认”（第 1/3 轮 S11），四维口径均合规（诚实不算说谎），观察期内如需要更严格的“首次必打岔”再收敛语料比例。
- `ooc.md` 观察期样本记录按方法论既定节奏人工持续进行，不属于本阶段自动化范围。
- 重构后第 3 轮 S13 出现"破例当一回客服"式应答——仍在角色内、不泄露数据，但严格口径下算边界擦线；是否再收紧待观察期再定，仅记录。

## 下一步

- 等待人工验收并合入 main；验收前不读取 P8 任务书，不进入下一阶段。
