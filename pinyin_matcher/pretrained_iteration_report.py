"""Rebuild MATCH-12 evidence from completed local runs; missing runs are errors."""

import json
from pathlib import Path

from pinyin_matcher.catalog import ROOT, fingerprint
from pinyin_matcher.pretrained_experiment import write

PRIVATE = ROOT / "private/pretrained-matcher"
RUNS = [
    "sensevoice-independent-v1",
    "sensevoice-temporal-v1",
    "sensevoice50-temporal-v1",
    "sensevoice-mixup-v1",
    "sensevoice-ensemble-v1",
]
TRAINING = [
    "sensevoice-independent-v1",
    "sensevoice50-independent-v1",
    "sensevoice50-temporal-v1",
    "sensevoice-temporal-v1-mps",
    "sensevoice-mixup-v1",
]


def build():
    artifacts = {}

    def read(path):
        path = Path(path)
        data = json.loads(path.read_text())
        artifacts[str(path.relative_to(ROOT))] = fingerprint(path)
        return data

    manifest = PRIVATE / "ompal-clips-v2/manifest.json"
    expected_sha = fingerprint(manifest)
    baseline = read(PRIVATE / "ompal-v2-sensevoice-four-tones-calibration.json")
    if baseline["manifestSha256"] != expected_sha:
        raise ValueError("BASELINE_DATA_MISMATCH")
    training = {}
    for name in TRAINING:
        model = read(PRIVATE / name / "model.json")
        history = read(PRIVATE / name / "training.json")
        calibration = read(PRIVATE / name / "calibration.json")
        if len(history) != 120 or model["testUsed"] or model["manifestSha256"] != expected_sha:
            raise ValueError("TRAINING_RUN_INCOMPLETE_OR_WRONG_SPLIT")
        training[name] = {
            "seconds": model["trainingSeconds"],
            "epochs": len(history),
            "selectedEpoch": model["selectedEpoch"],
            "selectedComponentEpochs": model.get("selectedComponentEpochs"),
            "trainRoots": model["trainRows"],
            "trainSpeakers": model["trainSpeakers"],
            "cachedCalibration": calibration["selected"],
            "history": history,
        }
    stress_manifest = read(PRIVATE / "stress-match12/manifest.json")
    previous_stress = read(PRIVATE / "stress-calibration-four-tones/manifest.json")
    if [(c["id"], c["sha256"], c["targetIds"]) for c in stress_manifest["cases"]] != [
        (c["id"], c["sha256"], c["targetIds"]) for c in previous_stress["cases"]
    ]:
        raise ValueError("STRESS_CASES_CHANGED")
    completed = {}
    pressure_sha = read(ROOT / "content/pronunciation-pretrained-cpu-pressure-continuous.json")[
        "payloadSha256"
    ]
    for name in RUNS:
        result = read(PRIVATE / f"{name}-full-calibration.json")
        stress = read(PRIVATE / f"{name}-stress.json")
        cpu = read(PRIVATE / f"{name}-cpu.json")
        cold = read(PRIVATE / f"{name}-cold.json")
        package = read(ROOT / "models/pinyin-pretrained/bundles" / name / "model.json")
        package_sha = fingerprint(ROOT / "models/pinyin-pretrained/bundles" / name / "model.json")
        if (
            result["split"] != "calibration"
            or result["rows"] != 4202
            or result["manifestSha256"] != expected_sha
            or result["modelSha256"] != package_sha
        ):
            raise ValueError("FULL_EVALUATION_MISMATCH")
        if (
            cpu["threads"] != 2
            or cpu["device"] != "Mac Studio M2 Ultra CPU"
            or cold["device"] != "cpu"
            or cold["threads"] != 2
            or not cpu["encoderActuallyExecuted"]
            or cpu["pressurePayloadSha256"] != pressure_sha
            or cold["payloadSha256"] != pressure_sha
            or cpu["modelSha256"] != package_sha
            or cold["modelSha256"] != package_sha
            or stress["metadataSha256"] != package_sha
        ):
            raise ValueError("CPU_OR_STRESS_IDENTITY_MISMATCH")
        completed[name] = {
            "metrics": result["metrics"],
            "stress": {k: v for k, v in stress.items() if k not in {"predictions", "modelInfo"}},
            "cpu": cpu,
            "cold": cold,
            "packageBytes": package["packageBytes"],
        }
    sources = read(ROOT / "content/pronunciation-ompal-data.json")
    final_files = [
        f for f in sources["files"] if f.get("split") == "test" and f["path"].endswith(".wav")
    ]
    present = [f["path"] for f in final_files if (PRIVATE / "ompal/raw" / f["path"]).exists()]
    if present or len(final_files) != 494:
        raise ValueError("FINAL_WAV_INVENTORY_CHANGED")
    report = {
        "schemaVersion": 1,
        "date": "2026-10-26",
        "acceptanceSlice": "MATCH-12",
        "finalAcceptanceEstablished": False,
        "finalTestRead": False,
        "frozenWavsAbsent": len(final_files),
        "manifestSha256": expected_sha,
        "baseline": baseline["metrics"],
        "training": training,
        "completedCpuRuns": completed,
        "diagnostic": read(PRIVATE / "sensevoice-original-readout-diagnostic-v2.json"),
        "sourceArtifacts": artifacts,
        "generatorSha256": fingerprint(Path(__file__)),
        "dataAcquisition": {
            "LATIC": "Not used, per user instruction. Official page requires IEEE login.",
            "THCHS30": (
                "Download interrupted after low throughput across official mirrors; "
                "partial archive never used for training."
            ),
        },
    }
    lines = [
        "# SenseVoice 后续优化实测（MATCH-12）",
        "",
        "2026-10-26。五次120轮真实训练，加一次固定三成员等概率集成；"
        "质量仍未达标，最终测试未启用。所有模型均为研究包，不替换应用 mock。",
        "",
        "同一 OMPAL 清单：训练实际7386根、28位说话人；校准4202根、8位说话人，"
        "其中2239正确、188实际错音、1775未知/含糊。"
        "门槛保持5%/10%/20%，拒判不从分母剔除。",
        "",
        "## 完整两线程 CPU 校准",
        "",
        "|方案|正确接受|明确误拒|拒判|近邻错误放行|真实错音放行|",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, metrics in [
        ("原始SenseVoice多头", baseline["metrics"]),
        *[(n, r["metrics"]) for n, r in completed.items()],
    ]:
        pos = metrics["positive"]

        def cell(entry):
            return f"{entry['count']}/{entry['n']} ({entry['rate']:.2%})"

        lines.append(
            f"|{name}|{cell(pos['accepted'])}|{cell(pos['explicitReject'])}|{cell(pos['abstention'])}|{cell(metrics['negativeOriginStrata']['counterfactual']['falseAccept'])}|{cell(metrics['negativeOriginStrata']['expert']['falseAccept'])}|"
        )
    lines += [
        "",
        "近邻按每个真实根的任一合法单分量近邻被接受计一次，不能用配对条数稀释。原始对照复用既有实际CPU概率及完整四声复评；本轮五包逐条重跑完整波形。区间、说话人整群bootstrap、未知行、分层样本量与门禁见JSON。",
        "",
        "## 训练与诊断",
        "",
        "独立头分别学习声母/韵母/声调投影，并分别按校准分量损失选检查点。时序头以固定16点插值保留帧顺序，使用独立卷积与注意力；插值不增加声学分辨率。特征插值轮次仅对三分量专家一致正确的训练行做软标签正则，不生成额外音频。集成固定原多头、独立头、插值头等权平均完整概率，编码器只运行一次。",
        "",
        "缓存校准不同于实际CPU量化推理，五次训练的完整120轮曲线、所选检查点、耗时及缓存结果在JSON中保留；50层独立池化头仅作缓存筛选，没有宣称完成其全量CPU验证。原始时序头首次CPU训练人为中断后从固定种子在MPS重训；中断日志保留，不计完成轮次。",
        "",
        "原始多头缓存诊断的三分量同时正确为1414/2239（63.2%）；在当前必须选对三个分量的规则下，仅调阈值无法达到至少约70%的正确接受率。短于200ms片段209/387三分量正确，200–400ms为737/1154，超过400ms为468/698；这提示时长相关困难，不能证明边界或标注一定错误，也不能用来删难例。",
        "",
        "## CPU 与输入挑战",
        "",
        "同一连续四秒原PCM，CPU两线程、3次暖机、30次计时，含解码/特征/模型/比较；冷启动5个独立进程，操作系统文件缓存未清除。本任务训练、批量评测和工程测试结束后顺序测量；宿主机其他任务可能造成负载，未独占整机。",
        "",
        "|方案|暖机p95 ms|RTF|冷启动p95 ms|RSS MiB|包MiB|",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, r in completed.items():
        lines.append(
            f"|{name}|{r['cpu']['fourSecondWarmP95Milliseconds']:.2f}|"
            f"{r['cpu']['realTimeFactor']:.4f}|"
            f"{r['cold']['freshProcessWallP95Milliseconds']:.2f}|{r['cpu']['peakRssMiB']:.1f}|"
            f"{r['packageBytes'] / 1024**2:.2f}|"
        )
    lines += [
        "",
        "|方案|清晰控制接受/误拒/拒判（24）|多读任一目标放行（72）|输入挑战整体|",
        "|---|---:|---:|---|",
    ]
    for name, r in completed.items():
        clean = r["stress"]["byKind"]["clean-control"]["statuses"]
        multiple = r["stress"]["byKind"]["two-syllable"]["matchedUnits"]["count"]
        passed = r["stress"]["stressChecksPassed"]
        lines.append(
            f"|{name}|{clean.get('matched', 0)}/{clean.get('retry', 0)}/"
            f"{clean.get('uncertain', 0)}|{multiple}/72|{'通过' if passed else '失败'}|"
        )
    lines += [
        "",
        "输入压力与旧实验逐个case ID、payload SHA、目标列表完全一致：312病例、384查询，"
        "24清晰控制及72多读波形；"
        "噪声/静音/坏格式等保持完整分母。各类结果和全部失败见JSON，"
        "相关派生波形不当作独立自然错音或最终验收。",
        "",
        "## 数据与剩余门禁",
        "",
        "OMPAL最终10位说话人的494份WAV仍未出现在预期原音目录，未打开最终集。真实声母/韵母错误校准根只有18/16，均只有4位说话人，未达到既定100根/5位说话人的分层门禁；反事实目标配对不能补足真实错音。没有真实儿童验证。",
        "",
        "补充数据调查：[THCHS-30官方页](https://www.openslr.org/18/)标注Apache 2.0，但几个官方镜像实测吞吐很低，本轮只保留未完成的部分下载，未用于训练；[LATIC官方页](https://ieee-dataport.org/open-access/latic-non-native-pre-labelled-mandarin-chinese-validation-corpus-automatic-speech)需要登录，按用户决定暂不使用。不把未取得的数据写成已完成的数据准备。",
        "",
        "本轮不能宣称达到要求。后续需要继续改进泛化，并补足与孤立拼音任务一致、独立核验的真实分量标签和错误样本；不能只调拒判阈值或重复消耗校准集后冒充冻结验收。运行命令见[工具文档](../engineering/pretrained-pronunciation-matcher.md)。",
    ]
    destination = ROOT / "docs/research/sensevoice-iteration-results.json"
    write(destination, report)
    destination.with_suffix(".md").write_text("\n".join(lines) + "\n")
    return {"report": str(destination), "finalAcceptanceEstablished": False}


if __name__ == "__main__":
    print(json.dumps(build()))
