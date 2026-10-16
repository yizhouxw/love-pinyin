# Docker 单镜像部署

对应 SPEC-013 / ADR-0021。需要已启动的 Docker Engine 或 Docker Desktop（Compose v2）。宿主不需要 Node、Python、声音文件或识别模型。首次构建需要互联网下载基础镜像、锁定依赖、固定 PinYinSound 和 Whisper small；成功构建后，运行无需下载任何外部音频或模型。

在仓库根目录执行：

```sh
docker compose up -d --build
```

打开 <http://localhost:8000>，可直接进入访客模式。容器端口转发不属于应用认可的本机 loopback，家长配对码从容器内取得：

```sh
docker compose exec app python -c 'import urllib.request; print(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8000/api/v1/local/pairing-code", data=b"", method="POST")).read().decode())'
```

将返回的 code 填入页面，首次配对设备成为家长。配对码有效期5分钟。端口冲突可用 `LOVE_PINYIN_PORT=8001 docker compose up -d`。检查状态和停止：

```sh
docker compose ps
docker compose logs --tail=50 app
docker compose down
```

`down` 保留 household 命名卷；重新 `up` 或重建镜像仍保留家庭进度和设备配对。不要使用 `down -v`，它会删除家庭卷。备份可用家长页面下载 JSON；容器内 SQLite 运维备份用 `docker compose exec app python -m server.backup`，备份保留在数据卷。宿主原 `private/data` 不会自动迁移到容器，使用家长 JSON 导出/恢复。

## 只运行已有镜像

```sh
docker build -t love-pinyin:local .
docker run -d --name love-pinyin -p 127.0.0.1:8000:8000 \
  --mount type=volume,src=love-pinyin-data,dst=/data love-pinyin:local
```

只有 `/data` 需要持久化；不要用宿主空目录覆盖 `/app`、资源或模型目录。镜像使用 UID/GID 10001，Docker 新命名卷会继承目录权限；已有 bind mount 需由运维者预先赋予该用户写权限。Compose 额外启用只读根目录、临时 /tmp 和去除 capabilities。

离线搬运相同 CPU 架构镜像：

```sh
docker save -o love-pinyin-image.tar love-pinyin:local
# 将 tar 复制到目标机器后：
docker load -i love-pinyin-image.tar
docker run -d --name love-pinyin -p 127.0.0.1:8000:8000 \
  --mount type=volume,src=love-pinyin-data,dst=/data love-pinyin:local
```

tar 包括全部音频、字体、前端和 Whisper，不包括家庭数据。默认构建宿主架构；Apple Silicon 是 linux/arm64，Intel/AMD 是 linux/amd64。跨架构需单独 `docker buildx build --platform linux/amd64 --load -t love-pinyin:local .`，不可把尚未运行的架构称已验收。

默认仅供本机访问。家庭 LAN 仍需可信 HTTPS 与设备信任，参见[本地部署](local-deployment.md)。可在宿主已有的 HTTPS 反向代理后接本机8000端口，保留原始 Host 并转发到同源入口；不要把 HTTP LAN 麦克风视为可用。容器不自动安装证书或开放宿主防火墙。

## 构建边界和验证

Dockerfile 多阶段构建；最终镜像不含 npm、uv、Git、FFmpeg、构建缓存、TTS/对齐模型、宿主私有文件或数据库。构建上下文由 `.dockerignore` 白名单限制。标准音构建期经过登记摘要、实际解码与非静音检查；中文引导、课程文件、840条每日材料及时间轴和模型经过既有发布检查。容器入口直接启动 Uvicorn，无启动下载脚本；一个进程维护本地识别互斥。

```sh
python3 scripts/docker_smoke.py --image love-pinyin:local
```

脚本创建随机隔离的 `--internal` Docker 网络和临时数据卷，容器没有互联网出口；检查网页、所有登记声音的真实HTTP响应、Whisper模型加载、访客会话、家长配对、选课及容器删除重建后的配对、选课和已提交作答恢复，结束清理仅自身临时资源。它不触碰真实家庭卷，也不代表移动真机、实际LAN、儿童识别质量或家庭试用验收。

PinYinSound 仍保留 unknown 许可状态，课程/PDF保留独立来源；随镜像提供 `LICENSE`、`THIRD_PARTY_NOTICES.md` 与 `resources/licenses`。本机制按用户要求构建私有家庭使用镜像，不自动向镜像仓库推送或公开发行素材。
