import hashlib
import io
import json

import pytest

from pinyin_matcher.pretrained_aishell3 import (
    PARSER_VERSION,
    fetch_verified,
    parse_content,
    prepare,
    resource_path,
    verify_pinyin,
)


def test_download_verifies_size_sha_and_existing_corruption(tmp_path):
    payload = b"a licensed test asset"
    record = {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}
    path = tmp_path / "asset"
    calls = []

    def opener(request, **kwargs):
        calls.append(request.full_url)
        return io.BytesIO(payload)

    assert (
        fetch_verified("https://example.invalid/pinned", record, path, opener=opener)["status"]
        == "downloaded-verified"
    )
    assert path.read_bytes() == payload
    assert (
        fetch_verified("https://example.invalid/pinned", record, path, opener=opener)["status"]
        == "verified-existing"
    )
    assert len(calls) == 1
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="EXISTING_RESOURCE_CORRUPT"):
        fetch_verified("https://example.invalid/pinned", record, path, opener=opener)
    assert path.read_bytes() == b"corrupt"


def test_missing_truncated_or_wrong_response_never_installs_asset(tmp_path):
    record = {"sha256": hashlib.sha256(b"right").hexdigest(), "bytes": 5}
    path = tmp_path / "asset"
    for payload in (b"bad", b"wrong", b"too-long"):
        with pytest.raises(ValueError, match="RESOURCE_(DIGEST_MISMATCH|TOO_LARGE)"):
            fetch_verified(
                "https://example.invalid/pinned",
                record,
                path,
                opener=lambda *a, payload=payload, **k: io.BytesIO(payload),
            )
        assert not path.exists()

    def missing(*args, **kwargs):
        raise FileNotFoundError("missing remote object")

    with pytest.raises(FileNotFoundError):
        fetch_verified("https://example.invalid/pinned", record, path, opener=missing)
    assert not path.exists()


def test_realized_pinyin_preserves_sandhi_neutral_and_rejects_relabeling():
    line = "SSB00010001.wav\t一 yi2 个 ge4 的 de5"
    source = parse_content(line)
    record = {
        "path": "train/wav/SSB0001/SSB00010001.wav",
        "pinyin": ["yi2", "ge4", "de5"],
        "pinyinSourceLineSha256": hashlib.sha256(line.encode()).hexdigest(),
    }
    verify_pinyin(record, source)
    record["pinyin"][0] = "yi1"
    with pytest.raises(ValueError, match="SOURCE_MISMATCH"):
        verify_pinyin(record, source)
    with pytest.raises(ValueError, match="SOURCE_MISSING"):
        verify_pinyin(record, {})
    with pytest.raises(ValueError, match="SOURCE_INVALID"):
        parse_content(line + "\n" + line)


def test_policy_blocks_test_data_before_network_or_output(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "revision": "a" * 40,
                "parserVersion": PARSER_VERSION,
                "selection": {"calibrationOrFinalTestUsed": False},
                "files": [
                    {"id": "test", "split": "test", "sourceSplit": "test", "path": "test/x.wav"}
                ],
            }
        )
    )
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="TRAINING_ONLY_POLICY_VIOLATION"):
        prepare(output, config_path=path)
    assert not output.exists()
    with pytest.raises(ValueError, match="PATH_INVALID"):
        resource_path(output, "../../outside")
