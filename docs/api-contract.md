# API 与数据契约

状态：除 health / capabilities / assessments 的未就绪响应外，以下均是下一阶段实施契约。后端运行时 `/openapi.json` 只描述已实现端点，不能把规划端点看成已经存在。

## 基本规则

- 前后端同源；API base 为 `/api/v1`，不允许在儿童页面输入任意评分 URL。
- JSON 用 UTF-8、NFC；ID 稳定且区分大小写；日期为 UTC ISO8601，业务日期固定 Asia/Shanghai。
- 错误体 `{error:{code,message?,retryable}}`，无堆栈、录音数据、密钥或数据库路径。
- 写操作需配对会话、Origin 检查、CSRF token 和请求体限制；没有通配 CORS。
- 路径参数不得转成任意文件路径；资源通过登记 ID 查找。无远程 URL 抓取或用户提交的模型名加载。

## 端点清单

| 方法/路径                            | 输入                    | 返回与约束                                                          |
| ------------------------------------ | ----------------------- | ------------------------------------------------------------------- |
| GET `/health`                        | 无                      | 200 服务状态；不暴露主机标识                                        |
| GET `/capabilities`                  | 无                      | 音频/评分可用性、引擎版本、支持目标；当前 available=false           |
| POST `/pair`                         | 短期 code               | Cookie + CSRF token；5次失败/分钟冷却；code 使用一次失效            |
| DELETE `/session`                    | Cookie + CSRF           | 204 清本设备配对，不删除家庭数据                                    |
| GET `/curriculum`                    | 配对                    | 已审校版本内容及 ETag；开发模式明确草稿                             |
| GET `/audio/{id}`                    | 配对 + 登记 id          | 正确 MIME / Range / 哈希；缺失404；禁止目录穿越                     |
| GET `/profiles`                      | 配对                    | 本地昵称/随机头像ID，不要求真名                                     |
| GET `/profiles/{id}/progress`        | 配对                    | `ProgressSnapshot` 与 revision                                      |
| POST `/profiles/{id}/attempts`       | 事件 + expectedRevision | 幂等插入；服务器生成时间；冲突409后重取，按attempt.id安全重试       |
| POST `/assessments`                  | 见下文                  | 本地评分结果；当前固定503未就绪，且不读取请求音频                   |
| GET `/assessments/{requestId}`       | 同一配对会话            | pending或已完成摘要；不重算；缓存过期返回410，目标不属于会话返回404 |
| GET `/attempts/{requestId}`          | 同一配对会话            | 已提交事件或404；客户端用原ID重试保证幂等                           |
| DELETE `/assessments/{requestId}`    | 配对                    | 取消；中止任务并清内存；晚到结果丢弃                                |
| GET `/profiles/{id}/export`          | 家长权限                | 限定schema JSON，不含声音或会话凭据                                 |
| POST `/profiles/{id}/import-preview` | 家长 + JSON≤1MiB        | 验证schema、内容版本、去重、知识引用；不写DB                        |
| POST `/profiles/{id}/import`         | 预览token+revision      | 单事务替换，过期或冲突409                                           |
| DELETE `/profiles/{id}/progress`     | 家长+确认token          | 原子清数据，不撤销其他设备；行为区别于注销整个家庭                  |

配对、认证和数据持久化尚待 SPEC-001，实现前基线仅允许开发者本机访问。

## 评分请求

`POST /assessments`：请求体为 `audio/wav` 原始 PCM WAV，单声道 16 kHz int16，最大 512 KiB、最长 10 秒。元数据放请求头 `X-Reading-Target-Id`、`X-Request-Id`、`X-Content-Version`、`X-CSRF-Token`。requestId 为 UUID，reading target 必须来自当前已审校内容。服务器必须流式累加字节上限，不使用会自动落临时文件的未配置上传方案。

语音 PCM 在 RAM 中解码；拒绝伪 WAV、头声明与实际长度不一致、超时、异常采样率。PCM 不传云、不写访问日志、SQLite、临时文件或故障附件；finally / 取消 / worker 回收路径释放 buffer。程序层及时释放不等同取证级物理内存擦除，不承诺后者。

初始超时预算：录音 10s、排队 5s、推理 5s、总请求 15s；预算是项目目标，SPEC-000 测量后修订。没有自动无限重试；429/503 不扣学习进度。重复 requestId 返回同一摘要，音频不进入去重缓存；摘要缓存 TTL 5分钟。客户端取消也取消 worker 工作。

`AssessmentResult` 见 `src/domain/contracts.ts`。`scored` 必须有 engineVersion、calibrationVersion、score、confidence 和有依据的维度；分值范围0–100、confidence范围0–1。不能衡量的维度缺省。`uncertain/unsupported/unavailable` 不含 score，不转成0分。具体阈值由真实样本验证确定，禁止主观设一个分段就称可靠评分。

## 存储设计（待实现）

`profiles(id,nickname,created_at)`；`attempts(id,profile_id,session_id,exercise_id,knowledge_id,mode,first_try_correct,hint_used,occurred_at,content_version,assessment_id)`；`profile_state(profile_id,revision,selected_lesson_id,settings_json)`；`assessment_summaries(id,profile_id,target_id,status,score_json,engine_version,calibration_version,created_at)`；`schema_migrations(version,applied_at)`。

外键约束和唯一索引必须显式建模。客户端不能写任意 profile，配对 session 需验证家庭范围。保存可重放客观事件而非只存累计百分比；题型/版本变更导致不兼容记录时保留历史但从新掌握度计算排除，家长可见原因。
