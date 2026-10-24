import json

from server import daily_reading, learning_audio


def test_all_21_sentences_have_complete_registered_speech_with_matching_text():
    sentences = daily_reading.sentence_readings()
    items = [
        i
        for d in daily_reading.load()["days"]
        for s in d["sections"]
        if s["kind"] == "sentences"
        for i in s["items"]
    ]
    assert len(sentences) == len(items) == 21
    assert set(sentences) == {i["id"] for i in items}
    hanzi = json.loads((daily_reading.CONTENT.parent / "daily-reading-hanzi.json").read_text())
    scripts = learning_audio.narration_scripts()
    for item in items:
        sentence = sentences[item["id"]]
        assert sentence["spokenText"] == hanzi[item["id"]]
        assert scripts[sentence["narrationId"]] == sentence["spokenText"]


def test_missing_sentence_sound_is_unavailable_not_a_synthetic_standard_fallback(
    paired_client, monkeypatch, tmp_path
):
    monkeypatch.setattr(learning_audio, "LEARNING_AUDIO_DIR", tmp_path)
    response = paired_client.get("/api/v1/guest/daily-reading").json()
    sentences = [
        i
        for d in response["days"]
        for s in d["sections"]
        if s["kind"] == "sentences"
        for i in s["items"]
    ]
    assert all(i["sentenceReading"]["available"] is False for i in sentences)
    assert all(i["sentenceReading"]["timings"] == [] for i in sentences)
