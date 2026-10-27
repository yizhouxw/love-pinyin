# API 与数据契约

本文描述当前 `server/api.py` 的实现。路径统一以 `/api/v1` 为前缀；运行服务的 `/openapi.json` 提供请求模型，客户端类型见 `src/domain/contracts.ts`。新增跟读端点只在家庭 Mac 内存处理录音；Whisper 音节对照与 MATCH-10 专用拼读端口独立，均不提供专业发音评分。

## 认证、错误与一致性

- 家庭接口需 `lp_session` Cookie；写操作另需可读 `lp_csrf` Cookie对应的 `X-LP-CSRF`。会话Cookie为HttpOnly、SameSite=Strict，HTTPS时加Secure，有效期30天。
- 首次loopback生成配对码；第一个有效家长设备建立家长角色，后续设备为学生。配对码5分钟、一次使用有效，失败限制为同一客户端地址60秒内5次，进程内计数。
- 提供Origin时检查同源；未提供时不统一拒绝。无通配CORS。访客请求另经白名单和隔离内存状态处理。
- 业务错误通常为 `{"detail":{"code":"..."}}`；请求模型校验为422 `detail` 数组，不存在统一的 `error.retryable` 包装。客户端应处理网络故障和非业务错误。
- 参数ID按登记内容查询，不作为任意文件路径。音频端点核验实际文件及摘要、支持单段Range；缺失404，非法Range416。
- 作答只提交 `requestId` 与 `answerOptionId`，正确性和时间由服务器决定。相同请求重试返回回执；同一请求号改实例/答案返回409 `IDEMPOTENCY_KEY_REUSED`；同一实例换请求号再答返回409。
- 选课要求 `expectedRevision`；导入确认绑定预览token、文件hash和revision。设置、普通作答不要求客户端传revision。

## 当前路由

“公开”表示不需要家庭配对，并不表示适合开放公网。“家长”由服务端角色校验，“写入”遵守相应CSRF/来源规则。

| 方法   | 路径（省略 `/api/v1`）                        | 行为及访问范围                                                                   |
| ------ | --------------------------------------------- | -------------------------------------------------------------------------------- |
| POST   | `/local/pairing-code`                         | 仅loopback生成首次配对码                                                         |
| POST   | `/pairing-codes`                              | 家长生成新设备配对码                                                             |
| POST   | `/pair`                                       | 以配对码换取Cookie                                                               |
| DELETE | `/session`                                    | 取消本设备会话                                                                   |
| GET    | `/devices`                                    | 家长查看型号、已用配对码、lastConnectedAt，不返回令牌                            |
| PUT    | `/devices/{device_id}`                        | 家长更新型号model（1–80字符），要求CSRF；不存在或已撤销返回404                   |
| DELETE | `/devices/{device_id}`                        | 家长撤销次设备，不可撤销当前家长设备                                             |
| GET    | `/health`                                     | 公开；服务状态、contentVersion、storage                                          |
| GET    | `/capabilities`                               | 公开；标准音及中文声音/课程录音就绪情况                                          |
| GET    | `/bootstrap`                                  | 未配对/失效Cookie返回200 paired=false；有效会话返回家庭入口信息；均含isLocalHost |
| GET    | `/curriculum`                                 | 配对；课程、知识点、题目、书写/图片和实际音频状态；移除答案、提示与旧审核字段    |
| GET    | `/audio/{asset_id}`                           | 配对；PinYinSound标准音                                                          |
| GET    | `/learning-audio`                             | 配对；中文声音和课程录音可用性映射                                               |
| GET    | `/voice/{asset_id}`                           | 配对；登记的中文声音或课程录音                                                   |
| PUT    | `/household/current-lesson`                   | 家长；选课及revision冲突检查                                                     |
| PUT    | `/household/settings`                         | 家长；soundEnabled、reducedMotion                                                |
| GET    | `/profiles/export`                            | 家长；家庭JSON备份                                                               |
| POST   | `/profiles/import-preview`                    | 家长；校验备份，生成5分钟预览token，不写学习数据                                 |
| POST   | `/profiles/import`                            | 家长；确认后单事务全量替换                                                       |
| DELETE | `/profiles/data`                              | 家长确认；清学习记录，保留设置与配对                                             |
| POST   | `/profiles/clock-pending/resolve`             | 家长确认；时钟恢复后删除待校时记录或保留为不计分                                 |
| DELETE | `/profiles/reset`                             | 家长确认；清数据/设置，撤销全部设备并清配对码                                    |
| POST   | `/reviews/{knowledge_id}/sessions`            | 配对；选定知识点的独立两题复习                                                   |
| POST   | `/sessions`                                   | 配对；当前课最多六题，冻结题单与选项顺序                                         |
| GET    | `/sessions/current`                           | 配对；当前未结束会话及已答/跳过状态                                              |
| POST   | `/sessions/{session_id}/finish`               | 配对；结束会话，全部题目已答/跳过才计完整轮次                                    |
| POST   | `/rest/complete`                              | 配对；完成休息，允许继续练习                                                     |
| POST   | `/instances/{instance_id}/hint`               | 配对；标记提示已使用并返回提示，不单独生成作答                                   |
| POST   | `/instances/{instance_id}/skip`               | 配对；幂等跳过，不计作答/掌握度                                                  |
| POST   | `/instances/{instance_id}/answer`             | 配对；保存首次作答并返回反馈                                                     |
| GET    | `/attempts/{request_id}`                      | 配对；查询待确认请求回执                                                         |
| GET    | `/profiles/progress`                          | 配对；掌握状态、复习、设置、revision及完成轮次                                   |
| GET    | `/profiles/knowledge/{knowledge_id}/attempts` | 配对；知识点记录，限定家庭/知识点的cursor分页，最多50条                          |
| POST   | `/guest/operate`                              | 公开；白名单操作与临时快照，返回result/state                                     |
| GET    | `/guest/curriculum`                           | 公开；教学内容，无家庭档案                                                       |
| GET    | `/guest/learning-audio`                       | 公开；已安装教学声音状态                                                         |
| GET    | `/guest/audio/{asset_id}`                     | 公开；已安装标准音                                                               |
| GET    | `/guest/voice/{asset_id}`                     | 公开；已安装中文声音及课程录音                                                   |

`learning-audio` 的形状为 `{narration: Record<audioId, boolean>, lessons: Record<lessonId, {audioId,title,available,sourceType}>}`。课程音频需求附 `available` 及可用时的 `standardSource`。标准音唯一来源是固定cmguo/PinYinSound；没有审核状态或备用审音来源。

访客 `operate` 接收 `{path,method,body,state}`，初始state为null。仅允许学习、选课/设置和查询等白名单操作，不支持家庭管理；客户端不携带家庭Cookie。请求最大4MiB，快照经校验后在请求级内存SQLite中执行，结果回存sessionStorage。公开资源接口包含课程录音，见[隐私边界](engineering/privacy.md)。

## 备份、时间与历史内容

家庭JSON schema为v5，显式迁移v2/v3/v4；最大16MiB、最多50000条作答，内存预览缓存最多8个。导入失败不部分写入。导出包含 `masteryRuleVersion: 1`；进度返回 `masteryRuleVersion: "mastery-v1"`，二者属于不同响应格式，不能交换使用。

选课ID已不在当前课程时，进度保留原ID，创建普通/复习会话返回409 `CURRENT_LESSON_REQUIRES_SELECTION`，家长重选后继续，不隐式改成第一课。旧会话从已登记历史内容及冻结题单恢复；未知历史版本拒绝。

服务器时间比最后观察时间回退超过5分钟时，新记录 `clock_pending=1`、`due_credit=0`，不推进掌握度/复习。恢复后由家长选择清除或保留为不计分记录，不自动改写时间戳。

## 实际 SQLite 存储

`server/storage.py` 维护迁移1–9及下列表：`schema_migrations`、`household`、`pairing_codes`、`devices`、`exercise_instances`、`attempts`、`request_receipts`、`review_plans`、`sessions`、`skipped_instances`、`assessment_summaries`。家庭设置在household中，没有独立profiles/settings表；assessment_summaries仅为历史兼容，首版不创建发音评测结果。

外键、实例唯一约束及事务保证一致性。每日同题去重在写事务内查询，服务端进度可从有效事件重建。未知迁移版本在改journal模式和执行DDL前拒绝，不能自动清库。具体字段与约束以迁移代码为准。

## 每日跟读（SPEC-008）

GET /api/v1/daily-reading（配对）及/api/v1/guest/daily-reading（访客）返回14份days、sections、items、源页码、逐条available和assessment返回本地识别可用性、mode=asr-syllable-match和toneAssessed=false。item.audioIds对应GET /daily-audio/{asset_id}，支持Range并校验固定归档摘要；未登记/缺失/停用/损坏返回404。item.narrationId通过既有voice端点读取本机中文词句朗读。不接收文件路径、拼音文本或录音。没有专业评分端点；SPEC-009新增POST /daily-reading/{item_id}/recognize及guest对应路径，仅接16kHz单声道PCM16 WAV（最多30秒/960044字节），在Mac内存识别后返回matched/different/uncertain/unavailable、原转写与其拼音。不落盘，配对端点要求CSRF；访客同源检查。

SPEC-012新增`settings.playbackGapSeconds`：基础间隔数字0.1～5、步长0.1秒，默认1。PUT `/household/settings`可选传入，省略时保留。SQLite迁移6使用整十分之一秒存储；v5备份可选携带此字段，旧备份缺字段恢复为1秒。访客临时备份同样支持。READ-05在基础间隔上按刚播放条目每多一个音节增加0.5秒跟读等待，末条不等待；READ-06学生快捷设置仅保存在当前浏览器，不调用家庭设置接口，不改变备份中的家庭默认值。daily-reading的组词条目附`wordExample`（id、examples含text/pinyin、spokenText）；有完整中文音频的条目附`timings`（逐音节start/end秒），仅当音频及中文脚本摘要一致时提供，非儿童读音分析。

DEVICE-01：POST `/pair`可带可选`model`（最多80字符）；GET `/devices`返回`model`、`pairingCode`、`lastConnectedAt`，缺失历史数据为null。已用配对码不是可重用邀请，不返回会话令牌。认证请求可附`X-LP-Device-Model`用于旧设备首次补全类型提示，不覆盖已有型号；连接时间只使用服务端时钟。

ACCESS-03：家长API与`/local/pairing-code`仅接受来源127.0.0.1且Host hostname为127.0.0.1的请求；否则返回403 `PARENT_LOCAL_REQUIRED`。家庭/访客bootstrap的`isLocalHost`表示这一严格入口条件。远程bootstrap的`device.isParent`固定false，即使旧Cookie对应历史家长角色；新远程配对也仅学习角色。远程访客PUT课程/设置同样拒绝。提供的Uvicorn启动命令禁用代理头，不信任转发头授予管理权限。

## SPEC-017 游戏接口与时间状态

- `GET /games`：配对设备只读取得`clock`和最近7天`report`（answered、independentCorrect、hints、skipped、pendingClock、practiceKnowledgeIds）；读取不修改revision。
- `POST /games/heartbeat`：需要CSRF，家庭共享游戏授权最长12秒，返回服务端结算的sessionSeconds/dailySeconds、剩余额度remainingSeconds、短期leaseSeconds、reason及breakRemainingSeconds。浏览器4秒续期，单调时钟到期锁界面，失联/后台后先续期。
- `POST /games/pause`：需要CSRF，结算并结束家庭当前游戏授权，不清零单次用量；连续无授权10分钟才重新开始一次。
- `POST /sessions`可选`gameId`（sound/tone/shape/blend），选择当前课及之前已学内容中该模式最多6题；返回及恢复包含gameId。新游戏关闭此前活动游戏会话，已保存结果不丢失。
- `PUT /household/settings`可选整数gameSessionMinutes（1～60，默认15）、gameDailyMinutes（1～180，默认60）；仍需soundEnabled和本机家长权限，未传保留。
- 游戏hint/skip/首次answer在同一写事务内检查授权；超限返回409 GAME_SESSION_LIMIT/GAME_DAILY_LIMIT，过期GAME_PAUSED，回拨GAME_CLOCK_ROLLBACK。已成功答案的幂等回执仍可重读。普通课程接口不受游戏时长限制。
- 时间按服务器UTC、日额度按Asia/Shanghai零点；跨设备重叠区间只计一次。`profile.gameState`保存version、days、runSeconds、accountedAt、leaseUntil，不含凭据。SQLite迁移8、JSON备份v5的可选扩展见SPEC-005。访客通过现有operate白名单使用同一计算，但仅标签页保留额度。

SCENE/ADAPT修订：`GET /games`增加`recommendation`（level/speed/sampleSize/correctCount/masteredCount），仅统计家长所选课及之前知识的有效掌握样本。`POST /sessions`新增gameDifficulty（auto/gentle/steady/challenge）及gameSpeed（auto/slow/normal/fast），默认auto；游戏响应和恢复包含冻结的`gameSettings`（实际level/speed、requestedDifficulty/requestedSpeed、推荐快照、version=1）。题库优先场景对应类型，缺少时以已学听辨/声调/拼读补足，必须具备真实标准音。最多六题，优先待巩固和当前课，再按历史轮转；难度不解锁课程。SQLite迁移9增加sessions.game_settings_json，schema5备份增加可选session.gameSettings；旧会话/旧备份默认为空对象。浏览器物理状态不上传，未命中动作不调用作答API。

LEVEL-01～04：`POST /sessions`可选`gameLevelId`（如runner-01），须与gameId对应；省略按推荐物理难度选择一关。新游戏会话绑定12道不同的已学真实题目，普通课程仍6题。响应/恢复含`gameRun`（version=1、catalogVersion=1、level、theme、patterns和依次绑定instanceId的bindings），无教学标准答案。SQLite迁移10的sessions.game_run_json冻结数据；导出schema5会话可选gameRun，旧档案缺省{}，恢复校验12段与题实例精确对应。前端自动接续已完成检查点，暂停可停留；刷新仅重走当前未完成段，首次成绩仍幂等。家庭导入16MiB、访客4MiB，超限拒绝且不截断。

## SPEC-018 应用识别端口（无 HTTP 路由）

`src/domain/pronunciation.ts` 固定 v1 异步 `match` / `recognize` 契约。应用开发可显式注入始终成功的 mock，返回 evidence=mock、toneAssessed=false；省略模式不会启用 mock。这是进程内 TypeScript 端口，尚未发布新的 REST 接口。参数、状态、取消和真实实现边界见[接口说明](engineering/pronunciation-interface.md)。

## 专用拼读应用接口（MATCH-13～15）

`POST /api/v1/pronunciation/{targetId}/assess` 使用配对、同源/CSRF 与 X-LP-Request-Id，接收有界内存 PCM WAV，返回 MATCH-10 match/recognition 与保存回执。`GET /api/v1/pronunciation/{targetId}/history` 返回本家庭最近20条及完整状态计数。访客 POST 前缀为 `/api/v1/guest`，不写家庭库。默认专用模型未配置，返回 unavailable，不产生成绩。仅可信服务端 acoustic 摘要可写库；不接受客户端自报准确结果。目标白名单、格式/大小、幂等与备份字段详见[拼读应用契约](engineering/pronunciation-interface.md#应用组装与摘要match1315)。原 Whisper 音节匹配接口独立保留。

PLAY-01/02：POST `/sessions`可选`gameTaskCount`（严格整数3～20，默认6），新`gameRun.version=2`按题量均衡分配三章且绑定精确等于冻结题单。version=1保留十二绑定/各章四段兼容。PATCH `/sessions/{sessionId}/game-settings`需要CSRF及同家庭活动游戏，body为`difficulty`（auto/gentle/steady/challenge）、`speed`（auto/slow/normal/fast）；校验游戏额度后仅更新并返回gameSettings，保留原推荐依据、题单、路线和成绩。访客operate仅新增对此路径的PATCH白名单，同样保存至临时快照。游戏内修改题量是本设备下次开局偏好，不改变当前题单。
