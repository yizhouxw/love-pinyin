#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
output=build/ios/Resources
if [[ $# == 1 && $1 == --trial-aac ]]; then
  output=build/ios/TrialAAC
elif [[ $# != 0 ]]; then
  echo 'Usage: deploy/ios/prepare.sh [--trial-aac]' >&2
  exit 2
fi
npm run build
npm run validate:release
mkdir -p build/ios
stage=$(mktemp -d "$PWD/build/ios/stage.XXXXXXXX")
trap 'rm -rf "$stage"' EXIT
uv run --locked python -m deploy.ios.prepare "$stage/Resources" "$@"
cp deploy/ios/probe.html deploy/ios/probe.js "$stage/Resources/Web/"
rm -rf "$output"
mv "$stage/Resources" "$output"
du -sh "$output"
