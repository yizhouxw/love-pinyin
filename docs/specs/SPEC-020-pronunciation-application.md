# SPEC-020：学习路径与天天练拼读交互

基于 [SPEC-018 MATCH-10/11](SPEC-018-target-pronunciation-matcher.md) 稳定端口，应用验收编号延续 MATCH-13～15；模型研发与质量门禁独立。

## MATCH-13～15：学习路径与天天练应用接入

2026-10-26 用户授权在独立 worktree 完成应用交互，验收后合入 main。

- MATCH-13：学习路径课程详情提供集中 readingTargets 的有声跟读；天天练当前条接入同一个 MATCH-10 端口。主动录音、停止后识别、回放、重录、取消和跳过均可用。不强制录音或以识别阻塞客观题。现有 Whisper 入口独立保留。mock 仅显式开发注入，始终展示模拟，不能写真实记录。
- MATCH-14：家庭 Mac 保存可信服务端结果摘要（目标、匹配状态、实际识别拼音、证据及声调能力、时间），不存录音。匹配与不符才构成准确情况的有效分母，拒判和不可用不计错；与客观题掌握度隔离。支持历史、备份恢复和清除。访客仅页面内存记录，不写家庭库。
- MATCH-15：共享端口处理请求关联、切条/退出/后台取消、迟到结果、权限/设备/网络错误、音频格式与时长边界。真实模型仍未通过质量门禁；默认服务返回 unavailable，不用 mock、Whisper 或期待文本冒充专用声学判断。应用流程验收与儿童准确率/真实移动设备验收分别报告。

## 验收记录（2026-10-26）

MATCH-13～15 的应用边界通过。独立 worktree 兼容已合入 main 的 SPEC-019，小卖部、课程和天天练共用 recording-wav.ts，不复制转换器。新增 pronunciation-practice.tsx、pronunciation-http.ts、server/pronunciation.py 与 routes/pronunciation.py；家庭摘要随迁移11创建，支持历史、幂等、导出恢复与清除。每日声母呼读和分拼目标分别传 initial/blend，教学映射来自集中内容。没有新增依赖。

`npm run verify:all` 通过：168项前端/工具、464项Python、36项本机浏览器、48项真实本机服务页面；补充目标目录边界后 `npm run verify:server` 465项通过，最终 `npm run verify` 与 `npm run validate:release` 再次通过。新增8项Chromium/WebKit页面覆盖真实MediaRecorder/PCM/家庭同源端点、默认不可用、迟到响应、切目标清除、麦克风拒绝和窄屏放大文字；Python专项10项覆盖可信结果入库、幂等、历史、备份恢复、删除、鉴权/CSRF、格式/大小、访客与mock隔离。默认服务确实返回not-configured，可信结果测试使用明确测试替身，不是模型质量证据。浏览器合成采音只证明传输与生命周期，不代表真实麦克风、儿童、iPad真机或家庭LAN验收。

剩余门禁：真实声学后端及其CPU、超时/并发资源和质量验收；真实儿童与移动设备/家庭LAN验证。当前不调用实验模型，不宣称学生已获得真实拼读准确率。模拟结果不保存，拒判不记错，录音不落盘。
