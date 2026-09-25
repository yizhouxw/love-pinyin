# 爱拼音 · Love Pinyin

面向小学一年级的汉语拼音学习应用。当前交付**课程研究、产品与技术方案、SPEC 和可运行工程基线**，尚未实现完整学习应用。

确定的产品方向：大陆统编人教版；电脑/iPad/手机浏览器；键鼠和触摸；短时游戏练习；首版包含自动发音评分。采用 **B/S + 自有 Mac Studio**：录音只经局域网发送到自己的 Mac，评分后丢弃，不调用第三方云。未来可封装 Android/iOS，本期不做原生工程。

## 从哪里开始

1. [交付状态与待关闭风险](docs/STATUS.md)：已完成、已验证和仍待验证的边界。
2. [产品方案](docs/product/PRD.md) / [交互设计](docs/product/UX.md)。
3. [课程依据](docs/research/curriculum.md) / [学习路径](docs/content/learning-path.md) / [结构化学习库](content/curriculum.json)。
4. [技术架构](docs/architecture.md) / [技术研究](docs/research/technology.md) / [音频与评分研究](docs/research/audio-and-assets.md)。
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

前端 `http://127.0.0.1:5173`，Vite代理 `/api` 到 Mac本机8000端口。浏览器打开工程验证页；API健康检查为 `http://127.0.0.1:8000/api/v1/health`。

也可验证B/S统一服务：

```sh
npm run build
npm run serve:local
```

此时同一个 `http://127.0.0.1:8000` 提供网页及API。局域网真机麦克风必须配置可信HTTPS，见部署文档；当前未修改系统证书、开机启动或防火墙。

本地声学依赖检查：

```sh
npm run audio:doctor
```

这是合成信号的运行验证，不代表拼音评分通过教学测试。自动评分功能当前明确返回未就绪，不产生伪分数。

## 验证命令

| 命令                       | 内容                                           |
| -------------------------- | ---------------------------------------------- |
| `npm run verify`           | 格式、lint、TS、内容Schema、内容回归、前端构建 |
| `npm run verify:server`    | Python lint/format/API测试                     |
| `npm run test:e2e`         | Chromium/Firefox/WebKit与移动/平板模拟         |
| `npm run verify:all`       | 前后端+本机浏览器检查（Firefox例外见下）       |
| `npm run validate:release` | 内容/音频/评分发布门禁；当前应失败             |
| `npm run licenses`         | 从npm锁文件更新依赖许可证清单                  |

本机 macOS 27 的 Firefox 自动化启动存在与上游已知问题一致的限制。`test:e2e:local` / `verify:all` 会明确说明并只跑5个 Chromium/WebKit 项目；完整6项目保留在 `test:e2e` 与 Linux CI。尚无远程 CI 运行结果，见[测试说明](docs/engineering/testing.md)。

首次下一阶段开发先执行 **SPEC-000 本地发音评分 PoC**。标准音频、评分效度和教师审校是尚未完成的真实工作，不能由低成本模型编造素材或分数绕过。其余课程、游戏和基础服务可按SPEC独立推进。

## 开源

项目代码、文档和原创题目采用 [MIT](LICENSE)。引用教材/政策链接不授予其素材的再分发权；示范音、字体、模型、第三方依赖各自保留许可证，详见 [第三方与资产说明](THIRD_PARTY_NOTICES.md)。目前只有本地Git仓库，没有自动创建远程仓库或公开发布。
