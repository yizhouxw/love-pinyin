# 拼音小卖部接入与维护

SPEC-019 SHOP-01～03、ADR-0035。入口：学习首页 → 游戏乐园 → 拼音小卖部。

商品目录在 `content/pinyin-shop.json`，每个 targetId 引用 `content/illustrations.json` 的拼音、课序和标准音；教学答案不写在 React。发布校验检查商品ID/目标引用/去重/规则。每柜六件，每篮最多六件，首课三个单韵母礼盒；篮子、录音及识别结果都只在本轮内存，退出清除，不计入客观题掌握度。家庭游戏短租约沿用原 heartbeat，不增加数据库迁移。

## 开发演示

运行 `npm run dev`，打开开发服务器地址并添加 `?shopRecognition=mock`，再进入小卖部。仅 `import.meta.env.DEV` 允许这个显式参数；生产构建即使有同名参数也不会启用模拟。页面始终标记“开发模拟演示”，清单标记“模拟购物清单”，不判断声音或声调。

录音需 localhost 或受信任 HTTPS，显式点击后请求麦克风。读完点完成，30秒安全上限只保护内存，没有作答倒计时。开发 mock 端口本身忽略音频；场景仍完整走采音、转换和取消链路。

## 替换真实服务

组装入口为 `src/platform/audio/shop-pronunciation.ts`。实现 `PronunciationService` 后返回 `{ service, mock: false, configured: true }`，并让 PinyinShop 使用该配置。默认工厂返回 `configured: false` 和 unavailable 端口，禁止假成功。React 组件还提供 `recognition` 属性作为显式依赖注入点，测试专用场景位于 `tests/support/shop-harness.*`，不进入生产构建。

输入为 MATCH-10 的 requestId、可信目录 targetId、内存 WAV Blob、AbortSignal。采音转换在 `recording-wav.ts`，与天天练共用既有转换逻辑，16kHz/单声道/PCM16，不持久化音频。当前未注册模型HTTP路由，也不调用旧Whisper或暂停的小模型。

匹配结果须版本/请求/目标一致；正式模式的 matched/retry 仅接受 acoustic 证据。mock 仅在显式演示中接受；uncertain/unavailable/异常/超时不判错。15秒超时取消，切商品、重听、取消、暂停、额度到期、退出或后台取消所有旧请求；旧实现即使忽略 AbortSignal 也不能用迟到响应入篮。toneAssessed=false 时不宣称声调准确度。

浏览器专项包含真实录音转换 + 受控接口分支，不能用它证明真实儿童识别有效性。模型质量、实体移动设备、家庭LAN与儿童试用独立验收。
