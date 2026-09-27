# 爱拼音 · Love Pinyin

面向小学一年级的汉语拼音学习应用。当前提供课程研究、产品与技术方案，以及可在本机试用的 B/S 学习流程；首版暂不包含发音评测，正式儿童产品仍需教师审校、标准音授权和真实设备验收。

确定的产品方向：大陆统编人教版；电脑/iPad/手机浏览器；键鼠和触摸；短时游戏练习；首版不录音、不做发音评测。采用 **B/S + 自有 Mac Studio** 提供课程、资源与家庭进度服务。未来可封装 Android/iOS，本期不做原生工程。

## 从哪里开始

1. [交付状态与待关闭风险](docs/STATUS.md)：已完成、已验证和仍待验证的边界。
2. [产品方案](docs/product/PRD.md) / [交互设计](docs/product/UX.md)。
3. [课程依据](docs/research/curriculum.md) / [学习路径](docs/content/learning-path.md) / [结构化学习库](content/curriculum.json)。
4. [技术架构](docs/architecture.md) / [技术研究](docs/research/technology.md) / [音频与评分研究](docs/research/audio-and-assets.md) / [PoC状态](docs/research/assessment-poc-status.md)。
5. [实施顺序与模型交接](docs/implementation-plan.md) / [SPEC 索引](docs/specs/README.md)。
6. [开发流程](docs/engineering/workflow.md) / [测试标准](docs/engineering/testing.md) / [Mac 部署](docs/engineering/local-deployment.md)。

课程库覆盖14课、83个知识项，包含145道原创种子题和79个朗读目标。声母/韵母/整体认读/声调/拼写规则全量列出，题库仍需扩充和教师审校。2024修订教材把 y/w 独立编为第9课；2026版本研究也记录了2025年课标日常修订，未把2022版冒称最新。

## 开发环境

需要 Node **24.18.1**、npm **11.16.0**、uv **0.12.5**；uv 根据 `.python-version` 管理 Python **3.12.12**。依赖版本精确锁定。若尚未安装 uv，按[官方安装说明](https://docs.astral.sh/uv/getting-started/installation/)安装。

```sh
npm ci
uv sync --locked
npx playwright install chromium firefox webkit
npm run verify:all
```

两个终端分别运行：

```sh
npm run dev:api
```

```sh
npm run dev
```

前端 `http://127.0.0.1:5173`，Vite代理 `/api` 到 Mac本机8000端口。浏览器打开配对页；API健康检查为 `http://127.0.0.1:8000/api/v1/health`。首次在 Mac 本机生成配对码并完成家长配对。课程、会话、客观题提交及家庭进度由 SQLite 保存；当前练习只显示不需要播放音频的视觉选择题。

也可运行同源 B/S 服务：

```sh
npm run build
npm run serve:local
```

此时同一个 `http://127.0.0.1:8000` 提供网页及API，仅本机访问。

在 Mac 上创建并校验滚动保留的 SQLite 数据库备份：

```sh
npm run backup:local
```

默认存放在 `private/backups/`，最多保留最新 7 份；家庭备份 JSON 则可在家长页单独导出与恢复。

局域网设备需先按[部署文档](docs/engineering/local-deployment.md)准备可信 HTTPS 证书，再设置 `LOVE_PINYIN_BIND_IP`（本机正在使用的 LAN IPv4）、`LOVE_PINYIN_TLS_CERT` 与 `LOVE_PINYIN_TLS_KEY` 并运行 `npm run serve:lan`。启动器只绑定指定接口地址，并检查该地址确属本机；不会监听所有接口，也不自动修改防火墙、信任证书或启用开机启动。

本地声学依赖检查：

```sh
npm run audio:doctor
```

这是开发声学工具检查，不属于首版产品功能，也不代表拼音发音评测通过教学测试。

本机素材转写研究工具（需联网时显式下载一次模型；推理过程本地运行）：

```sh
uv sync --locked --group audio-asr
uv run --locked --group audio-asr python -m scripts.fetch_asr_model
uv run --locked --group audio-asr python -m scripts.transcribe_audio_candidates \
  --index '/Users/chad/Documents/1汉语拼音音频/提取候选_20260927/candidate-index.csv' \
  --model models/whisper-small/ggml-small.bin \
  --output '/Users/chad/Documents/1汉语拼音音频/提取候选_20260927/asr-transcripts.csv' \
  --limit 12
```

移除 `--limit 12` 可处理全部候选。输出只是待人工听审的 ASR 转写草稿，不能作为课程答案、标准音或儿童发音分。模型与完整离线约束见 [ADR 0003](docs/adr/0003-local-asr-transcription.md)。

## 验证命令

| 命令                       | 内容                                           |
| -------------------------- | ---------------------------------------------- |
| `npm run verify`           | 格式、lint、TS、内容Schema、内容回归、前端构建 |
| `npm run verify:server`    | Python lint/format/API测试                     |
| `npm run test:e2e`         | Chromium/Firefox/WebKit与移动/平板模拟         |
| `npm run verify:all`       | 前后端+本机浏览器检查（Firefox例外见下）       |
| `npm run validate:release` | 内容/音频授权与审校发布门禁；当前应失败        |
| `npm run licenses`         | 从npm锁文件更新依赖许可证清单                  |

本机 macOS 27 的 Firefox 自动化启动存在与上游已知问题一致的限制。`test:e2e:local` / `verify:all` 会明确说明并只跑5个 Chromium/WebKit 项目；完整6项目保留在 `test:e2e` 与 Linux CI。尚无远程 CI 运行结果，见[测试说明](docs/engineering/testing.md)。

首版不包含麦克风录音或发音评测；练习通过标准音播放和客观选择完成。标准音授权、审音与教师内容审校仍未完成。旧评分研究资料仅作历史记录，不构成当前实现门禁。应用范围见[状态记录](docs/STATUS.md)。

## 开源

项目代码、文档和原创题目采用 [MIT](LICENSE)。引用教材/政策链接不授予其素材的再分发权；示范音、字体、模型、第三方依赖各自保留许可证，详见 [第三方与资产说明](THIRD_PARTY_NOTICES.md)。目前只有本地Git仓库，没有自动创建远程仓库或公开发布。
