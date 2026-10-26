# 预训练拼音匹配候选核验

核验日期：2026-10-26；对应 SPEC-018 MATCH-07。固定文件 URL、字节数与 SHA256 见 [`content/pronunciation-pretrained-models.json`](../../content/pronunciation-pretrained-models.json)。本文件核验公开产物和可运行路径；模型卡的开发集数字不作为本项目的效果证据。权重留在忽略目录，未获得完整独立权重许可证明的产物不随项目再分发。

| 候选               | 固定实际产物                                                                    | 能力与研究判断                                                                                                    |
| ------------------ | ------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| HanziFlow V2.1     | `93c4b3f185f67b2f82135b34ca0397ddf8254de1`；FP32 safetensors 1,262,115,108 字节 | 24 层 XLSR-53 共享编码器；24/44/7 类声母/韵母/声调 CTC。保留为直接声学比较候选。                                  |
| Charsiu 中文 XLS-R | `2d274d10cce1dd66818c0706abbc4cc20d4ef710`；PyTorch bin 1,262,784,689 字节      | XLS-R 300M，10ms 的 210 类帧分类；声母及携调韵母。保留为直接声学比较候选，许可边界明确记录。                      |
| SenseVoiceSmall    | `3847d57b6bdf2dd8875cb1508d2af43d80a16bf7`；PyTorch pt 936,291,369 字节         | 多语种 ASR/语言/情感/事件输出，没有现成声母、韵母或四声判定头。保留编码器训练比较，不把汉字转写正确当作发音正确。 |

## HanziFlow

公开、未门控，模型卡声明 Apache-2.0；固定库没有独立 LICENSE 文件。基础权重为 `jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn@9c9f6c082674a183353d6193a5ca09f100ae1b26`。卡片披露 AISHELL-1 子集：14,285/1,549 条训练/开发语音，310/36 个说话人，合计 17.714 小时；没有公开逐句训练清单。其声调是带有限语境规则的表层读音，独立音节任务须核对标签映射。开发 CTC 错误率不代表学习者准确率；作者也披露早期项目看过 AISHELL 测试文本，因此该测试集不充当全新外部验收。[固定模型卡](https://huggingface.co/thin-nwe-soe/hanziflow-v2-1-multihead-wav2vec2/blob/93c4b3f185f67b2f82135b34ca0397ddf8254de1/README.md)

上游 requirements 要求 Transformers 5.x，但代码只构造标准 `Wav2Vec2Model` 和三个线性头。可在本项目已锁定运行时中实现同构加载并检查权重键、形状和实际输出；不得运行时下载或执行漂移的远程代码。三个 CTC 序列独立解码，不能假设帧/音节数始终相等。[固定配置与源码](https://huggingface.co/thin-nwe-soe/hanziflow-v2-1-multihead-wav2vec2/tree/93c4b3f185f67b2f82135b34ca0397ddf8254de1)

HF 最后变更为 2026-08-30，仍标为研究产物，卡片留有待外部评估的发布提醒；公开可下载不等于已经部署验收。

固定 `v2_1_target_schema.json` 的真实字节 SHA256 为 `1664632ace184c2851d7e6d68884225287020d913d653a0f885c41245210f433`。其 `heads.final.apical_retroflex_final` 明确为 `ii`、`apical_alveolar_final` 为 `iii`；这与 Charsiu 的同名字符串含义相反。不能共享舌尖韵母别名表。[固定 HanziFlow 标签 schema](https://huggingface.co/thin-nwe-soe/hanziflow-v2-1-multihead-wav2vec2/blob/93c4b3f185f67b2f82135b34ca0397ddf8254de1/v2_1_target_schema.json)

## Charsiu

HF 产物自 2021-12-16 未更新，没有模型卡、LICENSE、词表或预处理文件。官方项目 README 明确使用该检查点并声明工具 MIT；对应代码 LICENSE 为 MIT（2021 jzhu）。这提供项目层许可依据，但尚不足以证明每个独立上传权重的许可证与训练语料再分发权都相同。本次保留本地研究比较，报告该不确定性，不把它写成已核验 Apache-2.0 权重。[官方 README 与许可](https://github.com/lingjzhu/charsiu/tree/13a69f2a22ca0c0962b75cc693399b0ae23a12c9)

固定代码 `13a69f2a22ca0c0962b75cc693399b0ae23a12c9`（最后提交 2022-09-18）的自定义 `Wav2Vec2ForFrameClassification` 继承 `Wav2Vec2ForCTC`。其 eval 前向就是 `wav2vec2 → dropout → lm_head`；训练损失是逐帧交叉熵，不能把输出当 CTC blank 序列。当前 Transformers 的其他帧分类类名不保证兼容该头。官方预处理是 16kHz 单声道、每条波形零均值/方差归一化；最后卷积步长改为 1，得到 10ms 帧。[固定模型源码](https://github.com/lingjzhu/charsiu/blob/13a69f2a22ca0c0962b75cc693399b0ae23a12c9/src/models.py)、[固定预处理源码](https://github.com/lingjzhu/charsiu/blob/13a69f2a22ca0c0962b75cc693399b0ae23a12c9/src/processors.py)

词表另锁 `charsiu/tokenizer_zh_pinyin@a370e90191d18be4035783a7b98c509666e5c058`。210 类含 1 号静音、声母及带 1—5 调韵母；ü 用内部 `v`，舌尖元音区分 `ii/iii`，`iu` 展开 `iou`。实际目标应映射到这些音素，再使用未给答案的帧证据比较。[固定词表](https://huggingface.co/charsiu/tokenizer_zh_pinyin/blob/a370e90191d18be4035783a7b98c509666e5c058/vocab.json)

官方固定 `processors.py` 的转换规则为 `zhi → zhiii`、`chi → chiii`、`shi → shiii`，而 `zi → zii`、`ci → cii`、`si → sii`，所以 Charsiu 舌尖后用 `iii`、舌尖前用 `ii`。此语义由源码确认，不能由词表字符串长度或模型输出猜测。[固定 Charsiu 转换规则](https://github.com/lingjzhu/charsiu/blob/13a69f2a22ca0c0962b75cc693399b0ae23a12c9/src/processors.py)

配置表明基础编码器为 `facebook/wav2vec2-xls-r-300m`；原论文说明 FC 使用强制对齐帧标签，但未能从检查点公开材料确定中文微调的完整语料、划分和标注清单。项目发布过多个中文语料的对齐结果，该列表不能反推全部语料都训练了此权重。[原始研究论文](https://arxiv.org/abs/2110.03876)、[项目对齐数据说明](https://github.com/lingjzhu/charsiu/blob/13a69f2a22ca0c0962b75cc693399b0ae23a12c9/misc/data.md)

## SenseVoiceSmall

官方源代码 MIT 与权重许可分别记录。HF 卡片的权重许可字段为 `other`，链接 FunASR Model Open Source License 1.1，包含归属与其他条款，不能用代码 MIT 或 TTS 模型 Apache-2.0 替代。官方当前源码固定 `586bbdb2b052f4fe19322581825228b6810a9fb3`（2026-09-30）。训练规模与多语种声明属于上游研究披露，未公开逐条训练语料；本项目报告重叠未知。[固定权重模型卡](https://huggingface.co/FunAudioLLM/SenseVoiceSmall/blob/3847d57b6bdf2dd8875cb1508d2af43d80a16bf7/README.md)、[官方源码](https://github.com/QwenAudio/SenseVoice/tree/586bbdb2b052f4fe19322581825228b6810a9fb3)、[权重许可](https://github.com/modelscope/FunASR/blob/main/MODEL_LICENSE)

原生汉字解码只作为额外诊断。公平编码器比较要使用统一训练/校准/测试及相同监督预算，明确区分原生音素头、冻结编码器探针和进一步优化后的头；不能把“原模型没有发音接口”伪装成模型质量为零。

## 公开真人错误标签补充核验：OMPAL

OMPAL 提供 CC BY 4.0 的成人普通话/法国学习者语音。实际 detailed JSON 为 1,768 段非母语语音，19,775 个词记录；标签表示声母、韵母、声调是否正确，没有错误实际读音或音节时间戳。9 个词记录含两个文字元素；一项声母记录只有两位评分，其余各项为三位评分，不能按 README 的“共四位专家”假设每项四评分。[官方数据说明](https://github.com/phantomhsieh/OMPAL-corpus)

核对 `non-native_scores-detail.json`（SHA256 `5f23e7eadefbe465a7a71a896bff0c1def665fe0c2e5d40985f47f8846ad6f48`）：14,461 个词记录三项全体评分一致正确；898 个至少一项一致错误；4,416 个存在分歧且没有一致错误。声调一致正确/一致错误/分歧为 15,094/796/3,885。二值验收必须预先冻结一致性政策并完整报告含糊标签数量，不能把多数表决标签当作无争议的实际读音。没有时间边界时不得用平均切片伪造单音节数据；若用对齐提取，还需独立验证边界及三声、轻声等语境政策。该数据不证明儿童能力。

## 已运行的原生头诊断与分割问题

2026-10-26 对初版提取清单 `58a366b3d59fdf702072ef75d9a15cf61a447ffedf342a79d7adbee3891f53f5` 的全部 160 段/4 位校准说话人实际运行原生头。按校准网格选出的概率 0.9、margin 0，HanziFlow 接受/明确拒绝/拒判为 13/9/138；Charsiu 为 55/26/79。原生诊断使用“任一替代音素组合”作为最难反例，含非词汇组合，不能直接当作最终冻结近邻验收。完整原始概率、拒判证据及期待标签保存在忽略目录 `private/pretrained-matcher/raw-native-calibration.json`；未读取测试音频。

模型互相独立的原生头在 `BEI_004_F` 上均只有 6/40 声母、6/40 韵母与 11/40 声调符合期待标签；Charsiu 在另三位校准说话人的声母为 32/40、39/40、40/40。该异常触发源录音/时间窗诊断，而非自动重标：第一窗从 0 秒开始、期待“汤”的 MFA 区间为 3.6218—3.7318 秒，旧全窗最大能量裁剪后两个模型均把保留片段识别为其他音节。模型一致不是实际读音真值，可能涉及宽窗内不同语音区域、锚点或原始标注问题，不能仅据此把期待标签改成模型输出。

`private/pretrained-matcher/raw-native-greedy-diagnostic.json` 保留全部校准根的期待声母/韵母/声调、两模型原生贪心音素、原生最大证据、说话人、源录音 SHA、提取窗与原始 MFA 区间。后续分割修复须采用独立固定的数值/时间锚规则，完整保留失败记录；旧结果只作诊断，新提取清单、缓存与模型另记摘要，不将其重新称为未接触的测试。

## 已证实的模型专用舌尖韵母映射缺陷

核验固定上游 schema 时发现，初版配置把 Charsiu 的 `i-dental → ii`、`i-retroflex → iii` 规则同时用于 HanziFlow。该配置错误影响 HanziFlow 历史原生头概率对照，以及以 HanziFlow 三头 CTC 生成的 OMPAL v1 边界；后者进一步影响三编码器的共同训练片段。它不能解释所有失败，也不能用作模型重标依据，但足以阻止该轮成为质量验收证据。

旧 OMPAL 片段清单 SHA256 为 `92f9f9469498575183335f3238a3e61d23aff48c841a7049174ff17369a6a464`，旧对齐器 SHA256 为 `4e2ee6f50cac2ea93702aa86327b51e721cc44565e6f268bfd603a3338c4312f`。原六组训练、概率、校准计数和实际 CPU 测量完整保留，并标为旧边界诊断；不会删除失败或改写为未受影响成绩。固定 schema 的证据是上述真实 SHA，缺陷确认未使用测试录音或模型一致性。

修复改为配置中逐模型的 `nativeRimeAliasesByModel`，`native_rime_aliases(name)` 显式取模型契约，缺失映射或相反舌尖语义立即报错。HanziFlow 原生比较、已知音素边界和目标比较都必须显式使用 HanziFlow 映射；Charsiu 保留原正确规则。修正后的边界、缓存、训练和模型包另记新版本及 SHA，并重新测量质量与 CPU，旧成绩不参与最终验收。

## OMPAL 标签 ID、文字备选与语音学政策修复

固定官方版本 `c3aaa9e892e4b1c2a25b637401f52f6e35b53e74` 的 aggregate 标注使用实际 46 位学习者的录音 ID，而 detailed 文件分成 65 个旧的篇章说话人块；1,112 个同 ID 记录可直接核对，另 656 个 ID 不同。不能按旧 ID 猜录音，也不能把旧篇章 ID 视为独立真人。实际逐字段验证发现，detailed 的句级评分均值（两位小数）及词级多数表决、原文与全部文字备选，和 aggregate 的 1,768 个记录形成完全相等的多重集合。1,708 种不同完整签名中的句子级碰撞，通过唯一完整篇章块在实际说话人内的精确匹配解决；65 个块、1,768 个逐句映射均唯一，无剩余或碰撞。派生映射、候选和来源摘要记录于 `content/pronunciation-ompal-detail-id-map.json`，可用 `pretrained_ompal_id_map` 重建。它是对官方元数据的精确身份连接，不能冒称作者发布过改名表；没有使用录音或模型输出。

aggregate 的二值标签不是一致评分：例如原始 `00200101` 的“都”，声调原票为 0/1/1、aggregate 为 1。只有经精确连接的 detailed 原票才能支持“一致正确/错误”的定义。9 个双元素文字数组也不是两个音节，而是“還/也”或“會/又”的备选措辞；保留第一项作边界锚，整项标为含糊，不拼成额外音节。

`content/pronunciation-ompal-policy.json` 的 `ompal-context-lexical-v2` 冻结 84 个实际文字上下文（82 个母语文本另有两种学习者变体），由锁定 pypinyin 0.55.0 草稿及明确语境词汇修正构成；修正包括先得/打掃得、乾淨、帶著等助词、空座位及“两只袜子”。它定义期待读音，**不是实际发音转写**。一/不、连续三声、轻声及可变轻声、儿化、地区词汇差异、语气词和文字不符等均保留音素锚并标为不能作明确四声质量判断，不用自动变调猜测替代标签证据。专家正确性原票不参与选择 pinyin。

在全部 19,775 个学习者词标注元数据中，v2 政策未标含糊的为 14,799 项，其中一致正确 10,502、一项或多项一致错误 749、专家意见有分歧 3,548；另 4,976 项带政策旗标，其中对应 3,959/149/868 项。全部数量完整记账，含糊记录不从发布报告中消失。实际选入的训练、校准与冻结测试数量由各清单独立记录；这里的全源统计未读取或评估测试声音。OMPAL 原论文还允许在特定条件下宽容漏读并按最后一次尝试评分，因此其标签是成人学习者评估任务的代理真值，不能证明严格漏读检测或儿童构音有效性。[OMPAL 原论文](https://www.isca-archive.org/interspeech_2025/hsieh25b_interspeech.html)
