# 爱拼音 · Love Pinyin

面向刚开始学习拼音的一年级学生与家长，按中国大陆统编人教版课序学习。浏览器提供语音引导、听辨、声调、拼读和字形游戏；自有 Mac Studio 通过同源 API 提供声音、课程和 SQLite 家庭进度。课程不录音、不做发音评测，不需要云账号。新增“天天练拼音”按用户PDF提供14份每日练习，可自愿在浏览器内存录音回放；并支持本地语音识别匹配判定，不提供专业发音/四声评分。

当前已实现14课、83个知识点和448道客观题，含课程录音、逐目标标准音、题目/提示/反馈朗读、书写观察、生活图片卡，以及家长备份恢复。桌面已有实际 Chrome/Safari 验收记录；**家庭 HTTPS/LAN、iPad/手机真机与家庭试用尚未完成，不能视为全平台交付通过**。详见[交付状态](docs/STATUS.md)。

## 安装与启动

macOS 开发者 clone 后，在项目目录执行：

```sh
./run.sh
```

也可双击 `run.command`。脚本自动安装项目本地 Node **24.18.1**、npm **11.16.0**、uv **0.12.5**（已有匹配版本则复用），用锁文件安装依赖和 Python **3.12.12**，自动 Git clone/pull 标准读音仓库、导入登记固定版本、校验仓库内课程/中文引导音频，首次下载并校验 Whisper small，构建并启动。需要系统 Git（通常在 clone 时已安装）；缺少时先运行 `xcode-select --install`。首次运行需要联网，模型约488MB，完成后不需要手动复制任何资源。普通启动无需TTS模型、Tingting或系统音色。

打开 `http://127.0.0.1:8000`，可先访客体验或生成家长配对码。Ctrl+C停止。默认端口占用可用 `LOVE_PINYIN_PORT=8001 ./run.sh`。`./run.sh --prepare-only`只安装准备，不启动；`npm start`调用同一脚本。重复启动检查并复用资源；上游联网更新失败且已有固定版本时可继续，新安装失败明确退出。不要同时运行两份准备脚本。

标准音直接信任[cmguo/PinYinSound](https://github.com/cmguo/PinYinSound)，自动同步上游但按`content/pinyin-source.json`的commit和逐文件摘要导入，不把上游HEAD更新直接变为教材声音。源码、课程JSON、原创SVG、13份课程MP3、每日PDF、全部中文引导WAV与白名单manifest都在仓库。课程录音与PDF保留非MIT说明。中文引导由本地开源 **Qwen3-TTS-12Hz-1.7B-CustomVoice / MLX** 重新生成，已附许可。日常运行直接播放，不调用TTS或外部语音服务。

维护者如修改中文脚本，可运行 `npm run prepare:voice` 在Apple Silicon Mac上下载校验固定Qwen3-TTS模型（约4.5GB）并离线重生成，再提交音频和manifest；模型大文件不入Git。固定参数和摘要见 `content/voice-build.json`。旧Mac声音准备工具仅保留兼容测试，不再是启动依赖。

数据库、儿童跟读、备份、上游Git缓存和模型留在忽略目录；家长页可下载JSON备份，`npm run backup:local`生成SQLite运维备份，默认保留最近7份。

## iPad / 手机与家庭局域网

默认入口只监听本机。其他设备按[部署说明](docs/engineering/local-deployment.md)准备受信任 HTTPS，设置 `LOVE_PINYIN_BIND_IP`、`LOVE_PINYIN_TLS_CERT`、`LOVE_PINYIN_TLS_KEY`，运行 `npm run doctor:lan` 后再 `npm run serve:lan`。启动器只绑定指定的本机 LAN IPv4，检查证书有效期、IP SAN与密钥匹配；不会自动安装根证书、改防火墙或启用登录启动。

这里的“离线”指断互联网、家庭 LAN 仍连通。Mac 停机或 LAN 断开时无法保存新进度，页面提供重试/恢复，不承诺浏览器独立离线学习。

## 开发与验证

开发时分别运行 `npm run dev:api` 和 `npm run dev`；前端 `http://127.0.0.1:5173` 代理本机8000端口。生产形态用 `npm start`，不要把 Vite 开发服务当家庭部署。

安装测试浏览器：`npx playwright install chromium firefox webkit`。真实声音测试前运行 `./run.sh --prepare-only`；中文引导与课程录音已随仓库提供，标准音仍从上游同步。

| 命令                       | 范围                                          |
| -------------------------- | --------------------------------------------- |
| `npm run verify`           | 格式、lint、TS、内容校验、前端/工具测试与构建 |
| `npm run verify:server`    | Python lint、格式、领域与 API 测试            |
| `npm run test:e2e`         | 六个浏览器/视口项目；含测试替身，不是真机验收 |
| `npm run test:e2e:live`    | 真实 Mac API/SQLite 的桌面数据与恢复流程      |
| `npm run test:e2e:product` | 真实声音、完整游戏与播放故障；需要私有音频    |
| `npm run test:e2e:soak`    | 独立长时真实练习与媒体资源观测                |
| `npm run verify:all`       | 工程检查、本机视口项目和真实服务 GUI          |
| `npm run validate:release` | 内容覆盖、课程依据与本机实际资源门禁          |

本机 macOS 27 / Playwright 1.63.0 的 Firefox 限制只影响 `test:e2e:local` 与 `verify:all` 的本机选择；Linux CI 保留六个视口项目。CI不包含私有声音和完整家庭交付验收，详见[测试说明](docs/engineering/testing.md)。

## 文档与许可

- [状态与剩余验收](docs/STATUS.md)、[实施计划](docs/implementation-plan.md)、[SPEC索引](docs/specs/README.md)
- [产品方案](docs/product/PRD.md)、[交互设计](docs/product/UX.md)、[学习路径](docs/content/learning-path.md)、[课程依据](docs/research/curriculum.md)
- [架构](docs/architecture.md)、[API](docs/api-contract.md)、[技术选型](docs/research/technology.md)、[声音与素材](docs/research/audio-and-assets.md)
- [贡献约定](CONTRIBUTING.md)、[开发流程](docs/engineering/workflow.md)、[隐私边界](docs/engineering/privacy.md)

代码、文档与原创题目采用 [MIT](LICENSE)。教材、外部录音、Mac 生成声音与第三方依赖不因此取得 MIT 再分发许可，见[第三方说明](THIRD_PARTY_NOTICES.md)。仓库已提交至 [yizhouxw/love-pinyin](https://github.com/yizhouxw/love-pinyin)，目前为私有仓库，默认分支 `main`；尚未公开发行素材包。

## 天天练拼音

首页“进入天天练拼音”可选择14份练习、分节逐条示范或连播。“语音引导”继承家长自动朗读设置；首页、课程练习导航及天天练当前内容区均有快捷开关，在浏览器记住选择，家庭设置变更优先。关闭后跳过操作说明，点击拼音或本节条目立即听示范，录音和识别仍可使用。点“录下我的跟读”才请求麦克风；录音只留当前页面内存，停止后发送家庭Mac内存做本地识别匹配；换条/退出/后台清除，不落盘。需要localhost或受信任HTTPS。可直接不录音跟读，家长标记只留本次页面，退出清除，不计入客观题成绩。

每日标准音与原课程共享固定来源；run.sh自动导入840条示范所需资源。42条轻声词句以本地Qwen3-TTS中文朗读提供，并与拼音标准音区分。停止录音后本机Whisper识别、核对音节；听不清拒判，不判断四声或专业发音准确度。模型首次显式启动下载，应用处理录音时不下载、不访问外网。详见[SPEC-009](docs/specs/SPEC-009-asr-reading-match.md)、[一键安装](docs/specs/SPEC-010-one-command-setup.md)与[开源中文声音](docs/specs/SPEC-011-open-chinese-voice.md)。

2026-10-14新增跟读细节：家长管理（或访客设置）可保存连播间隔，范围0.1～5秒、精度0.1秒、默认1秒。间隔用于分段标准音及两条示范之间，完整中文句子保留自然语流。“读音节并组词”各条提供默认折叠的汉字/拼音样例，展开自动朗读；换条收起。读句子按实际音频进度逐音高亮，完整中文示范使用与WAV摘要绑定的本地字音时间轴。生活里的拼音扩展为每课6张，共84张原创SVG；前两课为标明用途的单韵母记音图。

维护者`npm run prepare:voice`现在同时生成并校验字音时间轴；单独重建可用`npm run prepare:reading-timing`，首次额外安装约1.3GB对齐模型。运行端只需仓库内素材。实现与验收见[SPEC-012](docs/specs/SPEC-012-reading-enrichment.md)。
