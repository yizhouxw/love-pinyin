# 拼音听读、离线评分与资产调研

> **当前范围（2026-09-27，依 ADR-0004）：首版不采集录音、不提供发音评分。** 下文评分方案、隐私流程及相关 PoC 均为历史研究记录，不能作为当前实现指令或发布门禁。首版仅使用经授权和审校的标准音播放及客观听辨；评分须重新立项。

调研日期：2026-09-26。本文区分“官方文档支持”“可获取”“本机验证”“教学验证”；前两项不代表后两项已经通过。

## 结论与实施顺序

首版采用 **浏览器 + 自家 Mac Studio 服务端**：标准示范音是审核后的持权真人静态音频；儿童录音只经局域网 HTTPS 发到该 Mac，在本地评测后丢弃，禁止发送第三方。自动发音评分是首版必需能力。Mac 本地 Python 声学原型先行，产品页面只能使用通过儿童校准的评分器，不能以音量、录音完成、ASR 文字命中或随机数字冒充发音评分。

当前未取得任何**已核验权利并完成审音、可纳入发行的**生产用标准音、儿童评测语料或可证明适用本课程的成品离线评分模型。用户机器上现有一组来源疑似为第三方网盘的拼音课程 MP3（见下方 2026-09-26 本机盘点），只能算待核验文件，不能算授权生产素材。技术路径已经收敛，但“儿童拼音评分可用”仍是发布门禁。下一阶段首先执行评分 PoC，再实现依赖评分的学习闭环。真人音制作可以并行，采购说明见 [音频制作规范](../content/audio-production.md)。

## 1. 示范音路线比较

| 方案                | 核实到的能力与权利                                                         | 本项目决定                                                                   |
| ------------------- | -------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| 自录/委托真人       | 可以按声母教学呼读、本音、韵母、带调音节分别制作；质量和许可由项目逐条收集 | 首选。必须先获声音使用与再分发授权，并双人审音                               |
| 系统 Web Speech TTS | 浏览器可枚举当前设备声音，但语言包、音色和实现取决于设备                   | 不能作为教学标准音，也不作为离线保证；不在首版依赖链                         |
| CosyVoice 3         | 官方代码 Apache-2.0；指定官方模型卡标 Apache-2.0，支持中文拼音发音控制     | 仅未来内容生产试验；模型条款不等于录音参考音色授权，逐条人工审听仍必需       |
| F5-TTS              | 代码 MIT；官方基础权重为 CC-BY-NC-4.0                                      | 不纳入计划开源、可商业使用的默认发行物                                       |
| 当前 Piper          | 维护仓库代码 GPL-3.0，模型另有各自条款                                     | 不作为 MIT 首版运行依赖；不能沿用旧 Piper MIT 印象                           |
| 云 TTS              | 阿里 SSML 支持以带调拼音控制汉字读音，但输入仍按汉字对应                   | 不选。当前不使用第三方云处理录音；即便只做离线制音也须另审输出分发权与准确性 |

核实来源：[MDN speechSynthesis](https://developer.mozilla.org/en-US/docs/Web/API/Window/speechSynthesis)、[CosyVoice 代码](https://github.com/QwenAudio/CosyVoice)、[指定 CosyVoice3 模型卡](https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512)、[F5 代码许可](https://github.com/SWivid/F5-TTS/blob/main/LICENSE)、[F5 权重许可](https://huggingface.co/SWivid/F5-TTS)、[Piper 当前仓库](https://github.com/OHF-Voice/piper1-gpl)、[阿里 SSML](https://help.aliyun.com/zh/isi/developer-reference/ssml-overview)。均访问于 2026-09-25。

**发音类别不能混用。** `b` 的教学呼读、本音与音节 `bō` 必须是不同资产；把汉字“波”交给中文 TTS，不能据此获得 `b` 本音。自然词语的变调、轻声与单独读出的本调也不能互相覆盖。音频 manifest 必须声明目标类别、声调和语境，程序不得用临近字音自动补缺。

## 2. 历史研究：完全本地评分的已知能力与缺口（当前暂缓）

此处“离线”指断开互联网仍可使用局域网 Mac API。Mac 断电或客户端离开局域网时，服务器评分不可用；客户端可保留当前页面与明确错误提示；首版不承诺断开 Mac 后仍可完成学习、保存或评分。

| 候选                      | 核实范围                                                                                                                         | 主要缺口                                                                                                                                   | 决策                                                                   |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------- |
| Python DSP：MFCC/DTW + F0 | librosa 提供特征、动态时间规整和 pYIN 基频估计；代码 ISC                                                                         | 距离不等于教学正确率；需要持权多说话人模板、错误样本、儿童校准                                                                             | **先实施的透明研究基线**；未校准只输出诊断/未就绪，不输出产品分数      |
| MFA 普通话强制对齐        | MFA 代码 MIT；`mandarin_mfa` 模型卡 CC-BY-4.0；提供音素时间对齐                                                                  | “把预期文字强制对齐”不能证明读对；没有现成儿童评分/置信度校准                                                                              | 作为离线标注辅助候选，不能直接把对齐似然映射为成绩                     |
| SenseVoiceSmall           | 本地中文 ASR；代码 MIT；官方权重为 `other` 的 FunASR 模型协议                                                                    | 输出汉字，不是独立声韵母评分模型；模型许可不是 MIT/Apache                                                                                  | 可选错误读词筛查研究，不进入评分正确率公式或默认发行包                 |
| sherpa-onnx               | 代码 Apache-2.0；原生与 WASM ASR 运行路线可获得                                                                                  | 运行时许可不覆盖每个模型；ASR 不提供本项目所需拼音评价标准                                                                                 | 备选模型运行层，当前不引入大模型依赖                                   |
| 驰声 C/C++ 离线 SDK       | 官方 C/C++ 离线文档列 Mac、离线 native 资源及首次联网获取 provision；中文通用 `cn.word.score` 单独列拼音/声韵/调型能力及儿童资源 | 离线内核文档只列英文核心；没有证据证明中文拼音内核随 Mac C 离线包提供；C 文档未列 macOS dylib，且 M2 Ultra arm64 包、授权、留存/外联仍未知 | **Mac 候选，待书面核实中文内核和 arm64**；未采购、下载、实测，不能接入 |
| SpeechSuper 离线 SDK      | 官方产品矩阵标示 Mandarin 单字/短文评分、tone score、无网运行；平台列 iOS/Android/Flutter/Windows                                | 未列 macOS；离线包授权按设备/年，不适配当前 Mac 服务端部署                                                                                 | 本期排除；将来原生客户端可另评                                         |
| 腾讯智聆离线 SDK          | 官方列拼音多种评测模式、无网运行（首次联网激活后）                                                                               | 官方支持矩阵为 Android/iOS 终端，不支持本期 Mac B/S 服务器宿主                                                                             | 本期排除；未来原生客户端可另审                                         |

来源：[librosa pYIN](https://librosa.org/doc/0.11.0/generated/librosa.pyin.html)、[DTW](https://librosa.org/doc/0.11.0/generated/librosa.sequence.dtw.html)、[librosa 许可](https://github.com/librosa/librosa/blob/main/LICENSE.md)、[MFA 模型](https://huggingface.co/MontrealCorpusTools/mandarin_mfa)、[MFA 对齐流程](https://montreal-forced-aligner.readthedocs.io/en/v3.3.3/user_guide/workflows/alignment.html)、[SenseVoice 许可声明](https://github.com/QwenAudio/SenseVoice#license)、[官方权重条款](https://github.com/modelscope/FunASR/blob/main/MODEL_LICENSE)、[sherpa WASM](https://k2-fsa.github.io/sherpa/onnx/wasm/build.html)、[驰声 C/C++ 离线文档](https://www.chivox.com/en/docs/offline/sdkDoc/C-offline-sdk)、[驰声离线内核目录](https://www.chivox.com/en/docs/offline/coreEn)、[驰声通用中文拼音内核](https://www.chivox.com/docs/coreCn/Chinese/cn.word.score)、[驰声 Unity 离线平台矩阵](https://www.chivox.com/docs/offline/sdkDoc/Unity-offline-sdk)、[腾讯离线介绍](https://cloud.tencent.com/document/product/884/61498)、[腾讯离线授权与平台](https://cloud.tencent.com/document/product/884/61500)、[SpeechSuper 离线产品矩阵](https://www.speechsuper.com/dashboard/)、[SpeechSuper SDK 文档](https://docs.speechsuper.com/)。官方页面复核于 2026-09-26。librosa API 链接是 0.11 文档，后续实现应以锁定版本的 API 为准。

### 为什么不能直接给出“正确率”

F0 只反映有声段的基频变化，不能区分 `b/p` 的送气，也不能判断 `n/l`、`z/zh` 的全部声学区别；清辅音不能强行套用声调分。MFCC/DTW 同时受说话人、麦克风、距离和语速影响；一个成人模板不能代表儿童正确发音分布。第三声的语境变体、轻声以及拼读过程还需要各自的判定目标。

这是本项目的工程风险判断。已有儿童 GOP 研究也报告：儿童发音变异使传统发音检测更困难，不能把成人结果直接用于儿童；该研究本身也不构成本项目中文一年级验证。[原始研究：An Analysis of Goodness of Pronunciation for Child Speech](https://www.isca-archive.org/interspeech_2023/cao23_interspeech.html)（访问 2026-09-25）。

### 本地 PoC 的明确推进决定

1. 第一候选用 CPU 上的 NumPy/SciPy/librosa，加原创多模板比较与可解释的分项结果。先覆盖限定集合，验证声母、韵母、四声、完整音节四种任务，保留“不确定/无有效语音”结果。
2. 先用成人授权样音排查采样、噪声、断句和API问题，再由获得监护人许可的儿童样本评价；成人试验通过不等于儿童上线通过。
3. 在验证集上确定分数映射和阈值，在按说话人完全隔离的测试集上冻结验收；不能同一人/同一段音频变速后跨训练和测试集。
4. 若 DSP 在核心混淆音上不达标，转向持权中文音素后验模型 + 对齐/校准的专门研发，或取得可在 Mac 服务端使用的离线 SDK；不能偷偷改云服务或取消评分验收。
5. 首次 PoC 时间盒建议 5 个工作日，结束必须交付基准报告、缺口清单与继续/换路线判断。它是风险发现周期，不是承诺 5 天训练出合格模型。

测试集必须覆盖 `b/p、d/t、g/k、n/l、z/zh、c/ch、s/sh、u/ü、an/ang、en/eng、in/ing`、四声错读、无声、环境人声、示范音回灌、过短录音、噪声和截断。不能只验证“正确样音能得高分”。分项反馈若无稳定错误定位证据，只提示重听/重录，不向孩子编造舌位纠错。

### 商用 Mac SDK 的采购预审问题

发送询价前准备同一套 PoC 音频、设备规格（Mac Studio M2 Ultra / arm64 / 64 GB）和需求表；本阶段只准备要求，不联系供应商、不购买。要求供应商书面确认：

- 提供实际 C/C++ macOS 库文件名、最低 macOS 版本、arm64/x86_64 架构与 ABI；若只支持 x86_64，书面说明 Rosetta 支持、性能和维护期。Unity 页的 x86_64 声明不能替代 C/C++ 包的证据。
- 可部署为局域网服务端，由多浏览器调用；每设备/每服务器/并发/年费计量方式与试用期限。
- 离线 Mac 包是否包含 `cn.word.score` 与儿童资源 `chn.wrd.G4.A2`，并给出独立声母、韵母、声调、ü 和整音节输入映射及原始样例；通用中文内核页不能证明离线包已含该资源。
- 首次 provision/激活具体连接的域名和传输字段；激活后能否长期断网，是否存在鉴权心跳、诊断遥测、录音上传或外部留存；若请求参数 `attachAudioUrl=0` 可关闭音频外传/保存，需明确书面确认其对 C 离线包的行为。
- 商业评测、生产嵌入与家庭局域网多浏览器并发服务的授权范围、计费口径、试用期限；密钥、引擎和资源文件的保密及再分发限制、离线授权过期行为和支持周期。
- 儿童独立声母采用“本音”还是教学呼读；是否覆盖全部课程韵母、整体认读、ü、轻声及声调；提供逐项输入映射和原始样例。
- 引擎升级可固定版本，输出含错误/拒判原因；获取实际儿童测试许可。SDK、密钥和权重不提交 MIT 仓库。

驰声的通用中文 `cn.word.score` 说明可评单个拼音、整体音节、声母/韵母与声调，并列出儿童资源及独立 `b`/`a3` 输入示例。[中文内核文档](https://www.chivox.com/docs/coreCn/Chinese/cn.word.score) 但其[离线内核目录](https://www.chivox.com/en/docs/offline/coreEn)当前只列 `en.*` 核心，不能由产品 SDK 文档或在线/通用中文内核推断离线包已包含拼音内核。C 离线页虽声明 Mac 支持，公开列出的库只有 `aiengine.dll` 与 `libaiengine.so`，未列 macOS `.dylib`；同厂商 Unity 离线页所列 Mac 架构是 x86_64，也不构成 C 离线包的 arm64 支持证据。本期硬件是 M2 Ultra/arm64，因此这一候选仍需书面确认具体 C/C++ 离线包、`cn.word.score` 儿童资源、macOS arm64 ABI、局域网多端授权和首次激活后的隐私/断网行为；以上只是基于官方文档的采购预审，不是运行测试或产品性能结论。

## 3. 已排除的云评分与浏览器捷径

- 讯飞流式评测 `read_syllable` 对应单个汉字，能返回声韵和调型字段；不能仅凭名称推断能评独立声母。[官方 API](https://www.xfyun.cn/doc/Ise/IseAPI.html)。
- 腾讯新版有独立拼音模式，但要将音频发第三方，违背当前边界；旧基础版停止迭代，不能选旧教程作为新项目依赖。[新版拼音模式](https://cloud.tencent.com/document/product/1774/107402)、[基础版状态](https://cloud.tencent.com/product/oeb)。
- Azure 中文发音评价存在，但英文专属音节/音素功能不能推导为中文支持，且属于云服务。[官方评测能力](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/how-to-pronunciation-assessment)。
- 浏览器 `SpeechRecognition` 默认行为和本地语言包支持不一致；它是语音识别，不是儿童拼音评分。本期禁止调用此 API。[MDN Web Speech](https://developer.mozilla.org/en-US/docs/Web/API/Web_Speech_API)。

以上访问日期均为 2026-09-25，仅保留路线比较，不安排接入或费用。

## 4. 字体、插图与素材

拼音正文建议后续评估 SIL **Andika**：面向初学阅读者，单层 `a/g` 和组合附加符有明确字体功能；官方提供 WOFF2，许可 OFL-1.1。它不是“教育部认证拼音字体”，四线格位置、`ɑ/a` 的显示策略、带调 `ü` 和教材字形要由课程审核者单独确认。数据统一保存标准拉丁 `a/g` 与 NFC 归一化拼音，不为了看起来像教材把数据库字符替换为 IPA `ɑ/ɡ`。[字体主页](https://software.sil.org/andika/)、[字体特性](https://software.sil.org/andika/features/)、[官方下载](https://software.sil.org/andika/download/)、[OFL 原文](https://github.com/silnrsi/font-andika/blob/master/OFL.txt)（2026-09-25）。

系统中文字体用于界面；不把系统字体文件拷入仓库。正式引入 Andika 时固定包版本、保存原版权与 OFL，不删除保留字体名要求；若做子集/修改，先检查许可条件并按要求更名。字体需要测试 `ā á ǎ à ō ó ǒ ò ē é ě è ī í ǐ ì ū ú ǔ ù ǖ ǘ ǚ ǜ ü ê`，检查低端屏幕和缩放下声调不被裁切。

首版插图、徽章和音效优先原创 SVG/CSS/原创短音效；每件资产登记作者与许可。教材扫描、出版社配套音频、百科图片、搜索图片和网上“免费拼音包”都不因可下载而获再分发权。MIT 是项目原创代码协议，不会覆盖第三方字体、模型或录音。未知许可素材保持 `blocked`，不得混入构建。

## 5. 获取证据与当前状态

### 2026-09-26 用户本机文件盘点

检查 `/Users/chad/Documents/1汉语拼音音频/`：有 13 个 MP3、没有随附的来源/授权说明文件。文件为 ID3v2.3、44.1 kHz、联合立体声、256 kbps，单条约 2.7–5.9 分钟；仅用系统元数据工具查看格式、时长和 SHA-256，没有试听、转码、复制或上传。文件名对应 `a o e` 到 `ang eng ing ong` 的 13 课旧序列，其中 `2iuvYW.mp3` 把 `i/u/ü` 与 `y/w` 合在一起；本项目 2024 版路线把 `y w` 单列为第 9 课，所以这批音频与当前内容映射并非一一对应。长课件也不能直接替代按教学呼读、本音、韵母、带调音节分类的单项标准音。

文件目录本身不能证明表演者/录音制作者授权、教材版本或内容准确度；结合先前搜索到的个人博客网盘索引，当前应按第三方来源不明材料处理。未复制到 `public/audio/`、未加入 Git、未登记为 approved，也未向浏览器提供。继续集成前需有书面权利证据覆盖本地 Mac 私有托管、LAN 播放、必要的剪辑/转码和开源发行；其后仍须教师逐条审听、拆分为内容 ID 并校验 SHA-256。没有授权时改用原创委托录音。

### 2026-09-27 本机分句候选导出

按用户要求，在原目录下生成本机暂存目录 `/Users/chad/Documents/1汉语拼音音频/提取候选_20260927/`，不写入 Git。使用 macOS `afconvert` 解码成 16 kHz/16-bit/mono PCM，再用 Python 标准库做 10 ms RMS 静音检测：低于 -45 dBFS 且持续至少 0.80 秒视为候选边界，边缘保留约 0.12 秒。共输出 427 段 WAV（80.66 MiB）；CSV 清单含来源文件、起止时间、源与片段 SHA-256，`target_pinyin` 全部留空；107 段超过 8 秒标记需再次拆分，320 段标记需人工听审。输出目录/文件权限分别为 0700/0600。没有使用网络、外部 ASR、模型下载或云处理。

此操作只做声学静音粗切，不能识别内容、拼音目标、标准呼读/本音分类、教学正确性或许可。长段可能含讲解/儿歌，多音节目标也可能仍被合在一起；不应直接导入课程或对孩子显示为“标准音”。下一步需先核验授权，再由审校人逐段听辨、拆分/重切并填入音频类型与课程 ID。若要机器转写候选文本，只能另行准备已批准且保证完全本地的工具，仍须人工复核。

### 2026-09-26 官方与公开网络音频线索复查

人教社官网可查到《义务教育教科书 语文 一年级上册 CD》产品页，页面说明载体为 CD、适用一年级上学期，内容包括“汉语拼音”，由广播电台专业播音员朗读；这是与本项目最相关的权威标准音线索，但产品页没有提供可公开下载的音频文件或可再分发许可。页面所关联的教材简介标注 2011 年课标且为旧版目录，不能直接证明其录音与 2024 秋季修订教材逐条一致。官方入口：[人教社配套 CD 产品页](https://www.pep.com.cn/products/dzyxn/xx/yw/202006/t20200617_1951990.shtml)、[人教社教材介绍页](https://www.pep.com.cn/products/jc/jks/201608/t20160823_1369629.shtml)。

人教社“人教点读”官方平台介绍称其收录统编版教材数字资源；人民教育电子音像出版社官网列有人教易视听、申学等客户端。另一个官方 App“人教易视听”说明资源与出版物配套，并可能需输入出版物激活码。此类产品适合家长/教师通过正版渠道收听或核验发音，不代表允许本项目抓取、拆分、复制音频或向家庭局域网再分发。人教社服务条款将平台音频等内容列为其知识产权，并要求未经授权不得复制/传播；官方联系入口公布电子音像制品与网络产品咨询电话。来源：[人教点读介绍](https://www.pep.com.cn/products/sz/ydxx/)、[人民教育电子音像出版社官网](https://www.peeavp.com.cn/)、[人教社服务条款](https://www.pep.com.cn/xyzc/202412/t20241203_1997325.html)、[人教易视听产品说明](https://apps.apple.com/cn/app/%E4%BA%BA%E6%95%99%E6%98%93%E8%A7%86%E5%90%AC/id1346513674)。

搜索引擎也索引到个人博客的百度网盘音频合集、论坛里的拼音发音 MP3，以及旧版教材点读/朗读页面。它们没有提供能验证录音表演者授权、录制来源、教材版次与音频逐条对应关系的证据；“免费下载”“百度网盘可取”不产生许可。因此**没有打开/下载/试听或纳入项目**，全部只作为待权利人核验的线索，不进入资源清单。[个人博客网盘索引示例](https://www.hao589.com/4204/04.html)、[论坛 MP3 索引示例](https://www.ebama.net/thread-111634-1-1.html)、[第三方旧版课文音频页面](https://yw.suyang123.com/xiaoxue/yinianji/27_langdu.html)。

建议先由项目权利人联系人民教育出版社电子音像制品门市（官网公开电话 010-64044211、010-58759303）和网络产品咨询（010-58759332），询问：2024 修订版一年级上册拼音音频是否现成可授权；是否允许复制到私有 Mac Studio、通过家庭 LAN HTTPS 播放、切分/转码、供非商业或开源项目使用；表演者与录音制作者的权利是否覆盖该用途；许可证明和署名/期限/地域要求。电话和页面仅证明存在官方咨询渠道，不证明已获得许可。若无法取得书面许可，沿用原创委托录音方案并由教师审音。

2026-09-25 使用 Python 标准库对下列小型官方资源进行 HTTP 获取并计算 SHA-256；没有下载或试听模型权重、没有调用付费服务。哈希用于复核本次读到的文本，分支 URL 可变，正式引入还须固定 commit/release。

| 资源                                                                                                | HTTP | SHA-256                                                            |
| --------------------------------------------------------------------------------------------------- | ---- | ------------------------------------------------------------------ |
| [Andika OFL](https://raw.githubusercontent.com/silnrsi/font-andika/master/OFL.txt)                  | 200  | `ad7ddeb95bb5a7254938ab85336d8f8dc989ca95f2487f94e376fa60f33eae78` |
| [F5 代码许可](https://raw.githubusercontent.com/SWivid/F5-TTS/main/LICENSE)                         | 200  | `c70811d1402134de900e811d3eaa349eb60f4d38a8f635b27b1e378c630facd2` |
| [F5 权重卡](https://huggingface.co/SWivid/F5-TTS/raw/main/README.md)                                | 200  | `cf3354feaf4020527b3642b12a5a382de13d0af6bc99e8d37bee84425c1ca224` |
| [CosyVoice3 权重卡](https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512/raw/main/README.md) | 200  | `d4ec0fe1342b60a424ce1cd8971c670d26be38068a96148bcb6a1b8a334c3088` |
| [SenseVoiceSmall 权重卡](https://huggingface.co/FunAudioLLM/SenseVoiceSmall/raw/main/README.md)     | 200  | `6add90487ea3d685b6604ad0932b565fc5cf7e9daaf8aebc674de49da4560958` |
| [MFA 普通话权重卡](https://huggingface.co/MontrealCorpusTools/mandarin_mfa/raw/main/README.md)      | 200  | `c81bfac107e2f9174a617d2a25e8a0c419b140424142c7b1b4469e7b2f3dd288` |

另查询 npm 元数据获得 Meyda、Pitchy、ONNX Runtime Web 的 MIT 标记，以及 PyPI 上 librosa、ONNX Runtime、sherpa-onnx 等包元数据；这只证明索引可达和候选包存在。随后项目已实装并锁定 `assessment-poc` 组的 librosa/NumPy/SciPy，在本机合成220 Hz信号通过基本YIN运行验证（约220.24 Hz），仍未验证人声评分。实际已安装版本、锁文件和验证结果统一见 [依赖记录](../engineering/dependencies.md)，其余调研候选不等同实装依赖。GitHub releases API 本次返回 403 限流；字体官方下载页可打开，但字体包未安装验收。

| 项目                    | 现状                             | 放行条件                                       |
| ----------------------- | -------------------------------- | ---------------------------------------------- |
| 浏览器播放/采音技术路线 | 官方能力可核实，产品适配尚待实现 | 真实 iPad/iPhone/Android/桌面实测              |
| 真人教学音              | 尚未取得                         | 授权、文件、校验和、双人内容审核齐全           |
| 儿童评分标准集          | 尚未取得                         | 监护人许可、匿名编号、两位教师标注、隔离测试集 |
| 本地自动评分引擎        | 已确定 PoC 路径，尚无教学验收    | 基准、性能、拒判与隐私门禁通过                 |
| Andika                  | 许可与官方入口可获得，尚未入库   | 固定文件/许可、字形审核与跨端验收              |
| 商用 Mac 离线 SDK       | 可询证备选，不可承诺可用         | 架构/服务端授权/离线行为/试用通过              |
| 云 TTS/评分             | 明确不采用                       | 只有用户未来改动约束才重新决策                 |
