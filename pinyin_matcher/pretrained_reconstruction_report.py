"""Rebuild MATCH-13 evidence from actual local artifacts, never simulated results."""

import json
from pathlib import Path

from pinyin_matcher.catalog import ROOT, fingerprint
from pinyin_matcher.pretrained_experiment import write

PRIVATE = ROOT / "private/pretrained-matcher"
MODELS = ROOT / "models/pinyin-pretrained"
POOLED = [
    "sensevoice-factorized-v1",
    "sensevoice-v3-factorized-v1",
    "sensevoice-v3-multihead-v1",
]
SEQUENCE = [
    "sensevoice-native-sequence-fp32-v1",
    "sensevoice-native-sequence-int8-v1",
    "sensevoice-native-sequence-adapt-fp32-v1",
    "sensevoice-native-sequence-adapt-int8-v1",
]
TRAINING = [
    *(f"sensevoice-layer{depth}-multihead-v1" for depth in (20, 35, 50)),
    "sensevoice-factorized-v1",
    "ompal-v3-sensevoice-factorized",
    "ompal-v3-sensevoice-multihead",
    "sensevoice70-factorized-tail-v1",
    "sensevoice-adapt-multihead-v1",
    "sensevoice-adapt-factorized-v1",
]
LIMITS = {
    "nearNeighborFalseAccept": 0.05,
    "positiveExplicitReject": 0.1,
    "clearPositiveAbstention": 0.2,
}


def cell(value):
    return f"{value['count']}/{value['n']} ({value['rate']:.2%})"


def check_metrics(result, manifest_sha, *, clear_n=2239):
    metrics = result["metrics"]
    if (
        result["split"] != "calibration"
        or result["rows"] != 4202
        or result["manifestSha256"] != manifest_sha
        or metrics["positive"]["n"] != 2239
        or metrics["clearPositive"]["n"] != clear_n
        or metrics["negativeOriginStrata"]["expert"]["n"] != 188
        or metrics["gates"]["limits"] != LIMITS
    ):
        raise ValueError("REPORT_DENOMINATOR_OR_PROTOCOL_MISMATCH")
    if (
        sum(
            metrics["positive"][key]["count"]
            for key in ("accepted", "explicitReject", "abstention")
        )
        != 2239
    ):
        raise ValueError("POSITIVE_RESULTS_MISSING")


def build():
    artifacts = {}

    def read(path):
        path = Path(path)
        result = json.loads(path.read_text())
        artifacts[str(path.relative_to(ROOT))] = fingerprint(path)
        return result

    v2 = PRIVATE / "ompal-clips-v2/manifest.json"
    v3 = PRIVATE / "ompal-clips-v3/manifest.json"
    shas = {"v2": fingerprint(v2), "v3": fingerprint(v3)}
    read(v2)
    read(v3)
    pressure = read(ROOT / "content/pronunciation-pretrained-cpu-pressure-continuous.json")
    baseline = {}
    for name, path in {
        "original-sensevoice": "ompal-v2-sensevoice-four-tones-calibration.json",
        "previous-mixup": "sensevoice-mixup-v1-full-calibration.json",
        "mixup-frame-rms-fix": "sensevoice-mixup-v1-frame-guard-v2-full-calibration.json",
    }.items():
        result = read(PRIVATE / path)
        check_metrics(result, shas["v2"])
        baseline[name] = {
            "metrics": result["metrics"],
            "sourceManifest": "v2",
            "modelSha256": result["modelSha256"],
        }

    training = {}
    excluded_fields = {
        "coveredTargets",
        "calibrationExclusions",
        "tailTensorMaximumChanges",
        "lastEpochTailTensorMaximumChanges",
    }
    for name in TRAINING:
        model = read(PRIVATE / name / "model.json")
        history = read(PRIVATE / name / "training.json")
        expected_epochs = 12 if "tail" in name else 120
        if len(history) != expected_epochs or model["testUsed"]:
            raise ValueError("INCOMPLETE_TRAINING")
        training[name] = {
            "metadata": {k: v for k, v in model.items() if k not in excluded_fields},
            "history": history,
        }
        calibration = PRIVATE / name / "calibration.json"
        if calibration.exists():
            training[name]["cachedCalibration"] = read(calibration)
        if "tail" in name:
            training[name]["tailUpdateEvidence"] = {
                "selectedTensorsChanged": sum(
                    value > 0 for value in model["tailTensorMaximumChanges"].values()
                ),
                "lastTensorsChanged": sum(
                    value > 0 for value in model["lastEpochTailTensorMaximumChanges"].values()
                ),
                "lastMaximumAbsoluteChange": max(
                    model["lastEpochTailTensorMaximumChanges"].values()
                ),
            }
    for name, expected_epochs in (
        ("sensevoice-native-sequence-v2", 12),
        ("sensevoice-native-sequence-adapt-v1", 8),
    ):
        model = read(MODELS / name / "tuned.json")
        history = read(MODELS / name / "training.json")
        trained = [row for row in history if row["epoch"] > 0]
        if len(trained) != expected_epochs or model["testUsed"]:
            raise ValueError("INCOMPLETE_SEQUENCE_TRAINING")
        training[name] = {
            "metadata": {k: v for k, v in model.items() if k not in excluded_fields},
            "history": history,
        }
        training[name]["cachedCalibration"] = read(MODELS / name / "calibration.json")

    completed = {}
    for name in POOLED + SEQUENCE:
        package_path = MODELS / "bundles" / name / "model.json"
        package = read(package_path)
        result = read(PRIVATE / f"{name}-full-calibration.json")
        source = "v3" if "-v3-" in name else "v2"
        check_metrics(result, shas[source], clear_n=2226 if source == "v3" else 2239)
        package_sha = fingerprint(package_path)
        stress = read(PRIVATE / f"{name}-stress.json")
        cpu = read(PRIVATE / f"{name}-cpu.json")
        cold = read(PRIVATE / f"{name}-cold.json")
        if (
            result["modelSha256"] != package_sha
            or stress["metadataSha256"] != package_sha
            or cpu["modelSha256"] != package_sha
            or cold["modelSha256"] != package_sha
            or cpu["threads"] != 2
            or cold["threads"] != 2
            or cold["device"] != "cpu"
            or cpu["device"] != "Mac Studio M2 Ultra CPU"
            or not cpu["encoderActuallyExecuted"]
            or cpu["pressurePayloadSha256"] != pressure["payloadSha256"]
            or cold["payloadSha256"] != pressure["payloadSha256"]
        ):
            raise ValueError("CPU_STRESS_PACKAGE_OR_PAYLOAD_MISMATCH")
        completed[name] = {
            "sourceManifest": source,
            "modelSha256": package_sha,
            "metrics": result["metrics"],
            "originalPositiveRootAbstention": result["metrics"]["positive"]["abstention"],
            "derivedClearSubsetNote": (
                "v3 numerical flags exclude 13 roots from the emitted clear subset. "
                "Fair comparison retains all original 2239 positive roots, "
                "including these failures."
            )
            if source == "v3"
            else None,
            "stress": {k: v for k, v in stress.items() if k not in {"predictions", "modelInfo"}},
            "cpu": cpu,
            "cold": cold,
            "packageBytes": package["packageBytes"],
            "completeDirectoryBytes": sum(
                path.stat().st_size for path in package_path.parent.rglob("*") if path.is_file()
            ),
        }
        if name in SEQUENCE and "-fp32-" in name:
            required_source = MODELS / "sensevoice"
            completed[name]["requiredExternalResources"] = {
                resource: {
                    "bytes": (required_source / resource).stat().st_size,
                    "sha256": fingerprint(required_source / resource),
                }
                for resource in ("model.pt", "am.mvn", "config.yaml")
            }
        completed[name]["completeRequiredBytes"] = completed[name]["completeDirectoryBytes"] + sum(
            value["bytes"]
            for value in completed[name].get("requiredExternalResources", {}).values()
        )

    audit_names = [
        "match13-decision-audit",
        "match13-boundary-v3-audit",
        "match13-factorized-cpu-audit",
        "match13-native-sequence-cache-audit",
        "match13-native-sequence-error-audit",
        "native-sequence-adapt-int8-decision-audit",
        "match13-training-provenance-audit",
        "match13-additional-data-audit",
        "match13-sequence-cpu-audit",
        "aishell3-acquisition-summary",
    ]
    audits = {name: read(PRIVATE / f"{name}.json") for name in audit_names}
    for name in ("match13-native-sequence-error-audit", "match13-native-sequence-cache-audit"):
        records = audits[name].pop("records")
        audits[name]["privateRecordCount"] = len(records)
        audits[name]["recordsKeptInShaBoundPrivateArtifact"] = True
    data_audit = audits["match13-additional-data-audit"]
    audits["match13-additional-data-audit"] = {
        "observedAtUtc": data_audit["observedAtUtc"],
        "scope": data_audit["scope"],
        "conclusion": data_audit["conclusion"],
        "candidates": [
            {
                key: candidate[key]
                for key in (
                    "id",
                    "name",
                    "primarySources",
                    "actualLabelEvidence",
                    "licenseStatus",
                    "downloadStatus",
                    "adultAgeVerified",
                )
                if key in candidate
            }
            for candidate in data_audit["candidates"]
        ],
    }
    eduhk = read(PRIVATE / "eduhk-metadata-audit.json")
    audits["eduhkMetadata"] = {
        "scope": eduhk["scope"],
        "sources": eduhk["sources"],
        "permission": "Publisher permits acknowledged research; product rights not verified.",
        "wordEntriesNotVerifiedAcousticRoots": eduhk["sourceInventory"]["adult"],
        "toneCategories": eduhk["toneCategoryAudit"]["allAdults"],
        "adultSpeakers": 38,
        "excludedUnder18Count": 2,
        "wholeTaskAudioUrls": 76,
        "missingCanonicalWordEntries": 5,
        "extraWordEntries": 2,
        "unmarkedMeansConfirmedCorrect": False,
        "sourceWordTimestampsAvailable": False,
        "sourceCategoriesRequireCanonicalMapping": True,
        "mappingDiscrepancies": 22,
        "splitStatus": eduhk["preAudioSplitProposal"]["status"],
        "admittedToTrainingOrAcceptance": False,
    }
    guard_delta = read(PRIVATE / "sensevoice-mixup-v1-frame-guard-v2-delta.json")
    audits["guardDelta"] = {k: v for k, v in guard_delta.items() if k != "changedResults"}
    final_sources = read(ROOT / "content/pronunciation-ompal-data.json")
    final_files = [
        f for f in final_sources["files"] if f.get("split") == "test" and f["path"].endswith(".wav")
    ]
    if len(final_files) != 494 or any(
        (PRIVATE / "ompal/raw" / f["path"]).exists() for f in final_files
    ):
        raise ValueError("FINAL_AUDIO_INVENTORY_CHANGED")
    verification = {}
    for command, filename, marker in (
        ("npm run verify:all", "match13-verify-all-retry.log", "54 passed"),
        ("npm run validate:release", "match13-validate-release.log", "'release': True"),
        (
            "tools/pinyin-pretrained/run.sh test",
            "match13-final-regressions.log",
            "270 passed, 8 skipped",
        ),
    ):
        path = PRIVATE / filename
        if marker not in path.read_text():
            raise ValueError("VERIFICATION_LOG_INCOMPLETE:" + filename)
        relative = str(path.relative_to(ROOT))
        artifacts[relative] = fingerprint(path)
        verification[command] = {
            "log": relative,
            "sha256": fingerprint(path),
            "observedMarker": marker,
        }
    report = {
        "schemaVersion": 1,
        "date": "2026-10-26",
        "acceptanceSlice": "MATCH-13",
        "finalAcceptanceEstablished": False,
        "finalTestRead": False,
        "finalWavsAbsentAtExpectedRawPaths": 494,
        "interfaceChanged": False,
        "modelSelectionScope": "Repeated calibration diagnostics; no frozen or child acceptance.",
        "limits": LIMITS,
        "manifestsSha256": shas,
        "baselines": baseline,
        "training": training,
        "completedCpuRuns": completed,
        "audits": audits,
        "engineeringVerification": verification,
        "sourceArtifacts": artifacts,
        "generatorSha256": fingerprint(Path(__file__)),
    }
    lines = [
        "# SenseVoice 拒判重构与真实序列训练（MATCH-13）",
        "",
        "2026-10-26。本轮修复活动检测，完成中间层、分离监督、边界重构、尾层微调、真实整句CTC与混合域训练。对外v1匹配/识别/moc"
        "k接口不变。所有结论均为校准/诊断，质量与最终验收目标尚未完成。",
        "",
        "门槛保持近邻错误放行≤5%、正确音明确误拒≤10%、清晰正确音拒判≤20%。拒判包括证据不足、输入守卫或不可用结果，始终留在分母。所有完"
        "整CPU质量评测均保留4202根：2239正确、188真实错误、1775含糊或政策未知；8位校准说话人。",
        "",
        "## 完整两线程CPU对照",
        "",
        "|方案|波形边界|正确接受|明确误拒|正确拒判|反事实近邻放行|真实错误放行|",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for name, run in list(baseline.items()) + list(completed.items()):
        m = run["metrics"]
        p = m["positive"]
        lines.append(
            f"|{name}|{run['sourceManifest']}|{cell(p['accepted'])}|{cell(p['explicitReject'])}|{cell(p['abstention'])}|{cell(m['negativeOriginStrata']['counterfactual']['falseAccept'])}|{cell(m['negativeOriginStrata']['expert']['falseAccept'])}|"
        )
    lines += [
        "",
        "原始与上轮mixup为保存的历史CPU结果；活动修复是在同一v2音频和同一mixup权重上重新逐条推理。v3保持15015个根ID和专家"
        "标签，但边界改变，不能视为逐字节同一输入。近邻按每个根的任意一个合法单分量替代目标被放行计一次，不用大量目标配对稀释错误。详细分层、Wi"
        "lson区间、说话人bootstrap及全部门禁见JSON。",
        "",
        "活动检测由采样幅值计数改为10ms块RMS累计，避免把语音过零点误当静音；同一mixup模型多接受29条正确音，也多误拒7条。总体改善有限，不能把检测修复宣称为识别达标。",
        "",
        "v3边界使13个原正确根变成过短等数值异常，其原评测JSON的clearPositive子集为2226。"
        "上表和公平比较始终使用原2239正确根；这13个管线失败仍计拒判，不从分母消失。",
        "",
        "## 实际训练与失败",
        "",
        "|训练轮次|完成epochs|所选epoch|训练秒|",
        "|---|---:|---:|---:|",
    ]
    for name, r in training.items():
        m = r["metadata"]
        lines.append(
            f"|{name}|{sum(row['epoch'] > 0 for row in r['history'])}|"
            f"{m['selectedEpoch']}|{m['trainingSeconds']:.2f}|"
        )
    lines += [
        "",
        "下表是固定配置选中检查点的缓存筛选，不能当作完整CPU结果。全部正确根仍为2239；"
        "原生训练内网格与标准CTC部署网格分别记录，不把两者数字混用。",
        "",
        "|缓存筛选|正确接受|明确误拒|拒判|反事实放行|",
        "|---|---:|---:|---:|---:|",
    ]
    for name, run in training.items():
        if "cachedCalibration" not in run:
            continue
        m = run["cachedCalibration"]["selected"]["metrics"]
        p = m["positive"]
        cf = m["counterfactualFalseAcceptance"]
        if m["n"] != 2239 or sum(p.values()) != 2239:
            raise ValueError("CACHED_SCREENING_DENOMINATOR_CHANGED")
        lines.append(
            f"|{name}|{p.get('matched', 0)}|{p.get('retry', 0)}|"
            f"{p.get('uncertain', 0)}|{cf['count']}/{cf['n']}|"
        )
    lines += [
        "",
        "20/35/50层探针使用相同v2样本及120轮预算，仅作缓存诊断，未导出冒充70层包。分离头把正确身份交叉熵与分量有效性负监督分开；v"
        "2/v3均真实训练120轮。固定前64层、最后6层微调的factorized实验完成12轮，所选epoch0与初始化相同；末轮80个尾层"
        "张量确实更新，但未改善校准，保留失败。",
        "",
        "v3用三头锚点中位数和能量谷重分割14101个train/calibration片段。旧三头重叠证据146次对应102个不同正确根，不能"
        "算146个独立样本。新边界减少部分多读守卫，却增加低能量/过短片段；不能依靠裁掉难例取得改进。历史v3清单的elapsedSeconds"
        "继承v2来源字段，不代表v3实际运行耗时。",
        "",
        "原生序列实验保留完整人工拼音和CTC空白/多标签事件，先用真实整句，再混合OMPAL人工分量监督适应孤立短音。整句12轮所选epoch2"
        "仍处头预热阶段；后续尾层确实训练，不能将所选包描述成尾层已获益。"
        "初次MPS尝试因CPU float64转移路径失败，在完成任何epoch"
        "前停止；修复并用新v2目录重跑，失败日志/源码保留。训练入口随后加强原标签与缓存完整性校验，实际v2缓存独立审计通过；未重写历史模型的代"
        "码SHA。混合轮次固定8轮、两个域等权、头0.0001/尾层0.00001，按校准损失选检查点。训练根、重复曝光、排除、梯度和曲线见JS"
        "ON。",
        "",
        "混合INT8的2239个正确根中，三分量argmax同时正确仅1249（55.78%），"
        "其中826接受、423拒判；另有108根被音频守卫挡住。声调单独错357根，"
        "涉及声调错误575根，三声误作二声106根。当前要求三个身份都相符的规则下，"
        "单改阈值无法达到至少70%的正确接受率。",
        "",
        "冻结适应后表示再训multihead/factorized的三分量同时正确分别1425/1444根；"
        "同读出的原编码器分别1414/1486根，不能宣称表示总体改善。"
        "这两项消融未再打包，缓存拒判和完整曲线仍保留。",
        "",
        "## 真人补充数据与覆盖",
        "",
        "AISHELL-3的[OpenSLR93许可页](https://www.openslr.org/93/)标注Apache-2.0；[论"
        "文](https://arxiv.org/abs/2010.11567v2)说明实际拼音听辨标注。固定AISHELL账户镜像修订f20d"
        "5db4a31fe779ef07bb1af4ea92da5c786622，未独立证明该账户组织身份。镜像只有部分库存；本轮20位成人、2"
        "000句、592560484字节、6717.17秒（1.87小时），不是全部85小时/218人。未用其test目录。",
        "",
        "原提供22018拼音token；61句包含当前词表不能表达的儿化等，整句明确隔离。实际CTC训练1939句、21209音节；不从汉字重造"
        "读音，不把缺失音素删掉后继续训练。原音、派生音、原标签和每份特征均验SHA。性别5男15女；数据仅作训练补充，标注仍可能有误，无法证明跨"
        "数据集自然人身份完全不重叠，也未知预训练重叠，不能当独立验证。不使用LATIC。",
        "",
        "补充调查[EdUHK偏误库](https://lml-elearning.eduhk.hk/about_g.aspx)："
        "官方允许署名研究。元数据保留38位成人、2581个词条，源类别声母/韵母偏误507/447；"
        "这些尚非已验证音频根。录音没有逐词时间戳，1297个未标错词仍为未知，"
        "轻声、不完整三声和22个类别映射差异另记。未下载声音、未训练、未计入验收。",
        "",
        "## CPU与输入压力",
        "",
        "同一连续四秒许可PCM，两线程，含解码、特征、模型与目标比较；3次暖机、30次计时、5次新进程冷启动。操作系统文件缓存未清空，宿主机非独"
        "占。p95须同时≤500ms和RTF≤0.1，四秒对应实际≤400ms。",
        "",
        "|方案|暖机p95 ms|RTF|冷启动p95 ms|RSS MiB|包自身/完整所需MiB|",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, r in completed.items():
        lines.append(
            f"|{name}|{r['cpu']['fourSecondWarmP95Milliseconds']:.2f}|"
            f"{r['cpu']['realTimeFactor']:.4f}|"
            f"{r['cold']['freshProcessWallP95Milliseconds']:.2f}|"
            f"{r['cpu']['peakRssMiB']:.1f}|{r['completeDirectoryBytes'] / 1024**2:.2f}/"
            f"{r['completeRequiredBytes'] / 1024**2:.2f}|"
        )
    lines += [
        "",
        "FP32序列研究包除增量还需原936291369字节底座及核验资源，不能将上表包自身大小当成完整部署量。INT8序列包为自含图及资源，推"
        "理不读取外部底座或自动下载。数值检查覆盖0.15/0.5/4秒及变长批次，但数值接近不替代完整质量验收。",
        "",
        "|方案|清晰控制接受/误拒/拒判|多读任一目标放行|压力协议通过|",
        "|---|---:|---:|---|",
    ]
    for name, r in completed.items():
        clean = r["stress"]["byKind"]["clean-control"]["statuses"]
        multiple = r["stress"]["byKind"]["two-syllable"]["matchedUnits"]
        lines.append(
            f"|{name}|{clean.get('matched', 0)}/{clean.get('retry', 0)}/"
            f"{clean.get('uncertain', 0)}|{multiple['count']}/{multiple['denominator']}|"
            f"{'通过' if r['stress']['stressChecksPassed'] else '失败'}|"
        )
    lines += [
        "",
        "活动检测及v3边界改变候选锚点。MATCH-12与MATCH-13 v2仅283/312例的"
        "case ID、波形SHA和目标全相同；MATCH-13 v2/v3仅50/312例全相同。"
        "详细交集、噪声/静音/漏读/坏格式完整分母见JSON。短清晰控制子集表现不能替代2239"
        "正确根整体结果。",
        "",
        "原生FP32完整校准中的两个专家错音根发生MATCH_TIMEOUT，仍留在188分母；"
        "并发质量评测的耗时不用于性能结论。空闲时独立重放分别为retry（394.08ms）"
        "和uncertain（347.36ms），不覆盖原结果。",
        "",
        "## 剩余门禁",
        "",
        "本轮质量记录针对成人四声整音节及明确列出的输入挑战；"
        "没有据此验收单独声母、逐步拼读序列或自由拼音内容识别。"
        "整句CTC训练能力不等于这些用户任务已经达标。",
        "",
        "模型质量未达标。真实声母/韵母错误校准只有18/16根、各4位说话人，少于冻结的100根/5位说话人；反事实近邻不能补足真实错音。频繁使"
        "用的校准集已用于研发，不是盲测。最终10位说话人494份WAV仍未出现在预期原音路径，未读取；缺乏真实儿童验证。当前不发布儿童评测能力，"
        "不替换应用mock。",
        "",
        "工程验证：`npm run verify:all`通过（178个前端单测、465个Python测试、"
        "36个本地和54个真实服务浏览器测试），`npm run validate:release`通过。"
        "独立研究环境270项测试通过、8项显式慢测默认跳过；"
        "本轮另实际完成两组真实模型导出数值验证。"
        "首次全量验证遇到并行应用改动的格式问题，修正后完整重跑通过，日志分别保留。"
        "工程通过不替代当前未过的质量门禁。",
        "",
        "所有权重、录音、逐根结果留在忽略目录；Git保存代码、固定数据与训练配置、锁文件及聚合证据。复现命令见[工程文档](../enginee"
        "ring/pretrained-pronunciation-matcher.md)，本报告由`run.sh reconstruction"
        "-report`读取实际产物并核对身份/分母生成，缺失完整运行会报错。",
    ]
    destination = ROOT / "docs/research/sensevoice-reconstruction-results.json"
    write(destination, report)
    destination.with_suffix(".md").write_text("\n".join(lines) + "\n")
    return {"report": str(destination), "finalAcceptanceEstablished": False}


if __name__ == "__main__":
    print(json.dumps(build()))
