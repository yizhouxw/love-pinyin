# API 与数据契约

状态：下表混合已实现端点与目标端点；后端运行时 `/openapi.json` 只描述已实现端点，不能把规划端点看成已经存在。

## 基本规则

- 前后端同源；API base 为 `/api/v1`。首版没有语音上传或评分端点。
- JSON 用 UTF-8、NFC；ID 稳定且区分大小写；日期为 UTC ISO8601，业务日期固定 Asia/Shanghai。
- 错误体 `{error:{code,message?,retryable}}`，无堆栈、密钥或数据库路径。
- 写操作需配对会话、Origin 检查、CSRF token 和请求体限制；没有通配 CORS。
- 路径参数不得转成任意文件路径；资源通过登记 ID 查找。无远程 URL 抓取或用户提交的模型名加载。

## 端点清单

| 方法/路径                                        | 输入                       | 返回与约束                                                                                              |
| ------------------------------------------------ | -------------------------- | ------------------------------------------------------------------------------------------------------- |
| GET `/health`                                    | 无                         | 200 服务状态；不暴露主机标识                                                                            |
| GET `/capabilities`                              | 无                         | 标准音资源状态和内容审核状态                                                                            |
| POST `/pair`                                     | 短期 code                  | Cookie + CSRF token；5次失败/分钟冷却；code 使用一次失效                                                |
| DELETE `/session`                                | Cookie + CSRF              | 204 清本设备配对，不删除家庭数据                                                                        |
| GET `/devices`                                   | 家长配对会话               | 仅设备 ID、标签、加入时间和当前设备标记；不返回任何令牌                                                 |
| DELETE `/devices/{deviceId}`                     | 家长 + CSRF                | 撤销同一家庭的次设备；不能撤销当前家长设备                                                              |
| GET `/curriculum`                                | 配对                       | 课程内容明确为草稿；题目不含答案/提示，答案只在作答或请求提示后返回                                     |
| PUT `/household/current-lesson`                  | 家长 + expectedRevision    | 更改当前课程；revision 冲突 409；未知/过期选课不默默回退到第一课                                        |
| POST `/profiles/clock-pending/resolve`           | 家长 + CSRF                | 时钟恢复后将待校时练习整体删除，或保留为不计分练习；未恢复时返回 409                                    |
| PUT `/household/settings`                        | 家长 + CSRF                | 更新音频及减少动态效果设置；减少动态效果会随家庭备份保存                                                |
| POST `/sessions`                                 | 配对 + CSRF                | 冻结当前内容的最多6题会话；休息待处理时返回 `REST_REQUIRED`                                             |
| POST `/sessions/{id}/finish`                     | 配对 + CSRF                | 结束会话；仅全部题目已答/跳过的会话计为完整一轮                                                         |
| POST `/rest/complete`                            | 配对 + CSRF                | 清除连续轮次计数并允许继续练习                                                                          |
| GET `/audio/{id}`                                | 配对 + 登记 id             | 已实现：提供合格公开资源或本机已确认私有标准音，均核验摘要；正确 MIME/单段 Range；缺失404；禁止目录穿越 |
| GET `/profiles`                                  | 配对                       | 本地昵称/随机头像ID，不要求真名                                                                         |
| GET `/profiles/progress`                         | 配对                       | mastery snapshot、设置、家庭 revision 与服务端派生的完整会话数（花园叶片）                              |
| GET `/profiles/knowledge/{knowledgeId}/attempts` | 配对                       | 按知识点读取练习记录；稳定时间/ID 降序，cursor 分页，每页最多50条；游标限定同家庭、同知识点             |
| POST `/profiles/{id}/attempts`                   | 事件 + expectedRevision    | 幂等插入；服务器生成时间；冲突409后重取，按attempt.id安全重试                                           |
| POST `/instances/{id}/skip`                      | 配对会话 + CSRF            | 当前会话内幂等标记跳过；不创建作答/掌握事件，刷新可恢复                                                 |
| GET `/attempts/{requestId}`                      | 同一配对会话               | 已提交事件或404；客户端用原ID重试保证幂等                                                               |
| GET `/profiles/export`                           | 家长权限                   | 限定schema JSON，不含声音或会话凭据                                                                     |
| POST `/profiles/import-preview`                  | 家长 + JSON≤1MiB           | 已实现 schema v5 上传校验与5分钟预览token；显式迁移v2/v3/v4、严格校验且不写DB；最多缓存8个预览          |
| POST `/profiles/import`                          | 家长 + token/hash/revision | 已实现整档案单事务替换；revision过期/变化/跨家庭或hash不匹配均拒绝；家长UI已接入                        |
| DELETE `/profiles/data`                          | 家长+确认词                | 原子清练习/会话/复习/评分摘要与休息计数，保留家长设置和所有配对设备                                     |
| DELETE `/profiles/reset`                         | 家长+确认词                | 原子清学习数据/家长设置、撤销全部设备并清未使用配对码；清当前家长Cookie后要求重新配对                   |

配对、认证和数据持久化由 SPEC-001 实现。局域网部署仍需配置 HTTPS 与设备信任；开发服务器默认只用于本机开发。

若 `selected_lesson_id` 在当前课程包中不存在，`GET /profiles/progress` 保留并返回原 ID，客户端将其显示为待重新选择；`POST /sessions` 与 `POST /reviews/{knowledgeId}/sessions` 返回 409 `CURRENT_LESSON_REQUIRES_SELECTION`，不隐式回退首课、不创建会话。家长通过当前课更新端点选择有效课程后继续学习，历史会话与作答不变。

`GET /profiles/progress` 返回 `clockSkewDetected` 与 `pendingClockAttempts`。MAC 当前 UTC 时间比家庭档案最后观察时间回退超过 5 分钟时，后续新作答保留在本地数据库，但 `due_credit=0` 且 `clock_pending=1`，不参与掌握度或复习推进；时钟恢复到最后观察时间的 5 分钟范围内后，家长用 `POST /profiles/clock-pending/resolve` 并明确确认，将这些记录删除或保留为不计分练习。备份 schema v5 携带待校时标记；v2/v3/v4 迁移时旧记录默认不挂起。

## 未来可能的发音评测

发音评测已从首版移除，不存在 `POST /assessments`、评分状态查询或取消端点。历史备份 schema 与数据库可保留旧摘要字段以兼容旧数据，但新版本不创建评分记录。若未来重新启动，需新 SPEC 定义录音处理、局域网隐私、请求限制、结果契约和清理测试，再恢复相应 API。

## 存储设计（待实现）

`profiles(id,nickname,created_at)`；`attempts(id,profile_id,session_id,exercise_id,knowledge_id,mode,first_try_correct,hint_used,occurred_at,content_version)`；`profile_state(profile_id,revision,selected_lesson_id,settings_json)`；`schema_migrations(version,applied_at)`。迁移代码允许识别历史评分摘要字段，但新数据不写入。

外键约束和唯一索引必须显式建模。客户端不能写任意 profile，配对 session 需验证家庭范围。保存可重放客观事件而非只存累计百分比；题型/版本变更导致不兼容记录时保留历史但从新掌握度计算排除，家长可见原因。

## 语音优先家庭资源（2026-10-05，ADR-0005）

配对后 `GET /api/v1/learning-audio` 返回 `{ narration: Record<audioId, boolean>, lessons: Record<lessonId, {audioId,title,available,sourceType}> }`；可用性必须来自登记文件及摘要验证。`GET /api/v1/voice/{audioId}` 只读取固定私有根目录清单ID并支持Range，不接受文本合成、路径、外部URL。ID来自content/narration.json与lesson-recordings.json；内容文件与准备脚本记录不一致则不可用，不能播放旧题干。与 `/audio/{id}` 标准音审核路径分离；不产生任何作答记录。

## 私有标准音（ADR-0006）

`GET /curriculum` 的audioRequirements各项新增布尔`available`，由实际文件/摘要/审音记录计算，公开status/reviewStatus保持原值。`GET /audio/{id}`先选合格公开资源，再选当前目标签名匹配的家庭私有标准音；配对与Range规则不变。练习准入使用同一结果，撤下影响新会话和后续音频请求。

制作服务仅127.0.0.1:8019，与儿童API分离。GET `/api/catalog`（来源、候选、目标、草稿）；GET `/api/source/{id}`（固定目录内登记PCM）；POST `/api/preview`（sourceId,start,end）；POST `/api/draft`（另带targetId,expectedRevision）；POST `/api/activate`（targetId,sha256,revision,teachingReviewer,qualityReviewer及三项显式确认）；POST `/api/deactivate`（targetId,sha256）。写请求须持页面令牌；拒绝异源/非本机请求。草稿revision绑定源、边界、目标与摘要，旧版本返回409。工具不自动认证审音者资格。
