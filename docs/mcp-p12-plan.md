# P12 Model Router 改造计划

新增 model_router.py 和 tests/test_model_router.py；protocol.py 定义结构化 ModelFailure，仅503/明确无账号/网关5xx/连接类错误可触发；app.py所有模型生成入口统一经路由，状态命令增加模型状态，配置无model_pool时严格单模型兼容。

HEALTHY/DEGRADED/COOLDOWN/PROBING 状态、连续错误阈值、scope+owner粘性、串行最多3个候选、后台低频单模型恢复探测，成功达阈值才回主模型。手动切模型清理相关粘性。不会修改Sub2API、不并发竞速、不重复发送不同模型回答。读超时/已执行工具的后续失败可能产生未知付费或副作用，保守不自动重放；连接超时可故障转移。探测仅在显式配置备用池后启用，不改生产配置、不真实付费探测。
