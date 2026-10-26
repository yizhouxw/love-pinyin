# 预训练拼音匹配底层工具

对应 SPEC-018 MATCH-07～13。本工具独立于课程、跟读录音、HTTP 和家庭进度；模型包仅作本机研究，预训练质量结论与剩余门禁见[实测记录](../research/target-pronunciation-pretrained-results.md)。[候选核验](../research/pretrained-matcher-model-audit.md)说明实际权重、直接声学输出、许可及已知训练来源。下列命令不会替代独立真人或儿童验证。

当前交付包括实际运行过的比较、训练/微调、导出与CPU命令行工具；**质量门槛尚未通过，持续优化到约定质量的目标仍未完成**。尚需取得与孤立四声任务一致且可靠的实际发音标签、完成达到原门槛的模型优化，再冻结模型/参数/代码并开启最终评测。2026-10-26交付审阅只查元数据和路径：OMPAL预留10位说话人的494份WAV在预期目录和本轮忽略目录均未出现；现有公开结果为校准/诊断。儿童验证缺失不是当前唯一未完成项；应用层按本次范围不接入。

## 安装与固定资源

从仓库根目录执行，使用项目约定的 Python 3.12 和已锁定 uv；不使用 `latest` 或强制安装：

```sh
uv sync --project tools/pinyin-pretrained --locked --all-groups
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=2 VECLIB_MAXIMUM_THREADS=1
```

以下命令中的 Python 路径为 `./tools/pinyin-pretrained/.venv/bin/python`。该环境与应用、旧合成匹配器环境分开。MPS 只用于离线训练/缓存；最终加载和端到端测量固定 CPU 与两个推理线程。

显式准备固定模型；已有正确摘要的文件直接复用，坏文件明确报错，不静默替换：

```sh
./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_prepare hanziflow
./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_prepare charsiu
./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_prepare sensevoice
```

下载仅发生在显式准备阶段。`content/pronunciation-pretrained-models.json` 固定完整 revision、URL、字节数与 SHA256；权重进入 `models/pinyin-pretrained/`，缓存/语音进入 `private/pretrained-matcher/`，均不提交 Git。本地 CPU 包不意味着获得对外再分发第三方权重的授权；保留各自许可证。

## 复用冻结的公开成人数据配置

```sh
./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_data prepare \
  --config content/pronunciation-pretrained-data.json \
  --directory private/pretrained-matcher/data
```

普通复现使用已提交配置，**不要先执行 `snapshot`**。它按固定 OSF 文件版本和 SHA 下载 ManDi Standard Mandarin WL1，保留父录音/标注摘要、说话人、音节原始标注与提取时间窗。默认只准备训练和校准说话人，不读取留出的测试音频。ManDi 为成人语音，CC BY-NC 3.0，须保留原作者引用；语料预期读音和 MFA 时间戳并不保证实际发音逐项正确。

`pretrained_data snapshot` 是重新建立研究协议时的独立维护操作，会改变数据冻结配置，不能用来悄悄替换本次验收集。修复分割或发现标签问题后，保留旧结果作为诊断，记录协议变化，再冻结独立测试。

## 统一特征、探针和专用头

每个编码器使用相同清单与监督预算。示例为 HanziFlow；Charsiu 和 SenseVoice 替换 `--name`、模型/缓存/产物目录，并保持其余配置相同：

```sh
./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_experiment cache \
  --name hanziflow --model models/pinyin-pretrained/hanziflow \
  --manifest private/pretrained-matcher/data/manifest-train-calibration.json \
  --output private/pretrained-matcher/cache-hanziflow --device cpu

./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_experiment train \
  --name hanziflow --variant linear \
  --manifest private/pretrained-matcher/data/manifest-train-calibration.json \
  --cache private/pretrained-matcher/cache-hanziflow \
  --output private/pretrained-matcher/heads-hanziflow-linear --device cpu

./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_experiment train \
  --name hanziflow --variant multihead \
  --manifest private/pretrained-matcher/data/manifest-train-calibration.json \
  --cache private/pretrained-matcher/cache-hanziflow \
  --output private/pretrained-matcher/heads-hanziflow-multihead --device cpu
```

离线阶段可显式选择 `--device mps`。`linear` 为冻结编码器线性探针；`multihead` 学习非线性共享投影及声母/韵母/声调头，声调同时使用独立音高特征。训练自动导出 `heads.onnx`、归一化、学习曲线、阈值校准与模型摘要。所有声学编码器均看不到预期目标；没有汉字解码或语言模型补全。探针与专用头只是已完成的优化类型，不能写成完成了编码器全量微调或蒸馏。

原生直接声学头另作对照；SenseVoice 没有原生拼音/四声头，明确记为不适用：

```sh
./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_native \
  --name hanziflow \
  --manifest private/pretrained-matcher/data/manifest-train-calibration.json \
  --cache private/pretrained-matcher/cache-hanziflow \
  --output private/pretrained-matcher/raw-native-hanziflow-calibration.json
```

Charsiu 使用同命令替换名称/缓存/输出。HanziFlow 计算完整原词表的单标签 CTC 事件概率；空白、未知及多标签质量保留。Charsiu 使用全部原始音素的帧证据，声母和带调韵母归组；它的输出不能按 CTC 解释。原生词表外预测拒判，不只在训练目标子集中重新归一化伪造高置信。该原生校准命令的最难反例是任何替代音素组合，包含未出现在词表中的组合，属于保守诊断；正式冻结近邻类型须使用共同评测协议。

## 导出本地 CPU 包与调用

显式导出声学编码器的 FP32/动态 INT8 ONNX：

```sh
./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_export hanziflow \
  --model models/pinyin-pretrained/hanziflow

./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_bundle \
  --heads private/pretrained-matcher/heads-hanziflow-multihead \
  --encoder models/pinyin-pretrained/hanziflow \
  --output models/pinyin-pretrained-cpu/hanziflow-multihead --backend int8

./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_runtime info \
  --model models/pinyin-pretrained-cpu/hanziflow-multihead

./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_runtime match \
  --model models/pinyin-pretrained-cpu/hanziflow-multihead \
  --target pm-ba1 --wav /absolute/path/reading.wav
```

输出目录须不存在，避免覆盖已冻结产物。`info` 返回实际覆盖目标，调用时使用其中的 ID。输入为 16kHz 单声道 PCM16 WAV；返回 `matched/retry/uncertain/unavailable`，不返回儿童百分制。默认 `experimental=true`、`toneAssessed=false`，无可靠证据时拒判；目标未覆盖或文件缺失/坏摘要不作成功降级。推理只读本地资源，录音不落盘，加载 ONNX 固定 CPU provider 与两个推理线程。INT8 与 FP32 的效果及延迟须分别实测，导出成功不表示质量或性能达标。

正式冻结评测与 CPU 测量的最终命令和结果由[本轮实验记录](../research/target-pronunciation-pretrained-results.md)列出；最终语音准备、切片、缓存与评测均须显式提供同一 `--frozen-plan`。不得用测试选择训练轮次或阈值。

## 完整分母、冻结与验证

`pinyin_matcher.pretrained_metrics.metrics(records)` 对同一原始音频的多个错误目标取任一放行，完整报告正确接受、明确误拒、拒判、未知标签和每类反例；缺失结果计拒判。报告 Wilson 95% 区间和固定种子的说话人整群 bootstrap。每个描述性验收类别至少 100 个原始根样本、5 位已知说话人，仍不构成人群或儿童验证。质量门槛固定 5%/10%/20%；四秒端到端需同时满足 p95≤500ms、实时率≤0.1，即实际≤400ms。

`freeze(records, files=..., code_files=..., model_files=..., config=...)` 按数据、配置、代码和模型文件摘要形成确定计划，拒绝 train/calibration/test 之间的说话人、音色家族、克隆参考及音频谱系重叠。正式验收应保存该计划，不能只有一个测试清单的文件名。

实际 CLI 使用 `pretrained_evaluate freeze`。它绑定训练清单、公开源配置、依赖锁、教材目标、整个执行管线及每个 CPU 包文件；在打开最终声音前冻结公开专家票及词汇标注的完整字根库存。准备与评测会重算计划自身的摘要，校验全部文件，并拒绝换源、换说话人、改标签、漏字根或未绑定的派生清单。模型、代码或配置改变后须建立新实验；已使用的最终数据转为诊断。

```sh
# 所有优化完成并确定模型/阈值后执行；--model 可重复以固定多个待对比包
./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_evaluate freeze \
  --manifest private/pretrained-matcher/ompal-clips-v2/manifest.json \
  --model /absolute/path/final-cpu-package \
  --output private/pretrained-matcher/frozen-plan.json

./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_ompal prepare \
  --include-frozen-test --frozen-plan private/pretrained-matcher/frozen-plan.json

./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_ompal_clips \
  --utterances private/pretrained-matcher/ompal/utterances-with-frozen-test.json \
  --output private/pretrained-matcher/ompal-final-clips \
  --include-frozen-test --frozen-plan private/pretrained-matcher/frozen-plan.json

./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_evaluate evaluate \
  --manifest private/pretrained-matcher/ompal-final-clips/manifest.json \
  --model /absolute/path/final-cpu-package --split test \
  --freeze private/pretrained-matcher/frozen-plan.json \
  --output private/pretrained-matcher/final-evaluation.json
```

如果另做最终特征诊断，`pretrained_experiment cache --include-frozen-test` 也必须加 `--frozen-plan`；不能用该缓存继续训练或校准。

```sh
./tools/pinyin-pretrained/.venv/bin/python -m pytest tests/pretrained -q
./tools/pinyin-pretrained/.venv/bin/python -m ruff check pinyin_matcher/pretrained_*.py tests/pretrained
```

这些测试证明工具边界，不替代真实模型效果、CPU 资源、真实儿童或家庭 LAN 验收。

## 固定依赖与实装证据

本机 CPython 3.12.12/arm64 已实际安装下列直接依赖；完整 55 个锁文件条目与本机实际安装的 38 个 distribution、原始许可证元数据及随轮子许可证摘要见[机器清单](pretrained-python-dependency-inventory.json)。55 包含虚拟项目及 Linux CUDA 等平台条件项，不能写成在这台 Mac 上全部实装。

| 固定直接依赖           | 官方来源                                                                                                           | 许可证                        |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------ | ----------------------------- |
| torch 2.8.0            | [PyPI](https://pypi.org/project/torch/2.8.0/)、[PyTorch](https://github.com/pytorch/pytorch)                       | BSD-3-Clause                  |
| torchaudio 2.8.0       | [PyPI](https://pypi.org/project/torchaudio/2.8.0/)、[PyTorch Audio](https://github.com/pytorch/audio)              | BSD-2-Clause                  |
| transformers 4.57.1    | [PyPI](https://pypi.org/project/transformers/4.57.1/)、[Hugging Face](https://github.com/huggingface/transformers) | Apache-2.0                    |
| huggingface-hub 0.36.0 | [PyPI](https://pypi.org/project/huggingface-hub/0.36.0/)                                                           | Apache-2.0                    |
| safetensors 0.6.2      | [PyPI](https://pypi.org/project/safetensors/0.6.2/)                                                                | Apache-2.0                    |
| numpy 2.5.4            | [PyPI](https://pypi.org/project/numpy/2.5.4/)                                                                      | BSD-3-Clause 及随轮子组件许可 |
| scipy 1.18.1           | [PyPI](https://pypi.org/project/scipy/1.18.1/)                                                                     | BSD-3-Clause 及随轮子组件许可 |
| onnx 1.23.2            | [PyPI](https://pypi.org/project/onnx/1.23.2/)                                                                      | Apache-2.0                    |
| onnxruntime 1.31.0     | [PyPI](https://pypi.org/project/onnxruntime/1.31.0/)                                                               | MIT                           |
| pypinyin 0.55.0        | [PyPI](https://pypi.org/project/pypinyin/0.55.0/)                                                                  | MIT                           |
| pytest 9.1.1（dev）    | [PyPI](https://pypi.org/project/pytest/9.1.1/)                                                                     | MIT                           |
| ruff 0.17.1（dev）     | [PyPI](https://pypi.org/project/ruff/0.17.1/)                                                                      | MIT                           |

来源索引和全部平台轮子 SHA 由 `tools/pinyin-pretrained/uv.lock` 固定。实际模型加载、训练、导出与故障边界均需保留本轮运行记录，不从“已安装”推断识别质量。

## OMPAL 专家错误样本的固定准备

OMPAL 公开语音与标注使用 CC BY 4.0。实际说话人身份依据 WAV 目录；旧 detailed 的篇章 ID 不能作为独立说话人。`content/pronunciation-ompal-detail-id-map.json` 通过完整官方元数据的精确唯一连接保存原评分归属；`content/pronunciation-ompal-policy.json` 单独冻结期待词汇读音和含糊上下文。二值 aggregate 是多数表决，不代替 detailed 一致原票。文字数组中的备选词不拼接成多个音节。

普通复现使用已固定配置，不重新 snapshot：

```sh
./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_ompal prepare \
  --config content/pronunciation-ompal-data.json \
  --directory private/pretrained-matcher/ompal

./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_ompal_clips \
  --utterances private/pretrained-matcher/ompal/utterances-train-calibration.json \
  --output private/pretrained-matcher/ompal-clips-v2-rebuild \
  --model models/pinyin-pretrained/hanziflow --device cpu
```

实际 utterance 清单文件名以准备命令返回值为准。对齐只生成候选音节边界，**不提供发音正确性**；正确/错误来自独立专家原票，标签含糊与边界失败独立保留。最后一次尝试和语境轻声等标注政策限制，见[核验记录](../research/pretrained-matcher-model-audit.md)。冻结测试仍须显式准备参数和已保存的冻结计划，不能用已查看结果的数据重新充当盲测。

`ompal-clips-v2/manifest.json` 是本轮已经保存的历史清单。干净重建使用上例的新目录，并把后续所有 `--manifest` 一起指向新清单；它记录当前准备代码的 SHA，可能与历史清单摘要不同。不得覆盖旧清单或将新结果改写成旧摘要。原32目标模型、370条TTS诊断及历史pipeline快照保存在本机忽略目录；Git代码本身不包含这些历史权重和录音，丢失它们时不能由同文本重新生成音频来冒充逐字节重放。

如需重新核对 ID 连接，先使用固定源文件，再运行：

```sh
./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_ompal_id_map \
  --aggregate /absolute/path/non-native_scores.json \
  --detailed /absolute/path/non-native_scores-detail.json \
  --output /absolute/path/rebuilt-ompal-detail-id-map.json
```

精确签名不相等或评分平票会报错，多个候选身份保持 unresolved；不得由声音、预测标签或相近文件名猜配。

## 校准压力病例与三包 CPU 运行

协议固定在 `content/pronunciation-pretrained-stress.json`。只选 OMPAL 校准说话人的专家全对、政策/数值/边界无异常、三包共同覆盖片段，按固定 SHA 顺序每位选 3 个锚。两个音节使用不同父录音的真实片段连接；语音来源和专家票保留，不把拼接误称自然连续语流或新独立说话人。静音漏读、0/-5dB 污染、过长/过短、错误采样率、截断和坏格式均属于须拒判输入。

必须先完成 HanziFlow `ii/iii` 语义修正后的 v2 边界与三模型包重建。`prepare` 核对来源完整 SHA、v2 边界版本、模型专属韵母映射、上游 schema、对齐代码 SHA 及三包训练清单 SHA，拒绝旧边界或旧包。创建 v2 清单后只增加了冻结测试验证和来源元数据；其原切片代码快照仍保存在忽略目录，SHA `69e661fe6dead31808f28e482f57247717f0d4d887bc4cc0bb2ee91a150bec37`。压力清单同时保留创建时与当前代码/配置 SHA，以实值映射核对音素语义，不因后来训练配置或 final gate 的变化重写既有清单。

下面是本轮本地历史产物的重放命令，必须保留所列原清单、原包与原pipeline快照。对于当前代码新建的清单，应读取新清单实际SHA传给 `--expected-source-sha256`，并使用从同一新清单训练的三包；当前pipeline与清单相符时省略 `--source-pipeline-snapshot`。输出使用新目录/文件名，不覆盖已记录压力结果。

```sh
./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_stress prepare \
  --manifest private/pretrained-matcher/ompal-clips-v2/manifest.json \
  --expected-source-sha256 2e1259602b83a2d1445f8a58dfba28c21d2e83213993fc6cdb3b4fbc38ceff01 \
  --source-pipeline-snapshot private/pretrained-matcher/ompal-v2-clips-pipeline-before-final-gates.py \
  --package models/pinyin-pretrained/bundles/ompal-v2-hanziflow \
  --package models/pinyin-pretrained/bundles/ompal-v2-charsiu \
  --package models/pinyin-pretrained/bundles/ompal-v2-sensevoice \
  --output private/pretrained-matcher/stress-calibration-v2

./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_stress evaluate \
  --manifest private/pretrained-matcher/stress-calibration-v2/manifest.json \
  --package models/pinyin-pretrained/bundles/ompal-v2-hanziflow \
  --output private/pretrained-matcher/stress-hanziflow-v2.json
```

对另外两包使用相同病例清单，分别保存输出。运行只读取 CPU 包，不修改模型、阈值或录音。每个原始 payload SHA 合并其全部目标查询，两个构成目标任一被放行即该波形失败；重复静音/坏格式不虚增独立样本。缺失结果保留为 unavailable。报告同时列出清晰正例接受/误拒/拒判、多读放行、不可评估输入被接受及被明确判错的计数、完整分母与 Wilson 区间。这是有相关性的校准压力诊断，不是冻结真人或儿童验收。

## 原 32 目标基线的隔离复现

原实现固定为 `335a09d2782891c2858b8e248c471793ada14ecc`，模型仍为 2,730,431 字节的原双 ONNX 包。CLI 不加载当前工作目录的旧 matcher 源；启动前逐文件与该 Git 修订核对归档的 Python/content SHA，加载后再断言所有 `pinyin_matcher` 模块均来自归档。原模型、原 370 条 TTS 诊断清单也绑定固定 SHA，不重新训练。OMPAL 与 ManDi 仅读取校准；原 TTS 的历史 `split=test` 在本次属于已知诊断，不充当新冻结测试。

```sh
tools/pinyin-matcher/run.sh setup-runtime
baseline_repo=/Users/chad/dev/love-pinyin
baseline_snapshot="$baseline_repo/private/pretrained-matcher/baseline-code-335a09d"
mkdir -p "$baseline_snapshot"
git -C "$baseline_repo" archive 335a09d2782891c2858b8e248c471793ada14ecc \
  pinyin_matcher content/pronunciation-targets.json \
  content/pronunciation-rules.json content/pronunciation-training.json \
  | tar -x -C "$baseline_snapshot"

cd "$baseline_snapshot"
PYTHONPATH="$baseline_snapshot" OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=2 \
  VECLIB_MAXIMUM_THREADS=1 \
  "$baseline_repo/tools/pinyin-matcher/.runtime/bin/python" \
  "$baseline_repo/tools/pinyin-pretrained/preserved_baseline.py" \
  --repository-root "$baseline_repo" \
  --snapshot "$baseline_snapshot" \
  --model "$baseline_repo/models/pinyin-pretrained/baseline-preserved" \
  --mandi-manifest "$baseline_repo/private/pretrained-matcher/data/manifest-train-calibration.json" \
  --ompal-manifest "$baseline_repo/private/pretrained-matcher/ompal-clips-v2/manifest.json" \
  --tts-manifest "$baseline_repo/private/matcher-data/manifest.json" \
  --output "$baseline_repo/private/pretrained-matcher/baseline-comparison-v2-repro.json"
```

使用原 minimal `.runtime` 的已锁定 NumPy/SciPy/ORT 环境；实际 Python、包版本、解释器路径与代码/权重/输入清单 SHA 全部写入输出。CLI 拒绝覆盖已有结果；再次复现须使用新的输出文件名，保留第一次数据和统计。四秒基准采用同一 CHD_012_F 校准压力波形，2 CPU 线程、3 次暖机、30 次计时；涵盖解码、特征、两个模型和目标比较。模型内存在读取 OMPAL 大清单前采样；含离线评测元数据的进程峰值另报。首份 `baseline-comparison-v2.json` 在加载大清单后采样 RSS，其仪器口径问题保留记录，模型内存使用 `-v2-repro.json`。完整结果同时给出原 32 目标共同覆盖子集与全体不可用/拒判分母，不能用范围外输入被拒判推断错误放行能力。

## 独立 SwiftF0 音高缓存

`content/pronunciation-pretrained-pitch.json` 固定 `pretrained-swift-relative32-pitch68-v2`。它复用已有 MIT SwiftF0 本地 ONNX 与纯 CPU 适配器，只需要本工具已经锁定的 NumPy/SciPy/ORT；不导入 SwiftF0 Python 工具包或旧 matcher 决策。68 维仍是相对 F0 32 点、变化 32 点和有声比例/范围/跨度/中位音高 4 项。等距采样保留真实时间位置；少于六个有声帧返回全零和不可用 flag，不能把零向量当可靠声调证据。新头必须另训，不能复用旧 YIN 头权重。

如果本地固定 Swift 权重尚不存在，先按[已有工具的固定依赖和许可](../research/matcher-pitch-swift.md)显式准备；第二步只复制已安装工具包中的135,090字节ONNX和MIT许可，推理不会调用安装流程：

```sh
uv sync --project tools/pinyin-matcher --locked --all-groups
tools/pinyin-matcher/.venv/bin/python -m pinyin_matcher.pitch_swift \
  --install-from-tool-package models/matcher-pitch-swift
```

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=2 VECLIB_MAXIMUM_THREADS=1 \
  tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_pitch \
  --manifest private/pretrained-matcher/ompal-clips-v2/manifest.json \
  --model models/matcher-pitch-swift/model.onnx \
  --output private/pretrained-matcher/ompal-v2-swift-pitch
```

只准备 train/calibration，其他 split 只计元数据且不打开录音；显式 `--include-test` 拒绝执行。缓存按原音频 SHA 去重，identity 绑定协议、原清单、Swift 权重和许可、适配器、PitchTrack 辅助代码、解码器与特征代码 SHA。原声学缓存与全局特征配置不变。训练侧复用 `PitchCache(path).read(row)`，返回 `(float32[68], {available,flags})`；数值异常、placeholder 或弱有声记录保留，并通过读取接口返回全零不可用证据。推理侧使用 `SwiftPitchVector(local_model).vector(samples)`，不得忽略不可用 flag。

同一批预先固定的 24 个 OMPAL 专家全对校准锚中，原 YIN 有声 469/984 帧，Swift 285/592 帧；各自最低有效点规则通过 24/24 和 22/24。连续有声相邻点的近整倍频跳变分别 4/427 对和 2/253 对。它们的帧间隔、频率区间和有声阈值不同；没有 F0 真值，不能把更多点、更平滑或两者分歧说成准确率提高。实际逐帧诊断保留在 `private/pretrained-matcher/pitch-swift-calibration-probe.json`，不读取冻结测试，也不据此宣称声调或儿童验证通过。

## 末层微调及新特征读出的重建命令

HanziFlow 末层微调遵循 `content/pronunciation-pretrained-finetune.json`；SenseVoice50 使用 `content/pronunciation-pretrained-sensevoice-finetune.json` 固定层数、2轮头部预热和10轮末层训练。下列命令是可运行的独立重建，所有目录使用新名称；原始三模型及历史失败产物保留。示例清单来自当前代码重新准备的目录，实际复现本轮历史清单时替换为其本地原路径。

```sh
rebuild_manifest=private/pretrained-matcher/ompal-clips-v2-rebuild/manifest.json

./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_finetune train \
  --model models/pinyin-pretrained/hanziflow --manifest "$rebuild_manifest" \
  --output models/pinyin-pretrained/hanziflow-finetuned-rebuild --device mps --epochs 10

./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_sensevoice_finetune \
  --model models/pinyin-pretrained/sensevoice \
  --vocabularies models/pinyin-pretrained/hanziflow --manifest "$rebuild_manifest" \
  --output models/pinyin-pretrained/sensevoice-finetuned-rebuild --device mps

for rebuild_name in hanziflow sensevoice; do
  ./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_experiment cache \
    --name "$rebuild_name" --model "models/pinyin-pretrained/$rebuild_name-finetuned-rebuild" \
    --manifest "$rebuild_manifest" --device mps --batch-size 4 \
    --output "private/pretrained-matcher/$rebuild_name-finetuned-rebuild-cache"
done

./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_pitch \
  --manifest "$rebuild_manifest" --model models/matcher-pitch-swift/model.onnx \
  --output private/pretrained-matcher/swift-pitch-rebuild

./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_experiment train \
  --name hanziflow --variant tone-specialist --manifest "$rebuild_manifest" \
  --cache private/pretrained-matcher/hanziflow-finetuned-rebuild-cache \
  --pitch-cache private/pretrained-matcher/swift-pitch-rebuild/manifest.json \
  --output private/pretrained-matcher/hanziflow-swift-tone-rebuild --device mps

./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_bundle \
  --heads private/pretrained-matcher/hanziflow-swift-tone-rebuild \
  --encoder models/pinyin-pretrained/hanziflow-finetuned-rebuild --backend torch \
  --pitch-model models/matcher-pitch-swift/model.onnx \
  --output models/pinyin-pretrained/bundles/hanziflow-swift-tone-rebuild
```

同一新声学缓存可另训 `linear`、`multihead` 与 `tone-specialist`，替换输出目录保留对照；原始三款同预算比较也用同一清单，分别在各自原始编码器上缓存和训练。Swift消融通过有无 `--pitch-cache` 区分，打包Swift候选必须显式给出 `--pitch-model`；该权重与许可一起进入CPU包。MPS浮点运算不承诺跨硬件逐位相同，固定源文件、协议、依赖和输出SHA用于追踪每次实跑。所有这些训练/校准命令均不读取最终声音。

## 完整四声目标与直接 CTC 匹配

固定训练集合排除政策/数值异常及 placeholder 后有 7386 个自然音节根。目标集合只从这些根观察到的合法音节 base 扩展四声，现为 1208 个目标；不构造未见过的任意声母/韵母组合。旧 549 个观察目标及小目录没有覆盖每个音节的四声，全部结果保留为诊断。反事实评测须完整查询与真值恰差一个分量的合法目标，声调近邻覆盖 2239/2239 正确校准根。

`pretrained_ctc_runtime` 使用 HanziFlow 原有三头或本项目新训练的 SenseVoice50 三头，保留全部原生类别的空白、单标签、多标签、未知及目录外概率质量，不按已知目标或当前目录重新归一化。SenseVoice50 的头是追加训练结果，原始 SenseVoice 没有原生音素/声调头。两者沿用已核验的 HanziFlow 符号约定 `ii=卷舌`、`iii=平舌`；Charsiu 的相反约定另行处理。

```sh
# 示例：完成 HanziFlow 真实专家微调及绑定缓存后，固定15组阈值仅在校准集选择
./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_ctc_runtime calibrate \
  --name hanziflow \
  --manifest private/pretrained-matcher/ompal-clips-v2/manifest.json \
  --cache private/pretrained-matcher/ompal-v2-hanziflow-finetuned-cache \
  --model models/pinyin-pretrained/hanziflow-finetuned-v2 \
  --output private/pretrained-matcher/ompal-v2-hanziflow-finetuned-native-ctc-four-tones

./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_ctc_runtime bundle \
  --calibration private/pretrained-matcher/ompal-v2-hanziflow-finetuned-native-ctc-four-tones \
  --model models/pinyin-pretrained/hanziflow-finetuned-v2 \
  --output models/pinyin-pretrained/bundles/ompal-v2-hanziflow-finetuned-native-ctc-four-tones

./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_runtime match \
  --model models/pinyin-pretrained/bundles/ompal-v2-hanziflow-finetuned-native-ctc-four-tones \
  --target pm-ma1 --wav /absolute/path/to/local.wav

./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_evaluate evaluate \
  --manifest private/pretrained-matcher/ompal-clips-v2/manifest.json \
  --model models/pinyin-pretrained/bundles/ompal-v2-hanziflow-finetuned-native-ctc-four-tones \
  --split calibration \
  --output private/pretrained-matcher/ompal-v2-hanziflow-finetuned-native-ctc-four-tones-full-calibration.json
```

SenseVoice50 使用 `--name sensevoice`、模型目录 `models/pinyin-pretrained/sensevoice-finetuned-v1` 和绑定缓存 `private/pretrained-matcher/ompal-v2-sensevoice-finetuned-cache`，输出目录使用其独立名称。校准命令拒绝包含最终测试的清单；CPU 包只复制并核验本地固定资源，启动与推理不下载。运行时统一 CPU 两线程，坏包/取消/超时/弱证据返回不可用或拒判。完整波形评测保留所有专家原始行、反事实近邻和真实错误的分别根分母；不能将原生分量 best-label 诊断当成整体发音匹配准确率。

同一四秒压力文件须先生成并固定 SHA，所有包使用其原始 bytes：

```sh
# 原始基线归档步骤见前文；此命令不推理，也不裁剪静音。
# 已有文件时使用新的输出路径，避免覆盖已有计时来源。
./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_pressure \
  --source private/pretrained-matcher/data/clips/calibration/mandi-cmn-wl1-CHD_012_F-000.wav \
  --archived-audio-code "$baseline_snapshot/pinyin_matcher/audio.py" \
  --output private/pretrained-matcher/cpu-pressure-exact.wav

./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_evaluate benchmark \
  --model models/pinyin-pretrained/bundles/ompal-v2-hanziflow-finetuned-native-ctc-four-tones \
  --wav private/pretrained-matcher/cpu-pressure-exact.wav \
  --exact-four-seconds --target pm-ma1 \
  --output private/pretrained-matcher/ompal-v2-hanziflow-finetuned-native-ctc-four-tones-full-cpu.json
```

`pm-ma1` 必须是包声明的目标；若更换目标仍须在各包共同覆盖内，并记录同一 payload SHA。基准会断言每次实际进入编码器；包含解码、前端、模型和目标比较。先等同时运行的训练/评测结束，再做顺序性能测量。目标为暖机 p95≤500ms 且实时率≤0.1；四秒时两者共同意味着 p95≤400ms。

固定压力配置是 `content/pronunciation-pretrained-cpu-pressure.json`，它分别核对原始源 WAV、归档解码/编码源及最终四秒 bytes 的 SHA。已实际生成独立校验副本，与旧基线所用 payload 完全一致；此重复波形仅作长度压力，不能用来计算正确发音接受率。完整冷启动另用 `pretrained_cold --model … --wav … --target pm-ma1 --output …`，五个新进程均执行完整 CLI；系统文件缓存不清除，不能把此结果称为断电后的首次启动。

### 最终性能使用的新共同连续波形

实际重测发现，上述历史重复波形被当前多读数值保护拦截；九个包均没有进入编码器，18 次暖机/冷启动尝试的失败 JSON 留存，不能报告为模型 p95。最终改用公开 OMPAL 校准父句 `ompal-00200706` 的连续四秒原 PCM，不重复、不变幅、不重采样；仅按 ID 顺序和数值输入保护选窗，没有查询模型判定。完整句的多音节只用于长度压力，不赋予正确拼音标签。

```sh
./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_pressure \
  --source private/pretrained-matcher/ompal/raw/wav/SPEAKER02007/00200706.wav \
  --config content/pronunciation-pretrained-cpu-pressure-continuous.json \
  --output private/pretrained-matcher/cpu-pressure-continuous.wav

./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_evaluate benchmark \
  --model models/pinyin-pretrained/bundles/ompal-v2-sensevoice-finetuned-native-ctc-int8-four-tones \
  --wav private/pretrained-matcher/cpu-pressure-continuous.wav \
  --exact-four-seconds --target pm-ba1 \
  --output private/pretrained-matcher/sensevoice-int8-continuous-cpu.json

./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_cold \
  --model models/pinyin-pretrained/bundles/ompal-v2-sensevoice-finetuned-native-ctc-int8-four-tones \
  --wav private/pretrained-matcher/cpu-pressure-continuous.wav --target pm-ba1 \
  --output private/pretrained-matcher/sensevoice-int8-continuous-cold.json
```

配置固定源 SHA、PCM 帧区间 `[28000,92000)` 和最终 payload SHA `6d2ecbfa74b82a45326b7de100395406283db5ea35f1e5ce50b92197018f1cfc`。已从源重新生成独立校验副本，逐字节相同。每个候选均顺序运行上述两种基准；`pm-ba1` 为九包共同覆盖目标，计时包括完整模型和目标比较，但不以该句判断此目标的质量。

原基线使用前文同一归档、模型及清单参数，额外传 `--benchmark-only --pressure-wav /absolute/path/cpu-pressure-continuous.wav --pressure-sha256 6d2ecbfa74b82a45326b7de100395406283db5ea35f1e5ce50b92197018f1cfc`，另选新 `--output`。它不重新执行 4,732 条历史诊断；仍核验原修订/源码/权重，并断言实际进入编码器。冷启动在五个独立 `subprocess.run` 中为同一命令再加 `--cold-only`，分别使用新的输出路径；用 `time.perf_counter()` 在启动进程前、返回后计壁钟时间，并保存五次记录及 NumPy `percentile(times,95)`。`--cold-only` 不运行暖机或30次重复，壁钟包含 Python、归档来源核验、加载、一次完整推理、JSON及退出；系统文件缓存同样不清除。

## SenseVoice50 三头的独立 INT8 导出

`pretrained_sensevoice_export` 只导出本项目已训练的 50 层编码器、固定 prompt 与新增声母/韵母/声调头，省略原 SenseVoice 的字符输出和 20 层任务编码器。原始 70 层权重、50 层 FP32 微调模型和已有 CPU 包均保留。下例使用新目录，避免覆盖本轮已经实跑的 `sensevoice-finetuned-v1-int8`：

```sh
tools/pinyin-pretrained/run.sh sensevoice-export \
  --model models/pinyin-pretrained/sensevoice-finetuned-v1 \
  --output models/pinyin-pretrained/sensevoice-finetuned-v1-int8-rebuild

tools/pinyin-pretrained/run.sh ctc bundle \
  --calibration private/pretrained-matcher/ompal-v2-sensevoice-finetuned-native-ctc-four-tones \
  --model models/pinyin-pretrained/sensevoice-finetuned-v1 \
  --quantized-model models/pinyin-pretrained/sensevoice-finetuned-v1-int8-rebuild \
  --output models/pinyin-pretrained/bundles/sensevoice50-native-ctc-int8-rebuild

tools/pinyin-pretrained/run.sh evaluate \
  --manifest private/pretrained-matcher/ompal-clips-v2/manifest.json \
  --model models/pinyin-pretrained/bundles/sensevoice50-native-ctc-int8-rebuild \
  --split calibration \
  --output private/pretrained-matcher/sensevoice50-int8-rebuild-full-calibration.json
```

直接 Python 入口为 `python -m pinyin_matcher.pretrained_sensevoice_export --model … --output …`。导出同时保存 FP32 ONNX 诊断图和独立 INT8 运行资源；CPU 包的资源清单不包含该 FP32 图。运行适配器为 `OnnxSenseVoiceEvidence(directory, device="cpu", threads=2)`，返回 `frames` 与完整 `native.initial/final/tone`；只用 ORT CPU provider，保留空白、未知及多标签事件，不静默回退。前端沿用固定 CMVN、dither=0、LFR7/stride6 和四个固定中文 prompt，不接受目标作为编码器输入。

本轮实际 FP32 权重为 632,170,436 字节，动态逐通道 MatMul/Gemm INT8 图为 **162,521,455 字节**，SHA256 `c9d8b93ab64e9bf4e3e50d3df096a78f018a79aa3b2a538c29ec3af2b8762c95`；卷积及归一化保持 FP32。`tuned.json` 绑定图与全部小资源，`parent-tuned.json` 保留父 FP32 元数据原始字节，并分别核对父元数据 SHA、父权重 SHA、上游修订和许可；推理不需要原始 `model.pt` 或 `tuned.safetensors`。

实际 150ms、0.5s、4s 与变长批次的图/CPU 测试已运行，FP32 图对 Torch 最大差为隐藏帧 5.53e-5、三头 4.75e-5。所测 INT8 隐藏帧余弦为 0.99839～0.99982，但完整单标签 CTC 概率质量最大变化可达 0.0291。此处的重复真实波形只验证动态形状和数值，不带新的发音真值，不能据此宣称量化保留质量。动态激活缩放受同批音频及 padding 影响；最终采用逐条 batch=1 的完整 CPU 校准与压力评测，固定继承 FP32 校准阈值，不用小例或批量缓存替代实际运行，也不借量化重新放宽门槛。

```sh
# 复现本轮实际导出上的数值验证；只是计算/资源边界测试。
PRETRAINED_MODELS=models/pinyin-pretrained \
PRETRAINED_TEST_WAV=private/pretrained-matcher/ompal-clips-v2/clips/ompal-00200701-w002.wav \
PRETRAINED_PARITY_OUTPUT=private/pretrained-matcher/sensevoice50-int8-parity-repro.json \
  tools/pinyin-pretrained/.venv/bin/python -m pytest \
    tests/pretrained/test_sensevoice_export.py -q
```

该导出无新增依赖，复用锁定的 torch 2.8.0（BSD-3-Clause）、torchaudio 2.8.0（BSD-2-Clause）、ONNX 1.23.2（Apache-2.0）、ONNX Runtime 1.31.0（MIT）及 safetensors 0.6.2（Apache-2.0）；来源、轮子摘要和实装清单见前文。量化不改变许可归属：SenseVoice 代码 MIT 与权重 FunASR Model License 1.1 分别继承，新增三头使用的 HanziFlow 固定音素符号词表及 schema 保留来源与 SHA。权重、图和数据继续只放本机忽略目录，Git 不分发它们。

## 当前交付边界

三款原始模型的同预算比较、列出的实际微调和读出优化均保留各轮结果，但没有候选通过完整质量门槛。校准不能代替最终验收；OMPAL 预留的 10 位说话人、494 份 WAV 未下载、未推理，须在模型和阈值确定后才启用。其公开标注库存也显示真实声母、韵母错误分别不足 100 个独立根，因此最终留出本身仍不足以关闭全部分层样本量门禁。句中成人发音及最后一次尝试的专家评分不能验证儿童孤立拼音、多读/漏读的全部实际范围。

当前可运行包是研究包，应用层尚未接入。剩余门禁包括原 5%/10%/20% 质量、独立孤立音与真实近邻错误的可信分量标签及足量说话人、冻结测试和真实儿童验证；延迟/内存与输入挑战分别按实际结果报告，不用某一单项通过追认整体通过。

## MATCH-12：独立分量头、时序头与特征插值训练

本轮在同一 OMPAL v2 train/calibration 清单上实际完成五次 120 轮训练，并构建固定等权集成。所有超参继承已有锁定配置；`mixup` 另绑定 `content/pronunciation-pretrained-mixup.json`。仅专家三分量一致正确行参与特征软标签插值；没有新增合成音频或对未知错音伪造实际读音。新增实现不引入依赖，继续使用本工具 `uv.lock`。

以下复现原编码器三个新读出；使用新的输出目录，保留已实测包。运行前按前文准备同一清单与原始缓存。

```sh
for variant in independent temporal mixup; do
  tools/pinyin-pretrained/run.sh train \
    --manifest private/pretrained-matcher/ompal-clips-v2/manifest.json \
    --cache private/pretrained-matcher/ompal-v2-bound-sensevoice \
    --name sensevoice --variant "$variant" --device mps \
    --output "private/pretrained-matcher/rebuild-sensevoice-$variant"
  tools/pinyin-pretrained/run.sh bundle \
    --heads "private/pretrained-matcher/rebuild-sensevoice-$variant" \
    --encoder models/pinyin-pretrained/sensevoice --backend int8 \
    --output "models/pinyin-pretrained/bundles/rebuild-sensevoice-$variant"
done
```

实际原始独立头与 mixup 使用 CPU，时序头使用 MPS。复现逐轮数值时保持相同设备；MPS 与 CPU 不保证逐位一致。50 层衍生编码器的两次读出训练分别使用 `--variant independent --device cpu` 和 `--variant temporal --device mps`，缓存替换为 `private/pretrained-matcher/ompal-v2-sensevoice-finetuned-cache`；时序 CPU 包指定 `--encoder models/pinyin-pretrained/sensevoice-finetuned-v1 --backend torch`。50 层独立池化头只作缓存筛选，没有完整 CPU 质量结论。

```sh
tools/pinyin-pretrained/run.sh ensemble \
  --manifest private/pretrained-matcher/ompal-clips-v2/manifest.json \
  --cache private/pretrained-matcher/ompal-v2-bound-sensevoice \
  --member private/pretrained-matcher/ompal-v2-sensevoice-multihead \
  --member private/pretrained-matcher/sensevoice-independent-v1 \
  --member private/pretrained-matcher/sensevoice-mixup-v1 \
  --output private/pretrained-matcher/rebuild-sensevoice-ensemble
```

集成固定平均三个成员的完整类别概率，编码器只执行一次；不能混用不同清单、归一化或声学缓存。使用相同 `bundle` 命令导出，随后对每包执行前文 `evaluate --split calibration`、`stress evaluate`、`benchmark --exact-four-seconds` 和 `cold`。当前五包位于 `models/pinyin-pretrained/bundles/{sensevoice-independent-v1,sensevoice-temporal-v1,sensevoice50-temporal-v1,sensevoice-mixup-v1,sensevoice-ensemble-v1}`；四秒测速文件为 `private/pretrained-matcher/cpu-pressure-continuous.wav`，目标 `pm-ba1`。端到端评测逐条运行波形，不以缓存读出替代量化后的质量。

`run.sh readout-diagnostics --help` 提供仅校准缓存的分量混淆与时长诊断，明确不构成完整 CPU 评测。`run.sh iteration-report` 严格从本轮已完成的训练、全量校准、压力、暖机和冷启动文件重建[结果](../research/sensevoice-iteration-results.md)，核对模型、数据、压力波形摘要，缺失实验会失败。详细每轮曲线、区间及来源摘要在对应 JSON。494 份最终 WAV 未启用，结果仍为研发校准，未通过质量门槛，不替换应用 mock。

## MATCH-13：活动检测、边界、分量监督与原生序列

本轮保持 v1 应用匹配/识别接口和显式 mock 行为。底层研究返回原有状态；`uncertain` 仍表示证据不足，不转成匹配或明确读错。原始模型与失败轮次保留。活动检测改用10ms块RMS累计声音时长，测试周期过零、短脉冲、安静和削波边界；该修复不改变识别置信度门槛。

以下输出采用独立 `rebuild` 名称。已有正确摘要的数据可复用；训练、缓存、导出输出不能覆盖既有目录。重建会绑定当前代码SHA，因此不伪称与历史产物逐字节相同。GPU仅用于离线阶段，部署及评测仍是CPU两线程。

```sh
# 前20/35/50层使用同一波形；每层缓存身份绑定所选层与归一化方式。
./tools/pinyin-pretrained/run.sh layer-probe \
  --manifest private/pretrained-matcher/ompal-clips-v2/manifest.json \
  --model models/pinyin-pretrained/sensevoice \
  --output private/pretrained-matcher/sensevoice-layer-probes-rebuild --device mps

for matcher_depth in 20 35 50; do
  ./tools/pinyin-pretrained/run.sh train --name sensevoice --variant multihead \
    --manifest private/pretrained-matcher/ompal-clips-v2/manifest.json \
    --cache "private/pretrained-matcher/sensevoice-layer-probes-rebuild/$matcher_depth" \
    --output "private/pretrained-matcher/sensevoice-layer${matcher_depth}-rebuild" --device cpu
done

# 边界v3保留全部根ID、专家票、来源和旧边界；不按预测删难例。
./tools/pinyin-pretrained/run.sh alignment-v3 \
  --manifest private/pretrained-matcher/ompal-clips-v2/manifest.json \
  --output private/pretrained-matcher/ompal-clips-v3-rebuild
./tools/pinyin-pretrained/run.sh cache --name sensevoice \
  --manifest private/pretrained-matcher/ompal-clips-v3-rebuild/manifest.json \
  --model models/pinyin-pretrained/sensevoice \
  --output private/pretrained-matcher/ompal-v3-sensevoice-cache-rebuild --device mps
./tools/pinyin-pretrained/run.sh factorized \
  --manifest private/pretrained-matcher/ompal-clips-v3-rebuild/manifest.json \
  --cache private/pretrained-matcher/ompal-v3-sensevoice-cache-rebuild \
  --output private/pretrained-matcher/ompal-v3-factorized-rebuild
```

`factorized` 的身份分支只用专家正确分量；有效性分支保留已知错误期待分量和按根平衡的替代类负例。此轮将两分支乘积归一化为完整分布，不能将其解释成独立校准的绝对正确概率。原v2消融使用相同命令改回v2清单与对应缓存。20/35/50中间层探针只作缓存诊断，普通打包器明确拒绝它们；没有对应编码器导出时不能包装成原70层CPU模型。

```sh
# 为尾层实验先重建同一v2边界的原始编码器factorized初始化头。
./tools/pinyin-pretrained/run.sh cache --name sensevoice \
  --manifest private/pretrained-matcher/ompal-clips-v2/manifest.json \
  --model models/pinyin-pretrained/sensevoice \
  --output private/pretrained-matcher/ompal-v2-sensevoice-cache-rebuild --device mps
./tools/pinyin-pretrained/run.sh factorized \
  --manifest private/pretrained-matcher/ompal-clips-v2/manifest.json \
  --cache private/pretrained-matcher/ompal-v2-sensevoice-cache-rebuild \
  --output private/pretrained-matcher/sensevoice-factorized-rebuild

# 前64层常量缓存；最后6层与分量头实际梯度更新。
./tools/pinyin-pretrained/run.sh tail-finetune cache \
  --manifest private/pretrained-matcher/ompal-clips-v2/manifest.json \
  --model models/pinyin-pretrained/sensevoice \
  --output private/pretrained-matcher/sensevoice64-prefix-rebuild --device mps
./tools/pinyin-pretrained/run.sh tail-finetune train \
  --manifest private/pretrained-matcher/ompal-clips-v2/manifest.json \
  --model models/pinyin-pretrained/sensevoice \
  --cache private/pretrained-matcher/sensevoice64-prefix-rebuild \
  --initializer private/pretrained-matcher/sensevoice-factorized-rebuild \
  --output private/pretrained-matcher/sensevoice-tail-rebuild --device mps

# 显式下载固定AISHELL-3部分库存，逐文件SHA；仅外部训练补充。
./tools/pinyin-pretrained/run.sh aishell3 \
  --output private/pretrained-matcher/aishell3 --workers 8
./tools/pinyin-pretrained/run.sh native-sequence cache \
  --manifest private/pretrained-matcher/aishell3/manifest.json \
  --model models/pinyin-pretrained/sensevoice \
  --vocabulary models/pinyin-pretrained/hanziflow \
  --output private/pretrained-matcher/native-prefix-rebuild --device mps
./tools/pinyin-pretrained/run.sh native-sequence train \
  --native-cache private/pretrained-matcher/native-prefix-rebuild \
  --source-manifest private/pretrained-matcher/aishell3/manifest.json \
  --calibration-manifest private/pretrained-matcher/ompal-clips-v2/manifest.json \
  --calibration-cache private/pretrained-matcher/sensevoice64-prefix-rebuild \
  --model models/pinyin-pretrained/sensevoice \
  --vocabulary models/pinyin-pretrained/hanziflow \
  --output models/pinyin-pretrained/native-sequence-rebuild --device mps
```

固定配置 `content/pronunciation-aishell3-data.json` 包含修订、许可来源、说话人选择、音频与原拼音标注行的摘要；不是完整原语料。44.1kHz原音只在准备阶段明确重采样为16kHz，原音和派生音分别记SHA。作者提供的实际拼音作为完整CTC序列，HanziFlow只提供符号词表，未用其权重充当新头；不能表达的儿化等整句隔离，分母和理由保留。训练入口重新绑定原音、原人工标注、缓存标签及排除清单，防止标签缓存被改写。原生训练固定12轮；所选检查点取已有OMPAL校准损失，不读最终音频。

原生70层CPU包需显式完成导出、标准缓存校准、打包及逐条复评：

```sh
./tools/pinyin-pretrained/run.sh native-sequence-export \
  --model models/pinyin-pretrained/native-sequence-rebuild \
  --source models/pinyin-pretrained/sensevoice \
  --output models/pinyin-pretrained/native-sequence-int8-rebuild
./tools/pinyin-pretrained/run.sh cache --name sensevoice \
  --manifest private/pretrained-matcher/ompal-clips-v2/manifest.json \
  --model models/pinyin-pretrained/native-sequence-rebuild \
  --output private/pretrained-matcher/native-sequence-calibration-cache-rebuild --device mps
./tools/pinyin-pretrained/run.sh ctc calibrate --name sensevoice \
  --manifest private/pretrained-matcher/ompal-clips-v2/manifest.json \
  --cache private/pretrained-matcher/native-sequence-calibration-cache-rebuild \
  --model models/pinyin-pretrained/native-sequence-rebuild \
  --output private/pretrained-matcher/native-sequence-calibration-rebuild.json
./tools/pinyin-pretrained/run.sh ctc bundle \
  --calibration private/pretrained-matcher/native-sequence-calibration-rebuild.json \
  --model models/pinyin-pretrained/native-sequence-rebuild \
  --quantized-model models/pinyin-pretrained/native-sequence-int8-rebuild \
  --output models/pinyin-pretrained/bundles/native-sequence-int8-rebuild
./tools/pinyin-pretrained/run.sh evaluate \
  --manifest private/pretrained-matcher/ompal-clips-v2/manifest.json \
  --model models/pinyin-pretrained/bundles/native-sequence-int8-rebuild \
  --split calibration --output private/pretrained-matcher/native-sequence-cpu-rebuild.json
```

省略 `ctc bundle --quantized-model` 并使用另一输出目录建立FP32对照。FP32研究加载器需要原固定SenseVoice底座加可训练增量，报告大小必须加上底座；INT8包完整包含编码器、三个CTC头、词表、前端资源及许可证，不依赖原模型目录。ONNX数值对齐检查不是质量证明。导出后的完整四秒两线程测量沿用上文 `benchmark`、`cold` 命令和固定连续音频。

单/双包压力诊断须显式加 `stress prepare --allow-single-model-diagnostic`；该选项仅允许calibration，三包比较默认要求不变。对v3清单还必须提供 `--source-parent-manifest` 及原v2 SHA/管线证据，逐根核验来源和专家票一致。活动检测/边界改变会改变压力锚点，比较报告必须给出相同case和波形比例，不把不同压力波形写成完全相同输入。

混合域训练从原生序列所选检查点开始，保留全句序列回放，并引入OMPAL短片的已知正确/错误分量。每步两个域各一批、损失各0.5；OMPAL每分量按批内实际出现的正负组取均值，不等于整个数据集正负各占50%。实际曝光次数、有效组权重、所有8轮及初始化epoch0均保存，不把重复原生句当作新增独立样本。

```sh
# 重建产物的路径/源码SHA会改变，先显式绑定到新的独立配置；预算不变。
./tools/pinyin-pretrained/run.sh sequence-adapt-config \
  --initializer models/pinyin-pretrained/native-sequence-rebuild \
  --native-manifest private/pretrained-matcher/aishell3/manifest.json \
  --ompal-manifest private/pretrained-matcher/ompal-clips-v2/manifest.json \
  --output private/pretrained-matcher/sequence-adapt-rebuild-config.json
./tools/pinyin-pretrained/run.sh sequence-adapt \
  --config private/pretrained-matcher/sequence-adapt-rebuild-config.json \
  --initializer models/pinyin-pretrained/native-sequence-rebuild \
  --native-cache private/pretrained-matcher/native-prefix-rebuild \
  --native-manifest private/pretrained-matcher/aishell3/manifest.json \
  --ompal-cache private/pretrained-matcher/sensevoice64-prefix-rebuild \
  --ompal-manifest private/pretrained-matcher/ompal-clips-v2/manifest.json \
  --source models/pinyin-pretrained/sensevoice \
  --output models/pinyin-pretrained/native-sequence-adapt-rebuild --device mps
```

随后沿用 `native-sequence-export`、`cache`、`ctc calibrate/bundle`、`evaluate`，将原生模型路径替换成混合模型，并为每份输出另取新目录。新包中的 `adaptation-config.json` 和 `training-data.json` 分别绑定混合配置、初始化与两份训练源；导出资源不可覆盖图/身份文件。INT8运行前核验父资源及摘要，缺失或损坏返回不可用，不静默回退到网络或原目录。

固定混合编码器的两项读出消融复用上述标准缓存（包含pool5表示和68维音高），沿用原120轮预算。下列命令用于缓存诊断；本轮结果不足，普通打包器明确拒绝将native70读出错误配成原始70层或旧50层后端。

```sh
./tools/pinyin-pretrained/run.sh train --name sensevoice --variant multihead \
  --manifest private/pretrained-matcher/ompal-clips-v2/manifest.json \
  --cache private/pretrained-matcher/ompal-v2-native-sequence-adapt-v1-cache \
  --output private/pretrained-matcher/adapt-multihead-rebuild --device cpu
./tools/pinyin-pretrained/run.sh factorized \
  --manifest private/pretrained-matcher/ompal-clips-v2/manifest.json \
  --cache private/pretrained-matcher/ompal-v2-native-sequence-adapt-v1-cache \
  --output private/pretrained-matcher/adapt-factorized-rebuild
```

`ompal-v2-native-sequence-adapt-v1-cache` 是本轮历史混合编码器缓存；干净复现先按上文 `cache` 使用自己重建的混合模型生成新缓存，再将这两个命令一起指向该缓存。factorized严格绑定派生架构、父模型修订/权重/元数据和缓存身份，不移除身份来绕过校验。历史训练脚本在输入校验加固前后的SHA分别保留；当前命令复现数值流程，不承诺更换绝对路径、元数据或源码后仍生成逐字节相同的历史产物。

本轮完整记录由以下命令从实际本地产物生成，缺少任一完整评测或性能记录会报错；逐根录音/标签/结果保持本地忽略，Git结果仅含聚合统计、训练曲线和来源SHA：

```sh
./tools/pinyin-pretrained/run.sh reconstruction-report
./node_modules/.bin/prettier --write \
  docs/research/sensevoice-reconstruction-results.md \
  docs/research/sensevoice-reconstruction-results.json
```

报告生成依赖本轮保存的历史实验目录；训练的干净重建使用上文独立输出路径，不自动替换已记录证据。`run.sh test`包含活动检测、预训练管线和数据/资源身份边界；完整工程仍执行`npm run verify:all`与`npm run validate:release`，都不能替代声音质量验收。
