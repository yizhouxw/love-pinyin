#!/bin/bash
set -euo pipefail
resources="$SRCROOT/../../build/ios/Resources"
if [[ ! -f "$resources/Web/probe.html" ]]; then
  echo 'error: Run deploy/ios/prepare.sh from the repository before building the iOS target.' >&2
  exit 1
fi
output="$TARGET_BUILD_DIR/$UNLOCALIZED_RESOURCES_FOLDER_PATH/Offline"
rm -rf "$output"
ditto "$resources" "$output"
