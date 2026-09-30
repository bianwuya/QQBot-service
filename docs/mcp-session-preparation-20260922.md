# MCP 接入与 P7.1 阶段衔接任务书

日期：2026-09-22

## 状态

MCP 接入、工具发现、工程定位及本地测试基线核验完成。本次不代表 P7.1 人工验收完成，也未启动 P8。

## 工程基线

- 项目：F:/Apps/QQBot-service；工作区：F:/Apps。
- 当前分支：p7.1-persona-hardening，HEAD e6af2de。
- main：8bf11a1；git merge-base --is-ancestor 24fe151 main 返回 1，P7.1 人设重构提交尚未进入 main 历史。
- 阶段报告 docs/mcp-p7.1-persona-hardening.md 标记“完成，等待人工验收并合入 main”。其 204 项测试为旧报告记录，本次实测为 210 项。
- 用户原有未跟踪文件 QQBot-P5-P14阶段任务书/bot_persona_guide.md 保留，未修改或提交。
- 已阅读工作区 AGENTS.md、QQBot-P5-P14阶段任务书/00-阶段执行总约束.md、当前阶段报告及 README.md 的相关内容；未读取 P8～P14 任务书。

## MCP 使用规则

- 服务 shuncode-bridge 0.7.5，协议 2024-11-05，已完成 initialize、initialized 和 tools/list。
- 文件发现：list_directory / find_files；正文检索：search_files；语义导航：lsp；图像：read_image。
- 先 read_files 再 apply_patch；修改时传 expected_versions；冲突后重读，禁止覆盖用户并行修改。
- 独立读取可并行；有依赖操作串行，同一文件不并发写入；每个 JSON-RPC 请求使用唯一 ID。
- 验证：get_diagnostics、run_command；长命令使用 get_command_output，必要时 cancel_command / send_command_input。
- 明确指定命令 cwd，避免复用终端位置导致误操作。
- 多步工作用 set_todos / update_plan 维护完整清单，最多一项进行中；report_progress 用于必要进度，本次依用户要求不逐项播报问题。
- 报告存入项目 docs/mcp-*.md；不在报告中写连接凭据、网关 Key 或聊天正文。
- 工具提供的设备访问能力不等于任意修改授权；优先当前工程，不擅改其他服务。

## 本次问题与处理

1. MCP 并行请求曾因复用请求 ID 返回 HTTP 409：接入客户端已改为每次生成唯一 UUID，随后调用成功。
2. 全量测试发现 tests/test_persona_voice.py 两处 json.load(open(...)) 未关闭文件：改为 with open 上下文管理。不改测试断言、业务行为或角色数据。
3. 阶段闸门尚未满足：按项目总约束，不把“推进到 P7.1”当作“P7.1 已人工验收并合入 main”；不自动合并、不提前读取或实现 P8。

## 变更与验证

- 修改：tests/test_persona_voice.py（仅两处测试文件句柄管理）。
- 新增：docs/mcp-session-preparation-20260922.md（本任务书）。
- 修改前：210 项测试通过，出现两处 ResourceWarning。
- 修改后：.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests，210 项通过，输出不再出现上述警告。
- get_diagnostics 对修改的测试文件返回 0 条诊断。
- git diff --check 通过。
- 未执行在线付费模型评测、QQ 发消息、服务重启、数据库变更或 Git 提交/合并。

## 后续执行闸门

等待人工验收并合入 main。操作者明确指定下一阶段且其前置条件满足后，只读取总约束和该阶段任务书，再制定最小改造计划、实现、测试并输出阶段报告。过程中可安全决定的本阶段问题直接修复并集中记入最终报告；权限变化、数据删除或无法安全决定的问题不擅自处理。
