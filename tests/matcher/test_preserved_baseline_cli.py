"""The baseline CLI must bind original source and preserve all outcome counts."""

import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "tools/pinyin-pretrained/preserved_baseline.py"
spec = importlib.util.spec_from_file_location("preserved_baseline_cli_test", SCRIPT)
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)


def test_archive_bytes_are_checked_against_the_fixed_original_commit(tmp_path, monkeypatch):
    source = {
        "pinyin_matcher/inference.py": b"# original test-only archived source\n",
        "content/pronunciation-rules.json": b'{"testOnly":true}\n',
    }
    for relative, value in source.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)

    def git(arguments, **kwargs):
        if "rev-parse" in arguments:
            return SimpleNamespace(stdout=baseline.BASELINE_REVISION + "\n")
        if "ls-tree" in arguments:
            return SimpleNamespace(stdout="\n".join(source) + "\n")
        return SimpleNamespace(stdout=source[arguments[-1].split(":", 1)[1]])

    monkeypatch.setattr(baseline.subprocess, "run", git)
    actual = baseline.verify_snapshot(tmp_path, tmp_path)
    assert (
        actual["pinyin_matcher/inference.py"]
        == hashlib.sha256(source["pinyin_matcher/inference.py"]).hexdigest()
    )
    (tmp_path / "pinyin_matcher/inference.py").write_bytes(b"current matcher substituted")
    with pytest.raises(ValueError, match="SOURCE_MISMATCH"):
        baseline.verify_snapshot(tmp_path, tmp_path)


def test_unavailable_and_ambiguous_records_do_not_disappear_from_denominators():
    rows = [
        {"expectedMatch": True, "status": "unavailable", "reason": "TARGET_NOT_TRAINED"},
        {"expectedMatch": True, "status": "uncertain", "reason": "LOW_EVIDENCE"},
        {"expectedMatch": False, "status": "matched", "reason": None},
        {"expectedMatch": None, "status": "matched", "reason": None},
    ]
    report = baseline.summarize(rows)
    assert report["rows"] == 4 and report["unassessableRows"] == 1
    assert report["positiveAbstentionIncludingUnavailable"]["count"] == 2
    assert report["positiveAbstentionIncludingUnavailable"]["denominator"] == 2
    assert report["negativeFalseAcceptance"]["count"] == 1
    assert report["negativeFalseAcceptance"]["denominator"] == 1
    assert report["unassessableStatuses"] == {"matched": 1}


def test_import_assertion_rejects_current_repository_modules(tmp_path, monkeypatch):
    fake = SimpleNamespace(__file__="/outside-original-snapshot/pinyin_matcher/__init__.py")
    monkeypatch.setitem(baseline.sys.modules, "pinyin_matcher", fake)
    with pytest.raises(ValueError, match="CURRENT_MATCHER_IMPORT_FORBIDDEN"):
        baseline.assert_import_roots(tmp_path)
