# SPEC-009：本地语音识别跟读判定

2026-10-13用户明确要求：不训练评测模型，以语音识别模型能否识别来判定，配置增加拼音跟读场景。此需求更新SPEC-008 DAILY-03与ADR-0014；不是专业发音/四声评分，不恢复旧SPEC-000。

## ASR-01：本地运行

使用现有固定pywhispercpp 1.5.1与已显式安装、校验的Whisper small模型，不训练、不下载新权重、不访问远程推理。新增pypinyin 0.55.0（MIT，官方PyPI），固定uv锁。配置集中content/reading-recognition.json，中文语言、拼音场景initial_prompt、关闭历史上下文、确定性解码、禁止实时转写日志。提示包含场景而不包含当前题目标答案，避免提示诱导复述。

## ASR-02：判定语义

- 返回matched（识别出的音节与目标相符）、different（识别到其他内容）、uncertain（未听清、噪声、过短、歧义或置信不足）、unavailable（服务/模型不可用）。这些不是儿童发音对错或分数。
- 显示原识别文字和转换后的拼音。汉字转拼音用词组上下文，不把目标答案注入转换器；比较声母/韵母音节，声母的教学呼读别名集中在内容配置。
- Whisper可能将ā与á均转为“啊”；汉字转拼音字典不能重建实际声调。本模式明确仅核对识别音节，不判四声准确性、送气精确度或口语能力。没有0–100分、正确成绩、掌握度写入。
- 拉丁拼音按音节空格/数字解析，混排与多余音节不能通过删除凑出答案；模棱两可的连写返回uncertain。

## ASR-03：录音流与资源

主动录音后可点击“让电脑判定”。浏览器将当前录音解码并重采样为16kHz单声道PCM16 WAV，只传本家庭Mac；不传外网。服务端内存读取，最大30秒/960,044字节，不写磁盘、SQLite、备份或日志。退出/换条/后台取消客户端请求，晚到响应不覆盖新条。过长不判错。

POST /api/v1/daily-reading/{item_id}/recognize：配对、同源与CSRF；访客同源受限端点提供同样识别，不建立访客档案。目标从内容白名单取，不接任意目标文本/文件路径。单模型互斥，忙时立即返回unavailable，避免排队耗尽内存；原课程继续可操作。推理超时用模型abort callback中断，模型缺失明确不可用，不自动下载。

## ASR-04：验收

用实际PinYinSound音频和本机词句WAV验证推理/匹配/不匹配，不将标准音自识别当作儿童准确率。补PCM边界、权限、静音、低置信、未登记ID、CSRF、并发、旧响应和资源释放测试。运行verify:all、validate:release与真实服务页面测试。真实儿童/麦克风/移动设备验收仍独立未完成。

## 本机验证记录（2026-10-13）

verify:all已通过：63项前端/工具、303项后端、30项视口、24项真实服务GUI，日志private/daily-reading-verify-final.log；后续界面提示和书签入口改动另跑verify/build。validate:release已通过840条示范资源、中文引导和现有固定模型摘要检查。

实际标准MP3本地试跑ā/á→啊、bō→波、zhī→知；Chromium和WebKit用标准MP3注入真实MediaRecorder流，完成WAV转换、真实Mac API/Whisper、相符与不同结果、切条清除。测试注入不是真实麦克风或儿童样本，不宣称儿童识别准确率、真机或家庭LAN完成。浏览器全部597标准音及42中文词句解码也已验证。

最终专项日志private/daily-product-final.log，页面截图private/daily-asr-product-desktop-chromium.png与private/daily-asr-product-desktop-webkit.png。未推送或公开素材。
