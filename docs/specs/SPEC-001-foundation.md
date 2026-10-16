# SPEC-001：基础领域、局域网会话与存储

需求：R-001、R-007、R-009、R-011、R-018、R-019。基础实现、并发/迁移及真实停服恢复已有软件证据；真实家庭LAN多设备、物理故障仍待验收。当前状态见[STATUS](../STATUS.md)。

## 范围与实际文件

`src/domain/contracts.ts`、`src/app/App.tsx`的API调用与恢复、`server/api.py`、`server/storage.py`、`server/domain.py`、内容加载与相关Schema/测试。当前没有独立ProgressRepository类或src/services目录。课程文稿和教学规则在content，不在业务组件复制。

家庭SQLite是进度真源；访客临时快照另按[SPEC-007](SPEC-007-guest-access.md)隔离。修改契约先同步[API文档](../api-contract.md)、类型和测试。

## 契约与行为

- 内容加载校验版本、ID和引用；已登记历史内容支持旧会话，未知内容不猜测映射。当前课失效时保留历史并要求家长重选，不提供任意未知课包的只读浏览器。
- 家庭只有一个匿名档案，保存当前课、设置、会话、首次客观作答、复习及幂等回执。历史评分摘要只作兼容，不写新评测结果。
- 配对码5分钟、一次有效；仅127.0.0.1本机入口配对建立家长角色，远程配对只能学习；家长读写还需本机入口校验。Cookie HttpOnly/SameSite=Strict，HTTPS时Secure；CSRF、来源和角色规则见API文档。成人确认弹窗只防误触。
- 服务端校验实例、合法选项和内容版本；客户端不提交正确性。相同requestId重试返回原回执，实例只计首次答案。
- 日期由服务器UTC时间转换Asia/Shanghai；同知识点/题目/日的掌握计分由写事务内查询去重，原始重复练习可保留。并发不同题均保存，不覆盖别人进度。
- revision冲突用于选课/导入等条件写入；作答依赖实例与请求幂等，不要求expectedRevision。冲突后重新读取，不能无条件覆盖。
- 网络失败显示结果未确认，浏览器保存原请求ID并重连/刷新恢复，不伪称成功。声音失败不产生错误成绩。
- 迁移在事务中执行；未知迁移版本在写入前拒绝。不得删除旧库或创建空进度掩盖失败。备份恢复见SPEC-005/006。

## Given / When / Then

- Given 无效内容，When 加载，Then 返回可定位的校验错误，不让坏引用进入学习。
- Given 双击和网络重试，When 请求到达，Then 只有一个首次事件；改答案复用同一请求号须拒绝。
- Given 两个配对客户端，When 并发提交不同题，Then 两事件均保存且revision不丢增量。
- Given 响应中断，When 刷新恢复，Then 查询/重放原requestId，不重复计分。
- Given 未配对或已撤销设备，When 读写家庭进度，Then 拒绝且不泄露档案。
- Given 迁移或写入失败，When 恢复，Then 不静默重置；未知schema启动不修改原库。

## 验证与剩余边界

`verify:server`覆盖真实隔离SQLite、并发、认证和迁移；`test:e2e:live`覆盖真实服务/数据库的恢复。RECOVERY-01和ROLLBACK-01见SPEC-006，不能仍写成“恢复未实现”。实际Wi-Fi、多设备、整机/磁盘故障按交付矩阵继续验收，测试客户端不等于真实设备。

当前SQLite迁移版本为7，JSON备份schema仍为v5，两者不是同一版本号。每日跟读录音与识别结果不属于家庭持久化数据，边界见SPEC-009；播放间隔迁移见SPEC-012。
