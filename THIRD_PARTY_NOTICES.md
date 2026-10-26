# 第三方与资产说明

本仓库自身代码、原创文档、原创题目与public/illustrations中的原创SVG采用MIT（见LICENSE）。该许可不覆盖第三方依赖的原始代码、模型权重、教材/政策网页、字体、声音或录音者人格权益。

当前未收录教材图片、课文、出版社音频、商用SDK、模型权重或儿童声音。`content/curriculum.json`是按事实索引组织的原创知识说明与题目；`content/sources.json`仅提供依据链接，不宣称来源内容可以再分发。

- npm依赖声明见[自动依赖清单](docs/engineering/dependency-inventory.json)，按上游许可保留版权与notice。
- Python依赖、各轮子来源及校验哈希见`uv.lock`；主要许可和原生依赖注意事项见[依赖记录](docs/engineering/dependencies.md)。
- 本地转写研究额外依赖组 `audio-asr` 锁定 `pywhispercpp==1.5.1`（MIT）；Whisper multilingual small 权重为独立 MIT 资产，固定 revision/SHA 与用途限制见 [ADR 0003](docs/adr/0003-local-asr-transcription.md)。权重只在显式安装后存在于 Git 忽略目录，不随本仓库发布。
- 拼音文字使用随包SIL Andika 7.000（OFL-1.1），Regular/Bold原始WOFF2及许可在public/fonts/andika，来源与摘要见content/pinyin-font.json。默认单层a/g，保留原Unicode拼音字符；中文仍使用系统字体。教学笔顺与占格由content/writing.json原创SVG提供，字体不替代书写轨迹。
- 标准音固定采用cmguo/PinYinSound，当前205个目标由183份私有MP3提供。归档来源与摘要见content/pinyin-source.json；其中licenseStatus仍为unknown，不把产品直接信任决定写成MIT授权，不提交这些声音文件。
- `content/assessment-manifest.json`仅保留历史研究登记，当前为空；首版无评分模型或评测依赖，不作为发布门禁。

开源发布前重新检查实际分发内容，不能以代码MIT替第三方素材消除条件。

## 家庭私有语音资源（2026-10-05）

`content/narration.json` 原创中文脚本为 MIT；由 Mac 已安装 Tingting 生成的 WAV 仅在用户本机 `private/learning-audio/` 使用，不作为 MIT 资产提交或再分发。系统声音与项目代码许可不同，参见 [Apple 软件许可](https://www.apple.com/legal/sla/) 及其中 system voices 条款（例如 [macOS Sonoma 许可](https://images.apple.com/legal/sla/docs/macOSSonoma.pdf)）。准备命令调用本机 `/usr/bin/say`，不联网、不自动下载音色，不合成拼音标准音。

用户提供的13份课程MP3仅复制到家庭私有资源目录，保留来源文件名与SHA；原文件不修改。它们不是本仓库MIT素材，也不替代PinYinSound逐目标标准音。公开仓库/发布包不包含它们；本机同源家庭/访客资源接口分别提供配对访问与只读体验。

## 用户提供《一年级天天练拼音》

来源：行知小学一年级语文组，2026年9月，根目录用户提供PDF，SHA-256见content/daily-reading.json。转换为14份家庭每日跟读资料，保留原份号与PDF页码。不主张对原练习取得MIT许可；源PDF不提交Git，不公开发行本功能内容包。标准音复用既有固定cmguo/PinYinSound归档；42条中文词句用已安装macOS Tingting本机生成，个人家庭使用、不公开再分发。没有新增运行依赖。

## 本地跟读识别（SPEC-009）

pypinyin==0.55.0，MIT，官方https://pypi.org/project/pypinyin/0.55.0/ 与 https://github.com/mozillazg/python-pinyin；uv已锁定并实际安装。pywhispercpp==1.5.1（MIT）由原维护工具依赖提升为应用运行依赖，版本未改变，复用已锁定numpy。Whisper small固定来源、大小、SHA-256、MIT见scripts/asr_model.py；本次读取已有模型，无新模型下载、训练或外部识别。

## 2026-10-13 clone资源与开源中文声音更新

用户明确授权将当前13份课程MP3与《一年级天天练拼音》PDF提交当前私有仓库供开发者使用，文件位于resources/audio/lessons与resources，保留用户提供、非MIT的来源说明；此请求覆盖上文“不提交”限制，不授权以代码MIT公开发行原素材。儿童声音、数据库、证书、模型权重不包含。

旧Tingting生成录音未进入Git；现行中文声音由本地Qwen3-TTS-12Hz-1.7B-CustomVoice生成，模型Apache-2.0，官方模型卡https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice；mlx-community的bf16转换、固定revision、逐文件SHA和参数在content/voice-build.json，许可原文在resources/licenses/Qwen3-TTS-Apache-2.0.txt。本项目提供的原创脚本与生成音频可按Apache-2.0使用，课程录音/PDF仍排除。音频不含真实儿童或克隆用户人声。

维护组mlx-audio==0.5.8来自官方PyPI/Blaizzy/mlx-audio（MIT），mlx==0.32.3/mlx-metal==0.32.3（MIT）提供本地Apple Silicon推理；transformers==5.19.0（Apache-2.0）仅加载本地分词器，所有传递依赖精确版本/轮子SHA由uv.lock固定，许可证元数据见Python依赖清单。普通启动不安装或运行TTS维护组，不提交原生库或模型权重。此前Kokoro/sherpa-onnx已从维护组和发布素材移除。

SPEC-012新增Qwen3-ForcedAligner-0.6B，Apache-2.0；官方Qwen/Qwen3-ForcedAligner-0.6B，mlx-community固定8bit转换的revision/SHA在content/reading-alignment-build.json，许可原文resources/licenses/Qwen3-ForcedAligner-Apache-2.0.txt。仅维护时本地对齐原创脚本与合成示范，输出time轴不含儿童声音/信息；权重不入Git，不作为儿童发音评测器。72张新增SVG为项目原创MIT资产，不使用外部插图、平台emoji或教材扫描。

## SPEC-013 私有 Docker 镜像

镜像在构建期装入固定 PinYinSound 音频与 Whisper small，以便运行时完全使用本地资源。此打包不改变 PinYinSound 的 unknown 许可、课程/PDF的独立来源及其公开分发边界，不自动发布到公共镜像仓库。Whisper MIT 许可全文随包保存于 resources/licenses/Whisper-MIT.txt，来源为 OpenAI whisper v20250625 的 LICENSE（https://github.com/openai/whisper/blob/v20250625/LICENSE）。基础镜像、Debian构建工具和运行库的固定版本/官方来源见 docs/engineering/dependencies.md，OS组件许可保留于镜像/usr/share/doc。

## 2026-10-25 天天练一声派生示范（DAILY-12）

用户授权将固定PinYinSound中缺少一声的10个音节在本机处理为一声并记录来源。现有来源录音的unknown许可不变；本地派生WAV不纳入代码MIT或Qwen Apache许可，不提交Git、不对外发布。来源SHA、PSOLA参数在content/daily-reading-policy.json，结果SHA与配置摘要在private/pinyinsound/daily-first-tones.json。显式准备使用既有afconvert（macOS）或ffmpeg（Linux）及Python标准库，无新依赖；音高分析复用uv.lock维护组的librosa 1.0.0/numpy 2.5.3/scipy 1.18.1。

## 2026-10-26 预训练拼音匹配比较（SPEC-018 MATCH-07～09）

本轮为本地底层研究，权重与公开语音保存在忽略目录，不随代码再分发；固定版本、下载 URL、大小、SHA256 和已知许可边界见 `content/pronunciation-pretrained-models.json`，核验说明见 `docs/research/pretrained-matcher-model-audit.md`。不以模型卡准确率或汉字转写正确替代发音效果验证。

- HanziFlow V2.1：`thin-nwe-soe/hanziflow-v2-1-multihead-wav2vec2@93c4b3f185f67b2f82135b34ca0397ddf8254de1`，模型卡声明 Apache-2.0；保留 AISHELL-1 及中文 XLSR 基础检查点归属，卡片不含逐句训练清单。
- Charsiu：权重 `charsiu/zh_xlsr_fc_10ms@2d274d10cce1dd66818c0706abbc4cc20d4ef710`；官方项目 `lingjzhu/charsiu@13a69f2a22ca0c0962b75cc693399b0ae23a12c9` 声明 MIT，版权 2021 jzhu，完整文本为 `resources/licenses/Charsiu-MIT.txt`。HF 权重仓库未单独声明许可证，故保留独立权重许可不确定性，不宣称已获得统一 Apache-2.0 权重许可。
- SenseVoiceSmall：`FunAudioLLM/SenseVoiceSmall@3847d57b6bdf2dd8875cb1508d2af43d80a16bf7` 的权重适用 **FunASR Model Open Source License Agreement 1.1**；完整固定文本为 `resources/licenses/SenseVoice-FunASR-Model-License-1.1.txt`，来源 FunASR `fbbfe01800a8c4c9103cb2150fb1a5d06cc64758`。其 HF 模型卡标记 `other`，不能用代码 MIT 代替权重条款。
- 本地 SenseVoice SANM 推理实现参考并改写 QwenAudio/SenseVoice `586bbdb2b052f4fe19322581825228b6810a9fb3` 的 MIT 代码；保留官方完整版权和 MIT 文本于 `resources/licenses/SenseVoice-MIT.txt`。

新增研究依赖只在 `tools/pinyin-pretrained/pyproject.toml` 与其 `uv.lock` 精确锁定，应用运行依赖不变；实际安装和 CPU 运行结果记录在本轮研究报告。

## 2026-10-26 独立音高前端（SPEC-018 MATCH-05）

SwiftF0 0.3.0，Copyright (c) 2025–2026 Lars Nieradzik，MIT；来源 https://github.com/lars76/swift-f0 ，完整许可保留于 `resources/licenses/SwiftF0-MIT.txt`。本地显式安装的135090字节ONNX摘要为 `6385e8c2ebc3872e82c9ff5946228de44cd3be77a750ea53698b7dbfe94b0a22`，权重留忽略目录；部署包复制模型时同时复制许可并核对摘要。适配器不自动下载、不加载通用ASR。

Praat-Parselmouth 0.4.7（GPL-3.0-or-later）仅为隔离工具环境内的离线音高诊断对照，不进入推理包、不包含于应用发布；实际arm64 wheel安装记录与锁定摘要见 `docs/research/matcher-pitch-swift.md` 及 `tools/pinyin-matcher/uv.lock`。

## 2026-10-26 真实拼音研究语料（SPEC-018 MATCH-08）

ManDi：Liang Zhao、Eleanor Chodroff，_The ManDi Corpus: A Spoken Corpus of Mandarin Regional Dialects_，LREC 2022，1985–1990；[原论文](https://aclanthology.org/2022.lrec-1.213/)、[原始语料](https://osf.io/fgv4w/)，**CC BY-NC 3.0**，仅非商业用途。固定 OSF 文件 ID、版本及 SHA256 见 `content/pronunciation-pretrained-data.json`，本机音频、派生片段和原始 TextGrid 不进入 Git；代码 MIT 不覆盖语料及其非商业限制。

OMPAL：Wen-Wei Hsieh、Hao-Wei Chi、Kuan-Chen Wang、Ping-Cheng Yeh、Te-hsin Liu、Chen-Yu Chiang，_OMPAL: Bridging Speech and Learning with an Open-Source Mandarin Pronunciation Assessment Corpus for Global Learners_，Interspeech 2025，2415–2419，DOI [10.21437/Interspeech.2025-983](https://doi.org/10.21437/Interspeech.2025-983)。[官方仓库固定修订](https://github.com/phantomhsieh/OMPAL-corpus/tree/c3aaa9e892e4b1c2a25b637401f52f6e35b53e74)，**CC BY 4.0**，原许可全文保存在 `resources/licenses/OMPAL-CC-BY-4.0.txt`。音频及完整专家注释保存在忽略目录；本仓库的拼音上下文政策保留原语料词句及 CC BY 4.0 归属，另附本地的变调/歧义范围标记；旧注释 ID 到 WAV ID 的映射由官方注释完整身份重建，不修改专家票数。固定来源、Git blob SHA、元数据 SHA256 见 `content/pronunciation-ompal-data.json`，实际下载 WAV SHA256 记在本机可复现的清单中。以上许可不代表已经验证儿童发音效果。
