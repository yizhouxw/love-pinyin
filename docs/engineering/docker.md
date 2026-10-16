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

## Windows x86-64 / amd64（已配置支持，未验证）

Windows上的部署入口是Docker Desktop + WSL 2的 **Linux容器**，目标平台为`linux/amd64`。Intel/AMD x86-64 Windows宿主可使用；本项目不提供`windows/amd64` Windows内核镜像、原生exe或Windows版run.sh。Windows ARM不在本次支持范围。按用户要求，本次未在Windows或amd64上构建镜像、加载/推理模型或验证浏览器；下面是新增的配置和操作方式，不能视为验收通过。

先按[Docker官方Windows安装要求](https://docs.docker.com/desktop/setup/install/windows-install/)安装支持当前Windows版本的Docker Desktop与WSL 2，启用BIOS/UEFI硬件虚拟化、WSL 2后端，并选择Linux containers。宿主不需要安装Node、Python、FFmpeg、CUDA或模型。仓库应已解压/检出到本机；在仓库根目录的PowerShell执行：

```powershell
docker compose -f compose.yaml -f compose.amd64.yaml up -d --build
```

覆盖文件同时固定构建和运行平台为`linux/amd64`，镜像标签为`love-pinyin:amd64`，避免误用Apple Silicon的arm64本地镜像。打开 <http://localhost:8000>。家长配对码使用PowerShell here-string传入容器，无需执行Bash脚本：

```powershell
@'
import urllib.request
request = urllib.request.Request('http://127.0.0.1:8000/api/v1/local/pairing-code', data=b'', method='POST')
print(urllib.request.urlopen(request).read().decode())
'@ | docker compose -f compose.yaml -f compose.amd64.yaml exec -T app python -
```

返回code填入页面。端口冲突时先设置`$env:LOVE_PINYIN_PORT = '8001'`，再执行上述启动命令，改为访问localhost:8001。查看状态、日志和停止时持续使用同一组文件，数据卷仍保留：

```powershell
docker compose -f compose.yaml -f compose.amd64.yaml ps
docker compose -f compose.yaml -f compose.amd64.yaml logs --tail=50 app
docker compose -f compose.yaml -f compose.amd64.yaml down
```

本地识别也在amd64镜像内运行：`uv sync --locked`选择锁文件中的CPython 3.12 Linux x86-64 NumPy及`pywhispercpp==1.5.1`轮子；Whisper small的`ggml-small.bin`是跨架构权重数据，沿用scripts/asr_model.py中的固定大小和SHA-256，无需Windows专用权重。Docker显式设置`LOVE_PINYIN_ASR_CPU_ONLY=1`，通过`context_params.use_gpu=false`使用CPU，不需要Metal、MLX、NVIDIA显卡或GPU透传。上游提供[基础CPU轮子](https://github.com/absadiki/pywhispercpp)；Windows/amd64上的实际轮子兼容性、CPU指令集兼容性及推理耗时仍未验证。缺模型、模型损坏、资源不足或识别超时不会转用云服务，也不判孩子读错。

Qwen TTS/对齐模型仅供维护者在Apple Silicon预生成素材，容器已带生成后的声音与时间轴，Windows运行不需要安装这两个模型。本次没有增加Windows上的素材重生成支持。

离线交付Windows机器时，必须在联网的构建机器准备amd64镜像，再保存；可以在Apple Silicon跨架构构建，但速度与兼容性仍未验证，不要重命名arm64镜像冒充amd64：

```powershell
docker buildx build --platform linux/amd64 --load -t love-pinyin:amd64 .
docker save -o love-pinyin-amd64.tar love-pinyin:amd64
# 复制tar及两个compose文件到离线Windows机器，然后执行：
docker load -i love-pinyin-amd64.tar
docker compose -f compose.yaml -f compose.amd64.yaml up -d --no-build --pull never
```

离线启动不会构建或拉取镜像，音频和Whisper均从包内读取。Docker Desktop/WSL 2本身应已安装完毕；上述打包不包含它们的离线安装程序。命名卷保存在Docker的Linux环境，保留/data的Linux权限，避免将SQLite目录直接绑定到NTFS路径。跨机器家庭进度仍用家长JSON备份恢复。

## 机器规格与资源预算

下表是家庭单实例、最多一个本地识别任务的**最低建议部署起点**，不是经过最低配置测试得到的硬件下限或性能承诺。除前一版arm64镜像大小外，以下CPU/内存/磁盘预算均为保守估算；Windows/amd64和低配机器未验证。Windows、WSL、Docker Desktop与浏览器本身也需要资源，宿主内存不能全部分给容器。

| 资源                   | 仅运行已有完整镜像的最低建议                                               | 推荐配置                                        | 在本机从源码构建                                                     |
| ---------------------- | -------------------------------------------------------------------------- | ----------------------------------------------- | -------------------------------------------------------------------- |
| CPU                    | 宿主4个逻辑CPU；给Docker至少2个vCPU                                        | Docker可用4个vCPU以上                           | 至少2个vCPU，推荐4个以上；按目标架构原生构建                         |
| CPU架构/指令集         | Windows为Intel/AMD x86-64，保守选择支持AVX2/FMA的CPU；Apple Silicon为arm64 | 使用较新的64位CPU，不依靠跨架构模拟进行日常识别 | amd64和arm64分别构建，禁止混用原生库；AVX2/FMA也未做本项目兼容性验证 |
| 宿主内存               | 8GB                                                                        | 16GB以上                                        | 至少8GB，推荐16GB以上                                                |
| Docker/WSL可用内存     | 4GiB，供应用、模型和Linux环境使用                                          | 6GiB以上，宿主需留有余量                        | 至少4GiB，推荐6GiB；构建与识别尽量错开                               |
| Docker所在磁盘可用空间 | 至少10GB，不含操作系统和Docker/WSL安装占用                                 | 至少20GB，方便升级时保留旧镜像和备份            | 至少20GB，推荐30GB以上，包含上下文、依赖、下载、镜像层与缓存         |
| GPU/显存               | 无要求，Docker使用CPU识别                                                  | 无需购买显卡                                    | 不安装TTS/对齐维护组；构建不需要GPU                                  |

截至1106639的arm64镜像内容约718MB，在本机Docker存储中显示约1.72GB（含存储格式/解包开销）；amd64的实际镜像与占用大小未测量。首次构建会同时留下基础镜像、依赖缓存、声音归档、约488MB Whisper权重和中间层，所以不能按718MB估算构建磁盘。save导出的tar还需要额外空间；升级、旧镜像、日志和备份均会继续占用磁盘，10GB是起点，不是固定配额。

[whisper.cpp上游](https://github.com/ggml-org/whisper.cpp#memory-usage)列出的small模型推理内存约852MB，只代表模型参考值，不包括Python服务、解码缓冲、线程工作区、浏览器或Docker/WSL；据此为完整运行环境预留4GiB。Docker官方Windows安装要求列出至少8GB系统内存，具体受支持Windows/WSL版本以[官方页面](https://docs.docker.com/desktop/setup/install/windows-install/)为准。

识别按单任务互斥运行，最多接受30秒片段，推理超时45秒。满足上述建议不保证长片段能在45秒内完成；低配CPU或多个浏览器同时提交时可能提示忙/暂不可用，仍可听示范、跟读和完成客观练习。规格不包括维护时生成Qwen声音/对齐所需的约4.5GB TTS、约1.3GB对齐模型及Apple Silicon算力，也不包括真实移动设备与家庭LAN验收。
