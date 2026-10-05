# 依赖与供应链记录

核验/实装日期：2026-09-25。安装结果以锁文件为准，浏览到的“最新版本”不是无条件升级指令。

## 已选择并实装

| 用途            | 依赖                                    | 许可                              | 结果/选择原因                                                        |
| --------------- | --------------------------------------- | --------------------------------- | -------------------------------------------------------------------- |
| UI              | react / react-dom 19.3.0                | MIT                               | 单页交互生态成熟，后续可放入原生壳                                   |
| 构建            | vite 8.3.1 / plugin-react 6.1.1         | MIT                               | Node24兼容，静态产物由Mac API服务                                    |
| 类型            | typescript 6.0.3                        | Apache-2.0                        | 最新7.0.2超出typescript-eslint 8.70.1的peer范围，因此锁6.0.3         |
| 格式/lint       | prettier3.9.9 / ESLint10.11.0           | MIT                               | 自动化统一代码风格                                                   |
| 测试            | Vitest5.0.2 / Playwright1.63.0          | MIT / Apache-2.0                  | 已下载三浏览器运行时；不等同真机                                     |
| 内容Schema      | Ajv8.20.0                               | MIT                               | JSON结构及教学引用门禁                                               |
| API             | FastAPI0.141.1 / Uvicorn0.53.0          | MIT / BSD-3-Clause                | Python与声学计算环境一致                                             |
| 服务端测试/lint | pytest9.1.1 / httpx0.28.1 / ruff0.16.8  | MIT / BSD-3-Clause / MIT          | 锁定在uv dev组                                                       |
| 声学研究        | librosa1.0.0 / NumPy2.5.3 / SciPy1.18.1 | ISC / BSD-3-Clause / BSD-3-Clause | `assessment-poc`独立组，仅研究候选；已验证arm64原生轮子及YIN合成信号 |
| 数据库          | Python标准库sqlite3                     | 随Python/SQLite各自许可           | 单Mac家庭使用，避免数据库运维                                        |

Node24.18.1、npm11.16.0、uv0.12.5、Python3.12.12。本机更高Python版本不直接用于声学依赖，以减少兼容风险。安装Python时uv出现动态库install-name修补警告；预编译依赖与现有测试可运行，未来构建原生扩展须另行验证，不能据此声称所有C扩展都可编译。

`package-lock.json`和`uv.lock`包含固定版本/完整性哈希；项目registry使用官方npm/PyPI URL，避免把本机私人索引写进开源基础。用户可按网络环境使用受信镜像，但变更锁文件需验证哈希。

npm全部传递依赖的许可证声明见[自动清单](dependency-inventory.json)。声明不等于完整法律审查，二进制轮子、LLVM/OpenBLAS/libsndfile等附带许可证应保留随包分发的notice；Python分发包元数据另见[Python清单](python-dependency-inventory.json)，包/轮子来源及哈希见uv.lock。发布App二进制前另做实际打包产物SBOM，不仅看顶层许可证。

## 尚未选为产品依赖

评分模型/模板、商业离线SDK、示范真人音、教学拼音字体、笔顺资产均尚未获得完整发布资格。候选的代码、权重、训练数据和输出权利要分别审查，不以“GitHub开源”代替许可。SenseVoice是ASR且模型权重单列条款；MFA是对齐器；它们均不是直接合格的儿童拼音评分器。

暂无生产所需云API、收费配额或密钥。若研究授权离线SDK，需核验Mac arm64、服务器API封装、并发、离线激活、禁止外传、商用与再分发；只有维护者批准采购后才接入，不能把闭源SDK改标MIT。

## 升级流程

查官方release和peer约束 → 固定新版本 → 更新lock和清单 → 工程验证 → 受影响真机/评分基准 → 单独提交。禁止`npm audit fix --force`和未审查的安装脚本绕过。

一手资料：[Vite要求](https://vite.dev/guide/)、[uv项目与锁文件](https://docs.astral.sh/uv/guides/projects/)、[FastAPI部署](https://fastapi.tiangolo.com/deployment/)、[librosa](https://librosa.org/doc/latest/index.html)、[Playwright](https://playwright.dev/docs/intro)。版本和许可证通过npm/PyPI包元数据及实际安装核对，详见锁文件，不靠搜索片段推定。

已观察到的非阻塞提示：npm未执行可选fsevents安装脚本（未放宽脚本授权，Vite构建/测试已可运行）；FastAPI的上游TestClient对httpx与AnyIO接口发出弃用提醒，当前2项API测试通过，升级测试客户端时再处理，不屏蔽警告。

## 本机私有音频制作依赖

REVIEW-01–05未增加npm/uv包：服务使用既有锁定FastAPI/Uvicorn，裁切使用Python3.12标准库`wave`（PCM帧，不做合成拼音）。Mac源音解码调用操作系统自带`/usr/bin/afconvert`，官方来源是本机Apple系统安装，不复制或分发二进制，适用系统软件许可。该系统组件随macOS升级，不能通过npm/uv锁版；部署检查必须保留实际系统版本与13份MP3转换结果。开发机macOS27实装成功，其他系统不能声称已支持。运行时学习API不需要afconvert或ASR模型。

## 2026-10-05 家庭选定音频资源

[cmguo/PinYinSound](https://github.com/cmguo/PinYinSound/tree/62453b2a5ca6873eac1f4293b6e9794715d0fc8a)固定提交62453b2a5ca6873eac1f4293b6e9794715d0fc8a；归档SHA-256为c5d37feabd651ab3a1ccf7ac73d3a6e782c04caf4e61eb8778e7c7a7cacc5c18。原归档1420个MP3、22885289字节，未附LICENSE或来源说明，许可状态unknown，不作为MIT资产。已实际下载固定版本，99个映射经Mac afconvert解码/时长/非静音检查，85个去重MP3落在private/pinyinsound；各文件摘要见content/pinyin-source.json。不新增npm/uv软件依赖。产品按ADR-0008直接信任此来源作为标准音，不设置教学审核状态。
