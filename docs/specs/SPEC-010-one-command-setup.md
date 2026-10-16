# SPEC-010：clone 后一条命令运行

用户2026-10-13要求开发者clone仓库后直接运行；标准音自动git同步上游，其他资源纳入代码仓库。默认目标为当前项目的macOS开发环境，Git为系统工具前置，固定Node24/npm11/uv可在项目本地自动安装，不要求手工复制音频或下载模型。

- SETUP-01：根目录run.sh可从任意工作目录调用，安装锁定npm/uv依赖，自动clone或pull固定cmguo/PinYinSound仓库；导入登记的固定commit，不自动采用上游HEAD改动。校验205课程映射与600每日/组词标准音白名单文件摘要和解码。只在显式运行启动脚本时访问网络，应用运行不联网取音频。
- SETUP-02：用户已授权13份课程录音与原PDF加入当前私有代码仓库，保留独立非MIT说明。原创SVG/课程JSON/引导脚本已在仓库。中文引导已按SPEC-011用本地开源Qwen3-TTS重新生成并随仓库提供，不依赖Apple系统声音或手工复制。儿童跟读/数据库/密钥不打包。
- SETUP-03：首次显式启动自动安装已固定Whisper small并校验大小/SHA；已安装复用。权重不提交普通Git，GitHub单文件限制不允许488MB模型。无训练、云识别或运行时下载降级。
- SETUP-04：支持start（默认前台启动）、stop、restart、status；兼容top为stop别名。管理命令按LOVE_PINYIN_PORT（默认8000）选择实例，核对监听进程的工作目录与uvicorn应用/端口参数，不停止其他服务；status未运行返回3、端口被其他服务占用返回1。stop未运行幂等成功，发送TERM后最多等10秒，不强制杀进程；restart停止成功后走原启动准备流程。stop/status不安装依赖、不访问网络。支持--prepare-only、端口配置、正常Ctrl+C退出；重复启动复用已有资源，联网同步失败时仅在已验证固定源存在时可继续，首次失败明确退出。README给出唯一启动入口、首次耗时和工具前置。实际从干净checkout、新资源目录完整运行并验证健康、全部声音和识别模型可用；不能靠原private目录证明clone可运行。

初始版本实装证据（以下数量为835f296快照，当前数量见STATUS/SPEC-012，并非最新HEAD重新clone）：GitHub远端main的835f296全新clone到独立临时目录，PATH只留系统工具，run.sh自动安装Node24.18.1/npm11.16.0/uv0.12.5，完成新.venv、标准音Git导入、1284资源ID校验、固定Whisper首次下载/SHA校验、构建/发布门禁并在8002启动。健康、1270中文声音/14课音频/840条示范全可用，参考标准音API识别matched，真实Chromium播放通过；无TTS模型，无复制旧private/models。日志private/clone-start-success.log、clean-clone-proof.json、clean-clone-page.png。工程/发布/12项真实声音专项日志private/setup-voice-verify-all.log、setup-voice-release.log、open-voice-product.log。新增下载边界测试另外通过，不将标准音自识别称儿童准确率。
