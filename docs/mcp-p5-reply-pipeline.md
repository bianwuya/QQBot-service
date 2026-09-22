# P5 回复清洗与输出管线阶段报告

阶段：P5

状态：完成，等待人工验收并合入 main

## 新增文件

- `reply_pipeline.py`
- `tests/test_reply_pipeline.py`
- `docs/mcp-p5-reply-pipeline.md`

## 修改文件

- `app.py`
- `docs/architecture.md`

## 实现内容

1. 新增上下文感知的统一 Reply Pipeline，明确区分 `normal_chat`、`persona_chat` 与 `custom_gen`。
2. 清理普通文本中的 Markdown 强调、标题符号、连续空行、行尾空格、连续重复句和常见模板前缀。
3. 清洗前保护 fenced code、inline code、URL、Windows/Unix 路径与单行 JSON，避免破坏代码和结构化内容；Python dunder 名称不会被当作 Markdown 强调。
4. 提供 `ReplyResult(text, retry, reason)`、`clean_reply`、`validate_reply` 和 `process_reply` 接口。
5. 普通聊天、关键词人格和自定义 `gen` 的模型输出全部进入新管线；固定文本命令保持原样。
6. persona 明确 OOC 或空回复最多额外生成一次；第二次仍失败时继续使用原 `persona.FALLBACKS`，不会无限重试。
7. 普通聊天默认最大生成文本长度为 12000 字，可通过旧配置兼容的可选 `reply_max_chars` 覆盖；persona/custom gen 保留原 60/200 字边界。
8. `>1400` 字合并转发仍由原发送层处理，Reply Pipeline 不承担 QQ 分片。

## 兼容性

- 原功能：保持。固定命令、权限、限流、文件/视频、投递回执、崩溃恢复和发送层未改变。
- 数据库：未新增或修改表、字段、迁移和现有数据。
- 配置：兼容。旧 `config.json` 无需修改；`reply_max_chars` 为可选项并有默认值。
- 安全边界：保持。未给模型增加 tools、shell、PowerShell 或文件系统权限；未关闭 `safe_net`；未增加消息正文日志。
- 后续阶段：未读取或实现 P6～P14 的需求。

## 测试

- 修改前基线：90 项全部通过。
- 新增测试：16 项。
- 总测试结果：106 项全部通过，耗时 3.462 秒。
- 语法检查：`app.py`、`reply_pipeline.py`、`tests/test_reply_pipeline.py` 通过 `py_compile`。
- VS Code 诊断：0 个 error/warning。
- 运行验证：服务标准重启成功；`/healthz` 返回 HTTP 200，`onebot_connected=true`、`qq_online=true`。

## 发现但未处理

- `F:\Apps\QQBot-service` 当前没有 Git 元数据，无法在本机执行提交、分支检查或合入 main；本阶段未擅自初始化仓库。

## 下一步

- 等待人工验收并合入 main。
