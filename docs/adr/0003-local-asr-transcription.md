# ADR 0003：本机 Whisper 转写草稿工具

- 日期：2026-09-27
- 状态：已采纳用于本机素材整理；不得视作教学评分方案
- 约束：ASR 只在自有 Mac Studio 本地运行，不向云端发送音频；模型小于 5 GB

## 决定

1. 使用 `pywhispercpp==1.5.1`（MIT，PyPI 官方发行）连接 `whisper.cpp`，载入 OpenAI Whisper 多语种 `small` 权重。权重来自 Hugging Face `ggerganov/whisper.cpp`，固定 revision `5359861c739e955e79d9a303bcbc70fb988958b1`，文件 `ggml-small.bin` 为 487,601,967 字节，SHA-256 `1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b`，MIT。模型约 466 MiB，低于 5 GB。
2. 模型必须由维护者显式运行 `uv run --locked --group audio-asr python -m scripts.fetch_asr_model` 下载到 Git 忽略的 `models/`；下载后校验精确大小和 SHA-256。应用启动和客户端请求不会触发下载。
3. `scripts.transcribe_audio_candidates` 仅为维护者批量整理本地素材，生成含候选 ID、来源时间码、片段哈希、转写和模型元数据的人工听审草稿。程序校验片段路径、SHA-256。候选素材、权重和导出结果不进 Git。
4. 使用小批试跑检查格式与流水线后，需对真实素材逐条人工听审。中文/英文支持来自 Whisper 多语种能力；儿歌式念读、单个声母/韵母、拼音符号及中英混读的准确率尚无本项目实测结论，不用该转写自动回填课程答案。
5. 该组件不接儿童产品 API/界面，不作为自动发音评分器；绝不以 ASR 命中或置信信息生成儿童分数。首版评分已取消，SPEC-000暂停；若重启须另立SPEC。

## 依据

- [OpenAI Whisper README](https://github.com/openai/whisper/blob/main/README.md)：多语种识别任务与模型许可证。
- [whisper.cpp](https://github.com/ggml-org/whisper.cpp)：Apple Silicon 支持及量化模型资源要求。
- [固定模型文件](https://huggingface.co/ggerganov/whisper.cpp/blob/5359861c739e955e79d9a303bcbc70fb988958b1/ggml-small.bin)：文件及权利元数据。
- [pywhispercpp](https://github.com/absadiki/pywhispercpp) 与 [PyPI wheel](https://pypi.org/project/pywhispercpp/1.5.1/)：Python 接口及固定版本。

## 复审条件

本机试跑显示系统性漏识别/误识别、arm64 推理时延不可接受、权重元数据/哈希变化，或需要在面向儿童的产品流程里直接使用 ASR 时，重新评估；产品用途必须先修订 SPEC 并明确隐私/准确性验收。

## 本机执行记录（2026-09-27）

在 Apple M2 Ultra 上通过 Metal 加载固定 small 权重并处理本地候选目录 427 段，导出完整 CSV 于用户 Documents 目录（不进 Git）。中文讲解长句大体可读；针对字母/音节的片段存在明显错字、将拼音/读音转成汉字或注音符号、音乐/短音段不稳定等现象，例如“单韵母”被识别成“单孕母”。本次只是流水线连通性检查，没有人工逐条校对/计算识别率，也没有英文专门基准。因此确认模型能本机运行及粗略转写普通话，**没有证明其适合可靠识别拼音教学音**；结果只可辅助定位候选段，不能自动生成教学素材或评分。
