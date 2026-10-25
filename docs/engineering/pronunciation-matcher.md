# 拼音匹配底层工具

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

安装复制选定的声学/音高两个 ONNX、冻结目录、元数据与来源说明，检查摘要后原子落盘；不复制 checkpoint、训练音频或缓存，不联网。相同版本可重复安装，已有不同模型时拒绝覆盖。

## Python 接口和 CLI

```python
from pathlib import Path
from pinyin_matcher.inference import PinyinMatcher

matcher = PinyinMatcher(Path("models/pinyin-matcher"), threads=2)
result = matcher.match("pm-ma1", wav_bytes)
```

```sh
./tools/pinyin-matcher/run.sh match --model models/pinyin-matcher \
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

前十三项测试不依赖权重；三项实际产物集成测试在未指定环境变量时跳过，不冒充真实模型已验收。新增依赖仅位于两个工具子项目，不加入应用启动。固定版本和官方下载摘要在各自 uv.lock；直接依赖来源/许可及实装说明见旁边的依赖清单。训练 WAV、克隆参考、特征缓存及所有权重留在 private/ 或 models/，不提交 Git。实际训练效果和 CPU 测量见[本次验收记录](../research/target-pronunciation-matcher-results.md)；没有真实儿童验证时不宣称儿童准确率成立。
