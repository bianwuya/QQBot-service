# P13 任务并发 · 阶段报告

状态：实现与离线并发验证完成；生产进程尚未重启，实际运行仍是原已加载版本。

## 变更

新增 `task_dispatch.py`、`sqlite_runtime.py`、`tests/test_concurrency.py`；修改 `store.py`、`app.py`、`protocol.py`。计划见 `docs/mcp-p13-plan.md`。

默认chat×2、file×1、media×1、tool×1，Social Scheduler独立单线程。可选workers配置限定chat最多4、file最多2、media/tool固定最多1。模型生成和恢复探测共用2槽，不因增加其他worker无限增加模型请求。工具命令、知识导入/文件/视频按实际任务归类；已有FFmpeg/下载process_limits不变。

jobs原结构和数据保留，新增job_dispatch表并回填旧任务。原子领取使用BEGIN IMMEDIATE，共享单库WAL与RLock。同scope+owner全部任务FIFO领取（比只保证聊天更保守），不同用户并行。当前scope较早已运行chat形成投递屏障，所有job的多段输出使用会话锁保持连续；不会等待因其他用户长视频而尚不能领取的queued聊天，以免重新引入媒体堵聊天问题。

OneBot每线程独立HTTP Session；群关系get-modify-set和mood更新采用短时Store锁，模型网络调用不持锁。SQLite BUSY/LOCKED仅对未成功SQL语句有限重试，不重跑process/模型/发消息。未捕获的late DB故障保留处理中状态，重启后interrupted；sending恢复unknown。主动任务直接以processing入库，避免并发worker抢走其accept/update间隙。

## 测试

新增15项；原297 + 15 = **312项全部通过**，py_compile、git diff --check通过。

多线程实测（全部临时库、mock网络/长任务）：A长视频或长工具等待时B聊天可完成；同用户两聊天先后正确；不同用户同时进入生成而按序出站；多段不交错；一任务并发领取只有一次；模型峰值2；独立HTTP Session；真实SQLite外部写锁释放后恢复；旧jobs分类回填；崩溃后interrupted、unknown不重发；并发全局/每人队列限额不超。

## 中途解决与取舍

- 若投递屏障等待全部较早queued聊天，会让“排在A视频后的A聊天”间接堵住B；改为只等较早已运行chat并补专门回归。
- 为并发避免丢失群共享关系/mood更新，锁只包短时状态读写，不把整个群模型调用串行化。
- 为兼容原jobs九列结构及旧数据，采用独立分类表而非直接重建jobs。
- 同一用户文件/视频会延迟其自身后续聊天，以维护其文件上下文顺序；其他用户不受该入队锁限制。不同群独立。
- 本轮没有真实媒体压力测试、进程重启或生产数据库迁移。

下一步：按本轮授权进入最终 P14。

## 最终复核补充

最终复核补充：新增 service_instance.py，生产main在创建Bot/Store前先持有进程租约和loopback健康端口，防止第二实例误做在途任务恢复，也兼容仍未使用租约的旧服务占端口情形。补进程互斥/释放、旧端口占用、真实临时loopback健康HTTP交接测试；并对主动输出进入投递时复核关闭状态。最终全量337项通过。
