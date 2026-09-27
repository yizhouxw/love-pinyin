# 第三方与资产说明

本仓库自身代码、原创文档、原创题目采用MIT（见LICENSE）。该许可不覆盖第三方依赖的原始代码、模型权重、教材/政策网页、字体、声音或录音者人格权益。

当前未收录教材图片、课文、出版社音频、商用SDK、模型权重或儿童声音。`content/curriculum.json`是按事实索引组织的原创知识说明与题目草稿；`content/sources.json`仅提供依据链接，不宣称来源内容可以再分发。

- npm依赖声明见[自动依赖清单](docs/engineering/dependency-inventory.json)，按上游许可保留版权与notice。
- Python依赖、各轮子来源及校验哈希见`uv.lock`；主要许可和原生依赖注意事项见[依赖记录](docs/engineering/dependencies.md)。
- 本地转写研究额外依赖组 `audio-asr` 锁定 `pywhispercpp==1.5.1`（MIT）；Whisper multilingual small 权重为独立 MIT 资产，固定 revision/SHA 与用途限制见 [ADR 0003](docs/adr/0003-local-asr-transcription.md)。权重只在显式安装后存在于 Git 忽略目录，不随本仓库发布。
- 系统字体由操作系统提供，未打包字体文件；教学单层a/g和声调字形需审校后选用明确许可的素材或原创SVG。
- 167项计划音频（89项标准音、78项指令音）目前为`not-recorded`。必须取得表演者书面许可、版权与再分发权，核验后再入库；计划使用MIT不是已取得授权。
- 本地评分引擎/模型登记在`content/assessment-manifest.json`，当前为空且未通过。后续任何模型必须记录来源commit、文件SHA256、权重许可、适用目标和验证证据。

开源发布前重新检查实际分发内容，不能以代码MIT替第三方素材消除条件。
