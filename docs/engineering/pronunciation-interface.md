# 拼读识别应用端口 v1

对应 SPEC-018 MATCH-10/11。真实模型后续沿 SenseVoice 编码器＋声母/韵母/声调专用头研发，当前质量未通过；本端口让应用可以先用 mock 开发。端口本身没有新增依赖或 HTTP 路由；2026-10-26 小卖部页面已按 SPEC-019 接入，真实模型仍未配置。

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

对已登记目标 mock 永远成功；未知目标返回 unavailable/unsupported-target，不猜预期内容。省略 mode 或使用 unavailable 时返回 unavailable/not-configured，没有隐式模拟。mock 只由开发组装代码显式注入；实际产品组装不得使用它作为自动裁决，模拟结果不写掌握度或真实识别成绩。小卖部页面已提供显式开发演示：Vite 开发服务器加 `?shopRecognition=mock`，生产构建忽略此参数。页面和购物清单标记模拟，不记学习成绩；正式默认未配置。见[场景接入说明](pinyin-shop.md)。

## 后续真实实现边界

真实家庭 Mac CPU 适配器将实现相同端口；HTTP、认证/CSRF、输入上限、超时与服务端目标目录届时另行验收，本文不宣称已提供这些端点。标准答案由服务端可信目录解析，不能信任客户端 pinyin。原始 SenseVoice 多头保留质量基准，SenseVoice50/CTC/INT8 是优化候选；质量/儿童验证未完成时能力声明仍应如实拒判。现有 daily-reading 的 Whisper 契约独立保留。

验证：`npm test -- --run tests/unit/pronunciation-service.test.ts`，覆盖始终匹配/预期内容、空及坏音频不读取、NFC、目录快照、并发关联、取消、默认不可用和未知目标。工程 mock 测试不等于模型有效性验证。
