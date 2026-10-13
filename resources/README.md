# 开发运行素材

用户2026-10-13明确要求将现有课程录音与PDF纳入当前私有仓库，供获授权开发者clone后启动。audio/lessons包含13份原课程MP3；PDF为原每日练习材料。均为用户提供素材，不适用项目MIT，不是儿童跟读录音；不得以代码MIT许可公开再分发。用途/课程映射见content/lesson-recordings.json和content/daily-reading.json。

中文操作说明的原创文本在content，现已用本地Kokoro-82M-v1.1-zh重新生成到audio/narration，附带模型Apache-2.0许可；系统音色及其旧生成录音不在仓库。标准音通过一键脚本同步外部固定来源，Whisper模型首次显式启动下载并校验。见THIRD_PARTY_NOTICES.md。
