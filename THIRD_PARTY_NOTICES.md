# 第三方与资产说明

本仓库自身代码、原创文档、原创题目与public/illustrations中的原创SVG采用MIT（见LICENSE）。该许可不覆盖第三方依赖的原始代码、模型权重、教材/政策网页、字体、声音或录音者人格权益。

当前未收录教材图片、课文、出版社音频、商用SDK、模型权重或儿童声音。`content/curriculum.json`是按事实索引组织的原创知识说明与题目草稿；`content/sources.json`仅提供依据链接，不宣称来源内容可以再分发。

- npm依赖声明见[自动依赖清单](docs/engineering/dependency-inventory.json)，按上游许可保留版权与notice。
- Python依赖、各轮子来源及校验哈希见`uv.lock`；主要许可和原生依赖注意事项见[依赖记录](docs/engineering/dependencies.md)。
- 本地转写研究额外依赖组 `audio-asr` 锁定 `pywhispercpp==1.5.1`（MIT）；Whisper multilingual small 权重为独立 MIT 资产，固定 revision/SHA 与用途限制见 [ADR 0003](docs/adr/0003-local-asr-transcription.md)。权重只在显式安装后存在于 Git 忽略目录，不随本仓库发布。
- 系统字体由操作系统提供，未打包字体文件；教学单层a/g与声调使用content/writing.json中的原创SVG轨迹。
- 标准音固定采用cmguo/PinYinSound，当前205个目标由183份私有MP3提供。归档来源与摘要见content/pinyin-source.json；其中licenseStatus仍为unknown，不把产品直接信任决定写成MIT授权，不提交这些声音文件。
- 本地评分引擎/模型登记在`content/assessment-manifest.json`，当前为空且未通过。后续任何模型必须记录来源commit、文件SHA256、权重许可、适用目标和验证证据。

开源发布前重新检查实际分发内容，不能以代码MIT替第三方素材消除条件。

## 家庭私有语音资源（2026-10-05）

`content/narration.json` 原创中文脚本为 MIT；由 Mac 已安装 Tingting 生成的 WAV 仅在用户本机 `private/learning-audio/` 使用，不作为 MIT 资产提交或再分发。系统声音与项目代码许可不同，参见 [Apple 软件许可](https://www.apple.com/legal/sla/) 及其中 system voices 条款（例如 [macOS Sonoma 许可](https://images.apple.com/legal/sla/docs/macOSSonoma.pdf)）。准备命令调用本机 `/usr/bin/say`，不联网、不自动下载音色，不合成拼音标准音。

用户提供的13份课程MP3仅复制到家庭私有资源目录，保留来源文件名与SHA；原文件不修改。它们不是本仓库MIT素材，也不替代PinYinSound逐目标标准音。公开仓库/发布包不包含它们；本机同源家庭/访客资源接口分别提供配对访问与只读体验。
