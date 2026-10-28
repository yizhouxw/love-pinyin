# MATCH-17：单目标传统声学匹配研究（2026-10-28）

**结论：四种方案都未通过质量门槛，暂不能用于孩子判错或上线。** 沿此方向继续研究可优先检查梯度提升树的声母、韵母、声调特征及真实说话人适配；当前没有证据证明它优于保留的旧基线，更不能通过单纯调整阈值宣布达标。无真实儿童验证。

## 协议和数据

验收编号 MATCH-17；配置见 `content/pronunciation-traditional-shop.json`，实验范围仅为 32 个整音节（不是完整小卖部声母、韵母和所有音节）。不接入应用，保留既有接口和基线。声学特征为 13 维 MFCC、相对音高、变化与有声状态，时间规整到 20 帧；目标匹配分别使用多模板 DTW、目标与近邻的相对 DTW、线性 SVM 和梯度提升树（80 棵深度 2）。离线训练使用 sklearn，CPU 推理使用导出的数值参数、NumPy 和 SciPy，无 Transformer、外部识别服务或自动下载。四者有完全相同的源数据、模板、单目标输入和数据划分。TTS 模型自身可能含 Transformer：本限制针对匹配器，不是生成器。

复用先前实际生成的 Qwen 和 CosyVoice 音频：训练 3,374 根（20 个音色家族），校准 330 根（2 家族），先前已观察过的测试 370 根（2 家族）；两种 TTS 的性别/年龄均是生成意图，不能视为真实人口统计或儿童录音。TTS 文本只是弱标签，未逐条听辨实际发音。本轮没有额外合成。每个目标 6 条模板，其中共 96 条 Qwen、67 条 CosyVoice、29 条经 SHA 校验的 PinYinSound 标准音；标准音存在于训练模板，不能作为独立测试。训练根音频排除与模板同音色家族的比较。利用同一音频与仅相差一个声母、韵母或声调的其他目标比较，产生 7,661 个负对和 3,374 个正对（11,035 对）；这不是 7,661 条独立错音录音，亦不能保证 TTS 的预期标签正确。四个目标在本试验目标集合中没有一分量近邻，不能计算其近邻覆盖。

数据加载检查训练、校准、测试的音色家族、克隆参考来源、参考摘要及波形隔离和音频 SHA。真人诊断使用先前 OMPAL 成人校准区的 8 位说话人：159 条专家一致正确，8 条专家一致错误，另有 51 条专家不一致/未知的覆盖音节未纳入正确或错误分母。专家判断针对原词，自动切片边界未逐条人工复核。OMPAL 原始资料为 CC BY 4.0，具体来源和数据局限见 [既有记录](target-pronunciation-pretrained-data-audit.md)。不使用 LATIC。旧 TTS 测试和真人校准均已用于问题发现，仅作诊断，不是新的冻结验收集。所有录音和产物均留在忽略目录。

近邻放行以**根音频**为单位：对该根所有单分量近邻目标，任一被接受即计一次；包括拒判，不把它从分母去掉。下表正音包括所有正标签根，拒判也留在分母；信号质量失败亦保守计为拒判。这些不是清晰正确音的正式验收指标。原门槛保持近邻错误放行 ≤5%、正确音明确误拒 ≤10%、清晰正确音拒判 ≤20%；本次没有满足门槛的独立冻结验收结果。校准只使用 TTS 校准区，阈值在预先固定的网格选取，固定明确拒绝分界 0.05；不能将输出数值当作校准概率。

## 同一真人诊断集比较

| 方法            | 正确接受 / 159 | 明确误拒 / 159 | 拒判 / 159 | 近邻错误放行 / 139 | 专家错误被接受 / 8 |
| --------------- | -------------: | -------------: | ---------: | -----------------: | -----------------: |
| 原保留 TCN 基线 |             22 |              7 |        130 |                  6 |                  0 |
| DTW             |            133 |              0 |         26 |                124 |                  5 |
| 相对 DTW        |             12 |              0 |        147 |                 22 |                  1 |
| SVM             |             12 |              0 |        147 |                 22 |                  2 |
| 梯度提升树      |             11 |              0 |        148 |                 12 |                  1 |

20 条正确根无目标集合内近邻，未计入近邻分母；8 条真实错误数量过小，无法估计稳定错误率。真人中 13 条触发新模型输入/质量保护，基线保护机制不同。声学错误类别尚不足以覆盖每个声母、韵母和四声。基线也未经独立验收，本表只能说明在相同已暴露诊断根上的对照。

TTS 校准（330 正音、286 有近邻）按同样口径：DTW 接受 326、拒判 4、近邻放行 283；相对 DTW 接受 42、拒判 288、近邻放行 23；SVM 接受 3、拒判 327、近邻放行 3；树接受 41、拒判 289、近邻放行 16；均无明确误拒。44 根没有目标集合内近邻。旧 TTS 测试（370 正音、326 有近邻）：DTW 接受 369、拒判 1、近邻放行 325；相对 DTW 76、294、31；SVM 10、360、3；树 66、304、25；均无明确误拒，44 根没有近邻。训练时阈值选择未运行完整输入保护，因此模型元数据中校准计数与以上完整推理评测略有差别。

已观察过的异常输入诊断集原有 312 个案例，只有 35 个案例涉及本试验支持目标，不能代表完整覆盖；其中去重后 15 个双音节错误，DTW 放行 7、相对 DTW 放行 3，SVM 和树均拒判 15；2 个清晰对照 DTW 均接受，其余方法均拒判。噪声 4、过长 4、过短 2、静音漏读 1、采样率错误 2、截断 2、非 WAV 1 均未被任一方法接受；各类别数量太少，不构成验收。

## CPU、产物与可复现命令

Mac Studio、CPU 两线程上，四秒 WAV，30 次暖机和每方法 5 次新进程，包含 WAV 解码、特征、模型与目标比较，每次加载本地包；线程池探测为空，所用 NumPy 构建未报告可识别 BLAS 池，实际工作限制两线程而非声称占满两线程。DTW / 相对 DTW / SVM / 树暖机 p95 分别 19.7 / 21.6 / 21.0 / 21.1 ms，实时率分别 0.0049 / 0.0054 / 0.0053 / 0.0053；新进程冷启动 p95 分别 593 / 602 / 609 / 600 ms（仅 5 次，操作系统文件缓存未清空），同一进程峰值 RSS 153.4 MiB，包 331,073 字节。满足暖机 ≤500 ms 和实时率 ≤0.1，但性能通过不代表有效。模型 `model.json` SHA-256 `f16c5d8887582de0564819fc5af546c6aba4458f48e08a564af0cf8b9ed8b05a`，模板 SHA-256 `6dd9e9647f3c732083400137e8d322e0bab9578dcbf0882643790d0d3bf78271`，训练代码 SHA-256 `25d6be9afc70dd79e4863905d7ad3bab2daf5497f3710f27541834bfad55d781`，TTS manifest SHA-256 `d4163d8e3b090ec1219b5bbe2e9c3b3f9dac0499150820d3935c7311e0986e7c`。源、模型版本和许可按既有 [依赖和素材记录](../engineering/pronunciation-matcher.md)，具体工具轮子 SHA 固定在 `tools/pinyin-matcher/uv.lock`。

以下命令需要先按上述工程文档显式安装固定版本和准备 TTS、标准音、历史特征缓存与 OMPAL 校准切片；缓存的 ready.json 只用于核验历史数据身份，训练特征重新从核验的 WAV 提取。数据按各自许可使用；资料不齐则不能凭空复现。输出路径必须不存在。现有可运行包位于忽略目录 `models/pinyin-traditional/shop-v3`，与 `private/matcher-traditional-shop-v3` 内容一致。

```sh
./tools/pinyin-matcher/run.sh setup
./tools/pinyin-matcher/run.sh traditional train --manifest private/matcher-data/manifest.json --cache private/matcher-feature-cache --output private/matcher-traditional-shop-reproduced
./tools/pinyin-matcher/run.sh traditional match --package models/pinyin-traditional/shop-v3 --method boost --target pm-ma1 --wav path/to/16khz-mono.wav
./tools/pinyin-matcher/run.sh traditional-evaluate --package models/pinyin-traditional/shop-v3 --tts-manifest private/matcher-data/manifest.json --real-manifest private/pretrained-matcher/ompal-clips-v2/manifest.json --output private/traditional-evaluation-new.json
./tools/pinyin-matcher/run.sh traditional-baseline --package models/pinyin-traditional/shop-v3 --baseline models/pinyin-matcher --tts-manifest private/matcher-data/manifest.json --real-manifest private/pretrained-matcher/ompal-clips-v2/manifest.json --output private/traditional-baseline-new.json
./tools/pinyin-matcher/run.sh traditional-stress --package models/pinyin-traditional/shop-v3 --manifest private/pretrained-matcher/stress-match13-v2/manifest.json --output private/traditional-stress-new.json
./tools/pinyin-matcher/run.sh traditional-benchmark --package models/pinyin-traditional/shop-v3 --wav private/pretrained-matcher/cpu-pressure-continuous.wav --target pm-ma1 --output private/traditional-cpu-new.json
```

实际匹配返回 `matched`、`retry`、`uncertain` 或 `unavailable`；无效信号不判错，不输出伪分数。实验不对外宣称单独完成声调评测。后续需要补齐真实错音及逐条核验的音素边界、扩展小卖部声母韵母/全部目标、按人和音色/参考隔离固定独立验收集、错误类型迭代并通过原始门槛，再独立获取经授权的真实儿童录音做验证。

新增直接依赖与实装：离线训练使用 [scikit-learn 1.9.1](https://pypi.org/project/scikit-learn/1.9.1/)（BSD-3-Clause），离线标准音解码使用 [soundfile 0.14.0](https://pypi.org/project/soundfile/0.14.0/)（BSD-3-Clause；其捆绑的 libsndfile 为 LGPL-2.1-or-later），运行时线程限制使用 [threadpoolctl 3.7.0](https://pypi.org/project/threadpoolctl/3.7.0/)（BSD-3-Clause）；均已在工具 Python 3.12 环境安装，固定分发文件与 SHA 见锁文件。
