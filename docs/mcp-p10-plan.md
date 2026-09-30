# P10 改造计划

新增 tooling/registry.py、schemas.py、broker.py、builtin.py、conversation.py 与测试。app.py 普通聊天通过显式开启的工具模型路径；protocol.py 增加受控 structured tool conversation 接口。默认工具路径关闭，既有 chat 不变，主动和关键词路径不启用工具。

首批仅 L0：时间、管理员 Bot 状态/模型列表、本人当前范围记忆、当前允许知识、本人当前范围文件元数据。不开放 L1/L2/L3 实际操作。Broker 校验注册、risk、config.admins、scope、严格 schema、每消息最多3次、每用户/范围速率、失败去重和超时。低风险只读执行用最多2个后台执行槽；超时不释放尚未结束的槽，避免线程堆积。审计新表只存安全元数据，不存参数/结果正文。
