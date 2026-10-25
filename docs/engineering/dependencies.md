# 依赖与供应链记录

软件依赖首次实装：2026-09-25；后续系统工具和资源记录单独注明日期。安装结果以锁文件为准，浏览到的“最新版本”不是无条件升级指令。

## 已选择并实装

| 用途            | 依赖                                    | 许可                              | 结果/选择原因                                                        |
| --------------- | --------------------------------------- | --------------------------------- | -------------------------------------------------------------------- |
| UI              | react / react-dom 19.3.0                | MIT                               | 单页交互生态成熟，后续可放入原生壳                                   |
| 构建            | vite 8.3.4 / plugin-react 6.1.1         | MIT                               | Node24兼容，静态产物由Mac API服务                                    |
| 类型            | typescript 6.0.3                        | Apache-2.0                        | 最新7.0.2超出typescript-eslint 8.70.1的peer范围，因此锁6.0.3         |
| 格式/lint       | prettier3.9.9 / ESLint10.12.0           | MIT                               | 自动化统一代码风格                                                   |
| 测试            | Vitest5.0.4 / Playwright1.63.0          | MIT / Apache-2.0                  | 已下载三浏览器运行时；不等同真机                                     |
| 内容Schema      | Ajv8.20.0                               | MIT                               | JSON结构及教学引用门禁                                               |
| API             | FastAPI0.143.0 / Uvicorn0.54.0          | MIT / BSD-3-Clause                | 实际内容、家庭数据及资源API                                          |
| 服务端测试/lint | pytest9.1.1 / httpx0.28.1 / ruff0.17.0  | MIT / BSD-3-Clause / MIT          | 锁定在uv dev组                                                       |
| 声学研究        | librosa1.0.0 / NumPy2.5.3 / SciPy1.18.1 | ISC / BSD-3-Clause / BSD-3-Clause | `assessment-poc`独立组，仅研究候选；已验证arm64原生轮子及YIN合成信号 |
| 数据库          | Python标准库sqlite3                     | 随Python/SQLite各自许可           | 单Mac家庭使用，避免数据库运维                                        |

Node24.18.1、npm11.16.0、uv0.12.5、Python3.12.12。本机更高Python版本不直接用于声学依赖，以减少兼容风险。安装Python时uv出现动态库install-name修补警告；预编译依赖与现有测试可运行，未来构建原生扩展须另行验证，不能据此声称所有C扩展都可编译。

`package-lock.json`和`uv.lock`包含固定版本/完整性哈希；项目registry使用官方npm/PyPI URL，避免把本机私人索引写进开源基础。用户可按网络环境使用受信镜像，但变更锁文件需验证哈希。

npm全部传递依赖的许可证声明见[自动清单](dependency-inventory.json)。声明不等于完整法律审查，二进制轮子、LLVM/OpenBLAS/libsndfile等附带许可证应保留随包分发的notice；Python分发包元数据另见[Python清单](python-dependency-inventory.json)，包/轮子来源及哈希见uv.lock。发布App二进制前另做实际打包产物SBOM，不仅看顶层许可证。

## 不属于当前产品的研究依赖

assessment-poc与audio-asr保留为维护研究依赖组，不由默认学习服务加载，不构成首版门禁。标准音已采用下述固定PinYinSound；字形/笔顺由仓库原创SVG提供。外部声音许可不因代码MIT而改变。

运行产品不需要云API、收费配额、供应商密钥或商业SDK。未来重新研究发音评测须另立SPEC。

## 升级流程

查官方release和peer约束 → 固定新版本 → 更新lock和清单 → 工程验证 → 受影响功能与真机 → 单独提交。禁止`npm audit fix --force`和未审查的安装脚本绕过。

### DEPS-01（2026-10-25）

处理Dependabot #1–12：采用Vite8.3.4、Vitest5.0.4、ESLint10.12.0、FastAPI0.143.0、Uvicorn0.54.0、Ruff0.17.0及4个Actions更新；#8的TypeScript7超出typescript-eslint8.70.1的peer范围，#10的Node26类型与Node24运行时不符，关闭这两项并在Dependabot中忽略对应主版本更新。保留TypeScript6.0.3与@types/node24.13.6。

软件包来源为官方[npm registry](https://registry.npmjs.org/)与[PyPI](https://pypi.org/)，固定版本和完整性哈希见package-lock.json/uv.lock；上述npm包、FastAPI、Ruff为MIT，Uvicorn为BSD-3-Clause。另按npm audit修复传递依赖fast-uri3.1.9（BSD-3-Clause）、source-map-js1.2.2（BSD-3-Clause）、zod4.6.6（MIT）；完整依赖/许可由两份自动清单记录。fast-uri/zod的精确版本、tarball和integrity取自官方版本元数据，npm ci校验安装，不引入额外顶层依赖或override。

[FastAPI0.143.0](https://github.com/fastapi/fastapi/releases/tag/0.143.0)新增必需的opentelemetry-api1.45.1（Apache-2.0，官方[PyPI](https://pypi.org/project/opentelemetry-api/1.45.1/)），属于API接口依赖；未安装SDK、exporter或standard extras。server/main.py显式禁用全部遥测信号及环境自动配置，回归测试在宿主启用OTEL环境变量时阻止provider调用和网络连接，并核对无SDK/exporter加载。

CI Actions均为MIT，版本v7.0.0，通过各官方仓库发行tag核对并固定完整commit：

| 来源                                                                                      | 固定commit                                 |
| ----------------------------------------------------------------------------------------- | ------------------------------------------ |
| [actions/checkout](https://github.com/actions/checkout/releases/tag/v7.0.0)               | `9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0` |
| [actions/setup-node](https://github.com/actions/setup-node/releases/tag/v7.0.0)           | `820762786026740c76f36085b0efc47a31fe5020` |
| [actions/upload-artifact](https://github.com/actions/upload-artifact/releases/tag/v7.0.0) | `bbbca2ddaa5d8feaa63e36b76fdaad77386f024f` |
| [astral-sh/setup-uv](https://github.com/astral-sh/setup-uv/releases/tag/v7.0.0)           | `eb1897b8dc4b5d5bfe39a428a8f2304605e0983c` |

继续使用GitHub托管ubuntu runner及现有Node/npm/uv固定版本、只读contents权限；上传仍使用默认压缩归档，不开启直接单文件模式。Actions运行结果须以远端CI为准，本机安装与测试不代替云端执行。

一手资料：[Vite要求](https://vite.dev/guide/)、[uv项目与锁文件](https://docs.astral.sh/uv/guides/projects/)、[FastAPI部署](https://fastapi.tiangolo.com/deployment/)、[librosa](https://librosa.org/doc/latest/index.html)、[Playwright](https://playwright.dev/docs/intro)。版本和许可证通过npm/PyPI包元数据及实际安装核对，详见锁文件，不靠搜索片段推定。

已观察到的非阻塞提示：npm未执行可选fsevents安装脚本（未放宽脚本授权，Vite构建/测试已可运行）；FastAPI的上游TestClient对httpx与AnyIO接口发出弃用提醒，既有API测试可运行，升级测试客户端时再处理，不屏蔽警告。

## 本机私有音频制作依赖

当前准备脚本使用Python标准库及Mac系统 `/usr/bin/say`、`/usr/bin/afconvert`，分别生成中文指令与解码音频；系统组件随macOS安装，不由npm/uv锁版或随项目分发。Tingting须已安装，缺失时失败，不自动下载。macOS27已有实装证据，其他系统不能据此称已支持。学习API读取准备好的文件，运行时不需要ASR模型。旧裁切/审音工具已删除，不再列为制作依赖。

## 2026-10-05 家庭选定音频资源

[cmguo/PinYinSound](https://github.com/cmguo/PinYinSound/tree/62453b2a5ca6873eac1f4293b6e9794715d0fc8a)固定提交62453b2a5ca6873eac1f4293b6e9794715d0fc8a；归档SHA-256为c5d37feabd651ab3a1ccf7ac73d3a6e782c04caf4e61eb8778e7c7a7cacc5c18。原归档1420个MP3、22885289字节，未附LICENSE或来源说明，许可状态unknown，不作为MIT资产。已实际下载固定版本，205个映射经Mac afconvert解码/时长/非静音检查，183个去重MP3落在private/pinyinsound；各文件摘要见content/pinyin-source.json。不新增npm/uv软件依赖。产品按ADR-0008直接信任此来源作为标准音，不设置教学审核状态。

## 2026-10-05 LAN-01证书预检

运行端使用已锁定Node24.18.1内置`crypto.X509Certificate`、`createPrivateKey`与`tls.createSecureContext`，没有新增npm/uv包。测试调用现有系统OpenSSL生成临时自签证书；本机实测为OpenSSL3.6.4（2026-08-25），未安装或升级。该测试工具不随应用分发，也不在学习或预检命令中调用。官方[源码与版本来源](https://openssl-library.org/source/)及[许可证](https://openssl-library.org/source/license/index.html)说明3.x采用Apache-2.0。系统命令不受npm/uv锁文件管理，运行测试需提供支持`req -addext`的OpenSSL，并记录实际版本；没有自动下载或静默跳过证书单测。

## SPEC-009增量（2026-10-13）

新增pypinyin==0.55.0（MIT，官方PyPI及mozillazg/python-pinyin），uv.lock已固定，uv add实装成功；用于将本地识别文字转换为拼音，不判断实际声调。pywhispercpp==1.5.1（MIT）从可选维护组提升为运行依赖，复用原Whisper small文件和固定摘要，无新权重/训练。

## SPEC-010/011（2026-10-13）

维护组voice-build新增sherpa-onnx==1.13.8与sherpa-onnx-core==1.13.8，官方https://pypi.org/project/sherpa-onnx/1.13.8/ 与 https://pypi.org/project/sherpa-onnx-core/1.13.8/，k2-fsa Apache-2.0。macOS arm64 CPython3.12轮子实装成功；核心轮子提供libonnxruntime.dylib，不能仅安装Python扩展。uv.lock固定轮子哈希；仅维护生成组，播放服务不依赖它们。

Kokoro-82M-v1.1-zh，Apache-2.0，官方hexgrad模型卡与k2-fsa/sherpa-onnx官方ONNX转换。固定完整精度模型、归档和每个文件SHA见content/voice-build.json。实际本地CPU生成，无训练或云服务。模型/字典不入Git，输出中文WAV随仓库。MeloTTS与int8仅候选实验，未进入发布素材或最终构建配置。

一键脚本需要系统Git/curl/tar/shasum/macOS afconvert。缺失Node24.18.1/uv0.12.5时从官方nodejs.org及astral-sh GitHub固定release安装项目私有副本，下载SHA校验；npm11.16.0从官方registry固定包安装。Python3.12.12由uv使用.python-version安装。无全局npm升级、brew自动安装或sudo。

## SPEC-011 VOICE-09 中文质量替换（2026-10-13）

Kokoro/sherpa-onnx维护依赖已移除；使用[MLX-Audio 0.5.8](https://pypi.org/project/mlx-audio/0.5.8/)（[官方源码](https://github.com/Blaizzy/mlx-audio)，MIT），仅macOS arm64 voice-build组。锁文件固定mlx/metal 0.32.3（Apple MLX，MIT）、transformers 5.19.0（Hugging Face，Apache-2.0）及其全部传递依赖/轮子摘要；实装CPython3.12成功，Metal本地推理生成样例成功。许可元数据见python-dependency-inventory.json，安装包保留原许可。

[Qwen3-TTS-12Hz-1.7B-CustomVoice](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice)采用Apache-2.0；[mlx-community bf16转换](https://huggingface.co/mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-bf16)固定revision52f4770fd9726457eae3d3b6aa92047a25a10776。主权重3833402589字节SHA3a791fb8250fc32ab0259b679d834159d3c8516af62f033ff2b9f42913e3fab6；语音分词器682293092字节SHA836b7b357f5ea43e889936a3709af68dfe3751881acefe4ecf0dbd30ba571258。其余文件SHA/尺寸在content/voice-build.json。固定Serena/Chinese/教学语气，模型仅维护者显式下载，应用无模型推理依赖。无新增npm包、个人声纹、远程音频服务或模型训练。

## SPEC-012 READ-04（2026-10-14）

新增维护阶段[Qwen3-ForcedAligner-0.6B](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B)（Apache-2.0）用于已知中文脚本和预生成示范音频的逐字时间对齐。使用[mlx-community 8bit转换](https://huggingface.co/mlx-community/Qwen3-ForcedAligner-0.6B-8bit)，固定revision0e1a68e91d815300c7c9754b2a7639378b23db15；主权重1271924386字节SHAbe19ef8ac4326d032e7673342930b14c2df30bd68c1632493b0f563e30829f91。全部文件尺寸/SHA固定content/reading-alignment-build.json，许可resources/licenses/Qwen3-ForcedAligner-Apache-2.0.txt。复用已锁定MLX-Audio 0.5.8维护组，未增加npm/uv包；Apple Silicon实际离线加载、42段示范对齐成功。80ms分辨率，短音共用边界时采用锚定起点的40ms高亮窗口，不均分整句总时长。输出时间轴随Git提供，普通服务不下载或加载模型，也不分析儿童录音。

## 拼音字形 FONT-01（2026-10-15）

字体资产SIL Andika 7.000来自[官方固定发行](https://github.com/silnrsi/font-andika/releases/tag/v7.000)，OFL-1.1允许随应用分发，保留public/fonts/andika/OFL.txt。归档SHA-256为88ba6ea41ef4a8e5214b090df8fa2983be1babe4843efaa99cdb6078b0e2c070，与GitHub发行资产digest一致；Regular/Bold未修改WOFF2及文件摘要登记content/pinyin-font.json。文件由Mac同源服务提供，不使用CDN或系统字体作为拼音字形的必要依赖。官方[字形设计说明](https://software.sil.org/andika/design/)确认默认单层a/g与清晰变音符号；实际字形/声调须浏览器目视复核。没有新增npm/uv软件包。

## SPEC-013 Docker 构建（2026-10-16）

无新增 npm/uv 包。Node 官方镜像24.18.1-bookworm-slim（Node MIT，Debian组件各自许可）、Python 官方镜像3.12.12-slim-bookworm（Python PSF-2.0）与 Astral uv 0.12.5（MIT/Apache-2.0）均按多架构manifest SHA-256固定在`deploy/docker/Dockerfile`；npm11.16.0复用现有固定版本。官方来源分别为 https://github.com/nodejs/docker-node 、https://github.com/docker-library/python 、https://github.com/astral-sh/uv 。

Debian bookworm/security 软件包固定到 snapshot.debian.org 的20261015T000000Z快照（官方 https://snapshot.debian.org/），构建阶段安装 curl（curl许可）、FFmpeg（Debian构建GPL-2.0-or-later及其组件许可）以支持固定资源下载和音频检查；Python仅安装锁定的二进制轮子。运行镜像仅另含libgomp1（GCC运行库例外），各包许可保留在/usr/share/doc。具体实装与架构记录在SPEC-013，镜像内`dpkg-query -W`可查看精确版本。Whisper权重固定来源/摘要沿用scripts/asr_model.py，不纳入Git。

DOCKER-05的Windows x86-64宿主运行Linux amd64容器，不新增Windows原生包或更换模型。uv.lock已锁定pywhispercpp1.5.1的CPython3.12 manylinux_2_27/2_28_x86_64轮子（SHA-256 973eafb3c27f4bc67f5e13f92491f91cee4ae0dd2d50c1b19c610f34c9ded9d8）及NumPy2.5.3对应Linux x86-64轮子；来源均为官方PyPI，许可证分别MIT与BSD-3-Clause。Docker内CPU后端通过已锁定pywhispercpp的context_params.use_gpu=false选择，固定Whisper small权重摘要不变。Windows/amd64轮子实装、模型初始化与推理按用户要求本次未验证；此前arm64实装不作为Windows证据。

## DAILY-12 本地一声派生（2026-10-25）

无新增npm/uv依赖或模型。显式准备使用Python 3.12标准库的wave/struct/math实现时域PSOLA，解码复用现有macOS afconvert或Linux FFmpeg；目标300Hz与来源SHA记录在content/daily-reading-policy.json。维护检查复用已锁定的librosa 1.0.0（ISC，官方https://github.com/librosa/librosa）、NumPy 2.5.3（BSD-3-Clause，官方https://numpy.org/）、SciPy 1.18.1（BSD-3-Clause，官方https://scipy.org/），本机已实装并用于10条派生音的音高检查，普通运行/准备不依赖此维护组。派生音保持原录音unknown许可，仅写入private。

### GAME-01～03（2026-10-25）

新增游戏乐园无新增npm/uv依赖，沿用锁文件、React/FastAPI/SQLite及Python标准库zoneinfo。7份新增中文引导复用固定Qwen3-TTS/MLX本地生成，许可证与构建配置仍见content/voice-build.json、resources/licenses/Qwen3-TTS-Apache-2.0.txt和manifest；不下载模型或调用外部服务。

### SCENE-01～05、ADAPT-01～02（2026-10-25）

无新增依赖。四场景使用浏览器原生SVG、requestAnimationFrame与Web Audio短鼓声，纯TS物理计算；复用锁定React19.3.0和既有Andika字体。五段玩法中文按既有固定Qwen3-TTS/MLX配置在本机实际重新生成，manifest摘要与Apache-2.0许可保留；不在运行时下载模型或接入远程素材。新增会话配置使用Python标准库JSON和SQLite迁移9。安装来源和固定版本沿用本文件既有清单。
