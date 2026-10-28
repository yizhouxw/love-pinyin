# MATCH-18：真人语音 GMM-HMM 小卖部试验（2026-10-28）

**结果：不达质量门槛，不可接入孩子的发音判定。** 实际训练了两个非 Transformer、非字符转写的传统模型；添加成人专家一致正确训练片段也没有解决高拒判。独立最终测试及真实儿童测试均未使用。本记录只报告研发诊断，不将高拒判造成的低错误放行当作达标。

## 数据和方法

沿用 [AISHELL-3 来源核验](target-pronunciation-pretrained-data-audit.md)与 [MATCH-14 数据准备](../specs/SPEC-018-target-pronunciation-matcher.md)：来源为作者听辨的真实句子拼音，部分公开训练库存来源及 Apache-2.0 说明见既有记录；切片由声学模型给出，未逐条核验，因此音素和音节边界属于弱标注。训练仅用无政策或数值质量标记的 4,736 条 AISHELL-3 单音节切片，首轮 213 条质量检查未通过、使用 4,523 条；增加最低 5 个有声帧的保护后，另排除 383 条，使用 4,140 条。模型和数据不推送。人工听辨的句子拼音不能保证片段实际发音和切片边界正确。

每个声母和韵母分别用 4 分量对角协方差 GMM 表示声学帧分布；两个状态组成左到右 HMM，第一次按 35% 初始分界，第二次用目标路径 Viterbi 边界重估。相对音高、变化及有声信息构成 21 维向量，训练四个声调 GMM。帧特征为 13 维 MFCC。比较目标的声母、韵母和声调似然与其他同类模型的最强竞争者，三个差值取最小值；无零声母模型的目标保持拒判。采用 2 轮训练、种子 3182026，阈值从代码固定网格选出，不使用字符识别。训练中 sklearn 发出未收敛警告，最终原生模型 7 次、域适应模型 9 次，说明部分 GMM 的拟合尚不稳定，不能忽略。

域适应对照额外使用 5,035 条 OMPAL 训练说话人的专家一致正确片段；合计 9,771 根候选；增加有声帧保护后 8,635 根通过质量检查，269 条过静，867 条有声帧不足。它不使用专家错误或模糊样本作正例，校准说话人也未用于拟合。来源和说话人身份按 manifest 验证；跨来源是否存在同一真实个人无法绝对证明。两个模型用相同拓扑、训练轮数、特征和阈值选择规则。

## 相同成人诊断根比较

OMPAL 旧校准集涉及 8 名成人说话人，32 个试点音节内包含 159 条专家一致正确、8 条一致错误及 51 条专家意见不一致的切片。51 条不归入正确或错误分母；语流声调和自动切片均有限制，不能当作孤立音儿童验收。另有 20 条正确根在这 32 个音节中没有一分量近邻，近邻分母为 139；一条音频的任一近邻被接受就计一次。

| 模型                           | 正确接受 / 159 | 明确误拒 / 159 | 拒判 / 159 | 近邻错误放行 / 139 | 专家错音放行 / 8 |
| ------------------------------ | -------------: | -------------: | ---------: | -----------------: | ---------------: |
| 原生，首轮                     |              4 |              0 |        155 |                  4 |                0 |
| 加 OMPAL，首轮                 |              5 |              0 |        154 |                  4 |                0 |
| 原生，有声帧保护后重新训练     |              2 |              0 |        157 |                  1 |                0 |
| 加 OMPAL，有声帧保护后重新训练 |              5 |              0 |        154 |                  7 |                0 |
| 保留的旧 TCN 对照              |             22 |              7 |        130 |                  6 |                0 |

增加有声帧保护之前，域适应前对 159 条正确根的进一步诊断：143 条可计算声母、韵母和声调最高分，其中三类分别只有 25、39、60 条目标类别得到最高分；另 3 条无法解码/提取特征、4 条触发信号守卫、9 条缺少受支持声母。三项不一定属于同一组。不能将某个分量得到最高分理解成人工确认的音素识别正确率。最终域适应模型的 167 条专家正确/错误根中，3 条因静音、5 条因多个分离活动区、17 条因有声帧不足被拒判，剩余 142 条完成声学计算；缺失声母的目标另以拒判处理。

旧压力数据共 312 案，仅 35 个案覆盖试点目标（349 个目标查询不支持），去重后 15 条双音节和 2 条清晰对照全部拒判；静音、噪声、过长、过短、错误采样率、截断及非 WAV 样本均未接受。清晰对照也拒判，所以不能把压力结果解释为系统有效。未运行独立冻结测试，仍沿用近邻放行 ≤5%、正确明确误拒 ≤10%、清晰正确音拒判 ≤20% 的门槛。

## CPU 与复现

域适应包 CPU 两线程、四秒音频暖机 30 次，完整包含模型加载、解码、特征、输入守卫、GMM-HMM 和目标比较：p95 23.03 ms，实时率 0.00576；5 次新进程冷启动 p95 551.01 ms（样本少、未清操作系统缓存）；进程峰值 RSS 121.98 MiB，包 270,450 字节。性能达标不表示发音识别达标。包内两个 JSON 文件只含模型参数、实验配置和结果，无录音。

输入 manifest SHA-256 `36aa1f208896fa01a2bd34e7b88f6e5b731aa8615fb24622c48bcbf42cdfe311`；核心训练/推理代码 SHA-256 `69cd6b1312903086250dfe1eaad20456f8ea16e66ae7ccbe5d9485ee8eead15b`；域适应脚本 SHA-256 `f10eefc9498b91f6b48366670f973211a4a8e9291aeea7a3a15cd6c03c01fc60`；原生模型 SHA-256 `aa0b2793561d9d923851dca39f1da10cce4a1f84fd42fb3bf0bbe11171661ea4`，域适应模型 SHA-256 `30e80dc90a21fee5ce1f40f28c233d718955a32631facb6daf19d7600749b2c0`。当前模型包分别在忽略目录 `models/pinyin-gmm/native-v4`、`models/pinyin-gmm/adapt-v4`。manifest 内包含本机绝对音频路径，迁移环境需重新按既有数据准备流程生成并核验 manifest，不能假定复制 manifest 即可复现。依赖沿用固定的 `tools/pinyin-matcher/uv.lock`；scikit-learn 仅用于训练，推理使用 NumPy、SciPy 和 threadpoolctl，不下载模型或调用远程服务。

```sh
./tools/pinyin-matcher/run.sh setup
./tools/pinyin-matcher/run.sh gmm train --manifest private/pretrained-matcher/aishell3-clips-match14-v1/manifest.json --output private/gmm-native-reproduced
./tools/pinyin-matcher/run.sh gmm-adapt --manifest private/pretrained-matcher/aishell3-clips-match14-v1/manifest.json --output private/gmm-adapt-reproduced
./tools/pinyin-matcher/run.sh gmm match --package models/pinyin-gmm/adapt-v4 --target pm-ma1 --wav path/to/16khz-mono.wav
./tools/pinyin-matcher/run.sh gmm-stress --package models/pinyin-gmm/adapt-v4 --manifest private/pretrained-matcher/stress-match13-v2/manifest.json --output private/gmm-stress-new.json
./tools/pinyin-matcher/run.sh gmm-benchmark --package models/pinyin-gmm/adapt-v4 --target pm-ma1 --wav private/pretrained-matcher/cpu-pressure-continuous.wav --output private/gmm-cpu-new.json
```

后续需提高边界可靠性、重新设计声学状态与声调训练，覆盖零声母和独立声母/韵母，并使用可核验真实错音做模型选择；完整目标、独立冻结测试与儿童验证仍是剩余门禁。模型输出仅供研究，原应用接口不变。
