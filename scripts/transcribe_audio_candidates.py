"""Transcribe locally held candidate clips as unreviewed drafts (not scores)."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from .asr_model import (
    MODEL_LICENSE,
    MODEL_REVISION,
    MODEL_SHA256,
    sha256_file,
    validate_model,
)

FIELDS = [
    "candidate_id",
    "source_file",
    "source_start_seconds",
    "source_end_seconds",
    "clip_file",
    "clip_sha256",
    "transcript_draft",
    "segments_relative_seconds",
    "model_repo",
    "model_revision",
    "model_sha256",
    "model_license",
    "transcriber",
    "status",
]


def checked_clip(root: Path, relative: str, expected_sha256: str) -> Path:
    base = root.resolve()
    path = (base / relative).resolve()
    if not path.is_relative_to(base) or not path.is_file():
        raise ValueError(f"候选音频路径无效或越界: {relative}")
    if sha256_file(path) != expected_sha256:
        raise ValueError(f"候选片段摘要不符: {relative}")
    return path


def transcribe(index: Path, model_path: Path, output: Path, limit: int | None) -> int:
    validate_model(model_path)
    from pywhispercpp.model import Model

    model = Model(
        str(model_path.resolve()), language="zh", print_realtime=False, print_progress=False
    )
    with index.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        required = {
            "candidate_id",
            "source_file",
            "start_seconds",
            "end_seconds",
            "clip_file",
            "clip_sha256",
        }
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("candidate-index.csv 缺少必需列")
        output.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with output.open("w", encoding="utf-8-sig", newline="") as destination:
            writer = csv.DictWriter(destination, fieldnames=FIELDS)
            writer.writeheader()
            for row in reader:
                if limit is not None and count >= limit:
                    break
                clip = checked_clip(index.parent, row["clip_file"], row["clip_sha256"])
                segments = model.transcribe(str(clip), n_processors=1)
                text = "".join(str(segment.text) for segment in segments).strip()
                times = [
                    {
                        "start": round(float(segment.t0) / 100, 2),
                        "end": round(float(segment.t1) / 100, 2),
                        "text": str(segment.text).strip(),
                    }
                    for segment in segments
                ]
                writer.writerow(
                    {
                        "candidate_id": row["candidate_id"],
                        "source_file": row["source_file"],
                        "source_start_seconds": row["start_seconds"],
                        "source_end_seconds": row["end_seconds"],
                        "clip_file": row["clip_file"],
                        "clip_sha256": row["clip_sha256"],
                        "transcript_draft": text,
                        "segments_relative_seconds": json.dumps(times, ensure_ascii=False),
                        "model_repo": "ggerganov/whisper.cpp",
                        "model_revision": MODEL_REVISION,
                        "model_sha256": MODEL_SHA256,
                        "model_license": MODEL_LICENSE,
                        "transcriber": "pywhispercpp==1.5.1 / whisper.cpp",
                        "status": "needs_human_listening; not_a_pronunciation_score",
                    }
                )
                count += 1
                print(f"{count}: {row['candidate_id']} -> {text or '[空转写]'}", flush=True)
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True, help="候选目录内 candidate-index.csv")
    parser.add_argument(
        "--model", type=Path, required=True, help="已安装且校验的本地 ggml-small.bin"
    )
    parser.add_argument("--output", type=Path, required=True, help="仓库外的转写草稿 CSV")
    parser.add_argument("--limit", type=int, help="可选的最大候选数，便于小批试跑")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit 必须为正整数")
    count = transcribe(args.index, args.model, args.output, args.limit)
    print(f"完成 {count} 段；转写草稿必须人工听审。")


if __name__ == "__main__":
    main()
