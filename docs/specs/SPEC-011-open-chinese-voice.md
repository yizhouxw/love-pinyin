# SPEC-011：开源中文引导音频

用户2026-10-13要求选择本地开源TTS重新生成中文引导，试听Kokoro后反馈声音效果不佳，要求更适合中文。现采用Qwen3-TTS-12Hz-1.7B-CustomVoice（Apache-2.0）的mlx-community bf16转换，MLX-Audio 0.5.8仅放voice-build维护组，不加入播放服务依赖。模型revision、参数、逐文件SHA集中content/voice-build.json，架构选择见ADR-0019。

- VOICE-06：所有中文指令、题目/选项/提示、书写/图片说明、天天练说明/42词句、识别反馈统一本地生成。只合成原中文脚本；不合成拼音标准音。保留已有ID及文本摘要，覆盖全部当前中文脚本并去重；当前1556中文ID/722 WAV，包含SPEC-012新增内容，数量以content与manifest校验为准。
- VOICE-07：输出PCM16单声道24kHz WAV与白名单manifest，检查非空/非静音/有限样本/长度截断/摘要。资源及模型Apache-2.0许可进Git，模型大文件留忽略目录。服务从resources/audio读取，仍支持显式私有资源环境变量和旧Mac资源兼容。
- VOICE-08：维护者在Apple Silicon Mac显式prepare:voice下载校验固定模型后重生成；普通clone启动直接播放已提交录音，不安装MLX、不加载或下载TTS模型。真实生成、浏览器全量解码及本地转写抽查；不将机器抽查冒称人工逐句听审。
- VOICE-09：固定普通话温和女声Serena、Chinese语言、清晰自然的教学语气、bf16精度、种子及采样参数。先生成真实欢迎语和答题反馈试听，再替换整套中文素材。模型与分词器均从校验后的本地路径加载，设置离线模式；不训练、不克隆个人声音。标准拼音和原课程录音保持原来源。一键启动不新增TTS下载。

Kokoro上一版曾完成1270中文ID/436 WAV及浏览器解码；用户主观试听不满意，故更换模型。新的自然度仍需用户试听判断，工程检查不能替代该判断或儿童家庭试用。

VOICE-09初始版本真实生成记录（扩充前数量，当前见SPEC-012）：1270中文ID/436 WAV，PCM16 mono 24kHz、约104.5MB；含课程录音共1284 ID/449文件。固定模型文件全部摘要校验通过，普通run.sh --prepare-only通过且运行环境未安装mlx_audio。8001服务返回欢迎语摘要与新WAV一致，页面已刷新。日志private/qwen-full-build.log、qwen-start-check.log；16条本地Whisper抽查覆盖欢迎/反馈、教学规则、长提示与孤立词，转写仍有同音字和短词识别差异，不据此声称逐字发音或自然度已人工确认。

该版本VOICE-09验证通过：verify:all（311 Python、30本机视口、24真实服务流程及前端检查）、变更后verify、validate:release、一键准备检查、12项Chromium/WebKit真实声音专项；两个浏览器逐份解码全部436 WAV，并播放说明、验证597标准音/42词句、真实录音识别和引导开关。日志private/qwen-verify-all.log、qwen-verify-final.log、qwen-product.log。未关闭移动真机/LAN及儿童家庭试用门禁；自然度需用户试听。

prepare:voice当前还运行SPEC-012的字音时间轴构建；首次维护额外准备约1.3GB固定对齐模型。播放服务只读取已提交WAV/时间轴，不加载TTS或对齐模型。
