# ADR 0019：Qwen3-TTS 普通话素材

2026-10-13采纳，替代ADR-0018的Kokoro模型和CPU引擎选择。用户试听后认为原声音效果不佳，要求中文支持更好的TTS。

选择Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice（Apache-2.0），使用mlx-community保留bf16精度的转换版本、固定revision和逐文件SHA。MLX-Audio 0.5.8在Apple Silicon本地Metal推理。固定原生中文女声Serena、Chinese语言及清晰温和教学语气；不克隆个人声音、不训练。模型卡与引擎官方来源登记在content/voice-build.json和依赖清单。

保留ADR-0018的素材部署方式：维护组显式下载、校验并生成；运行端只播放随Git提供的PCM16 WAV。不让开发者日常启动下载4.5GB TTS模型或安装MLX；维护生成需要Apple Silicon Mac。所有原始中文脚本直接输入模型，拼音标准音和课程源录音保持来源。按文本/完整配置去重，摘要、音色、模型revision进入manifest。

检查空音频、非有限值、静音、生成长度上限截断、浏览器实际解码和转写抽查。机器转写只用于漏字错读抽查，不证明主观自然度或儿童可理解性。样例提供给用户试听。
