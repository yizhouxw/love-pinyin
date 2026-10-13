# 爱拼音 · Love Pinyin

面向刚开始学习拼音的一年级学生与家长，按中国大陆统编人教版课序学习。浏览器提供语音引导、听辨、声调、拼读和字形游戏；自有 Mac Studio 通过同源 API 提供声音、课程和 SQLite 家庭进度。课程不录音、不做发音评测，不需要云账号。新增“天天练拼音”按用户PDF提供14份每日练习，可自愿在浏览器内存录音回放；并支持本地语音识别匹配判定，不提供专业发音/四声评分。

当前已实现14课、83个知识点和448道客观题，含课程录音、逐目标标准音、题目/提示/反馈朗读、书写观察、生活图片卡，以及家长备份恢复。桌面已有实际 Chrome/Safari 验收记录；**家庭 HTTPS/LAN、iPad/手机真机与家庭试用尚未完成，不能视为全平台交付通过**。详见[交付状态](docs/STATUS.md)。

## 安装与启动

准备 Node **24.18.1**、npm **11.16.0**、uv **0.12.5**；项目使用 Python **3.12.12**。首次安装依赖可联网，资源准备完成后的学习不需要互联网，但浏览器必须能连接 Mac。

```sh
npm ci
uv sync --locked
npm run prepare:voice -- --source '/绝对路径/1汉语拼音音频'
npm run prepare:pinyin
npm run prepare:daily -- --archive /绝对路径/固定版本PinYinSound.zip
npm start
```

`prepare:voice` 导入家长提供的课程录音，并用 Mac 已安装的 Tingting 音色生成中文指令。音色缺失会报错，不自动补装。课程录音文件名/映射见[音频制作说明](docs/content/audio-production.md)；原13课映射新版14课，第2/9课共用旧合课录音，录音中的旧页码不是新版页码。

`prepare:pinyin` 显式下载固定版本的 cmguo/PinYinSound，校验摘要并在本机解码。也可用 `-- --archive /绝对路径/source.zip` 安装已有归档。应用直接信任此来源作为标准音，没有教师角色、审音台或批准流程。运行时不访问 GitHub，不加载识别模型。

打开 `http://127.0.0.1:8000`。可先访客体验；要保存家庭进度，在 Mac 本机生成配对码并连接，第一个家长设备可选课和管理其他设备。访客进度仅留在当前浏览器标签页，不能替代家庭档案。以后运行 `npm start` 即可构建网页、复用/准备本地中文声音并启动服务。

声音、课程录音、数据库和备份留在 Git 忽略的 `private/`。家长页可下载 JSON 备份、预览恢复和清除记录；`npm run backup:local` 另生成 SQLite 运维备份，默认保留最近7份。

## iPad / 手机与家庭局域网

默认入口只监听本机。其他设备按[部署说明](docs/engineering/local-deployment.md)准备受信任 HTTPS，设置 `LOVE_PINYIN_BIND_IP`、`LOVE_PINYIN_TLS_CERT`、`LOVE_PINYIN_TLS_KEY`，运行 `npm run doctor:lan` 后再 `npm run serve:lan`。启动器只绑定指定的本机 LAN IPv4，检查证书有效期、IP SAN与密钥匹配；不会自动安装根证书、改防火墙或启用登录启动。

这里的“离线”指断互联网、家庭 LAN 仍连通。Mac 停机或 LAN 断开时无法保存新进度，页面提供重试/恢复，不承诺浏览器独立离线学习。

## 开发与验证

开发时分别运行 `npm run dev:api` 和 `npm run dev`；前端 `http://127.0.0.1:5173` 代理本机8000端口。生产形态用 `npm start`，不要把 Vite 开发服务当家庭部署。

安装测试浏览器：`npx playwright install chromium firefox webkit`。真实声音测试前必须完成上面的私有资源准备；仅克隆 MIT 源码不包含音频。

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

首页“进入天天练拼音”可选择14份练习、分节逐条示范或连播。点“录下我的跟读”才请求麦克风；录音只留当前页面内存，停止后发送家庭Mac内存做本地识别匹配；换条/退出/后台清除，不落盘。需要localhost或受信任HTTPS。可直接不录音跟读，家长标记只留本次页面，退出清除，不计入客观题成绩。

每日标准音与原课程共享固定来源，先prepare:pinyin，再显式prepare:daily导入同版本归档（本机已有归档可用private/pinyinsound-source/source.zip）；最后prepare:voice生成中文引导及42条中文词句朗读。拼音标准音与中文词句朗读在页面区分。停止录音后电脑自动识别，显示识别文字、对应拼音和音节匹配结果；听不清拒判。ASR匹配不代表四声/专业发音准确度，不生成分数或课程正确成绩。运行识别需显式安装已固定的Whisper small权重（已有models/whisper-small/ggml-small.bin可复用）；缺失时运行 `uv run --locked --group audio-asr python -m scripts.fetch_asr_model`，应用不会自动下载。详见[SPEC-009](docs/specs/SPEC-009-asr-reading-match.md)与[SPEC-008](docs/specs/SPEC-008-daily-reading.md)。来源PDF为用户家庭素材，不加入Git或MIT公开素材包。
