# SPEC-011：开源中文引导音频

用户2026-10-13要求选择适合项目、可本地运行的开源TTS并重新生成中文引导。采用Kokoro-82M-v1.1-zh的官方sherpa-onnx转换模型（附Apache-2.0许可），sherpa-onnx与core固定1.13.8放在voice-build维护组，不加入播放服务的运行依赖。模型、字典、参数、文件摘要集中content/voice-build.json。

- VOICE-06：所有中文指令、题目/选项/提示、书写/图片说明、天天练说明/42词句、识别反馈统一本地CPU生成。只合成原中文脚本，不合成拼音标准音；固定speaker3、speed0.95、四线程。去重但保留全部1270中文 ID及文本摘要。
- VOICE-07：输出PCM16单声道WAV与白名单manifest，校验非空/非静音/有效采样/摘要。资源及模型Apache-2.0许可进Git，模型大文件留忽略目录。服务从resources/audio读取，仍支持显式私有资源环境变量和旧Mac资源兼容，不把旧Tingting录音伪称开源素材。
- VOICE-08：维护者显式prepare:voice下载校验固定模型后可重生成；普通clone启动直接使用已提交录音，不加载或下载TTS模型。真实生成、实际浏览器解码及多条本地转写抽查；不将机器抽查冒称人工逐句听审。
