# SPEC-019：拼音小卖部

2026-10-26，依据用户提供的橘黄量贩店 HTML 参考与 MATCH-10。借鉴暖橙货架、选商品、读包装拼音、入购物篮的流程；不复制参考文件的内嵌图片、字体或第三方素材。无新增依赖。

- SHOP-01：游戏乐园新增独立小卖部；商品、包装目标引用与规则集中在 content/pinyin-shop.json，目标拼音与示范复用 illustrations.json。限制当前已学课，首两课以单韵母礼盒参与，后续商品逐步增加。每次最多六件，每件只入篮一次；可查看购物清单、提前结束或完成后休息，无价格、购买、排行榜或无限奖励。全部操作可点击及键盘完成，窄屏可用。
- SHOP-02：依赖 MATCH-10 PronunciationService.match；显式点击才请求麦克风，停止后把浏览器内存录音转成有界 16kHz 单声道 PCM16 WAV。匹配须关联版本、requestId、targetId，且证据为 acoustic 才能正式自动入篮；retry 保留商品并给出再听/重读提示，uncertain/unavailable/异常不判错。toneAssessed=false 不声称声调判断。默认实现未配置，界面明确说明；不接入暂停的小模型，不降级 Whisper 或模拟。开发服务器可显式启用 mock 演示入篮，始终显示模拟标记，不写学习掌握度。
- SHOP-03：玩法、录音步骤、正确、重读、拒判及不可用状态均有随包中文引导；商品有真实标准音。复用家庭/访客游戏 heartbeat 时长；暂停、限额、切商品、重听、退出、隐藏页面均停止录音/播放并取消请求，忽略迟到结果。麦克风拒绝、格式失败、请求超时均可恢复。篮子仅本轮内存，不保存录音或识别分数，不写客观题成绩。

接口可注入真实实现；MATCH-10 真实模型和 HTTP 未完成时，不能把此场景称为真实儿童自动识别验收通过。软件流程、真实模型质量、移动真机、家庭 LAN 与儿童理解度分别记录。

## 实装与软件验收（2026-10-26）

SHOP-01～03按用户确认完成游戏与 MATCH-10 接入，真实模型另行验收。商品目录 `content/pinyin-shop.json` 提供24件商品/礼盒和已学目标引用；`src/domain/pinyin-shop.ts` 负责关联校验、声学/模拟证据边界与六件去重篮子；`src/app/pinyin-shop.tsx` / `.css` 提供货架、采音、提示与清单；`shop-pronunciation.ts` 为真实服务替换点，默认未配置。`recording-wav.ts` 抽取既有天天练转换，输入16kHz单声道PCM16；浏览器采音适配器给小卖部30秒安全上限，天天练仍120秒。无新增依赖、数据迁移或模型下载。

十段中文引导已按既有固定 Qwen3-TTS/Serena 配置本地生成，WAV与摘要清单随本提交入库并保留原许可。当前共1611中文ID/778个去重WAV。发布内容校验新增商品目标/ID/规则门禁。教学字体实测为随包 Andika Pinyin，单层 a/g；截图在 `docs/screenshots/pinyin-shop*.png`。

最终 `npm run verify:all` 通过：156项前端/工具、455项Python、36项六项目浏览器视口、40项真实服务GUI。`npm run validate:release` 通过。小卖部与全量中文声音专项按项目/用例去重共13项通过：Chromium真实采音转换及受控MATCH端口的匹配/重读/拒判/不可用/异常/关联不符、迟到响应/切商品/暂停/超时、六件完整入篮与模拟标记、麦克风拒绝恢复与租约暂停；Chromium/WebKit生产入口、键盘Enter、320/390/1280px、真实声音和暂停退出；两个引擎均实际解码全部778份中文WAV。9个WebKit采音用例显式跳过，未声称通过其麦克风路径。

首轮专项因入口精确名称未含箭头而失败，按真实可访问名称修正；麦克风/额度故障注入初次错误拦截了不存在的访客直连路由，改为访客实际 `/guest/operate` 事务及结果包后单项复验通过。首轮全套中既有WebKit权限测试5秒等待失败，单项及最终整套复跑均通过，未修改该权限用例或服务行为。最终日志为忽略目录 `private/shop-verify-all-final.log`、`shop-verify-final.log`、`shop-release.log`、`shop-browser-final.log`（12通过/1失败/9显式跳过，失败由 `shop-microphone-final.log` 补齐）、`shop-layout-final.log` 与 `shop-access-recheck.log`。未把早期失败算成通过。

剩余门禁：真实模型/HTTP/儿童语音质量独立接入与验收，WebKit真实采音、iPad/手机真机、家庭LAN故障及儿童理解度仍待实测。开发mock及受控端口用例只证明游戏状态处理，不证明识别准确率；正式模式当前只提供听示范/跟读，不自动裁决。
