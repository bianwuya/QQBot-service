# NapCat 二维码获取失败：恢复记录

检查日期：2026-09-21 21:15 起（Asia/Shanghai）。本文路径相对 F:/Apps 工作区。

## 已确认的故障

- 用户报告 WebUI 持续显示二维码获取失败。
- 初次检查时，`NapCat-runtime/node.exe` 对应进程不存在，6099 没有监听，直接访问本机 WebUI 连接被拒绝。
- QQBot 业务服务仍正常，3002 的 `/healthz` HTTP 200，但 onebot_connected=false、qq_online=false。
- 最后保存的 `NapCat-runtime/napcat/cache/qrcode.png` 时间为19:09:01，检查时已经过期。
- 日志中的 Login Error ErrType=1、ErrCode=3 在该版本源码中明确映射为二维码过期，并触发重新获取；不能据此断言账号风控或封禁。
- 当前证据足以确认“二维码后端不在运行”这个阻塞。没有进程退出事件证据，不能确定最后一次退出由何种操作导致。

## 已执行的恢复

1. 通过 `QQBot-service/start.ps1` 将 NapCat 作为 Windows 后台进程重新启动，而非仅依靠先前前台/受管终端命令。
2. 仅启动缺失的 NapCat；复用正在运行的业务服务。未结束、修改普通 QQ 客户端。
3. 使用本机配置中的 WebUI token，按官方实际接口正常认证，随后检查 QQ 登录状态和获取/刷新二维码。没有禁用鉴权或绕过账号登录。
4. 实测返回：webui_authenticated=true、qr_available=true、qr_refreshed=true、login_phase=waiting_qrcode、qq_online=false。
5. token、签名凭证、二维码登录URL未输出到诊断日志或文档。

## 脚本修复

### `QQBot-service/start.ps1`

- 启动/复用本项目进程后，等待WebUI与业务服务实际HTTP可用，不再仅报告“请求启动”。
- 核对WebUI监听地址为127.0.0.1，监听进程路径属于本项目NapCat。
- 超时或端口被其他程序占用时明确报错。
- 抑制PowerShell下载进度条，减少终端刷屏；不会隐藏错误。

### `QQBot-service/Open-WebUI.ps1`

- 打开网页前先调用启动与健康检查。
- 调用新增 `QQBot-service/tools/check-login.py --refresh`，执行正常鉴权、登录状态检查与二维码检查。
- 已在线或已扫码进入初始化时不刷新二维码，避免打断用户登录。
- 后台/鉴权/二维码检查失败时停止，不再打开一个明知后端不可用的页面。
- 成功后使用当前本机凭据打开新的登录入口，不回显敏感URL。

原入口 `QQBot-service/打开登录页面.cmd` 不变。

## 验证

- Python测试：原51项 + 新增7项登录辅助测试，共58项通过，退出码0。
- 测试日志：`QQBot-service/logs/qr-fix-tests.txt`。
- 新增覆盖：读取二维码、主动刷新、已登录不刷新、扫码中不刷新、生成中不重复刷新、鉴权失败拒绝、拒绝非回环配置，以及不在结果中暴露敏感值。
- PowerShell脚本语法解析通过。
- 重复运行启动脚本，NapCat进程数量2→2，PID集合不变，未重复启动实例。
- 编辑器检查未返回匹配错误/警告。

## 当前边界

本次修复验证到“二维码接口可获取新二维码、等待用户扫码”。未代替用户扫码，未确认用户浏览器最终显示效果，也未完成真实QQ登录与消息收发验收。

如果旧标签页仍提示失败，请关闭旧页后双击 `QQBot-service/打开登录页面.cmd`，使用新打开的页面。二维码会过期；需要时通过该入口重新检查/刷新。不要将WebUI访问token或二维码登录URL公开发送。
