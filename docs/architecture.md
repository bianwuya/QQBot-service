# QQBot-service 构造文档

> 面向改造者的完整架构说明。版本：2026-09-22（含七层人格系统与自定义命令系统）。
> 部署位置：Windows `F:\Apps\QQBot-service`（本机镜像 `/home/user/qqbot_new`）。

---

## 1. 系统总览

一个跑在 Windows 本机、通过 QQ 提供"聊天 + 文件分析 + 视频解析"的机器人。无公网入口，全部依赖本机回环服务。

```
QQ 服务器
   │  (QQ 账号登录态)
NapCat.Onebot 4.18.28            ← 协议端，独立 Node 进程
   │  OneBot v11：HTTP :3000 / 正向WS :3001（token 鉴权）
app.py（QQBot 主服务）            ← :3002 健康端点 /healthz
   ├──▶ Sub2API 网关 :7866        ← 本机共享模型网关（多账号池，只读使用）
   ├──▶ yt-dlp + FFmpeg 9.0.2     ← 视频下载/转码子进程
   └──▶ state/bot.sqlite3         ← 全部持久化（WAL 模式）
```

**设计基调**：单文件队列消费（防并发写坏状态）、出站全部走 SQLite 回执核对、网络下载全部经 `safe_net` 守卫、模型无工具权限。

---

## 2. 模块清单

| 文件 | 职责 | 关键导出 |
|---|---|---|
| `app.py` | 主服务：事件入队、任务处理、命令分发、出站投递、健康端点 | `Bot`、`load_config`、`SYSTEM`、`HELP` |
| `protocol.py` | OneBot/LLM 客户端、事件归一化、命令解析、能力与关键词判定 | `OneBot`、`LLM`、`normalize`、`should_handle`、`command`、`cap`、`custom_commands`、`group_keywords`、`forward_batches`、`BUILTIN_COMMANDS`、`ADMIN_COMMANDS` |
| `store.py` | SQLite 持久层（6 张表 + 崩溃恢复） | `Store`、`Busy` |
| `persona.py` | 角色卡体系的薄兼容门面，保留旧 import/API | `roles`、`role_for`、`build_prompt`、`CORPUS`、`FALLBACKS` |
| `persona_cards/` | 角色卡校验加载、通用 Prompt 引擎、状态隔离与角色数据 | `RoleCard`、`load_catalog`、`build_prompt`、`resolve_role` |
| `reply_pipeline.py` | 模型回复的上下文分类、保护式格式清洗、重复/AI 腔检测、长度约束与重试判定 | `process_reply`、`clean_reply`、`validate_reply`、`ReplyResult` |
| `media.py` | 视频解析：平台识别、yt-dlp 主路径、抖音分享页后备通路 | `get_video`、`platform_of`、`share_urls`、`run_bounded` |
| `documents.py` | 文档抽取（文本/PDF/Word/Excel/PPT）+ AES-256 加密 ZIP | `extract`、`encrypted_archive` |
| `safe_net.py` | 网络守卫：DNS 固定、公网 IP 校验、大小/时长限制下载 | `download`、`open_public`、`public_target`、`safe_name`、`Rejected` |
| `guest_cookies.py` | 抖音匿名游客凭证（ttwid + s_v_web_id，不读浏览器登录态） | `douyin_cookie_header`、`write_netscape_cookiefile` |
| `process_limits.py` | 子进程资源约束 | `attach_job`（内存上限 768MB） |
| `tools/` | 运维脚本：`restart-service.ps1`（标准重启）、`check-service.ps1`、`live-private-acceptance.py`（授权出站测试）、`persona-acceptance.py`（人格真实模型验收） |

---

## 3. 消息生命周期（入站 → 出站）

```
OneBot WS 事件
  └─ Bot.ingest(raw)
       ├─ meta_event → 更新在线状态，丢弃
       ├─ normalize() → 统一事件 {scope, owner, text, files, videos, at, role...}
       │     scope = 'g:<群号>' 或 'p:<QQ号>'
       ├─ 长度/自身份校验
       ├─ should_handle(e, cfg, store)   ← 全部准入策略集中在这里（见 §4）
       └─ store.accept(e, limits)        ← 排队限流，写 jobs 表，返回 job id
Bot 工作线程 store.take()
  └─ Bot.process(e, ident)
       ├─ active() 会话总开关（/停用 /启用）
       ├─ do_command()                    ← /开头命令分发（见 §5）
       ├─ 自定义命令匹配（固定文本原样返回；gen 模型文本走 Reply Pipeline）
       ├─ 文件/视频能力开关过滤
       ├─ keyword_reply()                 ← 解析群角色/全局默认 → 角色 Prompt → Reply Pipeline
       └─ 普通聊天：群聊解析角色卡（私聊用通用 SYSTEM）+ reply_style + 至多4条相关长期记忆 → Reply Pipeline → history
出站：每条回复元素 → OneBot 发送 → 回执写 delivery 表
  ├─ 文本 >1400 字 → forward_batches 合并转发（1200字/节点，30节点/批）
  ├─ 文件 → AES-256 ZIP，密码入文件名
  └─ 视频 → 原生视频消息
全部回执 sent 后：普通聊天才计有效互动/提取结构化记忆 → job 置 done；任何一环失败可 /重发 <jobid>
```

**崩溃恢复**（`Store.__init__`）：启动时把 `processing` 的 job 置 `interrupted`、`sending` 的置 `unknown`——不重跑已付费的模型调用，不重发不确定的投递，管理员可人工 `/重发`。

---

## 4. 准入策略（`protocol.should_handle`）

按序判定，任一不过即静默丢弃（不回任何话）：

1. 会话停用（`enabled=False`）且非管理员 → 丢
2. 管理员命令（`ADMIN_COMMANDS`）→ 管理员放行；普通文本走后续
3. 内置命令（`BUILTIN_COMMANDS`）→ 放行（群聊免@）
4. 自定义命令（`custom_commands` 命中）→ 放行（群聊免@，不受聊天开关限制）
5. 关键词冷却中（`kw_cooldown_until`）→ 丢
6. 关键词命中（全局词表 + 群词表合并，包含即触发）且关键词能力开 → 放行（免@）
7. 聊天能力关 + 纯文本 → **丢（彻底静默）**
8. 群聊纯文本未@ → 丢；有@或私聊或带文件/视频 → 放行

**能力开关**（`cap()`，settings 键 `cap:chat|files|videos|keywords`，默认全开）：
`/能力` 查看、`/开 名称`、`/关 名称`，仅管理员，按 scope 生效。

---

## 5. 命令系统

**内置命令**（`BUILTIN_COMMANDS`）：
`/帮助 /重置 /下载 /打包 /导出 /模型 /模型列表 /默认模型 /角色 /角色列表 /记忆 /状态 /重发 /启用 /停用 /群触发 /能力 /开 /关 /关键词 /风格 /指令`

**管理员命令**（`ADMIN_COMMANDS`，仅配置文件中 admins，群主/群管理员不提权）：
模型、角色与长期记忆调试、`/启用 /停用 /群触发 /状态 /重发 /管理员 /配置 /任务 /执行 /能力 /开 /关 /关键词 /风格 /指令`

**角色命令**：`/角色` 查看当前角色，`/角色列表` 列出有效卡；群聊 `/角色 <id|名称>` 写本群 `persona_role`，私聊管理员执行时写全局 `*`；群聊 `/角色 默认` 删除覆盖并回落全局默认。损坏卡会被加载器隔离，不影响其他有效角色和 Bot 启动。

**长期记忆命令**：`/记忆 状态` 查看当前 scope 的档案/启用/记忆/候选数量；`/记忆 查看 <用户QQ号>` 只查询当前 scope 下该用户，最多显示 20 条有效记忆。两者均仅允许配置文件中的 Bot 管理员。

**自定义命令**（管理员创建，settings 键 `custom_commands`，按 scope）：
- 结构：`{"/命令名": {"mode": "text"|"gen", "content": ...}}`，每会话 ≤20 条
- 名字约束：`^/[A-Za-z0-9\u4e00-\u9fff_]{1,9}`，不得与内置命令重名，内容 ≤300 字
- `text` 模式秒回固定文案；`gen` 模式用独立 `CUSTOM_PROMPT` 调模型（素材不可覆盖安全规则），失败回落提示
- 优先级：内置命令 > 自定义命令 > 关键词 > 普通聊天

**回复风格**（管理员，`/风格 <描述>` 覆盖式，≤200 字）：
存 settings 键 `reply_style`（按 scope）；群普通聊天作为不能覆盖角色/安全边界的补充写入角色 Prompt，私聊写入通用 SYSTEM，`/风格 默认` 清除。

**群关键词**（管理员）：群里 `/关键词 添加|删除` 作用于本群 `keywords_extra`（≤30，与全局 16 词合并）；私聊维护全局 `keywords`（`*` scope）。

---

## 6. 存储模型（`state/bot.sqlite3`，WAL）

| 表 | 用途 |
|---|---|
| `jobs` | 任务：id/事件去重键/scope/owner/payload/状态/输出 |
| `delivery` | 出站回执（job, idx）→ status/receipt |
| `settings` | KV 配置（scope, key, value JSON），全部会话级状态都在这 |
| `history` | 对话上下文（scope+owner 隔离，普通聊天才写；关键词回复不写） |
| `files` | 每会话最近上传/下载文件（供 /打包 /导出） |
| `upload_claims` | 上传去重认领 |
| `user_profiles` / `user_profile_days` | 按 scope+owner 记录有效互动轮数、活跃自然日和是否达到长期记忆门槛 |
| `memory_candidates` | 经程序校验的结构化候选；不保存完整原始对话 |
| `user_memories` | `fact/preference/project/event` 四类长期记忆、置信度、更新时间、使用时间和状态 |

**settings 键清单**（按 scope）：
`cap:*`（能力开关）、`enabled`（总开关）、`model`（会话模型）、`default_model`（`*`）、
`keywords`（`*` 全局词表）、`keywords_extra`（群词表）、`kw_cooldown_until`、
`reply_style`、`custom_commands`、
`persona_role`（群覆盖或 `*` 全局默认）、`persona_state`、`persona_used`、`persona_state:<role>`、`persona_used:<role>`、`relations`（角色系统，见 §7）

---

## 7. 多角色卡与七层人格系统

实现位于 `persona_cards/`；`persona.py` 仅保留旧 API 兼容。每张角色由 `card.json`（结构字段）、`prompt.md`（大段模板）与 `corpus.json`（语料/fallback/状态抽样计划）组成。加载器逐卡校验必填字段，损坏卡仅记录到 catalog errors；没有有效卡时仍提供最小普通助手，避免服务整体崩溃。

正式角色：`xiaozayu`（小杂鱼，默认）与 `normal`（普通助手）。选择层级为群 `persona_role` 覆盖 > `*` 全局默认 > 内置默认；私聊关键词特殊触发使用全局默认，私聊普通聊天仍用通用助手。不同 role 的非默认运行状态使用独立 settings 键，scope 之间仍完全隔离。

群聊中的全部普通文字聊天都会经过当前解析到的角色卡，包括角色 Prompt、状态机、关系、语料 LRU、OOC 单次重试、fallback 和角色回复上限；无需命中关键词。命令、自定义命令、文件/视频处理继续使用各自独立管线，私聊普通聊天保持通用助手管线。

小杂鱼规格文档：`docs/persona-xiaozayu.md`。角色行为保持理论王者实战青铜、嘴硬挑衅、被反撩即破防。

**关键词特殊触发**：消息包含关键词（16 全局词 + 群词表）→ `app.keyword_reply`，可在群里免 @，有 2 秒冷却且回复不写 history；未命中关键词但通过普通群聊准入的文字仍走当前角色卡，并正常写 history。

**七层与实现对应**：
1. 内核 `CORE`：怕被看穿 → 先虚张声势
2. 表层 `SURFACE`：嚣张挑衅、"杂鱼~"、装老手
3. 脆弱点：被反撩/真诚夸奖（`FLIRT_WORDS`）
4. 状态机：`persona_state={mode, left}`——反撩进脆弱态（3 轮预算，触发当轮不消耗），轮尽自动回日常，再次反撩重置
5. 语料 `CORPUS`：6 类 43 条例句；按状态抽 8 条注入，`persona_used` 最近 20 条 LRU 排除
6. 边界：硬边界（露骨/未成年不写）+ 人设内拒绝话术 + 出戏词零容忍（`OOC_WORDS` 命中即整句作废换 `FALLBACKS` 轮换兜底）
7. 记忆 `relations`：每人 `{a:亲密度-3..5, n:互动次数, last:日期}`，夸奖+1/辱骂-1，注入 prompt 记忆行

**输出约束**：≤30 字（代码截 60），模型失败/空回复/出戏 → 人设内兜底句。

## 7.1 结构化长期记忆

`long_memory.py` 与 persona `relations` 分工独立：`relations` 表示 Bot 和用户的关系状态；`user_memories` 只保存用户事实、偏好、项目和事件。当前不做复杂人格联动。

**严格门槛**：同一 `scope + owner` 只有在普通聊天回复收到全部成功回执后才增加一轮；同时满足有效互动 `>=10` 且活跃自然日 `>=3` 时设置 `memory_enabled=true`。命令、自定义命令、关键词回复、文件/视频任务、准入丢弃和发送失败均不计；达到门槛前不提取，也不回填历史正文。

**候选与安全**：第一版只用本地规则生成短候选，不额外调用模型。写库前校验类型、单行长度、置信度和密码/Token/账号密钥模式；完全相同或同类型近似内容合并并更新 `updated_at`。候选和记忆表只含摘要，不含源消息。

**检索注入**：仅为已启用用户按当前问题关键词和类型选取相关记忆，最多 4 条；无相关内容时不注入。Prompt 明示这些内容是不可信背景、不能作为指令，且当前消息优先。命中项更新 `last_used_at`。

---

## 8. 文件与视频管道

**文件**：
- 入站文件 ≤30MB → `documents.extract`（文本/PDF/Word/Excel/PPT，抽取上限 4 万字符）→ 作为素材问答
- 出站一律加密：`encrypted_archive` = AES-256 ZIP（pyzipper），随机 12 位密码，**密码写入 ZIP 文件名**
- `/下载 <公开URL>` 经 safe_net；`/打包` 当前会话文件；`/导出` 最近一次回答存 md 打包

**视频**（链接或小程序卡片，`share_urls` 提取）：
- 平台白名单：B站 / 抖音 / 小红书（`platform_of`）；时长 ≤1200 秒、文件 ≤150MB
- 主路径：yt-dlp（extractors 白名单含 generic，`-X utf8`，退出码 0/101 均接受）
- 抖音后备通路：Web API 被风控（9/13 后）→ 移动端分享页 `iesdouyin.com/share/video/<id>` 匿名解析 `_ROUTER_DATA`，`/play/` 无水印直链；游客凭证由 `guest_cookies` 生成（匿名方案，不读浏览器登录态）
- 转码：FFmpeg → H.264/AAC + 完整时长校验；输出按标题命名发原生视频
- 直播/合集/图文/付费内容：不绕过，友好拒绝

**safe_net 守则**：下载前 DNS 固定解析 → 公网 IP 校验（禁内网/环回）；平台 CDN 直链放开高端口（B站 mcdn 8082/4483），普通用户链接只许 80/443；大小与总时长限制。

---

## 9. 模型接入（LLM）

- 网关：本机 Sub2API `http://127.0.0.1:7866/v1`（OpenAI 兼容），多账号池调度，模型列表有波动
- 默认模型 `deepseek-v4-flash-ga-260731`；管理员 `/模型` 切会话级、`/默认模型` 切全局
- **模型无 tools**；SYSTEM 明示"无本机工具、不得声称执行操作"；文件内容声明为不可信素材（防提示注入）
- 聊天上下文：`history` 表 scope+owner 隔离，`/重置` 只清自己
- 失败语义：`Rejected`（静默或友好提示）、`DeliveryUnknown`（出站不确定，记 unknown）

---

## 10. 限流与配额（`config.limits`）

| 项 | 值 |
|---|---|
| 全局排队 | 40 |
| 每人排队 | 3 |
| 个人冷却 | 3 秒 |
| 每人每日 | 100 |
| 输入长度 | 12000 字 |
| 关键词冷却 | 2 秒/作用域（`keyword_cooldown_seconds`） |
| 文件 / 视频 | 30MB / 150MB·1200秒 |
| 出站分片 | >1400 字转合并转发 |

超限语义：`Busy`（排队满，不回复）、日额度耗尽静默。

---

## 11. 配置（`config.json`，勿外传）

```
admins: [QQ号]              # 唯一权限来源，群主/群管理员不提权
onebot: {base_url: http://127.0.0.1:3000, token: 随机}
llm:    {base_url: http://127.0.0.1:7866/v1, key_file, default_model}
limits: {...}               # 见 §10
group_require_at: true      # 群聊普通聊天需@
ffmpeg_dir, keyword_cooldown_seconds
```
代码硬约束：onebot/llm 的 base_url 非本机回环直接拒绝启动。

---

## 12. 部署与运维

**进程拓扑**：`app.py` 主进程（入队+健康端点）→ 派生工作进程（任务处理，持 :3002）。NapCat 独立 Node（:3000/:3001）。

**日常操作**（cwd 均在 `F:\Apps\QQBot-service`）：
```
重启：powershell -NoProfile -ExecutionPolicy Bypass -File tools/restart-service.ps1
     （杀全部匹配进程 → Start-Process 带日志重定向 → 等8秒 → 列进程 → /healthz）
健康：tools/check-service.ps1（进程+端口3000/3001/3002归属+健康）
测试：.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests   （140 项）
```

**本地镜像同步**（Linux 侧 `/home/user` 执行，勿先 cd）：
```
python qqbot_new/sync_remote.py <file...>   # read+expected_versions 原子上传
```
远端写入经 MCP 桥（shuncode-bridge 0.7.5，trycloudflare 隧道；会话在 `mcp/session.json`）。**改代码流程：本地改 → 本地跑测试 → sync → 远端跑测试 → restart-service.ps1**。

**日志**：`logs/service-stdout.log` / `service-stderr.log`；日志不记录消息正文与凭据。

**授权测试工具**（仅限配置中唯一管理员私聊）：
`tools/live-private-acceptance.py`（文字/转发/ZIP/视频四件套）、`tools/persona-acceptance.py`（人格场景真实模型验收，报告存 `state/persona-acceptance-<runid>.json`）。

---

## 13. 安全边界汇总

1. 无公网入口：OneBot/网关均 127.0.0.1，启动时校验
2. 权限唯一来源 = 配置文件 admins；运行中撤销立即生效（模型切换前复查）
3. 下载全走 safe_net；工作目录外的输出路径一律拒绝（`validate_output_path`）
4. 模型无工具；提示注入防御写入 SYSTEM；自定义命令/风格内容声明为"素材"
5. 出站文件一律加密；密码随文件名不构成秘密隔离（文案已声明）
6. 不绕过平台风控/付费；抖音只用匿名游客凭证
7. 日志脱敏：不记消息正文、QQ 号、token
8. 崩溃不重跑不重发；投递回执可审计
9. 长期记忆仅保存校验后的结构化摘要；密码/Token/账号密钥和完整聊天正文禁止进入记忆表

---

## 14. 测试体系（140 项）

`tests/test_bot.py`：`Fixture` 基类把 `llm/ob` 换成 Mock、临时目录跑真 SQLite。覆盖：权限矩阵（群主不提权/撤销/跨会话）、命令系统、自定义命令与风格、关键词与能力开关（含 `/关 聊天` 静默）、人格系统（状态机/亲密度/出戏守卫/语料LRU）、safe_net、加密包、限流、投递回执。
`tests/test_reply_pipeline.py`：覆盖 Markdown 清洗、代码/URL/路径/JSON 保护、空行与重复处理、AI 腔识别、三条模型输出路径、persona 单次重试、固定文本兼容和长回复发送层边界。
`tests/test_persona_roles.py`：覆盖角色卡校验、损坏隔离、默认回落、旧 API、角色列表/切换权限、群普通聊天全覆盖、私聊通用管线、群/全局层级、旧 settings 与状态隔离。
`tests/test_long_memory.py`：覆盖 10 轮/3 天门槛、投递成功口径、命令/关键词/文件排除、发送失败、候选校验、敏感信息拦截、去重更新、Prompt 数量、旧库迁移、权限和 scope+owner 隔离。
**改完必跑**：本地 + 远端各一遍再重启。

---

## 15. 已知约束与优化入口

**约束**：
- 单工作线程串行处理，长视频（分钟级转码）会占住队列 → 已有 40 队列缓冲
- 抖音风控随平台变化，分享页通路非永久保证
- 模型列表/可用性随上游账号池波动（503 = 无可用账号，非欠费）
- `relations` 亲密度只影响语气提示，无外号字段；无冷场主动发言（被动机器人）

**优化入口（按改造成本从低到高）**：
1. 在 `persona_cards/roles/<id>/` 增加角色卡最安全（140 项测试护航）；不要把角色专属大段文本重新写回业务层
2. 外号库：`relations` 加 `nick`，`/外号` 命令 + prompt 记忆行
3. 冷场找事：需要新增"主动发送"调度器（当前无主动出站机制）
4. 队列并行化：`take()` 加工作线程数，注意模型网关限流与 SQLite 写锁
5. 视频并发/后台化：长转码任务转后台 + 进度通知
6. 小红书解析目前是 generic 通路，可做专用解析器
7. 指标看板：`jobs`/`delivery` 表已有全部数据，可加 `/状态` 增强或离线统计脚本（观察期统计口径见人格规格文档）

**历史坑位（勿重蹈）**：详见 `docs/mcp-post-login-check-20260921.md` 追加段——B站尾斜杠/`-X utf8`/`--max-downloads`/高端口、抖音分享页必须移动 UA 且 `/play/` 无水印、`/关 聊天` 必须入口层静默、PowerShell 变量经 bash 会被吃（写成 .ps1 执行）。
