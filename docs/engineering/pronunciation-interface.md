# 拼读识别应用端口 v1

对应 SPEC-018 MATCH-10/11。真实模型后续沿 SenseVoice 编码器＋声母/韵母/声调专用头研发，当前质量未通过；本端口让应用可以先用 mock 开发。没有新增依赖。MATCH-13～15 已新增应用交互、同源 HTTP 桥接与独立摘要记录；真实模型仍未启用。

类型定义：`src/domain/pronunciation.ts`。实现：`src/platform/audio/pronunciation-service.ts`。应用依赖 `PronunciationService` 接口，通过依赖注入替换实现，不依赖研究 Python 或模型包。

## 调用

```ts
import type { PronunciationService, PronunciationTarget } from '../../domain/pronunciation';
import { createPronunciationService } from './pronunciation-service';

// targets 由 content/ 的课程或练习目录映射，不能在组件内重新编写答案。
export function createDevelopmentRecognition(
  targets: readonly PronunciationTarget[],
): PronunciationService {
  return createPronunciationService({ mode: 'mock', targets });
}

// 在应用组装处显式选择开发实现。
// const service = createDevelopmentRecognition(targets);
// const controller = new AbortController();
// const request = {
//   requestId: crypto.randomUUID(),
//   targetId: currentTarget.id,
//   audio: wavBlob,
//   signal: controller.signal,
// };
// const match = await service.match(request);       // status: 'matched'
// const content = await service.recognize(request); // recognizedPinyin: 当前目标预期拼音
// 切题、退出、后台时 controller.abort()，并按 requestId/targetId 忽略迟到结果。
```

目标含 id、pinyin、task；task 为 syllable（完整音节）、initial（声母呼读）、final（韵母）、blend（分拼合读）、sequence（词句）。这是接口的表达范围，不是实际模型的已验证覆盖。目录在构造时快照，显示拼音转换 NFC，ü 不转换为内部 v。空 ID/拼音及重复 ID 拒绝构造。每次调用必须有非空 requestId 和 targetId；requestId 由调用方唯一生成，不提供服务端幂等或结果持久化。

音频为浏览器内存中的 16kHz 单声道 PCM16 WAV Blob；采音与格式转换由调用方适配器负责，不把 Blob URL、文件路径或远程 URL 交给此端口。mock 完全忽略音频，空 Blob 和坏格式也按预期成功，不需模型、麦克风或网络。未来真实实现必须校验音频并独立从声音识别；recognize 的目标只是任务上下文，输出可以与预期不同。

## 返回与错误

所有返回含 contractVersion=1、requestId、targetId、evidence（mock/acoustic/none）、toneAssessed。mock 始终 evidence=mock、toneAssessed=false，不返回相似度、置信度或评分，不可用于声调能力或准确率验收。

| 方法      | 状态        | 内容                                                              |
| --------- | ----------- | ----------------------------------------------------------------- |
| match     | matched     | 目标匹配，reason=null；mock 的固定行为                            |
| match     | retry       | 有充分声学证据明确不符，reason=null；mock 不产生                  |
| recognize | recognized  | recognizedPinyin 为实际识别的 NFC 拼音；mock 固定返回目录预期内容 |
| 两者      | uncertain   | 无充分判断证据，reason 必填；内容识别 recognizedPinyin=null       |
| 两者      | unavailable | 模型/服务/目标不可用，reason 必填；内容识别 recognizedPinyin=null |

reason 枚举见类型：unsupported-target、not-configured、invalid-audio、insufficient-evidence、model-unavailable、timeout、busy、network-error。未来网络/模型失败转成 unavailable，声音不可评估转成 uncertain，不能转成 retry 或自动切 mock。用户取消以 Promise 拒绝 AbortError 表达，不显示“读错”；非法请求标识属于开发错误，抛 INVALID_PRONUNCIATION_REQUEST。

对已登记目标 mock 永远成功；未知目标返回 unavailable/unsupported-target，不猜预期内容。省略 mode 或使用 unavailable 时返回 unavailable/not-configured，没有隐式模拟。mock 只由开发组装代码显式注入；实际产品组装不得使用它作为自动裁决，模拟结果不写掌握度或真实识别成绩。课程详情和天天练已有页面入口；开发测试可显式给 PronunciationResults 注入该 mock。产品默认用家庭 HTTP 适配器，不存在自动 mock 开关。

## 后续真实实现边界

真实家庭 Mac CPU 适配器将实现相同端口；HTTP、认证/CSRF、输入上限、超时与服务端目标目录届时另行验收，本文不宣称已提供这些端点。标准答案由服务端可信目录解析，不能信任客户端 pinyin。原始 SenseVoice 多头保留质量基准，SenseVoice50/CTC/INT8 是优化候选；质量/儿童验证未完成时能力声明仍应如实拒判。现有 daily-reading 的 Whisper 契约独立保留。

验证：`npm test -- --run tests/unit/pronunciation-service.test.ts`，覆盖始终匹配/预期内容、空及坏音频不读取、NFC、目录快照、并发关联、取消、默认不可用和未知目标。工程 mock 测试不等于模型有效性验证。

## 应用组装与摘要（MATCH-13～15）

- `src/app/pronunciation-practice.tsx` 提供课程目标选择、主动录音、回放和共用结果交互；天天练借用原录音 Blob URL，经共享 `recording-wav.ts` 的 `recordingWav` 转为内存 PCM WAV。原 Whisper 比较独立显示，不写专用拼读成绩。
- `src/platform/audio/pronunciation-http.ts` 实现同一 MATCH-10 端口，同一 request 对象的 match/recognize 共享一次评估。`assess` 额外返回保存回执，用于显示保存状态。服务端响应必须关联请求与目标，不接受 mock；网络/协议失败不可用、音频拒绝不计错，取消为 AbortError。
- `POST /api/v1/pronunciation/{targetId}/assess`：配对、同源、CSRF，`X-LP-Request-Id` 为8～80字符的请求 ID，body 仅16kHz/单声道/PCM16 WAV，0.15～30秒、最大960044字节。服务端目录解析目标，body 不传答案。响应包含 match、recognition、createdAt、saved。默认 `server.pronunciation.evaluate` 返回 unavailable/not-configured，不能调用实验模型或 Whisper 冒充专用声音证据。后续可信后端在此替换，仍须独立验收质量、超时和并发资源边界。
- `GET /api/v1/pronunciation/{targetId}/history`：本家庭最近20条摘要与完整状态计数。只有服务端 acoustic 证据可存库；同家庭/请求 ID 幂等，同 ID 换目标409。摘要包含时间、目标、匹配/识别结果及声调能力，无录音。只有 matched/retry 进入有效分母，uncertain/unavailable 单列，不改客观题掌握度。SQLite 新表随迁移11创建；JSON备份5新增可选 pronunciationAttempts 字段，兼容已有备份。家长恢复预览显示摘要条数，清除与重置同时清除。
- 访客 POST 使用 `/api/v1/guest/pronunciation/{targetId}/assess`，仅校验同源，无家庭写入，摘要在当前结果组件内存显示。退出、切目标或刷新后不持久保留。

开发目标目录由 `src/platform/audio/pronunciation-development.ts` 导出，产品主包不加载整份每日 mock 目录。mock 仅供显式依赖注入（例如 `service={createPronunciationService({mode:'mock', targets: pronunciationTargets})}`），展示“开发模拟”且不保存。没有真实模型的产品默认只能验证录音、拒判和记录边界；不能宣称儿童准确率验收完成。

SPEC-019 小卖部按用户要求通过内容配置显式启用模拟体验，正式构建也可玩；页面和购物清单标记不是真实识别，不使用麦克风或记学习成绩。课程和天天练的正式后端仍独立默认不可用。见[场景接入说明](pinyin-shop.md)。
