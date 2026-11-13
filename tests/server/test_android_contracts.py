"""The native fixture is versioned and must stay aligned with Python's rules."""

import json
from pathlib import Path

from deploy.android.contracts import fixtures


def test_android_shared_rule_fixture_is_current():
    path = Path("deploy/android/app/src/androidTest/assets/contracts.json")
    assert json.loads(path.read_text()) == json.loads(json.dumps(fixtures()))
