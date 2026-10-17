# SPEC-010：clone 后一条命令运行

用户2026-10-13要求开发者clone仓库后直接运行；标准音自动git同步上游，其他资源纳入代码仓库。默认目标为当前项目的macOS开发环境，Git为系统工具前置，固定Node24/npm11/uv可在项目本地自动安装，不要求手工复制音频或下载模型。

2026-10-17补充 SETUP-05：已配置家庭HTTPS的机器，`run.sh`与`lovepinyin`的默认启动/start同时提供本机HTTP和LAN HTTPS；stop/top、restart、status统一管理两者。HTTP端口沿用`LOVE_PINYIN_PORT`（8000），HTTPS独立使用`LOVE_PINYIN_HTTPS_PORT`（8443）。配置保存在忽略目录`private/server.env`，仅允许已知的服务配置键和字面值，环境变量优先；不执行配置中的shell代码。绑定IP、证书、密钥三项完整后启用HTTPS，部分配置或失效证书必须明确失败，不能把只有HTTP当成成功；全无配置的新安装保留本机启动并提示HTTPS未配置。继续复用SPEC-006的本机IP、有效期、SAN和密钥预检，不生成证书、不安装系统信任或登录启动。

SETUP-05生命周期：status仅在所有已配置入口运行时返回0，缺失入口返回3，外来端口占用返回1，并逐入口列出状态；stop/top不要求证书仍有效、幂等停止两端，不下载或安装。停止前检查全部目标端口归属，任何外来服务均不发送信号。restart先验证HTTPS配置再停服；start补齐缺失的入口，不因HTTP已运行而跳过HTTPS，也不在修复部分运行时重新安装依赖。前台Ctrl+C和新启动的任一进程异常退出时清理本次启动的其他进程，不停止复用的旧进程。`lovepinyin`保留后台启动并打开本机页面的习惯，以本次启动就绪标记和完整status判断成功，不能只等待HTTP。回归须覆盖真实监听、部分运行、双端停止、外来端口保护、配置覆盖和进程清理；本机HTTPS检查不冒充iPad实测。此条更新SETUP-04的单端口管理语义。

- SETUP-01：根目录run.sh可从任意工作目录调用，安装锁定npm/uv依赖，先校验本地标准音，完整则直接复用且不访问上游Git；缺失或损坏时优先从本地固定commit重新导入，缓存不存在才clone，固定commit缺失才pull固定cmguo/PinYinSound仓库；导入登记的固定commit，不自动采用上游HEAD改动。校验205课程映射与600每日/组词标准音白名单文件摘要和解码。只在显式运行启动脚本时访问网络，应用运行不联网取音频。
- SETUP-02：用户已授权13份课程录音与原PDF加入当前私有代码仓库，保留独立非MIT说明。原创SVG/课程JSON/引导脚本已在仓库。中文引导已按SPEC-011用本地开源Qwen3-TTS重新生成并随仓库提供，不依赖Apple系统声音或手工复制。儿童跟读/数据库/密钥不打包。
- SETUP-03：首次显式启动自动安装已固定Whisper small并校验大小/SHA；已安装复用。权重不提交普通Git，GitHub单文件限制不允许488MB模型。无训练、云识别或运行时下载降级。
- SETUP-04：支持start（默认前台启动）、stop、restart、status；兼容top为stop别名。管理命令按LOVE_PINYIN_PORT（默认8000）选择实例，核对监听进程的工作目录与uvicorn应用/端口参数，不停止其他服务；status未运行返回3、端口被其他服务占用返回1。stop未运行幂等成功，发送TERM后最多等10秒，不强制杀进程；restart停止成功后走原启动准备流程。stop/status不安装依赖、不访问网络。支持--prepare-only、端口配置、正常Ctrl+C退出；重复启动复用已有资源，联网同步失败时仅在已验证固定源存在时可继续，首次失败明确退出。README给出唯一启动入口、首次耗时和工具前置。实际从干净checkout、新资源目录完整运行并验证健康、全部声音和识别模型可用；不能靠原private目录证明clone可运行。

初始版本实装证据（以下数量为835f296快照，当前数量见STATUS/SPEC-012，并非最新HEAD重新clone）：GitHub远端main的835f296全新clone到独立临时目录，PATH只留系统工具，run.sh自动安装Node24.18.1/npm11.16.0/uv0.12.5，完成新.venv、标准音Git导入、1284资源ID校验、固定Whisper首次下载/SHA校验、构建/发布门禁并在8002启动。健康、1270中文声音/14课音频/840条示范全可用，参考标准音API识别matched，真实Chromium播放通过；无TTS模型，无复制旧private/models。日志private/clone-start-success.log、clean-clone-proof.json、clean-clone-page.png。工程/发布/12项真实声音专项日志private/setup-voice-verify-all.log、setup-voice-release.log、open-voice-product.log。新增下载边界测试另外通过，不将标准音自识别称儿童准确率。

## SETUP-05 实装验收（2026-10-17）

`run.sh`与`run.command`统一使用`service-config.sh`和`service-lifecycle.sh`，通过已配置的两个独立监听进程提供HTTP/HTTPS；`scripts/lovepinyin.sh`以项目Python创建独立后台会话并等待本次启动标记。本机既有`lovepinyin`/`lovepy`别名已委托该版本化包装器，原本机包装器备份在忽略目录。实际IP和证书路径写入本机`private/server.env`，证书与密钥未入Git，无新增依赖。

`npm run verify:all`通过89项前端/工具、372项服务端、30项本机视口、34项真实服务GUI；之后针对复查发现的Bash空数组、绑定地址变更和后台会话边界补充回归，最终31项生命周期与14项命令专项共45项通过（独立临时监听、临时证书与真实进程组，无下载）。`npm run validate:release`通过。日志为`private/setup05-verify-all.log`、`setup05-release.log`、`setup05-final-lifecycle.log`。

实际执行现有`lovepinyin restart`，HTTP与HTTPS进程均更换；命令退出后的独立调用确认两端持续运行，首页与`/api/v1/health`均返回200。HTTPS验证使用现有家庭根证书且校验主机/IP，不跳过TLS验证。初次实测发现仅nohup未脱离进程组会被调用方清理，已改为独立会话并补真实进程组回归；最终成功证据在`private/setup05-live-endpoints.json`。`run.command status`也正确返回双入口。

以上是实际Mac运行和本机TLS验证，不是iPad真机或家庭断WAN验收；登录启动、Mac重启/休眠和完整多设备矩阵仍待独立验证。
