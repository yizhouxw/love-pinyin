"""Bind a locally trained Chinese encoder to its immutable source and result."""

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from pinyin_matcher.catalog import ROOT, fingerprint
from pinyin_matcher.pretrained_prepare import REGISTRY, verify

NAME = "chinese-xlsr-tail-v1"


def register(checkpoint: Path, source: Path, output: Path):
    if output.exists():
        raise ValueError("CHINESE_TAIL_DESTINATION_EXISTS")
    registry = json.loads(REGISTRY.read_text())
    existing = registry["models"].get(NAME)
    parent = verify("chinese-xlsr-asr", source)
    report = json.loads((checkpoint / "training.json").read_text())
    if (
        report["sourceModel"] != "chinese-xlsr-asr"
        or report["finalTestUsed"] is not False
        or report["epochs"] != 4
        or report["trainingRoots"] != 1200
        or report["configurationSha256"]
        != fingerprint(ROOT / "content/pronunciation-pretrained-xlsr-tail.json")
        or report["modelSha256"] != fingerprint(checkpoint / "model.safetensors")
        or not report["changedParameterNames"]
        or any(not x.startswith("encoder.layers.23.") for x in report["changedParameterNames"])
    ):
        raise ValueError("CHINESE_TAIL_CHECKPOINT_INVALID")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="chinese-tail-", dir=output.parent) as temp:
        stage = Path(temp) / NAME
        stage.mkdir()
        for filename in ("config.json", "preprocessor_config.json", "README.md"):
            shutil.copy2(source / filename, stage / filename)
        shutil.copy2(checkpoint / "model.safetensors", stage / "model.safetensors")
        shutil.copy2(checkpoint / "training.json", stage / "training.json")
        files = []
        for path in sorted(stage.iterdir()):
            files.append(
                {"path": path.name, "sha256": fingerprint(path), "sizeBytes": path.stat().st_size}
            )
        record = {
            **{
                k: parent[k]
                for k in (
                    "repository",
                    "revision",
                    "lastModified",
                    "license",
                    "licenseEvidence",
                    "source",
                )
            },
            "trainingData": parent["trainingData"] + " OMPAL CC BY 4.0 expert training components; "
            "last-layer fine-tune; see training.json.",
            "outputs": parent["outputs"],
            "runtime": "Locally trained derivative; pinned source and checkpoint; no downloads.",
            "parentWeightSha256": next(
                x["sha256"] for x in parent["files"] if x["path"] == "pytorch_model.bin"
            ),
            "trainingReportSha256": fingerprint(stage / "training.json"),
            "configurationSha256": report["configurationSha256"],
            "sourceCodeSha256": report["codeSha256"],
            "localDerivative": True,
            "files": files,
        }
        if existing is not None and existing != record:
            raise ValueError("CHINESE_TAIL_REGISTRY_ALREADY_BOUND_TO_OTHER_CHECKPOINT")
        registry["models"][NAME] = record
        stage.rename(output)
        REGISTRY.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n")
    return {
        "model": NAME,
        "directory": str(output.resolve()),
        "weightSha256": report["modelSha256"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(register(args.checkpoint, args.source, args.output)))


if __name__ == "__main__":
    main()
