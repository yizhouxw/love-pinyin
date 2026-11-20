# ADR-0044：Android Qwen3-ASR 离线识别

2026-11-20，采纳，SPEC-024 ANDROID-ASR-01～04。

Android 采用 sherpa-onnx 2.0.1 官方 AAR，通过 ONNX Runtime CPU 运行 Qwen3-ASR 0.6B int8 固定导出。与 Apple MLX 使用同一模型系列，运行库与权重格式分别固定，不复制 Apple 的 MLX 文件。模型配置集中于 content/android-asr.json，构建只随附运行库和清单；家长显式下载并逐文件校验后原子安装。下载专属执行器与识别执行器独立于课堂 SQLite 执行器，长推理不阻塞成绩保存。后台取消采音、使在途结果过期，恢复时由用户重新录音。

沿用现有 nativeOperation 录音、模型与转写协议；Android 10 系统 ICU Han-Latin 投影真实转写，再使用现有内容规则对照音节。仅 arm64/API29+ 提供识别，其他设备保留人工确认。采音、WAV及推理输入仅内存，不写磁盘或上传；识别不访问网络。包中新增 INTERNET 仅供固定 HTTPS 模型来源下载，RECORD_AUDIO 由系统弹窗授权；WebView 保持同源资源白名单。模型移除不触碰学习档案。

来源：[sherpa-onnx Android](https://github.com/k2-fsa/sherpa-onnx/releases/tag/v2.0.1)、[Qwen3 ONNX](https://k2-fsa.github.io/sherpa/onnx/qwen3-asr/pretrained.html)、[Qwen3-ASR 原模型](https://huggingface.co/Qwen/Qwen3-ASR-0.6B)。运行库与模型均 Apache-2.0；ONNX Runtime 为 MIT。不恢复 SPEC-018 暂停的自训编码器/匹配头实验。
