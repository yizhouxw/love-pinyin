"""Offline generation in separately locked Qwen/Cosy environments. Explicit local paths."""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

from pinyin_matcher.audio import SAMPLE_RATE, encode_wav, quality_check, trim_silence
from pinyin_matcher.catalog import ROOT, fingerprint, load_catalog, targets_by_id


def atomic_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def engine_qwen(model_dir: Path):
    import mlx.core as mx
    from mlx_audio.tts.utils import load_model

    model = load_model(model_dir)

    def synthesize(text: str, persona: dict, seed: int, reference: Path | None = None):
        mx.random.seed(seed)
        chunks = list(
            model.generate_voice_design(
                text=text,
                language="Chinese",
                instruct=persona["instruction"],
                max_tokens=256,
                temperature=0.7,
                top_k=50,
                top_p=0.95,
            )
        )
        if not chunks or sum(chunk.token_count for chunk in chunks) >= 256:
            raise ValueError("TTS_TRUNCATED")
        samples = np.concatenate([np.asarray(chunk.audio) for chunk in chunks])
        rate = chunks[0].sample_rate
        mx.clear_cache()
        return samples, rate

    return synthesize


def engine_cosy(model_dir: Path, source: Path, threads: int, device: str):
    import torch

    torch.set_num_threads(threads)
    source_lock = json.loads((ROOT / "content/pronunciation-models.json").read_text())["cosySource"]
    actual = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    if actual != source_lock["commit"]:
        raise ValueError("GENERATOR_SOURCE_VERSION_MISMATCH")
    subprocess.run(["git", "-C", str(source), "diff", "--quiet", "HEAD"], check=True)
    sys.path[:0] = [str(source), str(source / "third_party/Matcha-TTS")]
    import yaml
    from cosyvoice.cli.cosyvoice import CosyVoice3
    from cosyvoice.cli.frontend import CosyVoiceFrontEnd
    from cosyvoice.cli.model import CosyVoice3Model
    from hyperpyyaml import load_hyperpyyaml

    class InferenceOnlyCosyVoice(CosyVoice3):
        def __init__(self):
            # The upstream YAML also instantiates training discriminators and
            # dataset processors. Select inference nodes before resolving tags;
            # no vendor source is patched and unused training dependencies never run.
            document = yaml.compose((model_dir / "cosyvoice3.yaml").read_text())
            keys = {
                "sample_rate",
                "llm_input_size",
                "llm_output_size",
                "spk_embed_dim",
                "qwen_pretrain_path",
                "token_frame_rate",
                "token_mel_ratio",
                "chunk_size",
                "num_decoding_left_chunks",
                "llm",
                "flow",
                "hift",
                "get_tokenizer",
                "feat_extractor",
                "allowed_special",
            }
            document.value = [
                (key, value)
                for key, value in document.value
                if key.value in keys or key.value.startswith("__set_seed")
            ]
            configs = load_hyperpyyaml(
                yaml.serialize(document),
                overrides={"qwen_pretrain_path": str(model_dir / "CosyVoice-BlankEN")},
            )
            self.model_dir, self.fp16 = str(model_dir), False
            self.frontend = CosyVoiceFrontEnd(
                configs["get_tokenizer"],
                configs["feat_extractor"],
                str(model_dir / "campplus.onnx"),
                str(model_dir / "speech_tokenizer_v3.onnx"),
                allowed_special=configs["allowed_special"],
            )
            self.sample_rate = configs["sample_rate"]
            self.model = CosyVoice3Model(configs["llm"], configs["flow"], configs["hift"], False)
            self.model.load(
                str(model_dir / "llm.pt"), str(model_dir / "flow.pt"), str(model_dir / "hift.pt")
            )

    model = InferenceOnlyCosyVoice()
    if device == "mps":
        if not torch.backends.mps.is_available():
            raise ValueError("MPS_GENERATION_UNAVAILABLE")
        model.model.device = torch.device("mps")
        for module in (model.model.llm, model.model.flow):
            module.float().to("mps")
        original_vocoder = model.model.hift

        class CPUVocoder:
            def inference(self, speech_feat, **kwargs):
                # Upstream HiFT intentionally computes F0 in float64. Retain
                # that exact CPU path instead of changing its numerical behavior.
                return original_vocoder.inference(speech_feat.cpu(), **kwargs)

        model.model.hift = CPUVocoder()

    def synthesize(text: str, persona: dict, seed: int, reference: Path | None = None):
        torch.manual_seed(seed)
        if reference is None or not reference.is_file():
            raise ValueError("SYNTHETIC_REFERENCE_REQUIRED")
        # Cache the generated reference's conditioning; no real person is cloned.
        if persona["id"] not in model.frontend.spk2info:
            model.add_zero_shot_spk(
                "You are a helpful assistant.<|endofprompt|>" + persona["referenceText"],
                str(reference),
                persona["id"],
            )
        try:
            chunks = list(
                model.inference_zero_shot(
                    text, "", "", zero_shot_spk_id=persona["id"], stream=False, text_frontend=False
                )
            )
        finally:
            # Extremely short TTS outputs can fail before upstream cleanup.
            # Requests here are serial; retained speaker conditioning is separate.
            for name in ("tts_speech_token_dict", "llm_end_dict", "hift_cache_dict"):
                getattr(model.model, name).clear()
        samples = np.concatenate(
            [chunk["tts_speech"].cpu().numpy().reshape(-1) for chunk in chunks]
        )
        return samples, model.sample_rate

    return synthesize


def generate(args):
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    model_dir = args.model.resolve(strict=True)
    config = json.loads((ROOT / "content/pronunciation-training.json").read_text())
    personas = (
        json.loads((ROOT / "content/pronunciation-challenges.json").read_text())["personas"]
        if args.voice_set == "challenge"
        else config["personas"]
    )
    catalog = load_catalog()
    targets = targets_by_id(catalog)
    selected = args.targets or (list(targets) if args.all_targets else catalog["pilotIds"])
    if any(key not in targets or not targets[key].get("ttsText") for key in selected):
        raise ValueError("EXPLICIT_TTS_TEXT_REQUIRED_FOR_EVERY_SELECTED_TARGET")
    suffix = f"-shard{args.shard}" if args.shards > 1 else ""
    output = args.output.resolve() / (args.engine + suffix)
    output.mkdir(parents=True, exist_ok=True)
    manifest = output / "manifest.json"
    data = (
        json.loads(manifest.read_text())
        if manifest.exists()
        else {
            "version": 1,
            "cohort": "synthetic",
            "labelProvenance": "tts-intended-not-human-adjudicated",
            "items": [],
            "rejected": [],
        }
    )
    seen = {
        row["id"]
        for group in (data["items"], data["rejected"], data.get("quarantined", []))
        for row in group
    }
    installation_file = model_dir / "installation.json"
    if not installation_file.exists():
        installation_file = ROOT / f"private/matcher-{args.engine}-install.json"
    install = json.loads(installation_file.read_text())
    expected_install = json.loads((ROOT / "content/pronunciation-models.json").read_text())[
        "generators"
    ][args.engine]
    if install != expected_install:
        raise ValueError("TTS_INSTALLATION_VERSION_MISMATCH")
    for file in install["files"]:
        resource = (model_dir / file["path"]).resolve()
        if (
            not resource.is_relative_to(model_dir)
            or resource.stat().st_size != file["bytes"]
            or fingerprint(resource) != file["sha256"]
        ):
            raise ValueError("TTS_MODEL_DIGEST_MISMATCH")
    synthesize = (
        engine_qwen(model_dir)
        if args.engine == "qwen"
        else engine_cosy(model_dir, args.source.resolve(strict=True), args.threads, args.tts_device)
    )
    references = args.output.resolve() / "references"
    references.mkdir(exist_ok=True)
    generated = 0
    for persona_index, persona in enumerate(personas[: args.personas]):
        if persona_index < args.persona_start:
            continue
        if persona_index % args.shards != args.shard:
            continue
        reference = references / (persona["id"] + ".wav")
        if args.engine == "cosy" and not reference.exists() and args.wait_reference_seconds:
            deadline = time.monotonic() + args.wait_reference_seconds
            while not reference.exists() and time.monotonic() < deadline:
                time.sleep(1)
            if not reference.exists():
                raise ValueError("SYNTHETIC_REFERENCE_WAIT_TIMEOUT")
        if args.engine == "qwen" and not reference.exists():
            samples, rate = synthesize(
                persona["referenceText"], persona, config["seed"] + int(persona["id"][-2:])
            )
            samples = resample_poly(samples, SAMPLE_RATE, rate).astype(np.float32)
            reference.write_bytes(encode_wav(samples))
            print(
                json.dumps({"reference": persona["id"], "seconds": len(samples) / SAMPLE_RATE}),
                flush=True,
            )
        for key in selected:
            target = targets[key]
            for repeat in range(args.repetitions):
                item_id = f"{args.engine}-{persona['id']}-{key}-{repeat}"
                if item_id in seen:
                    continue
                seed = config["seed"] + int.from_bytes(item_id.encode(), "little") % 1_000_000
                started = time.monotonic()
                text = target["ttsText"] + "。"
                try:
                    samples, rate = synthesize(text, persona, seed, reference)
                    samples = trim_silence(
                        resample_poly(samples, SAMPLE_RATE, rate).astype(np.float32)
                    )
                    info = quality_check(samples)
                    filename = item_id + ".wav"
                    path = output / filename
                    path.write_bytes(encode_wav(samples))
                    row = {
                        "id": item_id,
                        "targetId": key,
                        "voiceFamilyId": persona["id"],
                        "referenceRootId": persona["id"] + "-reference",
                        "generator": args.engine,
                        "generatorRevision": install["revision"],
                        "generationDevice": "metal-mlx"
                        if args.engine == "qwen"
                        else ("mps+cpu-vocoder" if args.tts_device == "mps" else "cpu"),
                        "modelSha256": next(
                            f["sha256"]
                            for f in install["files"]
                            if f["path"] in {"model.safetensors", "llm.pt"}
                        ),
                        "split": persona["split"],
                        "text": text,
                        "seed": seed,
                        "file": filename,
                        "sha256": fingerprint(path),
                        "labelProvenance": "tts-intended",
                        "durationSeconds": info["durationSeconds"],
                    }
                    data["items"].append(row)
                    seen.add(item_id)
                    print(
                        json.dumps(
                            {
                                "generated": item_id,
                                "duration": info["durationSeconds"],
                                "elapsed": round(time.monotonic() - started, 2),
                            }
                        ),
                        flush=True,
                    )
                except (ValueError, RuntimeError) as error:
                    data["rejected"].append({"id": item_id, "reason": str(error)})
                    print(json.dumps({"rejected": item_id, "reason": str(error)}), flush=True)
                atomic_json(manifest, data)
                generated += 1
                if args.limit and generated >= args.limit:
                    return


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=["qwen", "cosy"], required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=ROOT / "private/matcher-cosy-source")
    parser.add_argument("--output", type=Path, default=ROOT / "private/matcher-data")
    parser.add_argument("--personas", type=int, default=24)
    parser.add_argument("--voice-set", choices=["training", "challenge"], default="training")
    parser.add_argument("--persona-start", type=int, default=0)
    parser.add_argument("--wait-reference-seconds", type=int, default=0)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--tts-device", choices=["cpu", "mps"], default="cpu")
    parser.add_argument("--limit", type=int)
    target_selection = parser.add_mutually_exclusive_group()
    target_selection.add_argument("--all-targets", action="store_true")
    target_selection.add_argument("--targets", nargs="+")
    parser.add_argument("--shards", type=int, default=1)
    parser.add_argument("--shard", type=int, default=0)
    args = parser.parse_args()
    if not 1 <= args.shards <= 4 or not 0 <= args.shard < args.shards:
        parser.error("shard must be within 0..shards-1, with at most four workers")
    if (
        not 1 <= args.personas <= 24
        or not 0 <= args.persona_start < args.personas
        or not 1 <= args.repetitions <= 20
    ):
        parser.error("personas must be 1..24, persona-start inside that range, repetitions 1..20")
    generate(args)


if __name__ == "__main__":
    main()
