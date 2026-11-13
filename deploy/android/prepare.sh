#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
npm run typecheck
node_modules/.bin/vite build --config config/vite.config.ts --mode ios-offline --outDir build/ios/Web
stage=$(mktemp -d "$PWD/build/android-stage.XXXXXXXX")
trap 'rm -rf "$stage"' EXIT
uv run --locked python -m deploy.ios.prepare "$stage/pack" --public
mkdir -p deploy/android/app/src/main/assets
rm -rf deploy/android/app/src/main/assets/pack
mv "$stage/pack" deploy/android/app/src/main/assets/pack
