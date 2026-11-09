#!/bin/bash
set -euo pipefail
resources="$SRCROOT/../../build/ios/Resources"
if [[ "${CONFIGURATION:-Debug}" == Release ]]; then
  resources="$SRCROOT/../../build/ios/PublicResources"
  if [[ ! -f "$resources/Data/distribution.json" ]] ||
    [[ "$(/usr/bin/plutil -extract profile raw "$resources/Data/distribution.json")" != public ]]; then
    echo 'error: Prepare the public iOS content package (deploy/ios/prepare.sh --public) before archiving.' >&2
    exit 1
  fi
fi
if [[ ! -f "$resources/Data/web-files.json" || ! -f "$resources/Data/qwen-asr.json" ]]; then
  echo 'error: Run deploy/ios/prepare.sh from the repository before building the iOS target.' >&2
  exit 1
fi
output="$TARGET_BUILD_DIR/$UNLOCALIZED_RESOURCES_FOLDER_PATH/Offline"
rm -rf "$output"
ditto "$resources" "$output"
