# SPEC-018 MATCH-08：真实语音数据准备审计

日期：2026-10-26。数据用于本机非商业研究。不是儿童发音验收记录。

## 来源选择与许可

- **ManDi**：Zhao、Chodroff，2022，[原论文](https://aclanthology.org/2022.lrec-1.213/)，[公开数据](https://osf.io/fgv4w/)。原作者公开许可为 **CC BY-NC 3.0**；[许可文件](https://osf.io/download/2k9dp/)明确限制非商业用途。保留署名与非商业限制，音频不提交 Git，不把其许可变为代码的 MIT。
- **Tone Perfect**：原作者[项目方法论文](https://ideah.pubpub.org/pub/hh90jpsu/release/2)记载 410 × 4 × 6 = 9,840 个真人孤立音节，原音频为 “In Copyright - Educational Use Permitted”，不能误记为 CC BY。完整包需要向 MSU 提交非商业用途申请；本次访问[旧站](https://tone.lib.msu.edu/)返回访问受限页面，未取得语音，也未绕过限制或把第三方副本视为新许可。
- **OMPAL**：[官方仓库](https://github.com/phantomhsieh/OMPAL-corpus/tree/c3aaa9e892e4b1c2a25b637401f52f6e35b53e74)，CC BY 4.0，49 名说话人、1,850 段句子，包含专家对声母、韵母和声调的逐字正确性标记。没有字音时间戳、实际错读音素与拼音。本轮以独立音素 CTC 提供边界，正确性只取原始专家票数，不把汉字平均切分或模型对齐当作发音真值；语流声调及边界限制见下文 OMPAL 补充范围。
- **Yali**：[作者发布数据](https://huggingface.co/datasets/real-ssb22/yali-lower)，GPL-3.0-or-later，单名说话人、部分声调经过音高修正，第三声为语流半三声；不满足独立说话人隔离的四声主验收需要。

## 冻结的 ManDi 范围

只使用明确标记 `CMN_WL1` 的普通话单字朗读任务，不将同一人的方言任务混入正确普通话样本。说话人来自区域方言背景，任务标签仍是预期读音；没有独立专家逐音确认实际音素/声调，不能把原文词表等同于每条录音毫无构音偏差。

公开目录有 36 份该任务 WAV，只有 26 份有对应的公开 MFA 输出 TextGrid。10 份缺少注释的数据保留在锁文件 `unavailableAnnotations` 内，未伪造标签。先以 `SHA256(mandi-v1:speakerId)` 排序，在未看模型结果前分为 **16 训练、4 校准、6 留出测试**。测试说话人的音频、TextGrid 默认均不下载。该分配由最初设想的 20/6/10 缩小，原因是上游标注缺失；质量阈值没有改变。

上游词典有 11 个音节的四声（44 项），已下载的每位训练/校准说话人实际有 40 个词标签：`ba / fu / zhe / chi / tang / meng / shen / xiang / you / yi` 的四声，`cai1–4` 均未出现。**覆盖声明按 40 类而非词典 44 类**。`CHD_034_F` 的注释有两条 `you2`、缺少 `you3`，原样保留计数，未把第二条擅自改标。

训练有 640 个根片段，校准 160 个，800 个 WAV SHA 均不同。每片段保存说话人、父 WAV SHA、原字标签、词/音素边界、音节/声母/韵母/声调、截取窗口、实际截取偏移及质量标记。所有同一说话人的样本属于同一集合。

## 切分方法与数值质量

MFA 有少量 30ms 的词边界，直接照边界切片会截掉真实音节。先以相邻非静音词/`sounding` 标注的中心中点确定独立窗口，再用 20ms 能量、窗口 p20 噪声能量 ×16、峰值能量 ×0.015 取阈值；合并不超过 120ms 的内部间隔，选靠近原词时间锚的能量段，两侧保留 80ms。此规则只看波形及原标注，在任何模型结果前制定。非词汇 `sounding` 区间单独记账，不给它编造音节标签。

所有 800 个条目均保留。时长中位数 0.606 秒，p99 1.434 秒，最大 2.818 秒。数值标记包括 16 个没有能量段、7 个时长短于预先限定的 0.15 秒、1 个能量段距原词时间锚超过 0.5 秒；标记可以重叠。训练若跳过这些条目须报告数量；评测不得删除它们以美化分母，应保留为拒判或按冻结规则给出的实际结果。

这些数值检查不是听音确认。原始录音与时间戳留在忽略目录，便于回溯切分和标签错误。此语料适于同音节四声、受控成人孤立字的比较；声母/韵母最小近邻覆盖不足，拼接多读是派生挑战，不代表自然连续语流。

## 复现与留出规则

所有远端文件使用 OSF 固定文件 ID、`?version=1`（实际版本以锁文件为准）、字节数和作者提供的 SHA256；下载后再核对 SHA，不允许推理阶段联网下载。

```sh
# 已提交的锁文件供普通复现使用；snapshot 只用于显式建立新锁，拒绝覆盖旧锁。
./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_data prepare

# 完成模型与校准参数冻结之后，才由验收流程显式打开保留的测试说话人。
./tools/pinyin-pretrained/.venv/bin/python -m pinyin_matcher.pretrained_data prepare \
  --include-frozen-test
```

输出位于被忽略的 `private/pretrained-matcher/data/`。默认清单为 `manifest-train-calibration.json`；包含测试的清单另存 `manifest-with-frozen-test.json`。再次运行复用通过摘要检查的原文件，固定同一切分规则，不随机改集合。一次打开后用于分析错误的测试集合必须降为诊断，后续质量声明需另留独立数据。

当前 6 名预留成人说话人即使点估计达标，也不足以说明儿童人群或所有普通话音节达标。需要报告 Wilson 区间、说话人相关性、实际样本量和近邻覆盖，不用每个简单音频-目标配对扩充分母。

## 实际模型运行后发现的上游转录风险

三模型实测中的独立电话音素诊断暴露 `BEI_004_F` 校准记录的严重异常：两个不同预训练编码器对其声母/韵母仅约 15% 与发布标签一致，其他三个校准说话人的声母/韵母结果明显更高。这个现象提示源标签或录音顺序问题，**模型一致不构成改标依据**，也不能据此删除该说话人或把它改成训练数据。

进一步查阅[作者论文第 3.2 节](https://aclanthology.org/2022.lrec-1.213.pdf)，作者明确说明部分转录丢失或与录音内容不符：参与者重启 Gorilla 会重新生成所有任务的随机顺序转录，覆盖先前完成的任务。第 2.3 节说明每个字词任务完全随机呈现，因此不能借用同一说话人的方言任务顺序修正普通话任务。

公开元数据中没有 `BEI_004_F_CMN_WL1` 的原始输入 TextGrid，输出 TextGrid 只有版本 1；2024 年新增人工修正目录只有方言 `DIA_WL1`，其 `BEI_004_F_BEI_WL1` 是不同录音、不同顺序。公开 Praat 脚本从逐记录 `.txt` 表依次赋值词标签，而这些逐记录原始表未在所列公开目录提供。WAV、网格 SHA、时长和本机切分偏移均与固定源文件相符，没有找到可独立核实的新标签顺序。

因此保留全部 v1 波形、源标签、诊断结果与完整分母，**不发布模型改写的 v2 标签，也不把该语料的当前结果当作已建立可靠成人发音真值的证明**。该风险需要独立标签来源或人工听音确认后解决；与儿童验证缺失是两个不同门禁。最终测试即使尚未打开，也应报告这一已知的语料标注风险。

## OMPAL 补充范围与独立专家标签

OMPAL 固定修订 `c3aaa9e892e4b1c2a25b637401f52f6e35b53e74` 的 46 名法语学习者按实际 WAV 说话人 ID 的固定 SHA 排序分成 28 训练、8 校准、10 预留测试，3 名母语参考说话人只用于诊断。默认显式下载并校验 904 训练、370 校准及 82 母语诊断 WAV；494 份最终测试 WAV 在本步骤未下载。原语料 **CC BY 4.0**，署名、作者、DOI 与完整许可保留于第三方说明及 `resources/licenses/OMPAL-CC-BY-4.0.txt`。

原始详细投票存在 65 个旧任务 ID 块，WAV 实际只有 46 名学习者，656 个 ID 不能直接相连。我们以作者公开的完整注释身份匹配：逐字候选文本、三个句子分数均值及全部声母/韵母/声调多数票构成指纹；再以完整旧任务块的指纹多重集合唯一定位实际说话人，解决全优记录的全局重复。1,768 条实际 WAV ID 与旧详细注释全部唯一对应，没有用波形、模型预测或文件位置猜测身份。多数票仅作记录连接，不能冒充专家一致；实际标签始终保留三位专家原始票。映射证据及重建代码见 `content/pronunciation-ompal-detail-id-map.json` 与 `pinyin_matcher/pretrained_ompal_id_map.py`。

预期拼音由 84 个固定上下文的词汇政策定义，与专家正确性及声学模型分开。三声相邻、一/不表层调、轻声、可选轻声、地区词汇读音、儿化、字文本候选及提示不一致均保留范围标记。原注释有的 `text` 字段含两个备选汉字，不能拼成两个音节。最终政策 v2 的 SHA256 为 `1bbacd4f50198d6ef9695f4c1a12a3c650a5d1dba5e72530b39bb2f39b01c464`。

默认清单保留全部 15,015 个字记录。政策范围内训练有 5,037 个三分量专家一致正确、419 个至少一分量一致错误、1,936 个意见不一致；校准对应 2,239 / 188 / 720。另有全部政策范围外及母语参考记录，均未删除。原始专家标签与拼音政策、边界不确定性分别记录；意见不一致和未覆盖输入必须明示为不可评估，不能丢弃后宣称全语料准确率。

[原论文第 2.2 节](https://www.isca-archive.org/interspeech_2025/hsieh25b_interspeech.pdf)说明每段由四位专家中的三位评分、逐字只看最后一次尝试，并可能对特定遗忘性漏字记为正确。因此连专家一致正确也不保证每个目标字都在波形中存在；强制对齐只提供候选时间边界，弱边界、漏读和重读仍须拒判或独立验证，不可被对齐成功“证明正确”。该补充语料扩展到真实学习者错音，但源录音是句中语流，不等同于儿童孤立拼音任务。

## 新增孤立语音候选的实际可用性调查

本轮继续查找真实孤立音节及四声素材，未改动任何既有 train/calibration/test 划分，也没有打开原预留录音或发送外部申请。不能把“论文开放”“网站有下载链接”或词典拼音标签当成已取得音频许可与实际构音正确性。以下结论区分可以取得的有限补充材料与尚未满足条件的研究语料。

| 候选及实际来源                                                                                                                                         | 说话人与人工标注证据                                                                                                                                                             | 音频/许可核验与本轮处理                                                                                                                                                                                                                                                                                      |
| ------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Shtooka `chi-balm-hsk1`，由 [Wikimedia 的 bā 录音页](https://commons.wikimedia.org/w/index.php?title=File:Zh-b%C4%81.ogg&oldid=1253199215)及原文件提供 | 所查记录为一位北京男声；署名 Wei Gao、Vion Nicolas。页面明确给出 `bā/八`，同来源另有 `bǎ/mǎ/shí/shì`。这些是发行者的词典发音标签，未找到独立声母/韵母/声调正确性票；年龄未注明。 | **CC BY 2.0 France**。实际下载并用 ffprobe 解码 `Zh-bā.ogg`：0.85秒、12,214字节；文件上传版本为2007-11-08，SHA1 `08ae57897f68e8b4798ce0514e383ff87464fbb3`，SHA256 `d676d02bc70967c8a12026a5e54e8559a81d1687f86c334420962ddafc78c974`。可作为署名充分的真实语音诊断/补充，不能以单声音源建立说话人独立验收。 |
| Shtooka `cmn-caen-tan`，由 [Wikimedia 的 bá 录音页](https://commons.wikimedia.org/w/index.php?title=File:Zh-b%C3%A1.ogg&oldid=963095645)及原文件提供   | 所查记录为一位辽宁女声 Yue Tan；页面给出 `bá/拔`，同来源另有 `má/mà`。年龄、逐分量专家复核均未注明；小样本里声调与声音源存在混杂，不能把两声音源拼成一个无说话人混杂的四声对照。 | **CC BY-SA 3.0 US**。实际下载并解码 `Zh-bá.ogg`：1秒、12,973字节；文件上传版本为2011-11-13，SHA1 `c58ca8cc0a436ae5123c1558e369e6427f1ab7d9`，SHA256 `a6efb206dff1744aabfa3e336a2379a110eca4edfc7deaba28a2aad063e3d6f7`。第三条下载返回429后停止，未绕过限流。可作有限补充，后续派生须保留其独立许可。        |
| Dong等2019，[HVPT原论文](https://doi.org/10.7717/peerj.7191)、[作者OSF项目](https://osf.io/wdh8a/)                                                     | 论文描述真实多说话人的孤立词最小声调对，以及4位母语者的6元音×四声共96个自然刺激；作者报告由母语者判断自然、可区分。部分其他实验刺激另经过音高合成，不能混为自然录音。            | 实际递归读取 OSF 的全部公开 provider/child/文件元数据：只有 `R analysis/scripts` 中5个 R/Rmd/HTML 文件及 `datafiles` 中7个 CSV/DOCX 行为文件，无音频 provider 或子项目。论文的数据开放声明指向行为数据和分析代码，没有建立可下载的固定音频及其许可；未把论文CC BY直接套到未发布录音上。                      |
| Zeng等2023，[清晰/自然四声原论文](https://doi.org/10.3389/fnhum.2023.1247811)                                                                          | 真人孤立词，有两名接受语音学训练的母语者审核发音与录音质量；存在自然和清晰发音两种风格。公开论文也说明实验版另加噪声，应与原清晰录音区分。                                       | 官方数据声明为作者将提供原始数据。本次未找到可固定的公开原录音URL及音频许可；没有发送申请，未下载未获明确许可的音频。这是有审核证据但当前不可直接获取的候选。                                                                                                                                                |
| [Long-lag priming作者项目](https://osf.io/6w8sy/)、[原论文](https://escholarship.org/uc/item/96k7g38p)                                                 | 一位长春男性母语者孤立随机读词，由两位作者选择清晰token。不是多说话人数据；音系标签来自研究者设计与选音，不能推断为逐分量错误评分。                                              | 完整检查刺激目录9页：902文件中896条WAV元数据，含固定文件ID、版本及源SHA，确有自然录音链接。节点与父项目 `node_license=null`，根目录和全部刺激文件中均未找到 LICENSE/README/rights 文件。**未下载其WAV**，公开可读不等于明确许可。                                                                            |
| [Yali-Lower作者数据](https://huggingface.co/datasets/real-ssb22/yali-lower/tree/72e72d7eead560d87ec322eb15840df606060a7c)                              | 一位 Cheng Ya Li 的2008年语境录音；作者README明确第一声/第六声调过音高，第三声是半三声。                                                                                         | 固定修订 `72e72d7eead560d87ec322eb15840df606060a7c`，录音明确GPL-3.0-or-later，可公开取得；但不满足本任务自然孤立四声和多说话人验收范围。本轮未加入训练或测试。                                                                                                                                              |
| [THCHS-30官方发布页](https://www.openslr.org/18/)                                                                                                      | 清华连续普通话语料；发布名明确为 Tsinghua Continuous Mandarin Speech Database。原文本/拼音不是对每个切片实际音素、表层调及构音正确性的人工确认。                                 | Apache-2.0且有公开归档，可用于其他声学训练，但不能解决当前语流与孤立四声的范围差异；本轮没有把连续文本切片转称孤立发音真值。                                                                                                                                                                                 |

八条 Shtooka 页面/文件元数据、两条实际OGG、解码结果和全部采样SHA保留于 `private/pretrained-matcher/corpus-research-isolated/shtooka-samples.json`，摘要 `c97cdf8c6fdaf32b0764633fe71c2a39e578b9f8eda5cbda8b463845963500ab`。研究候选的原OSF API快照、完整分页清单及范围结论保留于同目录 `isolated-corpus-audit.json`，摘要 `45b878f474318f22f68dca4c0ead7ae487f42cc72295f488b9d098439ac28520`；这些新样本均未用于本轮模型训练或验收。

因此，本轮确有可用的两套有限真实词典语音补充，并非“所有公开数据都不可得”；尚未取得的是同时满足**多说话人、自然孤立四声、人工发音复核、明确许可、固定公开下载**的新验收语料。该门禁不能靠扩大 OMPAL 句中语流训练量或合成音色数量消除。

## 统一四秒CPU压力波形

原基线及所有预训练原始/派生包共用 `private/pretrained-matcher/cpu-pressure-exact.wav` 的**原始字节**，128,044字节、16kHz单声道PCM16、64,000采样。按原基线 helper 的顺序选择 `CHD_012_F` 第一条校准记录 `mandi-cmn-wl1-CHD_012_F-000`，源SHA256为 `9bec97bd19e1006d99228ebb8cff9c136065b2b32cddbff4a2128f486ccfa034`；解码后直接 `numpy.resize(unit,64000)`，不额外trim，再用原归档编码器写PCM16。输出SHA256为 `f0f4fa647b5de7e9c766b11c33eb61d7fdd5aa9183dfd3dba0461ecc23300e69`，与 `baseline-comparison-v2-repro.json` 已有基准载荷摘要逐字节一致。

以下命令只准备文件，不运行任何模型或性能计时；需先按工程文档准备固定原实现归档及基线报告。

```sh
cpu_repo=/Users/chad/dev/love-pinyin
cd "$cpu_repo/private/pretrained-matcher/baseline-code"
PYTHONPATH="$PWD" "$cpu_repo/tools/pinyin-matcher/.runtime/bin/python" - <<'PY'
import hashlib
import json
from pathlib import Path
import numpy as np
import pinyin_matcher.audio as original_audio

snapshot = Path.cwd()
assert Path(original_audio.__file__).resolve().is_relative_to(snapshot)
repo = snapshot.parents[2]
manifest = repo / 'private/pretrained-matcher/data/manifest-train-calibration.json'
row = next(r for r in json.loads(manifest.read_text())['items']
           if r['split'] == 'calibration' and r['speakerId'] == 'CHD_012_F')
file = Path(row['file'])
if not file.is_absolute():
    file = manifest.parent / file
source = file.read_bytes()
assert hashlib.sha256(source).hexdigest() == row['sha256']
payload = original_audio.encode_wav(np.resize(original_audio.decode_wav(source), 64000))
report = repo / 'private/pretrained-matcher/baseline-comparison-v2-repro.json'
expected = json.loads(report.read_text())['benchmark']['pressurePayloadSha256']
assert hashlib.sha256(payload).hexdigest() == expected
output = repo / 'private/pretrained-matcher/cpu-pressure-exact.wav'
assert not output.exists() or output.read_bytes() == payload
output.write_bytes(payload)
print(expected)
PY
```

谱系记录另存同名 `cpu-pressure-exact.json`。该重复波形只用于长度/CPU开销压力，不是新的发音样本、标签或儿童验证；计时入口应读取上述原始文件，避免再次trim或编码改变被测载荷。
