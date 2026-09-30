# P13 并发与任务隔离计划

新增 task_dispatch.py（分类/保守worker数/按会话投递锁）、SQLite忙重试封装与测试；Store保留jobs原结构，新增job_dispatch分类表并兼容回填旧任务。分类chat/file/media/tool，默认2/1/1/1，social独立单线程。所有同scope+owner任务从领取时按入队顺序串行；不同用户可并行。chat生成可以并行，同scope聊天投递前等待更早chat结束；每job出站全程加会话锁避免多段交错。

app.py拆分领取循环与单job处理，模型并发信号量默认2，OneBot改线程本地Session。SQLite继续共享单库WAL/RLock，Busy只重试未成功的SQL语句，绝不包住模型/发送重试。processing/sending崩溃语义不变。共享群关系/mood短时更新需锁，不能把网络调用放进Store事务。媒体仍调用原process_limits，本阶段不换下载/FFmpeg实现。
