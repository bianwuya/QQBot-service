# P11 指定应用控制 · 阶段报告

状态：受控框架、适配器及离线测试完成；未启用生产控制、未真实重启/停止任何应用。

## 变更

新增 `app_control.py`、`app_executor.py`、`tools/control-napcat.ps1`、`controlled-apps.example.json`、`tests/test_app_control.py`；修改 Tool Broker/注册表/内置工具、app.py、protocol.py。计划见 `docs/mcp-p11-plan.md`。

语义工具 get_app_status（管理员L0）与 control_app（管理员L2申请），只收 app_id 和 start/stop/restart。命令 `/应用 状态|启动|停止|重启 <app_id>` 也经 Broker；`/应用 确认 <票据>` 为唯一执行确认入口，不把确认工具开放给模型。默认 app_control_enabled=false，示例白名单不自动加载。

本机配置含 id/display_name、start_method/stop_method/status_method、allowed_actions、timeout、allowed_scopes；restart_method用于既有标准重启脚本。模型不接触真实路径和argv。执行层只调用白名单里的固定PS1，通过固定绝对路径的PowerShell宿主、shell=False，不开放任意Shell入口。

所有变更需120秒一次票据，绑定HMAC操作者、scope、工具、参数和白名单配置hash；确认时再次核验管理员、开关、scope、动作和配置版本，先消费再执行。过期、重复、跨用户/群、改配置、撤权均拒绝。全局变更锁串行处理，审计包含执行预占和终态。超时/异常不返回原异常、脚本输出或路径；票据不恢复，未知操作不自动重跑。

QQBot restart强制使用项目 `tools/restart-service.ps1`，审计在先、发送“准备重启”收到message_id在先，再分离运行标准脚本。NapCat脚本仅匹配 `NapCat-runtime/node.exe`，不触碰普通QQ。Sub2API示例引用既有native-start/stop/restart脚本和PS7，不复制蓝绿轮换逻辑。示例QQBot只开放status/restart，避免误用会同时停止NapCat的原stop.ps1。

## 验证

新增13项，原271 + 13 = **284项全部通过**；py_compile、git diff --check通过。PowerShell AST解析通过（仅解析、未执行脚本）。覆盖白名单/动作/权限/scope拒绝、票据绑定/过期/一次性/撤权/配置改变、超时未知与不重放、审计脱敏、模型无确认能力/路径、重启准备顺序和失败不启动、固定argv与shell=False。

## 中途问题与取舍

- 原QQBot stop.ps1会停Bot和NapCat，故未把它冒充“只停止Bot”；示例仅提供Bot标准restart/status。
- 网关轮换脚本可等待3700秒，而控制操作只等待至配置上限120秒：超时记timeout_unknown，不能理解为操作撤销，也不自动再次轮换。
- Bash PATH不含powershell.exe，语法验证初次无法启动；改用SystemRoot下固定完整宿主路径并成功解析，没有改系统PATH。
- 不真实执行启停测试；需人工显式安装白名单和确认才能上线，报告不把mock当真实管理结果。

下一步：按本轮授权进入 P12；生产继续保持原运行状态。

## 最终复核补充

最终复核补充：自重启准备回执期间可能撤销管理员或修改白名单；回执成功后再次核验配置/权限，并使用会话投递锁。新增等待期间撤权回归，未真实重启。最终全量337项通过。
