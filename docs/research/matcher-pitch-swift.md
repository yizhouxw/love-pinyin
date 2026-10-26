# 拼音匹配器：SwiftF0 音高前端实验

日期：2026-10-26。对应 SPEC-018 / ADR-0034。这里只记录音高前端与声调分支；不表示完整匹配器通过验收，也不表示真实儿童发音准确率。

## 定位与结论

原前端的 40ms YIN、整数周期与严格有声阈值会漏掉下降音节的低音尾部。直接信任的标准 `mà` 在旧提取结果中只有约 271→340→320Hz，看起来先升后平；SwiftF0 能提取到约 275→341→157Hz 的完整轨迹。标准 `mǎ` 中间的低谷也能保留，而 Praat 原始自相关在部分中段出现约 480Hz 的倍频候选。这是前端算法差异，不能据旧轨迹推断标准音错误。

独立相对音高头只读取 32 点的相对 F0、变化量、置信度和有声状态；不读取目标、音节、Mel 或绝对 F0。标准音 325 个训练记录、92 个校准记录沿用原音节组划分，全部 32 个试验目标对应音节组仍排除。训练检查点只按校准损失选择。

| 候选                            | 标准音校准 | 原合成校准 | 原 370 段诊断 |
| ------------------------------- | ---------: | ---------: | ------------: |
| 原发布 YIN 声调头               |      81/92 |    110/330 |       202/370 |
| SwiftF0，仅标准音训练           |      91/92 |    227/330 |       298/370 |
| SwiftF0，标准音与原合成均衡训练 |      91/92 |    211/330 |       325/370 |

原合成集合主要是一声，最后一列已经用于问题诊断，不能当作新的盲测，也没有用于选择这些候选的训练检查点。均衡训练在校准中按来源和四声分配相同损失权重，其四声宏平均优于只用标准音的候选，整体正确数会因一声占比而出现不同排序。最终候选仍需用新增、冻结的校准集选择；不能按诊断列挑模型后宣称质量达标。

Swift 标准音候选校准中，一声 24/25、二声 22/22、三声 24/24、四声 21/21。它们是同一标准音来源的留出音节组，不是独立真人说话人或儿童验证。合成三声仍有明显域差，不能用标准音校准近 99% 替代合成或真实录音结果。

## 新增校准与冻结选择

另用 68 个未进入上述训练锚的标准音父记录，经固定 CosyVoice 转成四个全新合成音色家族 `voice-28`～`voice-31`，共 272 个不同波形、23 个音素组合、24 个原试验目标。源记录、所有转换子代和参考音谱系保持可追溯。它们是 68 个父记录的派生，而不是 272 个独立真人；也不表示真实儿童验证。

两头都完整评估 272 条，没有删除错误样本或缺失音高样本，两头的音高不可用数均为零。候选选择规则在这一校准集合中使用四声宏平均最高、NLL 作为平局比较；没有读取后续保留盲测的父源或 `voice-32`～`voice-35`。

| 候选                          |              命中 | 四声宏平均 |    NLL |
| ----------------------------- | ----------------: | ---------: | -----: |
| Swift，仅标准音训练           | 263/272（96.69%） |     96.61% | 0.1351 |
| Swift，标准音与原合成均衡训练 | 258/272（94.85%） |     94.92% | 0.2905 |

据此冻结选择仅标准音训练的头，SHA-256 `a823601bae50b1506325581d6e0d2cf467c53811552cb1c609de44f593cb6759`。新校准 manifest SHA-256 为 `16be384e20c7055d703669f3b434b62ba5ab35ede5686f0674bc0f9ef01e2516`，完整逐父记录/音色/声调结果保存在 `private/matcher-pitch-swift-selection.json`。

| 分组                     |                 冻结头命中 |
| ------------------------ | -------------------------: |
| 一 / 二 / 三 / 四声      | 71/72、62/64、60/64、70/72 |
| voice-28 / 29 / 30 / 31  | 67/68、67/68、62/68、67/68 |
| 四个转换家族全对的父记录 |                      59/68 |

这里的结果已用于选择候选，因此明确属于校准，不能重新称作盲测。完整匹配的错放行、正确音拒判和未来独立盲测仍由整体匹配器另行验收。

## 固定依赖、来源与安装

| 项目                                                                                                                    | 固定版本                   | 许可证                                  | 本机实装                                                                       |
| ----------------------------------------------------------------------------------------------------------------------- | -------------------------- | --------------------------------------- | ------------------------------------------------------------------------------ |
| [SwiftF0](https://github.com/lars76/swift-f0) / [PyPI](https://pypi.org/project/swift-f0/0.3.0/)                        | `swift-f0==0.3.0`          | MIT，Copyright 2025–2026 Lars Nieradzik | Python 3.12 的通用 wheel；模型随固定 wheel 提供，已在独立工具环境安装          |
| [Parselmouth](https://github.com/YannickJadoul/Parselmouth) / [PyPI](https://pypi.org/project/praat-parselmouth/0.4.7/) | `praat-parselmouth==0.4.7` | GPLv3+                                  | CPython 3.12 / macOS 11+ arm64 wheel，已安装；只作离线对照，不进入匹配运行环境 |

两个依赖只加入 `tools/pinyin-matcher/pyproject.toml` 的 `train` 组和对应 `uv.lock`。没有编译本地扩展，没有接受或绕过 Xcode 许可，没有修改应用依赖。

Parselmouth 0.4.7 实装显示内置 Praat 6.1.38，仅使用 `to_pitch_ac` 作原始自相关对照；不能把它说成已实现新版本的 filtered autocorrelation。[Praat 官方文档](https://praat.org/manual/pitch_analysis_by_filtered_autocorrelation.html)将滤波自相关用于语调测量，但本次未安装开发版或改变官方算法。

SwiftF0 是单声部音高估计器，属于声学前端，不进行 ASR、文字转写或语言模型补全。[官方模型说明](https://github.com/lars76/swift-f0)列出网络 14,386 个参数；本次 ONNX 文件包含固定 STFT 系数等初始化量，不能把全部初始化张量都计作可训练网络参数。上游性能和测试集数字没有作为本项目的识别质量证据。

固定文件：

- Swift wheel：`swift_f0-0.3.0-py3-none-any.whl`，SHA-256 `d7240c7c94b1d3e8f0e0cd2701b79be89a0f23a19cd5f944895a6518ecad72f3`。
- Swift ONNX：135,090 字节，SHA-256 `6385e8c2ebc3872e82c9ff5946228de44cd3be77a750ea53698b7dbfe94b0a22`。
- Parselmouth wheel：`praat_parselmouth-0.4.7-cp312-cp312-macosx_11_0_arm64.whl`，SHA-256 `29e468febc3de2acad8f7718b10cc800610871e229afc549b6b51f009a87ede7`。

本地 Swift 模型、许可证和安装记录在 `models/matcher-pitch-swift/`。匹配适配器只接受显式本地文件并核对固定摘要；不会通过包名加载模型或自动联网下载。部署运行只需已锁定的 NumPy / SciPy / ONNX Runtime，不导入 SwiftF0 Python 包、Parselmouth、Torch、MLX、Librosa 或 TTS。

显式安装可复现：先按锁文件安装离线工具，再将其中固定模型及许可证复制到指定目录。第二步只复制本地文件；匹配器不会自行调用它。

```sh
uv sync --project tools/pinyin-matcher --locked --all-groups
tools/pinyin-matcher/.venv/bin/python -m pinyin_matcher.pitch_swift \
  --install-from-tool-package models/matcher-pitch-swift
```

## 接口与产物

```python
from pathlib import Path
from pinyin_matcher.pitch_swift import SwiftPitch

tracker = SwiftPitch(Path("models/matcher-pitch-swift/model.onnx"))
array, info = tracker.contour(samples)  # 16kHz mono float32; shape [32, 4]
```

`featureVersion=relative-swift-f0-0.3.0-contour32-v1`。内部固定两条 CPU 线程，频率区间 46.875–1000Hz，输入限制沿用 0.15–8 秒。少于六个可靠 16ms 有声帧、静音、无可靠音高、模型损坏等情况失败或拒判，不切回原 YIN 伪造成功。ONNX `RunOptions` 可以随同主匹配请求传入以终止迟到的计算。

独立声调 ONNX 输入 `contour: [batch, 32, 4]`，输出 `tone: [batch, 6]`；0/5 两个未训练标签保留低 logit，支持的一至四声在索引 1–4。新头必须配套 Swift tracker，不能拿旧 YIN 特征解释同一组权重。

本地实验产物：

- `private/matcher-pitch-standard-ma-official.json`：标准 ma 四声的逐帧 YIN / 自适应 YIN / Praat / Swift 对照。
- `private/matcher-pitch-swift-standard/`：仅标准音训练，独立头 SHA-256 `a823601bae50b1506325581d6e0d2cf467c53811552cb1c609de44f593cb6759`，10,468 参数。
- `private/matcher-pitch-swift-combined/`：来源与四声均衡训练，独立头 SHA-256 `aa617b44ac5d8e87c9e67841713d47b737fecc25d30cb7dbbbad755228c61f7b`，10,468 参数。
- `private/matcher-pitch-swift-cpu.json`：本机 CPU 计时和内存。

训练数据与权重保持在忽略目录；不把它们提交为源码或儿童录音。

## CPU 实测与回归

Mac Studio M2 Ultra，本机固定 BLAS 一个线程、ORT 两个 CPU 线程，32 段既有标准音各跑三次。这里只测原始样本到 32×4 音高特征，不包含声学匹配网络或应用 HTTP。

| 项目                              |             实测 |
| --------------------------------- | ---------------: |
| Swift tracker 加载                |           21.0ms |
| 标准音音高特征 p95                |           5.03ms |
| 四秒重复标准音长度压力 p95，30 次 |          20.86ms |
| 峰值 RSS / 峰值增量               | 162.8MB / 40.8MB |

四秒输入通过重复实际标准音构造，只用于长度与计算开销，不算新的正确发音或儿童样本。完整匹配器的两线程时间、进程内存、取消与有效性需要另行整体测量。

`tests/matcher/test_pitch_v2.py` 的数值测试不证明声调准确率；本次另显式加载真实本地 Swift ONNX 与授权标准音，验证纯 CPU、32×4 有限输出、噪声拒绝、损坏/缺失模型及禁止 Python 网络连接。六项均通过。没有显式设置产物路径的 CI 会跳过实际权重测试，不把跳过写成通过。
