from pathlib import Path

import pytest

from pinyin_matcher.pretrained_metrics import freeze, metrics, wilson


def row(root, label, status, **extra):
    return {
        "root_id": root,
        "speaker_id": "s1",
        "source": "test",
        "label": label,
        "status": status,
        **extra,
    }


def test_negative_target_pairs_cannot_dilute_any_accept_failure():
    records = [
        row("same", "negative", "retry", target_id=f"t{i}", error_type="tone") for i in range(99)
    ]
    records.append(row("same", "negative", "matched", error_type="tone"))
    result = metrics(records)
    assert result["negative"]["n"] == 1
    assert result["negative"]["comparisons"] == 100
    assert result["negative"]["falseAccept"]["rate"] == 1
    assert result["negativeStrata"]["tone"]["falseAccept"]["count"] == 1
    assert not result["gates"]["passesPointEstimates"]


def test_status_denominators_include_abstention_missing_and_ambiguous():
    result = metrics(
        [
            row("p1", "positive", "matched"),
            row("p2", "positive", "retry"),
            row("p3", "positive", "uncertain"),
            row("p4", "positive", "unavailable"),
            row("p5", "positive", "broken"),
            row("a1", "ambiguous", "matched"),
            row("n1", "negative", "unavailable"),
        ]
    )
    assert result["positive"]["n"] == 5
    assert result["positive"]["accepted"]["count"] == 1
    assert result["positive"]["explicitReject"]["count"] == 1
    assert result["positive"]["abstention"]["count"] == 3
    assert result["ambiguous"]["roots"] == 1
    assert not result["ambiguous"]["qualityVerifiable"]
    assert result["negative"]["abstention"]["rate"] == 1


def test_repeated_positive_variants_do_not_expand_n_or_hide_rejection():
    result = metrics([row("p", "positive", "matched"), row("p", "positive", "retry")])
    assert result["positive"]["n"] == 1
    assert result["positive"]["explicitReject"]["count"] == 1


def test_all_negative_strata_are_gated_not_diluted_by_easy_cases():
    records = [row(f"n{i}", "negative", "retry", error_type="initial") for i in range(100)]
    records.append(row("bad-tone", "negative", "matched", error_type="tone"))
    result = metrics(records)
    assert result["negative"]["falseAccept"]["rate"] < 0.05
    assert not next(
        c for c in result["gates"]["checks"] if c["name"] == "nearNeighborFalseAccept:tone"
    )["passesPointEstimate"]


def test_any_component_counterfactual_union_cannot_be_diluted_by_expert_roots():
    records = [row(f"p{i}", "positive", "matched", speaker_id=f"s{i % 5}") for i in range(100)]
    for i in range(100):
        for index, component in enumerate(("onset", "rime", "tone")):
            records.append(
                row(
                    f"cf{i}",
                    "negative",
                    "matched" if i in {2 * index, 2 * index + 1} else "retry",
                    error_type=component,
                    negative_origin="counterfactual",
                    speaker_id=f"s{i % 5}",
                )
            )
    records += [
        row(f"expert{i}", "negative", "retry", error_type="expert-onset", speaker_id=f"s{i % 5}")
        for i in range(900)
    ]
    report = metrics(records)
    assert report["negative"]["falseAccept"]["rate"] == 0.006
    assert all(
        report["negativeStrata"][key]["falseAccept"]["rate"] <= 0.02
        for key in ("onset", "rime", "tone")
    )
    counterfactual = report["negativeOriginStrata"]["counterfactual"]
    assert counterfactual["n"] == 100
    assert counterfactual["comparisons"] == 300
    assert counterfactual["falseAccept"]["rate"] == 0.06
    assert not next(
        c
        for c in report["gates"]["checks"]
        if c["name"] == "nearNeighborFalseAccept:origin:counterfactual"
    )["passesPointEstimate"]
    assert not report["gates"]["descriptiveGatePassed"]


def test_exact_quality_boundaries_and_independence_audit():
    records = []
    for i in range(100):
        speaker = f"speaker{i % 5}"
        pstatus = "retry" if i < 10 else "uncertain" if i < 30 else "matched"
        records.append(row(f"p{i}", "positive", pstatus, speaker_id=speaker))
        records.append(
            row(
                f"n{i}",
                "negative",
                "matched" if i < 5 else "retry",
                speaker_id=speaker,
                error_type="tone",
            )
        )
    result = metrics(records)
    assert result["gates"]["descriptiveGatePassed"]
    assert not result["gates"]["populationOrChildValidationPassed"]
    assert result["negative"]["falseAccept"]["high"] > 0.05
    assert result["positive"]["accepted"]["speakerCluster95"]["low"] is not None
    result = metrics([row("p", "positive", "matched"), row("n", "negative", "retry")])
    assert result["gates"]["passesPointEstimates"]
    assert not result["gates"]["sampleSizeAdequate"]


def test_clear_abstention_uses_all_clear_correct_inputs_only():
    result = metrics(
        [
            row("p1", "positive", "uncertain", clear=False),
            row("p2", "positive", "matched", clear=True),
        ]
    )
    assert result["positive"]["abstention"]["rate"] == 0.5
    assert result["clearPositive"]["abstention"]["rate"] == 0


def test_wilson_empty_and_zero_events_are_not_perfect_certainty():
    assert wilson(0, 0)["rate"] is None
    assert wilson(0, 100)["high"] > 0
    with pytest.raises(ValueError):
        wilson(2, 1)


@pytest.mark.parametrize("identity", ["speaker_id", "voice_family", "reference_id", "source_sha"])
def test_freeze_rejects_every_shared_lineage_across_splits(identity):
    records = [
        row("train", "positive", "matched", split="train", speaker_id="s1"),
        row("test", "positive", "matched", split="test", speaker_id="s2"),
    ]
    for record in records:
        record[identity] = "shared"
    with pytest.raises(ValueError, match="Cross-split"):
        freeze(records)


def test_freeze_is_order_independent_and_binds_files_config_and_models(tmp_path: Path):
    records = [
        row("train", "positive", "matched", split="train", speaker_id="s1"),
        row("test", "positive", "matched", split="test", speaker_id="s2"),
    ]
    code = tmp_path / "code.py"
    model = tmp_path / "model.bin"
    code.write_text("code")
    model.write_bytes(b"model")
    a = freeze(records, code_files=[code], model_files=[model], config={"seed": 18})
    b = freeze(reversed(records), code_files=[code], model_files=[model], config={"seed": 18})
    assert a == b
    model.write_bytes(b"changed")
    assert (
        freeze(records, code_files=[code], model_files=[model], config={"seed": 18})["planSha256"]
        != a["planSha256"]
    )
    assert (
        freeze(records, code_files=[code], model_files=[model], config={"seed": 19})["planSha256"]
        != a["planSha256"]
    )


def test_freeze_requires_explicit_split_and_independence_identity():
    with pytest.raises(ValueError, match="split"):
        freeze([row("p", "positive", "matched")])
    with pytest.raises(ValueError, match="speaker"):
        freeze([{"root_id": "p", "split": "test"}])
