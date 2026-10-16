# ADR-0021：构建期准备资源的单镜像部署

2026-10-16，采纳，依据 SPEC-013。为已有本地 B/S 服务增加 Linux Docker 部署，Mac 原启动方式继续可用。

采用 Node 前端构建、Python 依赖及资源构建、精简 Python 运行三个阶段。版本固定，与现有 npm/uv 锁文件一致；Linux 使用 FFmpeg 解码检查标准音，避免把 macOS 工具带入容器。构建期下载并校验内容清单内固定归档及逐文件SHA的声音并下载校验固定 Whisper small，最终镜像包含完整可用资源和必要许可。应用启动、播放、识别阶段没有下载步骤。构建缓存可以复用，家庭数据不作为构建输入。

/data 独立持久化，只存家庭 SQLite 与备份；镜像内资源只读，非 root 运行，单进程保持 SQLite 和识别互斥语义。Docker 端口转发不视为 loopback，家长初始配对码通过 docker compose exec 在容器内部取得，不信任代理头或网桥来源。HTTPS/真实设备信任继续由家庭部署负责。

代价是镜像包含约488MB识别权重及课程音频，首次构建需网络。save/load 可搬运完整镜像到离线主机。PinYinSound许可仍为unknown，用户请求仅用于当前私有家庭镜像，不自动公开分发。

2026-10-16补充（DOCKER-05/06）：Windows x86-64通过Docker Desktop的WSL 2 Linux容器运行linux/amd64，不制作Windows内核镜像或原生安装器。`deploy/docker/compose.amd64.yaml`显式选择目标架构，基础镜像的多架构manifest及uv.lock选择对应Linux x86-64原生依赖；Whisper GGML权重不含平台代码，保持同一固定摘要。Docker设置LOVE_PINYIN_ASR_CPU_ONLY=1，通过pywhispercpp context_params.use_gpu=false选择CPU；macOS原生启动保持现有默认后端。MLX/Qwen TTS与对齐仅用于Apple Silicon维护，不作为容器运行依赖。Windows/amd64及最低规格按用户要求暂不验证，文档必须明确此状态。
