# QQbot 新部署与验收记录

日期：2026-09-21，Asia/Shanghai。工作区根：F:/Apps。本文路径均相对该工作区。

## 用户确认的范围

- 旧部署先归档校验再清理。
- 普通群友和好友均可聊天、文件分析、视频解析；仅指定管理员可管理 Bot。QQ群主/群管理员不自动提权。
- 沿用原管理员名单，模型使用本机 Sub2API，管理员可在 QQ 内选择模型。
- 优先 B站、抖音、小红书；公开视频转成 QQ 原生视频发回来源会话。
- 出站文件为 AES-256 加密 ZIP，名称包含原文件名和随机密码，密码同时在来源会话提示。
- 长回复通过合并转发聊天记录发送，群聊和私聊均适用。
- 发现当前 PMHQ 要求厂商授权后，用户明确选择切换其他 OneBot 协议端，现使用 NapCat。

## 迁移与目录

- 完整归档：`backups/qqbot-legacy-20260921-174204/`。
- 归档内含旧 `LLBot`、`QQ-OpenAI-Bridge`、旧任务 XML、运行时配置副本及 `manifest.json`。
- 668 个文件逐一 SHA-256 校验通过。源目录内旧文件已全部清理；若某终端持有目录句柄，空目录可能暂时无法移除。
- 初次目录移动失败已回滚；`backups/qqbot-legacy-20260921-174138/` 是该次准备记录，不是完整主备份。
- 旧 `QQBridgeWatchdog` 计划任务已移除。
- 管理员名单迁移后仍为 1 人，未输出QQ号或凭据。
- 新业务代码：`QQBot-service/`。
- 新协议端：`NapCat-runtime/`；独立用户数据目录：`NapCat-runtime/profile/`。
- `LLBot-personal`、`LLBot-runtime` 保留但不作为现行协议端启动，未改动或覆盖用户普通 QQ 安装。

## 组件与来源

### NapCat

- GitHub API 核实版本：v4.18.28，发布日期 2026-09-14。
- 包：`https://github.com/NapNeko/NapCatQQ/releases/download/v4.18.28/NapCat.Shell.Windows.Node.zip`。
- 发布摘要与实测包 SHA-256：`fb64fa3b036ad2df1a5d7c204c482694c20e4b763978c8a4968fd3474c05b4a8`。
- 独立 Node 包无需替换普通 QQ 的文件。发行包缺少 crypto.dll、ssl.dll，已从本机腾讯 QQ 9.9.35-52892 安装目录只读复制，清单在 `NapCat-runtime/supplemental-dlls.json`。
- `napcat.mjs` 增加小范围用户数据目录隔离补丁，只支持 `NAPCAT_USERDATA_PATH`；未修改鉴权、平台限制或授权机制。
- 官方包中原始 napcat.mjs SHA-256：`b161061c32acc7724381fbabd2a6ef022892cdb6038aa86c28de552c74c5dde0`。
- 补丁后：`02cc960abbd6a9784402bdc94e452f16d08f12d9274801555049fca48290170f`。
- **升级时不能直接覆盖补丁后就沿用启动脚本，须重新核对并应用目录隔离补丁。**

### FFmpeg

- LLBot 原附带精简版不能通过 H.264 生成测试，已换为独立完整构建。
- 来源：`https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/ffmpeg-9.0.2-essentials_build.zip`。
- 发布摘要与下载包实测 SHA-256：`60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba`。
- 新可执行文件位于 `QQBot-service/tools/`；旧精简副本以 `.llbot-original` 后缀保留。

### Python

- 解释器：本机 Python 3.14，新建 `QQBot-service/.venv`，使用本机现有系统包，并在该环境补充 pyzipper、websocket-client。
- 版本清单：`QQBot-service/requirements.txt`。环境非完全隔离，升级系统包后应复测。

## 实现与安全边界

- 从本机带 token 的 OneBot WebSocket 接收事件，HTTP 调用 API；不提供公开入站 webhook。
- 只有配置中的 QQ 号能触发管理指令；忽略昵称、自称、群角色、模型建议及文件内指令。
- 模型请求没有 tools/functions/Agent；包括管理员在内，模型均不能执行系统命令或任意读写本机文件。
- 群聊默认 @ 才聊天；文件和支持的视频链接自动处理。管理员可用 `/群触发 全部` 调整本群。
- 群与私聊按会话及发送者分别保留上下文，不把群里其他人的上下文混入某人的私聊。
- 下载仅允许公开 HTTP/HTTPS 地址，阻止内网、回环、云元数据和非标准端口；逐跳校验，文件实际下载使用 DNS 固定连接。yt-dlp 仅用于受支持平台提取元数据。
- 上传文件不执行，不解压任意归档到磁盘。Office/PDF 在受时间和 Windows Job 内存限制的子进程中解析。
- 文件默认 30MB；视频默认 150MB、20分钟；只发经校验的 H.264/AAC MP4。不绕过付费、登录、DRM 或权限限制。
- yt-dlp 已包含 BiliBili、Douyin、XiaoHongShu 提取器；平台反爬可能要求用户自己配置合法 Cookie。本次未读取浏览器 Cookie。
- SQLite 持久化任务、文件认领、输出与分项投递回执。重启不自动重跑进行中的付费任务、不自动重发投递结果不明的消息。
- 超长回复按 UTF-16 长度分节点，批次标签独立占节点，正文不截断。
- 只有收到实际 message_id/file_id 才记录对应投递成功。
- 文件、历史、任务默认保留24小时；日志轮转且不记录消息正文、账号或密钥。数据库和工作文件仍含会话数据，应仅供本机授权用户读取。
- 密码放在同一会话和文件名是用户指定行为：能看到该会话的人也能解压，不等于端到端私密交付。

## 当前验证结果

| 检查 | 结果 |
| --- | --- |
| 新代码离线单元/契约测试 | 51项通过，退出码0；日志 `QQBot-service/logs/offline-tests.txt` |
| 编辑器诊断 | 检查时无匹配错误/警告；不能替代运行测试 |
| 默认模型初选 deepseek-v4-flash | 网关返回503，不作为最终默认模型 |
| deepseek-v4-flash-ga-260731 真实网关调用 | 返回 OK，约1.14秒；已设为最终默认模型 |
| 网关模型列表 | 可读取13个模型ID；不代表所有模型均已实际调用验证 |
| H.264转码 | 本地生成1秒测试MP4成功，2325字节 |
| NapCat native wrapper | 补齐依赖后加载成功 |
| NapCat启动 | 已进入扫码登录，WebUI HTTP200 |
| 新业务服务 | /healthz HTTP200，service=qqbot-service |
| 监听边界 | 6099和3002仅127.0.0.1；OneBot端口待QQ登录后启动 |
| QQ账号在线、消息/视频/文件真实投递 | 待扫码与人工验收，未标为通过 |

注意：启动脚本初版参数引号有误，已修复并重新启动后确认健康端点。上述最终运行状态以修复后实测为准。

## 启动与接下来验收

1. 运行 `QQBot-service/启动机器人.cmd`。
2. 运行 `QQBot-service/打开登录页面.cmd`，会读取本机 WebUI token 并打开登录页，不在终端回显 token。
3. 用拟作为机器人的账号扫码，建议与管理员账号分开。登录前业务服务显示 onebot_connected=false、qq_online=false 属预期。
4. 登录后确认 OneBot HTTP3000、WS3001 只监听127.0.0.1，健康状态在线。
5. 使用指定测试群/好友分别检验：短聊天、长回复转发、非管理员管理命令拒绝、管理员模型切换、文件分析、带密码ZIP上传、三个平台视频链接与小程序卡片。
6. 未经上述验收不声称部署全部完成。尚未启用登录自启或注册新守护任务，应在真实收发稳定后添加。

官方部署文档参考：`https://napneko.github.io/guide/boot/Shell`。以本机发行包实际帮助和配置 schema 为准。
