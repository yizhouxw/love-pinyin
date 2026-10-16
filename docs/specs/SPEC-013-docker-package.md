# SPEC-013：自带资源的 Docker 应用镜像

2026-10-16，用户要求将应用打包为一个 Docker 镜像，运行镜像无需另行下载外部音频。沿用当前课程、声音来源及家庭数据边界；不自动发布镜像。

- DOCKER-01：多阶段构建静态前端与锁定 Python 运行依赖；最终单镜像用非 root 用户运行一个 Uvicorn 进程，提供网页、API、声音和本地识别。提供 Docker build/run、Compose 与 save/load 命令，不要求宿主安装 Node、Python 或准备声音。
- DOCKER-02：构建阶段联网准备固定 PinYinSound、Whisper small 并校验摘要、解码与全部发布资源；课程录音、中文声音、时间轴、字体随镜像。资源失败则构建失败。运行入口直接启动 API，不调用安装器、不联网下载；Linux 解码使用 FFmpeg，macOS 保留 afconvert。镜像不包含 TTS/对齐模型、儿童录音、家庭数据库或证书。素材许可随包保留，私有家庭镜像不自动上传公共仓库。
- DOCKER-03：SQLite 使用独立 /data 卷，重建容器后保留配对与进度；资源放在 /app 下，不被数据卷遮蔽。默认宿主仅发布 127.0.0.1:8000；容器内可通过 loopback 命令取得家长配对码，不放宽本地管理接口。提供健康检查与正常停止。
- DOCKER-04：真实构建并运行镜像，用无外网网络验证网页、全部音频、模型初始化、访客学习、家长配对和数据重建恢复；检查损坏资源失败边界。工程与发布检查记录实际结果；未执行的架构或移动真机/LAN验收明确保留。

- DOCKER-05：增加Windows x86-64宿主的Docker Desktop / WSL 2 Linux容器入口，显式构建并运行linux/amd64镜像；沿用锁定的Linux x86-64 Python/NumPy/pywhispercpp轮子与固定Whisper small GGML权重，容器强制CPU识别，不依赖Apple Metal/MLX、CUDA或宿主Python。提供PowerShell构建、运行、配对和离线搬运命令；按用户要求本轮不做Windows/amd64构建、推理或设备验证，标记“已配置支持，未验证”。不生成windows/amd64原生Windows容器。
- DOCKER-06：文档给出运行与构建的CPU、宿主/容器内存及可用磁盘起始要求，区分项目保守估算、上游要求和实际测量；不把未压测配置称性能保证。说明识别超时、单任务串行与TTS维护模型的适用边界。

实现和操作见[Docker 部署](../engineering/docker.md)、[ADR-0021](../adr/0021-self-contained-docker.md)。验收结果在本文件追加，不以配置文件存在代替容器运行证据。

## 2026-10-16 验收记录

DOCKER-01～04在本机Docker Engine29.6.2（Docker Desktop）/ linux/arm64软件验证通过。从仅包含HEAD及本切片暂存变更的独立干净目录构建，不复制宿主private/models/.venv，镜像`love-pinyin:local`约718MB。基础镜像按manifest摘要固定；构建期使用内容清单固定归档与逐文件SHA校验，Linux FFmpeg完成205个标准音映射和600条每日/组词声音的解码检查。1570个课程/中文声音ID、840条每日材料、字音时间轴和Whisper大小/SHA检查全部通过；Whisper许可原文随包保存。

`python3 scripts/docker_smoke.py --image love-pinyin:local`在无互联网出口的internal网络、非root、只读根目录、独立临时卷运行两次容器；全部登记声音真实HTTP读取、网页、Whisper初始化、访客六题会话、家长配对与一次真实API作答通过。删除并重建容器后，原Cookie配对、选课和作答记录保持。模型文件644、父目录755，非root可读取；数据仅写入/data。另在独立无网络容器破坏中文声音文件，完整性门禁明确拒绝。Compose在独立测试项目/端口18098实际启动，首页和健康接口通过后清理测试卷。

工程验证`npm run verify:all`通过（66项前端/工具测试、323项服务端测试、30项浏览器视口测试、24项真实服务GUI测试）；新增构建下载损坏/超限/断网边界3项与平台解码5项回归通过，最终`verify:server`覆盖326项。`npm run validate:release`通过。证据为本机忽略目录的docker-build-complete.log、docker-build-verified.log、docker-smoke-complete.log、docker-corrupt-resource.log、docker-verify-all.log、docker-server-final.log和docker-release.log。

剩余门禁：linux/amd64未实际构建运行；真实移动设备、家庭可信HTTPS/LAN、真实断WAN与家庭试用仍按SPEC-006继续，不以Docker隔离网络或桌面自动化替代。未推送镜像或公开发行素材。

## Windows/amd64 与规格补充（2026-10-16）

DOCKER-05已增加配置：`deploy/docker/compose.amd64.yaml`固定linux/amd64构建/运行并使用独立amd64镜像标签；Docker镜像显式禁用识别GPU后端。固定Whisper权重跨CPU架构复用，原生推理库由uv.lock中的Linux x86-64轮子提供；不将macOS二进制复制到Windows。DOCKER-06的规格与PowerShell操作见Docker部署文档。

按用户明确要求，本轮不进行Windows/amd64镜像构建、模型加载/推理或Windows真机验证；CPU/内存/磁盘配置是保守部署起点，未做最低配置压测。此前arm64验收是1106639版本的历史证据，不能扩展为本次版本或Windows验收。未新增或升级npm/uv依赖。

本轮仅执行Prettier、改动Python文件的Ruff格式/lint与Compose合并配置静态检查，确认构建/运行平台均为linux/amd64、标签为love-pinyin:amd64；没有重新构建镜像、加载模型、执行推理或运行工程/GUI测试。机器规格中的Docker/Whisper上游参考已在部署文档附官方来源，项目资源预算明确为未压测估算。

DOCKER-01/05文档补充：Windows PowerShell的docker run明确包含linux/amd64、amd64镜像标签、禁止拉取、持久卷与只读运行参数；提供docker exec配对码、停止/重启/删除重建及端口调整说明，并区分Compose卷和直接运行卷。通用docker run示例同样禁止隐式拉取。本次仅检查文档格式与差异，Windows/amd64命令仍未实际运行。
