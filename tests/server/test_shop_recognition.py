import io
import wave

import pytest

from server import qwen_recognition, reading_recognition, shop_recognition
from server.storage import connect


def test_shop_tolerance_is_symmetric_and_game_only(monkeypatch):
    def check(target, text):
        monkeypatch.setattr(qwen_recognition, "transcribe", lambda *_a, **_k: {"transcript": text})
        return shop_recognition.evaluate({"pinyin": target}, b"")["status"]

    for target, text in [
        ("xīng", "心"),
        ("xīn", "星"),
        ("zhū", "租"),
        ("zū", "猪"),
        ("zhǎng", "赞"),
    ]:
        assert check(target, text) == "matched"
    for target, text in [("bā", "趴"), ("zhū", "猪猪"), ("sī", "私下")]:
        assert check(target, text) == "uncertain"
    assert (
        reading_recognition.match_transcript({"syllables": ["xīng"]}, "心")["status"] == "different"
    )


@pytest.mark.parametrize(
    ("target", "transcript", "expected"),
    [
        ("v1-star", "心", "matched"),
        ("shop-sentence-tea", "爸爸喝茶。", "matched"),
        ("shop-sentence-tea", "爸爸喝", "uncertain"),
        ("shop-sentence-tea", "爸爸喝茶茶", "uncertain"),
        ("shop-sentence-tea", "爸爸茶喝", "uncertain"),
    ],
)
def test_shop_assessment_is_ephemeral_and_uses_pinned_target(
    paired_client, monkeypatch, target, transcript, expected
):
    monkeypatch.setattr(
        qwen_recognition, "transcribe", lambda *_a, **_k: {"transcript": transcript}
    )
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setparams((1, 2, 16_000, 0, "NONE", ""))
        wav.writeframes(b"\0\0" * 12_000)
    response = paired_client.post(
        f"/api/v1/pronunciation/{target}/assess",
        content=output.getvalue(),
        headers={
            "Content-Type": "audio/wav",
            "X-LP-Request-Id": "shop-test-request",
            "X-LP-CSRF": paired_client.cookies["lp_csrf"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["match"]["status"] == expected
    assert body["match"]["toneAssessed"] is False
    assert body["saved"] is False
    with connect() as db:
        assert db.execute("SELECT COUNT(*) FROM pronunciation_attempts").fetchone()[0] == 0
