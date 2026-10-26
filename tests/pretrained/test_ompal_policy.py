from pinyin_matcher.pretrained_ompal_policy import annotate_prompt


def annotate(text):
    return annotate_prompt(text, [{"text": [c]} for c in text])


def test_context_polyphones_are_explicit_not_traditional_g2p_defaults():
    text = "先得把屋子打掃得乾乾淨淨"
    rows = annotate(text)
    assert [r["expectedPinyin"] for r in rows if r["text"] == "得"] == ["dei3", "de5"]
    assert [r["expectedPinyin"] for r in rows if r["text"] == "乾"] == ["gan1", "gan1"]
    assert (
        next(r for r in annotate("我趕快找到一個空座位坐好") if r["text"] == "空")["expectedPinyin"]
        == "kong4"
    )
    rows = annotate("只是看著我笑")
    assert rows[3]["expectedPinyin"] == "zhe5"
    assert rows[3]["labelPolicyFlags"]


def test_third_tone_neutral_and_yibu_remain_flagged_alignment_anchors():
    rows = annotate("所以起晚了")
    for row in rows[:4]:
        assert "THIRD_TONE_SANDHI_OR_PROSODIC_BOUNDARY" in row["labelPolicyFlags"]
        assert row["tone"] == 3
    assert rows[4]["expectedPinyin"] == "le5"
    assert "NEUTRAL_TONE_OUTSIDE_FOUR_TONE_SCOPE" in rows[4]["labelPolicyFlags"]
    rows = annotate("我家還有一隻小黑狗")
    assert rows[4]["expectedPinyin"] == "yi1"
    assert "YI_BU_SURFACE_TONE_CONTEXT" in rows[4]["labelPolicyFlags"]


def test_text_alternatives_are_one_word_not_concatenated_syllables():
    text = "孩子們還可以從大人那裡得到裝著錢的小紅包"
    words = [{"text": [c]} for c in text]
    words[3]["text"] = ["還", "也"]
    rows = annotate_prompt(text, words)
    assert len(rows) == len(words)
    assert rows[3]["expectedPinyin"] == "hai2"
    assert rows[3]["alignmentPinyin"] == ["hai2"]
    assert rows[3]["textAlternatives"] == ["還", "也"]
    assert "WORD_TEXT_ALTERNATIVES" in rows[3]["labelPolicyFlags"]


def test_unreviewed_or_mismatched_prompt_cannot_supply_unflagged_truth():
    rows = annotate("你好")
    assert all("PROMPT_NOT_CONTEXT_REVIEWED" in r["labelPolicyFlags"] for r in rows)
    rows = annotate_prompt("他們都很忙", [{"text": [c]} for c in "他們也很忙"])
    assert all("PROMPT_WORD_TEXT_MISMATCH" in r["labelPolicyFlags"] for r in rows)
    assert all(not r["pinyinProvenance"]["contextReviewed"] for r in rows)


def test_phonetic_decomposition_matches_teaching_zero_onset_and_umlaut():
    rows = annotate("他的女朋友很漂亮是日本人")
    female = next(r for r in rows if r["text"] == "女")
    assert female["onset"] == "n"
    assert female["rime"] == "ü"
    rows = annotate("還有一個非常好看的小花園")
    you = next(r for r in rows if r["text"] == "有")
    assert you["onset"] == ""
    assert you["rime"] == "iou"
    assert all(not r["pinyinProvenance"]["realizedPhoneticTranscription"] for r in rows)


def test_expert_scores_never_change_expected_reading():
    text = "他們都很忙"
    words = [{"text": [c], "tone": ["0", "0", "0"]} for c in text]
    assert annotate_prompt(text, words) == annotate(text)
