#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
uv run --locked python -m deploy.android.runtime
mkdir -p deploy/android/app/src/main/assets
cp content/android-asr.json deploy/android/app/src/main/assets/android-asr.json
cp resources/licenses/Android-ASR.txt deploy/android/app/src/main/assets/Android-ASR-LICENSE.txt
npm run typecheck
node_modules/.bin/vite build --config config/vite.config.ts --mode ios-offline --outDir build/ios/Web
stage=$(mktemp -d "$PWD/build/android-stage.XXXXXXXX")
trap 'rm -rf "$stage"' EXIT
uv run --locked python -m deploy.ios.prepare "$stage/pack" --public
mkdir -p deploy/android/app/src/main/assets
rm -rf deploy/android/app/src/main/assets/pack
mv "$stage/pack" deploy/android/app/src/main/assets/pack
