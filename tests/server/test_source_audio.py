import hashlib
import json
import zipfile
from copy import deepcopy

import pytest

from scripts import prepare_pinyin_source
from server import api, source_audio
from server.content import load_curriculum
from server.source_audio import target_signature


def test_pinned_mapping_covers_existing_targets_and_preserves_teaching_boundaries():
    source = source_audio.catalog()
    targets = {
        a["id"]: a for a in load_curriculum()["audioRequirements"] if a["kind"] != "instruction"
    }
    rows = {a["id"]: a for a in source["assets"]}
    assert rows.keys() == targets.keys()
    assert len(rows) == 99
    assert "teachingReview" not in source
    assert source["licenseStatus"] == "unknown"
    for key, target in targets.items():
        assert rows[key]["targetSignature"] == target_signature(target)
    assert rows["audio-rt-02-v1"]["filename"] == "v1.mp3"
    assert rows["audio-rt-04-nv3"]["filename"] == "nv3.mp3"
    assert rows["audio-whole-syllable-ri"]["filename"] == "ri4.mp3"
    assert rows["audio-whole-syllable-zi"]["exampleTone"] == 1
    for base, labels in (("a", "āáǎà"), ("o", "ōóǒò"), ("e", "ēéěè")):
        for tone, label in enumerate(labels, 1):
            question = next(
                q
                for q in load_curriculum()["exercises"]
                if q["type"] == "tone-choice"
                and q.get("audioRef")
                and q["primaryKnowledgeId"] == f"k-tone-{tone}"
                and f"k-final-{base}" in q["knowledgeIds"]
            )
            assert targets[question["audioRef"]]["transcript"] == label
            assert rows[question["audioRef"]]["filename"] == f"{base}{tone}.mp3"


@pytest.fixture
def selected_source(monkeypatch, tmp_path):
    # Synthetic bytes test registration/security only. Product GUI uses actual MP3s.
    source = deepcopy(source_audio.catalog())
    source["assets"] = source["assets"][:1]
    row = source["assets"][0]
    payload = b"synthetic-non-private-asset-for-integrity-tests"
    row.update(sha256=hashlib.sha256(payload).hexdigest(), bytes=len(payload))
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(f"PinYinSound-{source['commit']}/{row['filename']}", payload)
    source["archiveSha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    monkeypatch.setattr(source_audio, "catalog", lambda: source)
    monkeypatch.setattr(prepare_pinyin_source, "check_recording", lambda *_: {"seconds": 1})
    prepare_pinyin_source.prepare(archive, source_audio.SOURCE_DIR)
    target = next(a for a in load_curriculum()["audioRequirements"] if a["id"] == row["id"])
    return source, row, target, archive, payload


def test_selected_source_requires_pairing_then_allows_range_and_real_question(
    selected_source, test_client
):
    source, row, target, _, payload = selected_source
    route = f"/api/v1/audio/{row['id']}"
    assert test_client.get(route).status_code == 401
    code = test_client.post("/api/v1/local/pairing-code").json()["code"]
    test_client.post("/api/v1/pair", json={"code": code, "label": "家庭"})
    response = test_client.get(route)
    assert response.content == payload
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.headers["cache-control"] == "no-store"
    ranged = test_client.get(route, headers={"Range": "bytes=2-7"})
    assert ranged.status_code == 206 and ranged.content == payload[2:8]
    data = test_client.get("/api/v1/curriculum").json()
    asset = next(a for a in data["audioRequirements"] if a["id"] == target["id"])
    assert asset["available"] is True
    assert "reviewStatus" not in asset
    assert asset["standardSource"]["title"] == "cmguo/PinYinSound"
    assert "teachingReview" not in asset["standardSource"]
    session = test_client.post(
        "/api/v1/sessions", json={}, headers={"X-LP-CSRF": test_client.cookies.get("lp_csrf")}
    ).json()
    assert any(task["exercise"].get("audioRef") == row["id"] for task in session["tasks"])
    assert "draftContent" not in session
    assert source["repository"] not in response.headers


@pytest.mark.parametrize("change", ["corrupt", "disabled", "version", "target", "escape"])
def test_invalid_source_fails_closed_per_asset(selected_source, paired_client, tmp_path, change):
    _, row, target, _, payload = selected_source
    path = source_audio.SOURCE_DIR / "clips" / f"{row['sha256']}.mp3"
    state_path = source_audio.SOURCE_DIR / "installation.json"
    state = json.loads(state_path.read_text())
    assert source_audio.available(target)
    if change == "corrupt":
        path.write_bytes(b"changed")
    elif change == "disabled":
        state["enabled"] = False
        state_path.write_text(json.dumps(state))
    elif change == "version":
        state["commit"] = "other-version"
        state_path.write_text(json.dumps(state))
    elif change == "target":
        row["targetSignature"] = "stale"
    else:
        outside = tmp_path / "outside.mp3"
        outside.write_bytes(payload)
        path.unlink()
        path.symlink_to(outside)
    assert not source_audio.available(target)
    assert paired_client.get(f"/api/v1/audio/{row['id']}").status_code == 404
    assert row["id"] not in api._available_standard_audio(load_curriculum())


@pytest.mark.parametrize("change", ["archive", "mapping", "decode"])
def test_failed_preparation_preserves_previous_installation(selected_source, monkeypatch, change):
    _, row, _, archive, _ = selected_source
    state_path = source_audio.SOURCE_DIR / "installation.json"
    previous = state_path.read_bytes()
    if change == "archive":
        archive.write_bytes(b"wrong version")
    elif change == "mapping":
        row["targetSignature"] = "changed"
    else:

        def fail(*_):
            raise ValueError("decode failed")

        monkeypatch.setattr(prepare_pinyin_source, "check_recording", fail)
    with pytest.raises(ValueError):
        prepare_pinyin_source.prepare(archive, source_audio.SOURCE_DIR)
    assert state_path.read_bytes() == previous


def test_legacy_approval_cannot_enable_uninstalled_source(
    selected_source, paired_client, monkeypatch
):
    _, _, target, _, _ = selected_source
    legacy = {
        **target,
        "file": "/audio/sample.wav",
        "status": "approved",
        "reviewStatus": "approved",
        "rightsEvidence": "old",
        "reviewEvidence": "old",
    }
    monkeypatch.setattr(api, "load_curriculum", lambda: {"audioRequirements": [legacy]})
    (source_audio.SOURCE_DIR / "installation.json").write_text('{"enabled":false}')
    assert paired_client.get(f"/api/v1/audio/{target['id']}").status_code == 404
