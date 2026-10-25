"""Release gate for every authored route and its real Chinese introduction."""

import argparse

from server import learning_audio
from server.game_levels import catalog, validate_catalog


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", action="store_true")
    args = parser.parse_args()
    result = validate_catalog()
    scripts = learning_audio.narration_scripts()
    available = learning_audio.available_assets() if args.release else {}
    for level in catalog()["levels"]:
        if level["voiceId"] not in scripts:
            raise ValueError(f"missing level guidance: {level['id']}")
        if args.release and not available.get(level["voiceId"], False):
            raise ValueError(f"unavailable level guidance: {level['id']}")
    print({**result, "release": args.release})


if __name__ == "__main__":
    main()
