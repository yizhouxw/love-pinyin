# 拼音匹配底层工具

**状态（2026-10-28）：MATCH-17 非 Transformer 路线正在研究，尚未通过质量门禁。** 以下保留既有实验，当前产品不加载或调用研究模型；研究命令不属于默认安装、启动或发布流程。MATCH-17 的实际数据、命令和失败结果见 [传统匹配实验报告](../research/traditional-shop-matcher-results.md)。

关联 SPEC-018。此模块提供独立 Python/CLI 能力，不注册产品 HTTP 路由、不修改页面、录音入口、家庭数据库或掌握度。

## 隔离安装

在仓库根目录执行：

```sh
./tools/pinyin-matcher/run.sh setup
./tools/pinyin-matcher/run.sh prepare-generators
```

第一条只安装 `tools/pinyin-matcher/uv.lock` 中的固定工具依赖；第二条才显式安装生成器环境及下载固定 TTS 权重和源码。Qwen 使用项目原有锁定的 MLX-Audio 0.5.8，但安装在 private/matcher-qwen-env，不改变应用 .venv；CosyVoice 使用它自己的 pyproject.toml/uv.lock，避免与 MLX 的 Transformers 版本冲突。模型文件逐一核验 SHA-256，不使用随上游变动的默认修订。

`content/pronunciation-models.json` 记录模型、引擎、源码和 Matcha 子模块修订及全部模型文件摘要。`pinyin_matcher.prepare` 只在显式调用时联网，`PinyinMatcher` 和匹配命令从不安装或下载资源。

只部署推理时执行 `./tools/pinyin-matcher/run.sh setup-runtime`，它安装独立的 `tools/pinyin-matcher/.runtime`，只有 NumPy、SciPy、ONNX Runtime 及其间接依赖。下列生成/训练命令才需要完整 setup。命令在仓库根目录执行；从其他目录调用 Python 时须将仓库根目录加入 Python 模块搜索路径。

CosyVoice 加载器只构造官方 YAML 的推理节点，保留官方模型类和权重，不加载仅训练数据处理所需的 pyworld。可选 Metal 生成模式将 LLM/flow 放在 MPS；上游 HiFT 明确使用 float64，保持原 CPU 声码器路径。实时匹配模型始终只用 CPU，与这些生成器无关。

## 生成、检查和划分

```sh
private/matcher-qwen-env/bin/python -m pinyin_matcher.generate \
  --engine qwen --model models/matcher-qwen --personas 24 --repetitions 3

tools/pinyin-matcher/cosyvoice/.venv/bin/python -m pinyin_matcher.generate \
  --engine cosy --model models/matcher-cosy --personas 24 --repetitions 3 \
  --tts-device mps --threads 4

./tools/pinyin-matcher/run.sh merge \
  private/matcher-data/qwen/manifest.json \
  private/matcher-data/cosy/manifest.json \
  --output private/matcher-data/manifest.json

tools/pinyin-matcher/.venv/bin/python -m pinyin_matcher.audit \
  private/matcher-data/manifest.json
```

生成支持断点续跑，已登记的样本 ID 不重复生成。CosyVoice 需要先存在 Qwen 生成的虚构音色参考；参考音文本也在内容配置中。批量并行可加 `--shards 3 --shard 0`（另两进程分别用 1/2），各分片写独立 manifest；合并时改用 cosy-shard0、cosy-shard1、cosy-shard2 的 manifest。分片并行不改变音色家族的既定划分。

`pronunciation-targets.json` 是明确目标/发音形式目录，`pronunciation-training.json` 保存实验目标、TTS 文本、音色家族、划分、训练和增强参数。`pronunciation-rules.json` 集中保存音系转换规则。用锁定 pypinyin 0.55.0 的 `python -m pinyin_matcher.compile_targets` 可重新生成目标目录，`--check` 检查可复现性；训练将当时的目录复制进产物并绑定摘要，后续目录变化不会悄悄改变已有模型。

32 个训练目标和独立挑战使用显式汉字文本。其余候选只定义发音目录，`ttsText=null`；生成器不会用字典猜测汉字或静默跳过。全量扩展前需补齐明确文本，`--all-targets` 在缺少文本时拒绝启动。`pronunciation-challenges.json` 的换调和 u/ü 样本只能单列测试，不并入训练 manifest。

训练读取前核验音频摘要、目标引用及全部谱系。音色家族、同一参考、相同波形不能跨训练/校准/测试集合；先分组再增强。增强版本和拼接反例不计为新的独立根样本。TTS 文本是预期标签，manifest 明确标为 `tts-intended`，不是人类裁定或真实儿童数据。

质量检查隔离过长单音节、静音/过短、削波和缺少可靠有声段的样本；隔离原因留在 manifest，原始数据不被删除。该检查不能证明所有 TTS 音素/声调标签准确。

## 训练、导出和评估

```sh
./tools/pinyin-matcher/run.sh build \
  --manifest private/matcher-data/manifest.json \
  --output private/matcher-model --cache-dir private/matcher-feature-cache

./tools/pinyin-matcher/run.sh evaluate \
  --manifest private/matcher-data/manifest.json \
  --output private/matcher-model

tools/pinyin-matcher/.venv/bin/python -m pinyin_matcher.baseline \
  --manifest private/matcher-data/manifest.json --output private/matcher-model

tools/pinyin-matcher/.venv/bin/python -m pinyin_matcher.benchmark \
  --model private/matcher-model --output private/matcher-model/cpu-reference.json
```

完整 build 先训练/量化声学网络，再准备标准音声调锚、训练独立轮廓头、按校准冻结组合阈值，最后才打开测试集。准备标准音时只读取本机已显式安装的素材，不联网；按音节分组并排除所有 32 个目标的音节组。`train` 命令只用于共享声调头的离线对照，缺少独立声调头的实验产物不能通过 install。

默认用本机 MPS 训练声学网络，可显式 `--device cpu`；微型音高头用 CPU 训练。模型只看声音，不输入目标答案；目标在推理比较阶段参与。环境增强包括受控噪声、程序 RIR、增益和保调变速；额外音节拼接参与 CTC 训练。推理还检查自由音素序列是否比候选更可信、声母/韵母/声调独立分类结果是否一致，降低忽略多读内容或强行套入有限词表的风险。

训练/校准/测试相互独立；最多 160 轮，检查点、拒判阈值和 FP32/INT8 的选择只看校准集，测试集不参与选择。`--generators qwen` / `--generators cosy` 和 `--no-augmentation` 支持独立消融；比较时必须采用同样轮数、数据划分和目标范围，短程管线检查不算公平的模型比较。共享 `--cache-dir` 前先等待首个进程完成准备（ready.json），不能并发写相同特征文件。

产物包括 checkpoint.pt、训练/校准记录、FP32 和 INT8 ONNX、model.json、targets.json、逐目标/生成器/音色家族测试报告。model.json 绑定目录/模型/数据摘要、覆盖目标和阈值。量化损失过大时按校准结果保留 FP32，不绕过效果门槛。

CPU benchmark 使用核验过的 PinYinSound 留出录音作为参考，单列冷启动、两线程暖机耗时、实时率、进程增量/总峰值内存及匹配结果；另用重复真人语音测四秒长度性能与额外音节拒判。运行 benchmark 前设置 `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1`，ORT 固定两个线程。声调锚与这些留出记录同源，虽然整组目标未用于训练/校准，也不能声称独立说话人或儿童验证。`python -m pinyin_matcher.challenges --help` 提供冻结模型后的噪声、多读、非语音、独立换调测试。

安装最小本地模型包：

```sh
./tools/pinyin-matcher/run.sh install \
  --source private/matcher-model --destination models/pinyin-matcher
./tools/pinyin-matcher/run.sh info --model models/pinyin-matcher
```

安装复制选定的声学 ONNX、独立声调头 ONNX、冻结目标目录、元数据与来源说明；使用 SwiftF0 的 v3/v4/v5 包还复制 SwiftF0 ONNX 及对应 `SWIFT-F0-LICENSE`，共三个 ONNX。检查摘要后原子落盘；不复制 checkpoint、训练音频或缓存，不联网。相同版本可重复安装，已有不同模型时拒绝覆盖。

## v4 显式研究管线

2026-10-26 已显式安装 `models/pinyin-matcher-v4`，保留原 `models/pinyin-matcher`。v4 包与冻结候选的声学、声调和 Swift 权重字节相同，已校准，实际冻结测试已失败，保持 `qualityPassed=false`：VC近音3/52错放行，5个公开正确目标的20段声音仅10段匹配、5段明确误拒、5段拒判。完整摘要见[v4结果](../research/matcher-v4-results.md)。运行接口继续兼容该包，不能用安装完成表示效果门禁通过。

以下保留v4固定输入与历史命令，组装示例补上当前CLI要求的特征版本。**历史生成/质量锁绑定Git提交`4ea2bbc`的源码摘要，不能在v5源码上续跑、重算或重新生成旧留出。** 若要核验历史锁须使用该历史源码与其原CLI（当时组装尚无`--feature-version`参数）；当前源码拒绝旧锁属于预期保护。已有目录和失败报告不得覆盖，v5使用下一节的新目录及新锁。校准源v2已排除v4迁入训练的全部标准父源派生，旧校准v1仅作诊断。

```sh
tools/pinyin-matcher/.venv/bin/python -m pinyin_matcher.train_v2 \
  --manifest private/matcher-data/manifest.json \
  --anchors private/matcher-v4-acoustic/anchors/manifest.json \
  --derived private/matcher-v4-acoustic/manifest-vc-training-v4.json \
  --derived private/matcher-v4-acoustic/manifest-vc-calibration-v2.json \
  --foreign private/matcher-v2-foreign/qwen-train/manifest.json \
  --foreign private/matcher-v2-foreign-female/qwen-train/manifest.json \
  --foreign private/matcher-v2-foreign/cosy-full-train/manifest.json \
  --foreign private/matcher-v2-foreign/qwen-calibration/manifest.json \
  --configuration content/pronunciation-training-v4.json \
  --resume private/matcher-v3-finetuned/checkpoint.pt \
  --epochs 20 --device mps \
  --cache-dir private/matcher-v4-feature-cache --output private/matcher-v4-trained

tools/pinyin-matcher/.venv/bin/python -m pinyin_matcher.assemble_v3 \
  --acoustic private/matcher-v4-trained \
  --pitch private/matcher-pitch-swift-standard/pitch.onnx \
  --tracker models/matcher-pitch-swift \
  --feature-version relative-swift-f0-0.3.0-contour32-v1 \
  --precision int8 --output private/matcher-v4-final-candidate

tools/pinyin-matcher/.venv/bin/python -m pinyin_matcher.calibration_v3 \
  --model private/matcher-v4-final-candidate \
  --manifest private/matcher-v4-acoustic/manifest-vc-calibration-v2.json \
  --foreign private/matcher-v2-foreign/qwen-calibration/manifest.json \
  --non-speech private/matcher-v2-nonspeech-calibration/manifest.json \
  --output private/matcher-v4-final-calibration-protocol2
```

`train_v2` 读取同一清单内的划分，只有 `split=train` 参与梯度；校准行用于检查点选择及量化校准。外语训练384段、校准96段；外语仅对预先声明的目标对施加拒绝损失，不编造未知音素转写或声调。每个原始波形只推理一次，错误目标复用证据。协议2的稳定复算可用 `calibration_v3 --model … --records 原校准目录/records.json --output 新目录`，不重新推理、不修改旧报告。

将校准选定的三个阈值显式写入单独冻结副本 `private/matcher-v4-frozen/model.json`，标记 `calibrationPassed=true`，保留 `qualityPassed=false`；声学、声调、Swift与目标目录字节不变。生成锁会核对冻结副本与原候选、所用校准报告及谱系检查，而不只信任标记。本次绑定稳定报告后生成52个 VC 波形及96个英法波形的命令如下；只有锁建立以后才允许读取和生成这批留出音频。

```sh
tools/pinyin-matcher/.venv/bin/python -m pinyin_matcher.controlled_generation \
  --create-evaluation-lock \
  --evaluation-model private/matcher-v4-frozen \
  --calibration-model private/matcher-v4-final-candidate \
  --calibration-report private/matcher-v4-final-calibration-v2-stable/calibration.json \
  --configuration content/pronunciation-contrast-training.json \
  --output private/matcher-v4-frozen-new-families \
  --evaluation-lock private/matcher-v4-generation.lock.json

private/matcher-qwen-env/bin/python -m pinyin_matcher.controlled_generation \
  --engine qwen --model models/matcher-qwen --references-only --modes character \
  --source-pool locked-evaluation --suffix=-locked-evaluation --threads 4 \
  --configuration private/matcher-v4-generation.lock.configuration.frozen.json \
  --output private/matcher-v4-frozen-new-families \
  --evaluation-lock private/matcher-v4-generation.lock.json

tools/pinyin-matcher/cosyvoice/.venv/bin/python -m pinyin_matcher.controlled_generation \
  --engine cosy --model models/matcher-cosy --modes vc \
  --source-pool locked-evaluation --suffix=-locked-evaluation --threads 4 \
  --tts-device mps \
  --configuration private/matcher-v4-generation.lock.configuration.frozen.json \
  --output private/matcher-v4-frozen-new-families \
  --evaluation-lock private/matcher-v4-generation.lock.json

tools/pinyin-matcher/.venv/bin/python -m pinyin_matcher.foreign_evaluation create \
  --evaluation-lock private/matcher-v4-generation.lock.json \
  --output private/matcher-v4-foreign-evaluation \
  --plan private/matcher-v4-foreign-evaluation.plan.json

private/matcher-qwen-env/bin/python -m pinyin_matcher.foreign_evaluation generate \
  --plan private/matcher-v4-foreign-evaluation.plan.json --model models/matcher-qwen
```

VC 是13个已知标准音父源在4个新合成家族上的派生，不能宣称52个独立真人来源。外语叶计划冻结不同文字、词根、家族和具体目标差异；只有语言名不同不构成负例。所有计划波形必须保留，缺失或不完整输入阻止完整验收；不得依据匹配结果删样本。

下列历史查询构造步骤不选模型、不执行匹配；VC和确定性双音节拼接查询全部公开目标，外语只查询预先写明的差异目标，并显式加入原音高锚清单排除谱系。实际输出为 `private/matcher-v4-quality-cases/manifest.json`、`private/matcher-v4-quality.plan.json`、`private/matcher-v4-quality-results.json`，已完成且失败；此后该批仅供诊断，不能重新称为未见测试。

```sh
tools/pinyin-matcher/.venv/bin/python -m pinyin_matcher.evaluation_cases \
  --evaluation-lock private/matcher-v4-generation.lock.json \
  --vc-manifest private/matcher-v4-frozen-new-families/cosy-locked-evaluation/manifest.json \
  --foreign-plan private/matcher-v4-foreign-evaluation.plan.json \
  --foreign-manifest private/matcher-v4-foreign-evaluation/manifest.json \
  --exclude-manifest private/matcher-standard-anchors/manifest.json \
  --output private/matcher-v4-quality-cases

tools/pinyin-matcher/.venv/bin/python -m pinyin_matcher.quality freeze \
  --model private/matcher-v4-frozen \
  --manifest private/matcher-v4-quality-cases/manifest.json \
  --calibration-manifest private/matcher-v4-acoustic/manifest-vc-calibration-v2.json \
  --calibration-manifest private/matcher-v2-foreign/qwen-calibration/manifest.json \
  --calibration-manifest private/matcher-v2-nonspeech-calibration/manifest.json \
  --output private/matcher-v4-quality.plan.json

tools/pinyin-matcher/.venv/bin/python -m pinyin_matcher.quality evaluate \
  --plan private/matcher-v4-quality.plan.json \
  --output private/matcher-v4-quality-results.json

./tools/pinyin-matcher/run.sh install \
  --source private/matcher-v4-frozen --destination models/pinyin-matcher-v4
./tools/pinyin-matcher/run.sh info --model models/pinyin-matcher-v4
```

## v5 当前管线

v5声学训练使用438段直接标准原音：346段训练、92段校准；训练VC为1,384段（346个父源×4个训练家族）。其中新增40段VC来自8个已降为诊断的原blind非公开父源及`daily-ni1/ri1`两个直接许可标准源，使用00/06/08/10训练家族。两个daily源已核对为原始标准资产，非PSOLA或基于旧blind的派生；本次52段已消耗测试VC及32～35参考不参与训练。VC校准仍为原228段，包含96个公开正确目标波形；外语仍为384段训练、96段校准。

`content/pronunciation-training-extensions-v5.json`只为明确的`pm-ni1/pm-ri1`训练标签复用既有音素，把局部模型目录从649扩为651条并复制进模型包；全局目标目录、CTC词汇和声母/韵母类别不变，公开能力仍为32目标。模型的`run-inputs.json`绑定这些输入及扩展配置摘要，不能凭训练目录扩充宣称新公开能力。

```sh
tools/pinyin-matcher/.venv/bin/python -m pinyin_matcher.train_v2 \
  --manifest private/matcher-data/manifest.json \
  --anchors private/matcher-v5-acoustic/anchors/manifest.json \
  --derived private/matcher-v5-acoustic/manifest-vc-training-v5.json \
  --derived private/matcher-v4-acoustic/manifest-vc-calibration-v2.json \
  --foreign private/matcher-v2-foreign/qwen-train/manifest.json \
  --foreign private/matcher-v2-foreign-female/qwen-train/manifest.json \
  --foreign private/matcher-v2-foreign/cosy-full-train/manifest.json \
  --foreign private/matcher-v2-foreign/qwen-calibration/manifest.json \
  --configuration content/pronunciation-training-v5.json \
  --resume private/matcher-v4-trained/checkpoint.pt \
  --epochs 24 --device mps \
  --cache-dir private/matcher-v5-feature-cache --output private/matcher-v5-trained

tools/pinyin-matcher/.venv/bin/python -m pinyin_matcher.assemble_v3 \
  --acoustic private/matcher-v5-trained \
  --pitch private/matcher-pitch-swift-standard/pitch.onnx \
  --tracker models/matcher-pitch-swift \
  --feature-version relative-swift-f0-0.3.0-contour32-v1 \
  --precision int8 --output private/matcher-v5-candidate

tools/pinyin-matcher/.venv/bin/python -m pinyin_matcher.calibration_v3 \
  --model private/matcher-v5-candidate \
  --manifest private/matcher-v4-acoustic/manifest-vc-calibration-v2.json \
  --foreign private/matcher-v2-foreign/qwen-calibration/manifest.json \
  --non-speech private/matcher-v2-nonspeech-calibration/manifest.json \
  --fixed-thresholds content/pronunciation-thresholds-v5.json \
  --output private/matcher-v5-calibration
```

Swift组件版v2与原轮廓v1使用不同特征版本；旧v1运行路径保持兼容。v2在原标准校准上的NLL略差，本轮未选用，v5继续固定v1声调头。组装必须显式传特征版本，且同目录`pitch.json`中的头SHA、`featureVersion`、`inputShape`须与ONNX及声明一致，不能将v1头改名冒充v2。

v5仅核验 `content/pronunciation-thresholds-v5.json` 的单个设置0.5/0.025/0.45，报告应为`thresholdSelectionMode=predeclared-single-setting`、`combinations=1`；不可行时保留`thresholds=null`及失败，不能自动搜索较宽设置。24轮训练已完成，INT8与FP32均在原固定阈值下通过校准；精度选择和冻结只使用校准结果，不能读取新测试选择。以下是校准通过后才能执行的新留出流程，不预填v5测试结果。所有输出必须是新目录，失败或中断尝试不能重抽直到成功。

先在单独冻结副本中显式采用已通过的固定阈值，保持模型权重/目录字节不变及`qualityPassed=false`，再建立新锁。保留的5个公开标准父源仅在36～39新家族生成20段VC；它们是已知父源，不是20个独立来源。外语使用新词汇排除旧训练、校准及已消耗测试词，另立叶计划。

```sh
tools/pinyin-matcher/.venv/bin/python -m pinyin_matcher.controlled_generation \
  --create-evaluation-lock \
  --evaluation-model private/matcher-v5-frozen \
  --calibration-model private/matcher-v5-candidate \
  --calibration-report private/matcher-v5-calibration/calibration.json \
  --configuration content/pronunciation-contrast-training-v5.json \
  --output private/matcher-v5-frozen-new-families \
  --evaluation-lock private/matcher-v5-generation.lock.json

private/matcher-qwen-env/bin/python -m pinyin_matcher.controlled_generation \
  --engine qwen --model models/matcher-qwen --references-only --modes character \
  --source-pool locked-evaluation --suffix=-locked-evaluation --threads 4 \
  --configuration private/matcher-v5-generation.lock.configuration.frozen.json \
  --output private/matcher-v5-frozen-new-families \
  --evaluation-lock private/matcher-v5-generation.lock.json

tools/pinyin-matcher/cosyvoice/.venv/bin/python -m pinyin_matcher.controlled_generation \
  --engine cosy --model models/matcher-cosy --modes vc \
  --source-pool locked-evaluation --suffix=-locked-evaluation --threads 4 \
  --tts-device mps \
  --configuration private/matcher-v5-generation.lock.configuration.frozen.json \
  --output private/matcher-v5-frozen-new-families \
  --evaluation-lock private/matcher-v5-generation.lock.json

tools/pinyin-matcher/.venv/bin/python -m pinyin_matcher.foreign_evaluation create \
  --evaluation-lock private/matcher-v5-generation.lock.json \
  --configuration content/pronunciation-foreign-evaluation-v5.json \
  --output private/matcher-v5-foreign-evaluation \
  --plan private/matcher-v5-foreign-evaluation.plan.json

private/matcher-qwen-env/bin/python -m pinyin_matcher.foreign_evaluation generate \
  --plan private/matcher-v5-foreign-evaluation.plan.json --model models/matcher-qwen
```

新增纯TTS叶计划单列`pure-tts-new-family-qwen/cosy`两个来源。它只根据公开目录的明确汉字文本生成，不用标准录音提供读音；32目标×4家族×2引擎共256个预定波形，每个查询全部32个目标，共8,192次查询，其中ma四声有96个错误声调查询。全部为弱意图标签，同一目标文字及家族共享不能称为独立真人来源。下列为生成和合并命令，不表示已生成或已通过；应用仍不集成。

先建立主生成锁，再在首段纯TTS生成前创建这个叶计划。Qwen/Cosy分别调用，顺序运行；两者共享主锁的一次性参考与家族描述。生成器每个unit先保存`attempt-started`，失败或中断不重抽；机械质量失败的WAV仍保留正负查询。缺失音频保留全部占位并阻止完整合并，不能通过移除难例完成验收。

```sh
tools/pinyin-matcher/.venv/bin/python -m pinyin_matcher.tts_evaluation create \
  --evaluation-lock private/matcher-v5-generation.lock.json \
  --output private/matcher-v5-pure-tts-evaluation \
  --plan private/matcher-v5-pure-tts-evaluation.plan.json

private/matcher-qwen-env/bin/python -m pinyin_matcher.tts_evaluation generate \
  --plan private/matcher-v5-pure-tts-evaluation.plan.json \
  --engine qwen --model models/matcher-qwen

tools/pinyin-matcher/cosyvoice/.venv/bin/python -m pinyin_matcher.tts_evaluation generate \
  --plan private/matcher-v5-pure-tts-evaluation.plan.json \
  --engine cosy --model models/matcher-cosy --source private/matcher-cosy-source

tools/pinyin-matcher/.venv/bin/python -m pinyin_matcher.evaluation_cases \
  --evaluation-lock private/matcher-v5-generation.lock.json \
  --vc-manifest private/matcher-v5-frozen-new-families/cosy-locked-evaluation/manifest.json \
  --foreign-plan private/matcher-v5-foreign-evaluation.plan.json \
  --foreign-manifest private/matcher-v5-foreign-evaluation/manifest.json \
  --exclude-manifest private/matcher-standard-anchors/manifest.json \
  --output private/matcher-v5-core-quality-cases

tools/pinyin-matcher/.venv/bin/python -m pinyin_matcher.tts_evaluation merge \
  --tts-plan private/matcher-v5-pure-tts-evaluation.plan.json \
  --manifest private/matcher-v5-core-quality-cases/manifest.json \
  --manifest private/matcher-v5-pure-tts-evaluation/quality-manifest.json \
  --output private/matcher-v5-quality-cases

tools/pinyin-matcher/.venv/bin/python -m pinyin_matcher.quality freeze \
  --model private/matcher-v5-frozen \
  --manifest private/matcher-v5-quality-cases/manifest.json \
  --calibration-manifest private/matcher-v4-acoustic/manifest-vc-calibration-v2.json \
  --calibration-manifest private/matcher-v2-foreign/qwen-calibration/manifest.json \
  --calibration-manifest private/matcher-v2-nonspeech-calibration/manifest.json \
  --output private/matcher-v5-quality.plan.json

tools/pinyin-matcher/.venv/bin/python -m pinyin_matcher.quality evaluate \
  --plan private/matcher-v5-quality.plan.json \
  --output private/matcher-v5-quality-results.json
```

合并器逐字段核验完整规范TTS清单，删查询、增加容易查询或弱化来源门禁均拒绝；保留VC、外语及纯TTS各自来源/生成器/类别分组，再统一冻结最终音频摘要和CPU评估计划。

v5实际结果为失败，见[v5结果](../research/matcher-v5-results.md)。一段外语生成缺少WAV，完整合并被阻止。新增`evaluation_subsets`仅报告原计划中完整的VC/固定双音节来源，以及保留全部96个计划单位的外语诊断；不能将子集改称整批通过。外语诊断对95个实际WAV推理，缺失单位返回`unavailable`，分别报告观测波形和完整计划分母。它不补造音频、不重抽生成、不修改模型/阈值，已有输出不得覆盖。

```sh
tools/pinyin-matcher/.venv/bin/python -m pinyin_matcher.evaluation_subsets vc \
  --evaluation-lock private/matcher-v5-generation.lock.json \
  --vc-manifest private/matcher-v5-frozen-new-families/cosy-locked-evaluation/manifest.json \
  --exclude-manifest private/matcher-standard-anchors/manifest.json \
  --output private/matcher-v5-vc-quality-cases

tools/pinyin-matcher/.venv/bin/python -m pinyin_matcher.evaluation_subsets foreign-freeze \
  --foreign-plan private/matcher-v5-foreign-evaluation.plan.json \
  --manifest private/matcher-v5-foreign-evaluation/manifest.json \
  --output private/matcher-v5-foreign-diagnostic.plan.json

tools/pinyin-matcher/.venv/bin/python -m pinyin_matcher.evaluation_subsets foreign-run \
  --plan private/matcher-v5-foreign-diagnostic.plan.json \
  --output private/matcher-v5-foreign-diagnostic-results.json
```

VC子集仍须用`quality freeze/evaluate`显式冻结后评估；`--calibration-manifest`应传其清单中的全部`exclusionManifests`，不能只排除当前公开校准而漏掉训练、声调或旧清单谱系。10项子集回归测试覆盖失败/缺失保留、拒绝替换音频、摘要/单位篡改、父源泄漏及完整分母。

## Python 接口和 CLI

2026-10-26 的 v3 实验候选使用逐帧归一化/填充屏蔽声学编码、全目录音素头和独立 SwiftF0 波形前端。基础声学训练入口为 `python -m pinyin_matcher.train_v2`，必须显式传入 `--manifest`、`--anchors`、`--cache-dir`、`--output`。`--resume` 使用内容配置中的微调学习率；可重复 `--foreign` 添加有明确目标差异的弱标签反例，可重复 `--derived` 添加经过父源/划分核验的标准音 VC 派生。外语反例只对明确目标对施加拒绝损失，不编造它们的音素转写，也不参与 CTC 或声调标签损失。

Swift 的固定本地安装、许可、训练/校准与 CPU 证据见[音高前端记录](../research/matcher-pitch-swift.md)。`python -m pinyin_matcher.assemble_v3 --help` 将显式声学/声调/Swift 本地文件组装为新的私有校准候选；不会覆盖现有部署包。候选默认 `qualityPassed=false`，不能用组装成功表示通过门禁。原运行接口继续兼容旧模型，v3 独立使用原始 WAV 提取音高，不再由旧 YIN 帧数预先拒绝。缺失或损坏 Swift 权重时失败，不退回旧音高路径。

`python -m pinyin_matcher.quality freeze --help` 冻结模型、运行代码、协议、阈值、校准来源与留出音频摘要；`quality evaluate` 逐来源/生成器/反例类别执行固定 5%/10%/20% 门禁，并保留缺失结果。主指标按实际波形跨所有错误目标取最难近邻事件，父源跨声音的联合压力另列，不以配对或增强虚增独立来源。[反例覆盖说明](../research/matcher-negative-coverage.md)列出跨语言/方言样本量的解释边界。机械非语音输入使用 `python -m pinyin_matcher.calibration_inputs --output 新目录` 复现，只用于不可误判孩子的工程契约，不作为发音准确率证据。

```python
from pathlib import Path
from pinyin_matcher.inference import PinyinMatcher

matcher = PinyinMatcher(Path("models/pinyin-matcher-v4"), threads=2)
result = matcher.match("pm-ma1", wav_bytes)
```

```sh
./tools/pinyin-matcher/run.sh match --model models/pinyin-matcher-v4 \
  --target pm-ma1 --wav /absolute/path/reading.wav
```

输入只接受有界的 16kHz、单声道 PCM16 WAV。合法时长 0.15～8 秒；Python 接口接字节，CLI 文件路径是操作者显式提供的本地录音，不是标准答案路径。返回 `matched/retry/uncertain/unavailable`，不返回儿童分数。`experimental` 和 `toneAssessed` 明确区分实验预测与经过真实域验证的声调能力；模型未覆盖目标返回 TARGET_NOT_TRAINED，不偷用 Whisper 判定。

没有模型、摘要不符、无效目标、忙和推理失败返回 unavailable；静音、削波和证据不足返回 uncertain。接口串行使用模型，不能无限排队。`match(..., cancel=threading.Event())` 支持取消，取消或超过两秒的结果被丢弃；ORT 运行配置也设置终止看门狗。没有写录音或转写日志的路径；调用者负责与实际浏览器录音衔接，这属于后续应用集成。

## 验证与依赖

```sh
./tools/pinyin-matcher/run.sh test
tools/pinyin-matcher/.venv/bin/ruff check pinyin_matcher tests/matcher
tools/pinyin-matcher/.venv/bin/ruff format --check pinyin_matcher tests/matcher
MATCHER_MODEL=models/pinyin-matcher \
MATCHER_MANIFEST=private/matcher-data/manifest.json \
./tools/pinyin-matcher/run.sh test
```

2026-10-26 已实际运行的当时完整 matcher 测试为133项通过；其后新增的查询构造 helper 测试另计，不能用这个快照代替提交时重新验证。实际产物集成测试在未指定环境变量时跳过，不冒充真实模型已验收。新增依赖仅位于两个工具子项目，不加入应用启动。固定版本和官方下载摘要在各自 uv.lock；直接依赖来源/许可及实装说明见旁边的依赖清单。训练 WAV、克隆参考、特征缓存及所有权重留在 private/ 或 models/，不提交 Git。实际训练效果和 CPU 测量见[本次验收记录](../research/target-pronunciation-matcher-results.md)；没有真实儿童验证时不宣称儿童准确率成立。
