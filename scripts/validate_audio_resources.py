"""Validate installed audio without a human approval lifecycle."""

import json

from server import source_audio
from server.content import load_curriculum
from server.learning_audio import available_assets


def main():
    targets = [a for a in load_curriculum()["audioRequirements"] if a["kind"] != "instruction"]
    missing = [a["id"] for a in targets if not source_audio.available(a)]
    missing.extend(key for key, ready in available_assets().items() if not ready)
    print(json.dumps({"missing": missing, "standardTargets": len(targets)}, ensure_ascii=False))
    if missing:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
