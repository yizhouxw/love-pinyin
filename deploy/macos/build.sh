#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
[[ $(uname -s) == Darwin ]] || { echo 'macOS required' >&2; exit 1; }
arch=$(uname -m)
output="$PWD/build/macos"
rm -rf "$output"
app="$output/爱拼音.app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources/app"
cp deploy/macos/Info.plist "$app/Contents/Info.plist"
cp deploy/macos/AppIcon.icns "$app/Contents/Resources/AppIcon.icns"
swiftc -O deploy/macos/main.swift -framework AppKit -framework WebKit -o "$app/Contents/MacOS/LovePinyin"
npm ci --no-audit --no-fund
uv sync --locked
uv run --locked python -m scripts.sync_standard_audio
uv run --locked python -m scripts.check_bundled_resources
npm run build
uv python install 3.12.12
python_path=$(cd / && uv python find --no-project --managed-python 3.12.12)
python_root=$(dirname "$(dirname "$python_path")")
cp -R "$python_root" "$app/Contents/Resources/python"
uv export --locked --no-default-groups --group voice-build --no-emit-project --quiet -o "$output/requirements.txt"
uv pip install --break-system-packages --python "$app/Contents/Resources/python/bin/python3" --requirements "$output/requirements.txt"
root="$app/Contents/Resources/app"
cp -R server scripts content resources dist "$root/"
mkdir -p "$root/private"
cp -R private/pinyinsound "$root/private/"
cp LICENSE THIRD_PARTY_NOTICES.md "$root/"
find "$root" -name __pycache__ -type d -prune -exec rm -rf {} +
/usr/bin/python3 deploy/macos/smoke.py
# A writable data directory and model are never part of the application bundle.
mkdir -p "$output/image"
cp -R "$app" "$output/image/"
ln -s /Applications "$output/image/Applications"
hdiutil create -quiet -volname '爱拼音' -srcfolder "$output/image" -ov -format UDZO "$output/LovePinyin-$arch.dmg"
(cd "$output" && shasum -a 256 "LovePinyin-$arch.dmg" > "LovePinyin-$arch.dmg.sha256")
echo "Created $output/LovePinyin-$arch.dmg"
