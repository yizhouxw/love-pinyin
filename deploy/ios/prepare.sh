#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
output=build/ios/Resources
if [[ $# == 1 && $1 == --trial-aac ]]; then
  output=build/ios/TrialAAC
elif [[ $# == 1 && $1 == --public ]]; then
  output=build/ios/PublicResources
elif [[ $# != 0 ]]; then
  echo 'Usage: deploy/ios/prepare.sh [--trial-aac | --public]' >&2
  exit 2
fi
npm run typecheck
node_modules/.bin/vite build --config config/vite.config.ts --mode ios-offline --outDir build/ios/Web
if [[ $output != build/ios/PublicResources ]]; then
  npm run validate:release
fi
mkdir -p build/ios
stage=$(mktemp -d "$PWD/build/ios/stage.XXXXXXXX")
trap 'rm -rf "$stage"' EXIT
uv run --locked python -m deploy.ios.prepare "$stage/Resources" "$@"
rm -rf "$output"
mv "$stage/Resources" "$output"
du -sh "$output"
